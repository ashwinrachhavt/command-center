// @vitest-environment node

import { afterEach, expect, it, vi } from "vitest";
import { api, ApiError } from "./api";

afterEach(() => vi.unstubAllGlobals());

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
