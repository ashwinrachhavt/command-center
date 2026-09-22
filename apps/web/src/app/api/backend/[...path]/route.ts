import { auth } from "@clerk/nextjs/server";
import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

async function forward(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const session = await auth();
  if (!session.userId)
    return NextResponse.json(
      { detail: "Sign in to continue" },
      { status: 401 },
    );
  const mutating = request.method !== "GET";
  const origin = process.env.CC_WEB_ORIGIN ?? "http://localhost:3001";
  const allowed = new Set([
    origin,
    ...(process.env.NODE_ENV === "development"
      ? ["http://127.0.0.1:3001"]
      : []),
  ]);
  if (mutating && !allowed.has(request.headers.get("origin") ?? ""))
    return NextResponse.json(
      { detail: "Invalid request origin" },
      { status: 403 },
    );
  const { path } = await context.params;
  if (!path.length || path.some((part) => !/^[a-zA-Z0-9_-]+$/.test(part)))
    return NextResponse.json({ detail: "Invalid API path" }, { status: 400 });
  const token = await session.getToken();
  if (!token)
    return NextResponse.json({ detail: "Session expired" }, { status: 401 });
  const contentType = request.headers.get("content-type") ?? "";
  const multipart = contentType
    .toLowerCase()
    .startsWith("multipart/form-data;");
  const body = mutating ? await request.arrayBuffer() : undefined;
  const maxRequestBytes = multipart ? 21 * 1024 * 1024 : 1_000_000;
  if (body && body.byteLength > maxRequestBytes)
    return NextResponse.json(
      { detail: "Request is too large" },
      { status: 413 },
    );
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
  };
  const accepts = request.headers.get("accept");
  if (accepts) headers.Accept = accepts;
  if (contentType) headers["Content-Type"] = contentType;
  const key = request.headers.get("idempotency-key");
  if (key) headers["Idempotency-Key"] = key;
  const eventStreamRequest =
    request.method === "GET" &&
    path.length === 3 &&
    path[0] === "agent-runs" &&
    path[2] === "events";
  try {
    const upstream = await fetch(
      `${process.env.CC_API_URL ?? "http://127.0.0.1:8000"}/api/v1/${path.join("/")}${request.nextUrl.search}`,
      {
        method: request.method,
        headers,
        body,
        cache: "no-store",
        redirect: "error",
        signal: eventStreamRequest
          ? request.signal
          : AbortSignal.any([request.signal, AbortSignal.timeout(40000)]),
      },
    );
    const responseHeaders: Record<string, string> = {
      "Content-Type":
        upstream.headers.get("Content-Type") ?? "application/octet-stream",
      "Cache-Control": "no-store",
      "X-Request-ID": upstream.headers.get("X-Request-ID") ?? "",
    };
    const disposition = upstream.headers.get("Content-Disposition");
    if (disposition) responseHeaders["Content-Disposition"] = disposition;
    const nosniff = upstream.headers.get("X-Content-Type-Options");
    if (nosniff) responseHeaders["X-Content-Type-Options"] = nosniff;
    if (
      eventStreamRequest &&
      upstream.body &&
      upstream.headers.get("Content-Type")?.includes("text/event-stream")
    ) {
      responseHeaders["Cache-Control"] =
        "no-store, no-cache, must-revalidate, no-transform";
      responseHeaders["X-Accel-Buffering"] = "no";
      return new NextResponse(upstream.body, {
        status: upstream.status,
        headers: responseHeaders,
      });
    }
    return new NextResponse(await upstream.arrayBuffer(), {
      status: upstream.status,
      headers: responseHeaders,
    });
  } catch {
    return NextResponse.json(
      {
        detail:
          "The workspace API is unavailable. Check that the API container is running.",
      },
      { status: 503 },
    );
  }
}
export { forward as GET, forward as POST, forward as PATCH };
