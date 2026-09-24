import type { SpaceDetail, SpaceLink } from "../../src/lib/api";

const now = "2026-09-24T10:00:00Z";
const storageKey = "synthetic-spaces";
const spaces: SpaceDetail[] = JSON.parse(
  localStorage.getItem(storageKey) ?? "null",
) ?? [
  {
    id: "space-research",
    title: "Research planning",
    purpose: "Keep research questions and the next useful steps together.",
    state: "active",
    row_version: 1,
    archived_at: null,
    created_at: now,
    updated_at: now,
    links: [],
  },
  {
    id: "space-finished",
    title: "Finished review",
    purpose: "Retain the context of a completed review.",
    state: "archived",
    row_version: 2,
    archived_at: now,
    created_at: now,
    updated_at: now,
    links: [],
  },
];
const receipts = new Map<string, unknown>();
const requests: {
  path: string;
  method: string;
  key: string;
  body: Record<string, unknown>;
}[] = [];
const resourceFor = {
  task: "tasks",
  artifact: "artifacts",
  contact: "contacts",
  company: "companies",
  opportunity: "opportunities",
};

export async function spacesFixture(
  url: URL,
  init: RequestInit | undefined,
  rows: Record<string, Record<string, unknown>[]>,
) {
  const route = url.pathname.replace("/api/backend/", "");
  for (const item of spaces) {
    for (const link of item.links) {
      if (
        link.record_type === "task" &&
        !rows.tasks.some((task) => task.id === link.record_id)
      )
        rows.tasks.push(link.record);
    }
  }
  if (route === "test/space-requests") return Response.json(requests);
  if (route !== "spaces" && !route.startsWith("spaces/")) return null;
  const method = init?.method ?? "GET";
  const key = new Headers(init?.headers).get("Idempotency-Key") ?? "";
  const body: Record<string, unknown> = init?.body
    ? JSON.parse(String(init.body))
    : {};
  if (method !== "GET")
    requests.push({ path: route + url.search, method, key, body });
  const segments = route.split("/");
  const space = spaces.find((item) => item.id === segments[1]);
  if (method === "GET") {
    if (space) {
      for (const link of space.links) {
        const current = rows[resourceFor[link.record_type]]?.find(
          (record) => record.id === link.record_id,
        );
        if (current) link.record = current;
      }
      return Response.json(space);
    }
    if (segments.length > 1)
      return Response.json({ detail: "Space not found" }, { status: 404 });
    const state = url.searchParams.get("state") ?? "active";
    const search = (url.searchParams.get("q") ?? "").toLowerCase();
    const limit = Number(url.searchParams.get("limit") ?? 50);
    const offset = Number(url.searchParams.get("offset") ?? 0);
    const matches = spaces.filter(
      (item) =>
        (state === "all" || item.state === state) &&
        item.title.toLowerCase().includes(search),
    );
    return Response.json({
      items: matches.slice(offset, offset + limit),
      total: matches.length,
      limit,
      offset,
    });
  }
  if (receipts.has(key)) return Response.json(receipts.get(key));
  if (route === "spaces" && method === "POST") {
    const created: SpaceDetail = {
      id: crypto.randomUUID(),
      title: String(body.title),
      purpose: body.purpose ? String(body.purpose) : null,
      state: "active",
      row_version: 1,
      archived_at: null,
      created_at: now,
      updated_at: now,
      links: [],
    };
    spaces.unshift(created);
    localStorage.setItem(storageKey, JSON.stringify(spaces));
    receipts.set(key, structuredClone(created));
    return Response.json(created);
  }
  if (!space)
    return Response.json({ detail: "Space not found" }, { status: 404 });
  const action = segments[2];
  const version =
    action === "tasks"
      ? Number(url.searchParams.get("expected_version"))
      : body.expected_version;
  if (version !== space.row_version)
    return Response.json(
      { detail: "This Space changed. Refresh and try again." },
      { status: 409 },
    );
  if (space.state === "archived" && action !== "restore")
    return Response.json(
      { detail: "This Space is archived." },
      { status: 409 },
    );
  let result: unknown = space;
  if (method === "PATCH") {
    space.title = String(body.title);
    space.purpose = body.purpose ? String(body.purpose) : null;
  } else if (action === "archive" || action === "restore") {
    space.state = action === "archive" ? "archived" : "active";
    space.archived_at = action === "archive" ? now : null;
  } else if (action === "links" && segments[4] === "unlink") {
    space.links = space.links.filter((link) => link.id !== segments[3]);
  } else if (action === "links") {
    const kind = body.record_type as SpaceLink["record_type"];
    const record = rows[resourceFor[kind]]?.find(
      (item) => item.id === body.record_id,
    );
    if (!record)
      return Response.json({ detail: "Record not found" }, { status: 404 });
    if (
      !space.links.some(
        (link) => link.record_type === kind && link.record_id === record.id,
      )
    )
      space.links.push({
        id: crypto.randomUUID(),
        record_type: kind,
        record_id: String(record.id),
        record,
        created_at: now,
      });
  } else if (action === "tasks") {
    const task = {
      id: crypto.randomUUID(),
      ...body,
      state: "open",
      due_date: null,
      completed_at: null,
      row_version: 1,
      created_at: now,
      updated_at: now,
    };
    rows.tasks.push(task);
    space.links.push({
      id: crypto.randomUUID(),
      record_type: "task",
      record_id: task.id,
      record: task,
      created_at: now,
    });
    result = { space, task };
  } else
    return Response.json(
      { detail: "Unsupported Space fixture request" },
      { status: 404 },
    );
  space.row_version += 1;
  localStorage.setItem(storageKey, JSON.stringify(spaces));
  receipts.set(key, structuredClone(result));
  return Response.json(result);
}
