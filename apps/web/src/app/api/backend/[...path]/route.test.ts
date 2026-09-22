// @vitest-environment node

import { NextRequest } from "next/server";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { GET, PATCH, POST } from "./route";

const clerk = vi.hoisted(() => ({ auth: vi.fn() }));
vi.mock("@clerk/nextjs/server", () => clerk);

const upstream = vi.fn<typeof fetch>();
const getToken = vi.fn<() => Promise<string | null>>();
const origin = "https://workspace.synthetic.invalid";
const context = (path = ["companies"]) => ({
  params: Promise.resolve({ path }),
});

beforeEach(() => {
  vi.stubEnv("NODE_ENV", "production");
  vi.stubEnv("CC_WEB_ORIGIN", origin);
  vi.stubEnv("CC_API_URL", "https://api.synthetic.invalid");
  vi.stubEnv("CC_API_TOKEN", "synthetic-service-token-must-stay-server-side");
  vi.stubGlobal("fetch", upstream);
  upstream.mockReset();
  getToken.mockReset().mockResolvedValue("synthetic-actor-session");
  clerk.auth.mockReset().mockResolvedValue({ userId: "actor-a", getToken });
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

it("rejects unresolved or expired sessions before reaching the API", async () => {
  clerk.auth.mockResolvedValueOnce({ userId: null, getToken });
  const unsigned = await GET(
    new NextRequest(`${origin}/api/backend/companies`),
    context(),
  );
  expect(unsigned.status).toBe(401);
  expect(getToken).not.toHaveBeenCalled();

  getToken.mockResolvedValueOnce(null);
  const expired = await GET(
    new NextRequest(`${origin}/api/backend/companies`),
    context(),
  );
  expect(expired.status).toBe(401);
  expect(upstream).not.toHaveBeenCalled();
});

it.each([
  undefined,
  "https://unrelated.synthetic.invalid",
  "http://127.0.0.1:3001",
])(
  "rejects write origin %s before requesting a token or forwarding",
  async (requestOrigin) => {
    for (const [method, handler] of [
      ["POST", POST],
      ["PATCH", PATCH],
    ] as const) {
      const request = new NextRequest(`${origin}/api/backend/companies`, {
        method,
        headers: requestOrigin ? { origin: requestOrigin } : undefined,
        body: "{}",
      });
      expect((await handler(request, context())).status).toBe(403);
    }
    expect(getToken).not.toHaveBeenCalled();
    expect(upstream).not.toHaveBeenCalled();
  },
);

it.each([
  { path: [] },
  { path: [".."] },
  { path: ["me?owner=another"] },
  { path: ["https:", "external"] },
  { path: ["me/credentials"] },
])(
  "rejects a nonliteral API path $path without forwarding",
  async ({ path }) => {
    const response = await GET(
      new NextRequest(`${origin}/api/backend/companies`),
      context(path),
    );
    expect(response.status).toBe(400);
    expect(getToken).not.toHaveBeenCalled();
    expect(upstream).not.toHaveBeenCalled();
  },
);

it("forwards only the verified session, approved headers and exact write intent", async () => {
  const body = JSON.stringify({
    title: "Synthetic research",
    expected_version: 3,
  });
  upstream.mockResolvedValueOnce(
    new Response(JSON.stringify({ detail: "Revision conflict" }), {
      status: 409,
      headers: {
        "Content-Type": "application/json",
        "X-Request-ID": "synthetic-request",
        Authorization: "synthetic-upstream-secret",
        "Set-Cookie": "provider_session=synthetic",
      },
    }),
  );
  const response = await PATCH(
    new NextRequest(`${origin}/api/backend/tasks/task-a?mode=exact`, {
      method: "PATCH",
      headers: {
        origin,
        "content-type": "application/json",
        accept: "application/json",
        "idempotency-key": "synthetic-stable-write-key",
        authorization: "Bearer untrusted-client-credential",
        cookie: "browser_session=synthetic",
        "x-api-key": "untrusted-provider-key",
      },
      body,
    }),
    context(["tasks", "task-a"]),
  );

  expect(upstream).toHaveBeenCalledTimes(1);
  const [url, options] = upstream.mock.calls[0];
  expect(url).toBe(
    "https://api.synthetic.invalid/api/v1/tasks/task-a?mode=exact",
  );
  expect(options?.method).toBe("PATCH");
  expect(options?.cache).toBe("no-store");
  expect(options?.redirect).toBe("error");
  const headers = new Headers(options?.headers);
  expect(Object.fromEntries(headers)).toEqual({
    authorization: "Bearer synthetic-actor-session",
    accept: "application/json",
    "content-type": "application/json",
    "idempotency-key": "synthetic-stable-write-key",
  });
  expect(new TextDecoder().decode(options?.body as ArrayBuffer)).toBe(body);
  expect(response.status).toBe(409);
  expect(await response.json()).toEqual({ detail: "Revision conflict" });
  expect(response.headers.get("cache-control")).toBe("no-store");
  expect(response.headers.get("x-request-id")).toBe("synthetic-request");
  expect(response.headers.has("authorization")).toBe(false);
  expect(response.headers.has("set-cookie")).toBe(false);
});

it.each([
  { contentType: "application/json", size: 1_000_001 },
  {
    contentType: "multipart/form-data; boundary=synthetic",
    size: 21 * 1024 * 1024 + 1,
  },
])(
  "rejects an oversized $contentType body before forwarding",
  async ({ contentType, size }) => {
    const request = new NextRequest(`${origin}/api/backend/artifacts`, {
      method: "POST",
      headers: { origin, "content-type": contentType },
      body: new Uint8Array(size),
    });
    const response = await POST(request, context(["artifacts"]));
    expect(response.status).toBe(413);
    expect(upstream).not.toHaveBeenCalled();
  },
);

it("preserves a private document download without forwarding upstream credentials", async () => {
  const bytes = new TextEncoder().encode("%PDF-synthetic");
  upstream.mockResolvedValueOnce(
    new Response(bytes, {
      headers: {
        "Content-Type": "application/pdf",
        "Content-Disposition": 'attachment; filename="synthetic.pdf"',
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "public, max-age=3600",
      },
    }),
  );
  const response = await GET(
    new NextRequest(
      `${origin}/api/backend/documents/versions/version-a/download`,
    ),
    context(["documents", "versions", "version-a", "download"]),
  );
  expect(new Uint8Array(await response.arrayBuffer())).toEqual(bytes);
  expect(response.headers.get("content-disposition")).toContain(
    "synthetic.pdf",
  );
  expect(response.headers.get("content-type")).toBe("application/pdf");
  expect(response.headers.get("x-content-type-options")).toBe("nosniff");
  expect(response.headers.get("cache-control")).toBe("no-store");
});

it("delivers the first streamed event before completion and propagates disconnect", async () => {
  let source!: ReadableStreamDefaultController<Uint8Array>;
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      source = controller;
    },
  });
  upstream.mockResolvedValueOnce(
    new Response(stream, { headers: { "Content-Type": "text/event-stream" } }),
  );
  const disconnect = new AbortController();
  const request = new NextRequest(
    `${origin}/api/backend/agent-runs/run-a/events?after=7`,
    {
      headers: { accept: "text/event-stream" },
      signal: disconnect.signal,
    },
  );
  source.enqueue(new TextEncoder().encode("id: 8\ndata: synthetic-token\n\n"));
  const response = await GET(
    request,
    context(["agent-runs", "run-a", "events"]),
  );
  const reader = response.body!.getReader();
  expect(new TextDecoder().decode((await reader.read()).value)).toContain(
    "synthetic-token",
  );
  expect(response.headers.get("x-accel-buffering")).toBe("no");
  expect(response.headers.get("cache-control")).toContain("no-transform");
  disconnect.abort();
  expect(upstream.mock.calls[0][1]?.signal?.aborted).toBe(true);
  await reader.cancel();
});

it("returns a safe transport error without exposing provider exception details", async () => {
  upstream.mockRejectedValueOnce(
    new Error("synthetic-secret-in-provider-error"),
  );
  const response = await GET(
    new NextRequest(`${origin}/api/backend/companies`),
    context(),
  );
  expect(response.status).toBe(503);
  expect(await response.text()).not.toContain("synthetic-secret");
});
