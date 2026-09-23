type Row = Record<string, unknown>;
type State = {
  documents: Row[];
  versions: Record<string, Row[]>;
  tasks: Row[];
  links: Record<string, string[]>;
  receipts: Record<string, Row>;
};
const storage = "synthetic-library-v1";
const stamp = "2026-09-22T10:00:00Z";
function seed(): State {
  const documents = [
    [
      "note-library-interview",
      "Northstar · interview notes",
      "The team is exploring a new platform. Ask about developer ownership.",
    ],
    [
      "note-library-ideas",
      "Ideas worth returning to",
      "A quiet place for half-formed thoughts and unexpected connections.",
    ],
    [
      "note-library-week",
      "This week",
      "Make three meaningful connections. Leave room to follow a good idea.",
    ],
  ].map(([id, title]) => ({
    id,
    title,
    kind: "document",
    document_type_id: "document-type-notes",
    sensitivity: "private",
    row_version: 1,
    latest_version: 1,
    created_at: stamp,
    updated_at: stamp,
    archived_at: null,
  }));
  const texts = [
    "The team is exploring a new platform. Ask about developer ownership.",
    "A quiet place for half-formed thoughts and unexpected connections.",
    "Make three meaningful connections. Leave room to follow a good idea.",
  ];
  return {
    documents,
    versions: Object.fromEntries(
      documents.map((item, index) => [
        item.id,
        [
          {
            id: `${item.id}-v1`,
            artifact_id: item.id,
            version: 1,
            payload: { text: texts[index] },
            created_at: stamp,
            content_sha256: "synthetic",
            input_version_ids: [],
          },
        ],
      ]),
    ),
    tasks: [],
    links: {},
    receipts: {},
  };
}
export async function libraryFixture(
  url: URL,
  init: RequestInit | undefined,
  rows: Record<string, Row[]>,
  imports: Row[] = [],
) {
  const route = url.pathname.replace("/api/backend/", "");
  const method = init?.method ?? "GET";
  const state: State =
    JSON.parse(localStorage.getItem(storage) ?? "null") ?? seed();
  const save = () => localStorage.setItem(storage, JSON.stringify(state));
  const page = (items: Row[]) => {
    const limit = Number(url.searchParams.get("limit") ?? 30);
    const offset = Number(url.searchParams.get("offset") ?? 0);
    return Response.json({
      items: items.slice(offset, offset + limit),
      total: items.length,
      limit,
      offset,
    });
  };
  const key = new Headers(init?.headers).get("Idempotency-Key") ?? "";
  if (route === "test/library") return Response.json(state);
  if (
    route === "artifacts" &&
    method === "GET" &&
    (url.searchParams.has("collection") || url.searchParams.has("task_id"))
  ) {
    let list = [...state.documents, ...rows.artifacts].filter(
      (item) => !item.archived_at,
    );
    if (url.searchParams.get("collection") === "notes")
      list = list.filter(
        (item) => item.document_type_id === "document-type-notes",
      );
    const collection = url.searchParams.get("collection");
    if (["library", "vault", "notes", "generated"].includes(collection ?? ""))
      list = list.filter(
        (item) =>
          !imports.some((entry) => entry.extraction_artifact_id === item.id) &&
          (collection === "vault"
            ? imports.some((entry) => entry.artifact_id === item.id)
            : !imports.some((entry) => entry.artifact_id === item.id)),
      );
    if (collection === "generated")
      list = list.filter((item) => item.id === "artifact-generated-brief");
    list = list.map((item) => ({
      ...item,
      review_status: item.review_status ?? "unreviewed",
    }));
    const review = url.searchParams.get("review");
    if (review) list = list.filter((item) => item.review_status === review);
    if (url.searchParams.has("task_id"))
      list = list.filter((item) =>
        state.links[String(item.id)]?.includes(
          url.searchParams.get("task_id")!,
        ),
      );
    const type = url.searchParams.get("document_type_id");
    if (type) list = list.filter((item) => item.document_type_id === type);
    const q = (url.searchParams.get("q") ?? "").toLowerCase();
    if (q)
      list = list.filter((item) =>
        `${item.title} ${(state.versions[String(item.id)]?.[0]?.payload as Row)?.text ?? ""}`
          .toLowerCase()
          .includes(q),
      );
    if (url.searchParams.get("sort") === "title")
      list.sort((a, b) => String(a.title).localeCompare(String(b.title)));
    return page(list);
  }
  if (route === "artifacts" && method === "POST") {
    const body = JSON.parse(String(init?.body));
    if (body.document_type_id !== "document-type-notes") return null;
    if (state.receipts[key])
      return Response.json(state.receipts[key], { status: 201 });
    const id = `note-library-${crypto.randomUUID()}`;
    const note = {
      ...state.documents[0],
      id,
      title: body.title,
      row_version: 1,
      latest_version: 1,
    };
    state.documents.unshift(note);
    state.versions[id] = [
      {
        id: `${id}-v1`,
        artifact_id: id,
        version: 1,
        payload: { text: body.text },
        created_at: stamp,
        content_sha256: "synthetic",
        input_version_ids: [],
      },
    ];
    state.receipts[key] = note;
    save();
    return Response.json(note, { status: 201 });
  }
  const task = state.tasks.find((item) => route === `tasks/${item.id}`);
  if (task) return Response.json(task);
  const linked = route.match(/^artifacts\/([^/]+)\/tasks$/);
  if (linked) {
    if (method === "GET")
      return page(
        state.tasks.filter((item) =>
          state.links[linked[1]]?.includes(String(item.id)),
        ),
      );
    if (state.receipts[key])
      return Response.json(state.receipts[key], { status: 201 });
    const task = {
      id: `task-note-${crypto.randomUUID()}`,
      ...JSON.parse(String(init?.body)),
      row_version: 1,
      state: "open",
      created_at: stamp,
      updated_at: stamp,
      completed_at: null,
      due_at: null,
    };
    state.tasks.unshift(task);
    (state.links[linked[1]] ??= []).push(task.id);
    state.receipts[key] = task;
    save();
    return Response.json(task, { status: 201 });
  }
  const match = route.match(/^artifacts\/(note-library-[^/]+)(.*)$/);
  if (!match) return null;
  const note = state.documents.find((item) => item.id === match[1]);
  if (!note) return Response.json({ detail: "Note missing" }, { status: 404 });
  if (!match[2]) {
    if (method === "PATCH") {
      const body = JSON.parse(String(init?.body));
      if (body.expected_version !== note.row_version)
        return Response.json({ detail: "Document changed" }, { status: 409 });
      Object.assign(note, {
        title: body.title,
        sensitivity: body.sensitivity,
        row_version: Number(note.row_version) + 1,
      });
      save();
    }
    return Response.json(note);
  }
  const versions = state.versions[match[1]];
  if (match[2] === "/version-history")
    return Response.json({
      items: versions.map((row) => ({
        id: row.id,
        artifact_id: row.artifact_id,
        version: row.version,
        created_at: row.created_at,
        content_sha256: row.content_sha256,
        is_text: true,
        has_file: false,
      })),
      total: versions.length,
      next_before: null,
    });
  if (match[2] === "/versions" && method === "POST") {
    if (state.receipts[key])
      return Response.json(state.receipts[key], { status: 201 });
    const body = JSON.parse(String(init?.body));
    if (body.expected_version !== note.row_version)
      return Response.json({ detail: "Document changed" }, { status: 409 });
    const version = {
      ...versions[0],
      id: `${match[1]}-v${versions.length + 1}`,
      version: versions.length + 1,
      payload: { text: body.text },
    };
    versions.unshift(version);
    note.latest_version = versions.length;
    note.row_version = Number(note.row_version) + 1;
    state.receipts[key] = version;
    save();
    return Response.json(version, { status: 201 });
  }
  if (match[2].startsWith("/versions/"))
    return Response.json(
      versions.find((item) => item.id === match[2].split("/")[2]),
    );
  if (match[2] === "/versions") return Response.json(versions);
  return null;
}
