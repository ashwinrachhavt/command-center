// @vitest-environment node

import { afterEach, expect, it, vi } from "vitest";
import { api, ApiError, runFailureMessage } from "./api";

afterEach(() => vi.unstubAllGlobals());

it("turns a plain-text upstream failure into a recoverable API error", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        new Response("Internal Server Error", { status: 500 }),
      ),
  );
  await expect(api("workspace", { retry: false })).rejects.toMatchObject({
    status: 500,
    message:
      "The workspace service is temporarily unavailable. Try again shortly.",
  });
});

it.each([
  "connected_request_failed",
  "connected_request_running",
  "connected_request_outcome_unknown",
  "spending_work_limit",
])(
  "preserves the %s outcome code without automatically issuing another request",
  async (code) => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: { code, message: "Synthetic operation outcome" },
        }),
        { status: 409, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetch);
    const result = api("integrations/composio/accounts/sync", {
      method: "POST",
      body: {},
      key: "synthetic-retained-key",
    });
    await expect(result).rejects.toMatchObject({
      status: 409,
      code,
      message: "Synthetic operation outcome",
    });
    await expect(result).rejects.toBeInstanceOf(ApiError);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][1].headers["Idempotency-Key"]).toBe(
      "synthetic-retained-key",
    );
  },
);

it.each([
  ["model_not_found", "Refresh the model picker"],
  ["model_request_rejected", "tool configuration"],
  ["model_access_denied", "account does not have access"],
  ["model_rate_limited", "quota limit"],
])("explains %s with a recovery action", (code, expected) => {
  expect(runFailureMessage(code)).toContain(expected);
});
