import type { Schema } from "../../src/lib/api";

type Snapshot = Schema["DiscoveryRead"];
const storeKey = "synthetic-discovery-results";
const logKey = "synthetic-discovery-requests";
export async function contactDiscoveryFixture(url: URL, init?: RequestInit) {
  const route = url.pathname.replace("/api/backend/", "");
  if (route === "test/discovery-requests")
    return Response.json(JSON.parse(localStorage.getItem(logKey) ?? "[]"));
  if (!route.startsWith("contact-discovery/")) return null;
  const params = new URLSearchParams(location.search);
  if (route.endsWith("/evidence")) return Response.json([]);
  if (route.endsWith("/providers"))
    return Response.json(
      ["apollo", "hunter"].map((id) => ({
        id,
        name: id === "apollo" ? "Apollo" : "Hunter",
        configured: !params.has("provider_setup"),
        setup_variable: `${id.toUpperCase()}_API_KEY`,
        documentation_url: "https://example.com/provider-docs",
        description:
          "Synthetic contact discovery. Provider credits and plan limits apply.",
      })),
    );
  const snapshots: Snapshot[] = JSON.parse(
    localStorage.getItem(storeKey) ?? "[]",
  );
  if (route.endsWith("/recent"))
    return Response.json(snapshots.slice().reverse());
  const body = JSON.parse(String(init?.body ?? "{}"));
  const key = new Headers(init?.headers).get("Idempotency-Key");
  const log = JSON.parse(localStorage.getItem(logKey) ?? "[]");
  log.push({ route, body, key });
  localStorage.setItem(logKey, JSON.stringify(log));
  if (params.has("discovery_failure"))
    return Response.json(
      {
        detail: {
          code: "connected_request_outcome_unknown",
          message:
            "The provider outcome is unknown; this request was not replayed",
        },
      },
      { status: 409 },
    );
  const contact = {
    id: "contact-1",
    name: "Alex Morgan",
    email: params.has("discovery_existing") ? null : "alex@example.com",
    title: "My current title",
    notes: "My notes",
    linkedin_url: null,
    row_version: 1,
  };
  if (route.endsWith("/fill-missing"))
    return Response.json({
      ...contact,
      email: "alex@example.com",
      row_version: 2,
    });
  if (route.endsWith("/import"))
    return Response.json({
      created: !params.has("discovery_existing"),
      contact,
    });
  const provider = route.endsWith("/reveal") ? "apollo" : body.provider;
  const full = route.endsWith("/reveal") || provider === "hunter";
  const snapshot: Snapshot = {
    source_version_id: crypto.randomUUID(),
    source_artifact_id: crypto.randomUUID(),
    observed_at: new Date().toISOString(),
    cached: false,
    query: {
      provider,
      operation: route.endsWith("/reveal") ? "reveal" : "search",
      domain: body.domain ?? "example.com",
      title: body.title ?? "",
    },
    result: {
      total: 1,
      page: body.page ?? 1,
      has_more: false,
      items: [
        {
          provider,
          external_id: `${provider}-alex`,
          name: full ? "Alex Morgan" : "Alex M***",
          name_complete: full,
          title: "Engineering lead",
          company_name: "Northstar",
          domain: "example.com",
          email: full ? "alex@example.com" : null,
          email_status: full ? "accept_all" : "not_revealed",
          sources: ["https://example.com/team"],
          confidence: full ? 93 : null,
          linkedin_url: null,
        },
      ],
    },
  };
  snapshots.push(snapshot);
  localStorage.setItem(storeKey, JSON.stringify(snapshots));
  return Response.json(snapshot);
}
