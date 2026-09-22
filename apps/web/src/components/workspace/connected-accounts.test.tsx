import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import type { Schema } from "@/lib/api";
import { ConnectedAccounts } from "./connected-accounts";

const account: Schema["AccountRead"] = {
  id: "11111111-1111-4111-8111-111111111111",
  row_version: 3,
  toolkit: "gmail",
  display_name: "Work Gmail",
  provider_identity: { email: "synthetic@example.test" },
  connection_status: "ACTIVE",
  identity_verified_at: "2026-09-22T12:00:00Z",
  selected_purpose: null,
};

function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ConnectedAccounts />
    </QueryClientProvider>,
  );
}

function idempotencyKey(call: unknown[]) {
  return new Headers((call[1] as RequestInit).headers).get("Idempotency-Key");
}

it("keeps refresh and selection intents independent and retries an unknown refresh with its original key", async () => {
  let refreshCalls = 0;
  const fetch = vi.spyOn(global, "fetch").mockImplementation((input, init) => {
    const path = String(input);
    if (
      init?.method === "GET" &&
      path.endsWith("/integrations/composio/accounts")
    ) {
      return Promise.resolve(Response.json([account]));
    }
    if (path.endsWith("/integrations/composio/accounts/sync")) {
      refreshCalls += 1;
      return Promise.resolve(
        refreshCalls === 1
          ? Response.json(
              {
                detail: {
                  code: "connected_request_outcome_unknown",
                  message: "The refresh outcome is unknown.",
                },
              },
              { status: 409 },
            )
          : Response.json([account]),
      );
    }
    if (path.endsWith(`/${account.id}/select`)) {
      return Promise.resolve(
        Response.json({ ...account, selected_purpose: "outreach" }),
      );
    }
    throw new Error(`Unexpected request: ${path}`);
  });
  mount();
  await screen.findByText("Work Gmail");

  fireEvent.click(screen.getByRole("button", { name: "Refresh accounts" }));
  await screen.findByRole("button", { name: "Retry the same refresh" });
  fireEvent.click(screen.getByRole("button", { name: "Use for outreach" }));
  await waitFor(() =>
    expect(
      fetch.mock.calls.filter(([input]) => String(input).endsWith("/select")),
    ).toHaveLength(1),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Retry the same refresh" }),
  );
  await waitFor(() => expect(refreshCalls).toBe(2));

  const writes = fetch.mock.calls.filter(([, init]) => init?.method === "POST");
  expect(idempotencyKey(writes[2])).toBe(idempotencyKey(writes[0]));
  expect(idempotencyKey(writes[1])).not.toBe(idempotencyKey(writes[0]));
});

it("starts a fresh user-requested refresh after a definitive spending denial", async () => {
  let refreshCalls = 0;
  const fetch = vi.spyOn(global, "fetch").mockImplementation((input, init) => {
    const path = String(input);
    if (
      init?.method === "GET" &&
      path.endsWith("/integrations/composio/accounts")
    ) {
      return Promise.resolve(Response.json([account]));
    }
    if (path.endsWith("/integrations/composio/accounts/sync")) {
      refreshCalls += 1;
      return Promise.resolve(
        refreshCalls === 1
          ? Response.json(
              {
                detail: {
                  code: "spending_limit_exceeded",
                  message: "The connected-tool spending limit was reached.",
                },
              },
              { status: 409 },
            )
          : Response.json([account]),
      );
    }
    throw new Error(`Unexpected request: ${path}`);
  });
  mount();
  await screen.findByText("Work Gmail");

  fireEvent.click(screen.getByRole("button", { name: "Refresh accounts" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "Start a fresh refresh" }),
  );
  await waitFor(() => expect(refreshCalls).toBe(2));

  const writes = fetch.mock.calls.filter(([, init]) => init?.method === "POST");
  expect(idempotencyKey(writes[1])).not.toBe(idempotencyKey(writes[0]));
});
