import type { ProfileFact } from "../../src/lib/api";

// Synthetic profile API for persistence, exact-review and lost-response browser checks.
const source =
  "Company Name: Synthetic Orbit\nTitle: Engineer\nDescription: Built synthetic systems.\nLocation: Remote\nStarted On: 2020\nFinished On: ";
const legacy: ProfileFact = {
  id: "synthetic-career",
  field: "experience",
  row_version: 1,
  active: null,
  current: {
    id: "synthetic-career-v1",
    version: 1,
    value: source,
    context: "LinkedIn export · Positions.csv, data row 1.",
    source_version_id: "synthetic-source-v1",
    source_artifact_id: "synthetic-source",
    source_excerpt: source,
    valid_until: null,
    review_state: "proposed",
    created_at: "2026-09-22T00:00:00Z",
    career: null,
    career_suggestion: {
      schema_key: "career.v1",
      kind: "experience",
      organization: "Synthetic Orbit",
      role: "Engineer",
      location: "Remote",
      start_date: "2020",
      end_date: null,
      current: null,
      description: "Built synthetic systems.",
    },
  },
};

export async function careerFixture(url: URL, init?: RequestInit) {
  if (!new URLSearchParams(location.search).has("career-history")) return null;
  const route = url.pathname.replace("/api/backend/", "");
  if (!route.startsWith("profile/facts")) return null;
  const key = "synthetic-career-server";
  const facts: ProfileFact[] = JSON.parse(
    sessionStorage.getItem(key) ?? JSON.stringify([legacy]),
  );
  const method = init?.method ?? "GET";
  if (method === "GET")
    return Response.json({
      items: facts,
      total: facts.length,
      offset: 0,
      limit: 20,
    });
  const receiptsKey = `${key}:receipts`;
  const receipts = JSON.parse(sessionStorage.getItem(receiptsKey) ?? "{}");
  const receipt =
    new Headers(init?.headers).get("Idempotency-Key") ?? "missing";
  function loseReply() {
    const lost = Number(sessionStorage.getItem(`${key}:lost`) ?? 0);
    if (
      new URLSearchParams(location.search).has("lose-fact-reply") &&
      lost < 2
    ) {
      sessionStorage.setItem(`${key}:lost`, String(lost + 1));
      throw new TypeError("Synthetic response lost after saving");
    }
  }
  if (receipts[receipt]) {
    loseReply();
    return Response.json(receipts[receipt]);
  }
  const body = JSON.parse(String(init?.body));
  const id = route.split("/")[2];
  let fact = facts.find((item) => item.id === id);
  if (id && !fact)
    return Response.json({ detail: "Fact not found" }, { status: 404 });
  if (fact && body.expected_version !== fact.row_version)
    return Response.json(
      { detail: "Fact changed. Review the latest revision." },
      { status: 409 },
    );
  if (route.endsWith("/reviews") && fact) {
    if (fact.current.id !== body.revision_id)
      return Response.json({ detail: "Wrong revision" }, { status: 409 });
    fact.current.review_state = body.decision;
    fact.active = body.decision === "approved" ? { ...fact.current } : null;
    fact.row_version += 1;
  } else {
    if (!fact) {
      fact = {
        ...legacy,
        id: `synthetic-fact-${facts.length + 1}`,
        field: body.field,
        active: null,
        row_version: 0,
      };
      facts.push(fact);
    }
    fact.row_version += 1;
    fact.current = {
      ...legacy.current,
      id: `${fact.id}-v${fact.row_version}`,
      version: fact.row_version,
      value: body.value,
      context: body.context ?? null,
      review_state: "proposed",
      source_version_id: body.source_version_id ?? null,
      source_excerpt: body.source_excerpt ?? null,
      career: body.value.startsWith("{") ? JSON.parse(body.value) : null,
      career_suggestion: null,
    };
  }
  receipts[receipt] = fact;
  sessionStorage.setItem(key, JSON.stringify(facts));
  sessionStorage.setItem(receiptsKey, JSON.stringify(receipts));
  loseReply();
  return Response.json(fact);
}
