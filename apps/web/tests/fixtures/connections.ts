import type { Schema } from "../../src/lib/api";

const accounts: Schema["AccountRead"][] = [
  {
    id: "11111111-1111-4111-8111-111111111111",
    row_version: 1,
    toolkit: "gmail",
    display_name: "Alex · alex@example.com",
    provider_identity: { email: "alex@example.com" },
    connection_status: "ACTIVE",
    identity_verified_at: "2026-09-21T10:00:00Z",
    selected_purpose: "outreach",
  },
  {
    id: "22222222-2222-4222-8222-222222222222",
    row_version: 1,
    toolkit: "gmail",
    display_name: "Sam · sam@example.com",
    provider_identity: { email: "sam@example.com" },
    connection_status: "ACTIVE",
    identity_verified_at: "2026-09-21T10:00:00Z",
    selected_purpose: null,
  },
  {
    id: "33333333-3333-4333-8333-333333333333",
    row_version: 1,
    toolkit: "linear",
    display_name: "Northstar workspace",
    provider_identity: { workspace_id: "synthetic-workspace" },
    connection_status: "EXPIRED",
    identity_verified_at: "2026-09-20T10:00:00Z",
    selected_purpose: null,
  },
];
const requests: { route: string; body: unknown }[] = [];

// This fixture never contacts a provider. Keep connection mutations separate
// from the reviewed-action fixtures used by other workspace pages.
export async function connectionsFixture(url: URL, init?: RequestInit) {
  if (location.pathname !== "/connections") return null;
  const route = url.pathname.replace("/api/backend/", "");
  const method = init?.method ?? "GET";
  if (route === "test/connections") return Response.json(requests);
  if (route === "integrations")
    return Response.json({
      services: [],
      model_providers: [],
      composio_configured: true,
      composio_toolkits: ["gmail", "googlecalendar", "linear", "linkedin"],
      auth: "clerk",
    });
  if (!route.startsWith("integrations/composio/")) return null;
  if (method === "POST")
    requests.push({ route, body: JSON.parse(String(init?.body ?? "{}")) });
  if (route === "integrations/composio/accounts")
    return Response.json(accounts);
  if (route === "integrations/composio/accounts/sync") {
    if (
      new URLSearchParams(location.search).get("toolkit") === "linkedin" &&
      !accounts.some((account) => account.toolkit === "linkedin")
    ) {
      accounts.push({
        id: "44444444-4444-4444-8444-444444444444",
        row_version: 1,
        toolkit: "linkedin",
        display_name: "Alex Synthetic",
        provider_identity: { sub: "member-synthetic" },
        connection_status: "ACTIVE",
        identity_verified_at: "2026-09-23T10:00:00Z",
        selected_purpose: null,
      });
    }
    return Response.json(accounts);
  }
  const selection = route.match(
    /^integrations\/composio\/accounts\/([^/]+)\/select$/,
  );
  if (selection) {
    const account = accounts.find((item) => item.id === selection[1]);
    if (!account)
      return Response.json({ detail: "Not found" }, { status: 404 });
    for (const item of accounts) {
      item.selected_purpose = item === account ? "outreach" : null;
      item.row_version += 1;
    }
    return Response.json(account);
  }
  if (route === "integrations/composio/connect")
    return Response.json({
      redirect_url: "https://provider.example/authorize",
    });
  return null;
}
