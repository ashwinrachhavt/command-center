import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import type { Schema } from "@/lib/api";
import { ConnectedAccounts } from "./connected-accounts";

vi.mock("./contact-discovery", () => ({
  ContactDiscoveryConnections: () => null,
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

const integrations = {
  services: [],
  model_providers: {
    openai: false,
    gemini: false,
    mistral: false,
    cohere: false,
  },
  openai_configured: false,
  composio_configured: true,
  auth: "clerk",
  composio_toolkits: ["gmail", "googlecalendar", "linear", "notion"],
};

beforeEach(() => {
  window.history.replaceState(null, "", "/connections");
  sessionStorage.clear();
});

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
    if (path.endsWith("/integrations"))
      return Promise.resolve(Response.json(integrations));
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
    if (path.endsWith("/integrations"))
      return Promise.resolve(Response.json(integrations));
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

it("shows saved account identity and inactive status without fetching provider data on navigation", async () => {
  const fetch = vi.spyOn(global, "fetch").mockImplementation((input) => {
    if (String(input).endsWith("/integrations"))
      return Promise.resolve(Response.json(integrations));
    if (String(input).endsWith("/accounts"))
      return Promise.resolve(
        Response.json([
          {
            ...account,
            connection_status: "EXPIRED",
            selected_purpose: "outreach",
          },
        ]),
      );
    throw new Error(`Unexpected request: ${input}`);
  });
  mount();
  const gmail = await screen.findByRole("region", { name: "Gmail" });
  expect(within(gmail).getByText("Needs attention")).toBeVisible();
  expect(within(gmail).getByText("Expired")).toBeVisible();
  expect(within(gmail).getByText("Work Gmail")).toBeVisible();
  expect(within(gmail).queryByText("Outreach account")).not.toBeInTheDocument();
  expect(
    within(gmail).getByRole("button", { name: "Use for outreach" }),
  ).toBeDisabled();
  expect(
    within(gmail).getByRole("button", { name: "Reconnect" }),
  ).toBeEnabled();
  expect(fetch.mock.calls.every(([, init]) => init?.method === "GET")).toBe(
    true,
  );
});

it("explains missing configuration without offering an unusable connect action", async () => {
  vi.spyOn(global, "fetch").mockImplementation((input) =>
    Promise.resolve(
      Response.json(
        String(input).endsWith("/integrations")
          ? { ...integrations, composio_toolkits: [] }
          : [],
      ),
    ),
  );
  mount();
  const gmail = await screen.findByRole("region", { name: "Gmail" });
  expect(within(gmail).getByText("Setup required")).toBeVisible();
  expect(
    screen.getByRole("button", { name: "Refresh accounts" }),
  ).toBeDisabled();
  fireEvent.click(within(gmail).getByRole("button", { name: "View setup" }));
  expect(
    await screen.findByRole("dialog", { name: "Set up Gmail" }),
  ).toBeVisible();
  expect(screen.getByText("CC_COMPOSIO_AUTH_CONFIGS")).toBeVisible();
});

it("automatically verifies an OAuth return and clears provider parameters", async () => {
  window.history.replaceState(
    null,
    "",
    "/agent-settings?tab=connectors&connected=1&status=success&connected_account_id=ca_synthetic&toolkit=gmail",
  );
  const fetch = vi
    .spyOn(global, "fetch")
    .mockImplementation((input) =>
      Promise.resolve(
        Response.json(
          String(input).endsWith("/integrations")
            ? integrations
            : String(input).endsWith("/sync")
              ? [account]
              : [],
        ),
      ),
    );
  mount();
  await screen.findByText("Work Gmail");
  await waitFor(() => expect(window.location.search).toBe("?tab=connectors"));
  expect(
    within(screen.getByRole("region", { name: "Gmail" })).getByText(
      "Connected",
    ),
  ).toBeVisible();
  expect(
    sessionStorage.getItem("command-center:pending-app-connection"),
  ).toBeNull();
  const writes = fetch.mock.calls.filter(([, init]) => init?.method === "POST");
  expect(writes).toHaveLength(1);
  expect(String(writes[0][0])).toMatch(/accounts\/sync$/);
});

it("verifies a pending connection when returning without the provider callback", async () => {
  const key = crypto.randomUUID();
  sessionStorage.setItem(
    "command-center:pending-app-connection",
    JSON.stringify({
      expiresAt: Date.now() + 60_000,
      refreshKey: key,
    }),
  );
  const fetch = vi
    .spyOn(global, "fetch")
    .mockImplementation((input) =>
      Promise.resolve(
        Response.json(
          String(input).endsWith("/integrations")
            ? integrations
            : String(input).endsWith("/sync")
              ? [account]
              : [],
        ),
      ),
    );
  mount();
  await screen.findByText("Work Gmail");
  fireEvent.focus(window);
  fireEvent(window, new Event("pageshow"));
  const writes = fetch.mock.calls.filter(([, init]) => init?.method === "POST");
  expect(writes).toHaveLength(1);
  expect(idempotencyKey(writes[0])).toBe(key);
});

it("keeps an unfinished automatic verification key across a page reload", async () => {
  window.history.replaceState(null, "", "/connections?connected=1");
  let attempts = 0;
  const fetch = vi.spyOn(global, "fetch").mockImplementation((input) => {
    const path = String(input);
    if (path.endsWith("/integrations"))
      return Promise.resolve(Response.json(integrations));
    if (path.endsWith("/sync")) {
      attempts++;
      return Promise.resolve(
        attempts === 1
          ? Response.json(
              {
                detail: {
                  code: "connected_request_outcome_unknown",
                  message: "Verification outcome unknown",
                },
              },
              { status: 409 },
            )
          : Response.json([account]),
      );
    }
    return Promise.resolve(Response.json([]));
  });
  const first = mount();
  await screen.findByRole("button", { name: "Retry the same refresh" });
  first.unmount();
  mount();
  await screen.findByText("Work Gmail");
  const writes = fetch.mock.calls.filter(([, init]) => init?.method === "POST");
  expect(writes).toHaveLength(2);
  expect(idempotencyKey(writes[1])).toBe(idempotencyKey(writes[0]));
});

it("shows cancelled authorization without automatically verifying accounts", async () => {
  window.history.replaceState(
    null,
    "",
    "/connections?connected=1&status=failed",
  );
  const fetch = vi
    .spyOn(global, "fetch")
    .mockImplementation((input) =>
      Promise.resolve(
        Response.json(
          String(input).endsWith("/integrations") ? integrations : [],
        ),
      ),
    );
  mount();
  expect(await screen.findByText("Connection wasn’t completed")).toBeVisible();
  await screen.findByRole("region", { name: "Gmail" });
  expect(fetch.mock.calls.every(([, init]) => init?.method === "GET")).toBe(
    true,
  );
});

it("keeps an invalid OAuth redirect on the page with a recoverable error", async () => {
  const fetch = vi.spyOn(global, "fetch").mockImplementation((input) => {
    const path = String(input);
    if (path.endsWith("/integrations"))
      return Promise.resolve(Response.json(integrations));
    if (path.endsWith("/accounts")) return Promise.resolve(Response.json([]));
    if (path.endsWith("/connect"))
      return Promise.resolve(
        Response.json({ redirect_url: "javascript:alert(1)" }),
      );
    throw new Error(`Unexpected request: ${input}`);
  });
  mount();
  const gmail = await screen.findByRole("region", { name: "Gmail" });
  fireEvent.click(within(gmail).getByRole("button", { name: "Connect" }));
  expect(await screen.findByText("Gmail could not connect")).toBeVisible();
  expect(screen.getByText(/invalid connection link/)).toBeVisible();
  expect(within(gmail).getByRole("button", { name: "Connect" })).toBeEnabled();
  const call = fetch.mock.calls.find(([input]) =>
    String(input).endsWith("/connect"),
  );
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({ toolkit: "gmail" });
});
