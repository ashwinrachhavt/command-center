import type { Schema } from "../../src/lib/api";

type Saved = Schema["FollowUpRead"];
const storageKey = "synthetic-follow-ups";
export async function followUpFixture(url: URL, init?: RequestInit) {
  const route = url.pathname.replace("/api/backend/", "");
  const list = route.match(/^contacts\/([^/]+)\/follow-ups$/);
  const detail = route.match(/^follow-ups\/([^/]+)$/);
  const source = route.match(/^documents\/versions\/([^/]+)\/text$/);
  if (!list && !detail && !source) return null;
  const store: Record<string, Saved> = JSON.parse(
    localStorage.getItem(storageKey) ?? "{}",
  );
  const method = init?.method ?? "GET";
  if (source) {
    const saved = Object.values(store).find(
      (item) => item.version.id === source[1],
    );
    if (!saved) return null;
    const text = String(saved.version.payload?.text ?? "");
    return Response.json({
      artifact_id: saved.artifact.id,
      version_id: source[1],
      title: saved.artifact.title,
      text,
      offset: 0,
      next_offset: null,
      total_chars: text.length,
    });
  }
  if (method === "GET") {
    if (detail)
      return store[detail[1]]
        ? Response.json(store[detail[1]])
        : Response.json({ detail: "Missing draft" }, { status: 404 });
    const items = Object.values(store)
      .filter((item) => item.contact_id === list![1])
      .reverse();
    const offset = Number(url.searchParams.get("offset") ?? 0);
    return Response.json({
      items: items.slice(offset, offset + 10).map((item) => ({
        artifact_id: item.artifact.id,
        title: item.artifact.title,
        row_version: item.artifact.row_version,
        version_id: item.version.id,
        version: item.version.version,
        updated_at: item.artifact.updated_at,
        channel: item.version.payload?.channel,
        subject: item.version.payload?.subject,
        preview: item.plain_text,
      })),
      total: items.length,
      offset,
      limit: 10,
    });
  }
  const receipt = new Headers(init?.headers).get("Idempotency-Key");
  const receiptKey = `synthetic-follow-up-receipt:${receipt}`;
  const replay = localStorage.getItem(receiptKey);
  if (replay) return Response.json(JSON.parse(replay));
  const body = JSON.parse(String(init?.body));
  const previous = detail ? store[detail[1]] : undefined;
  if (detail && previous?.artifact.row_version !== body.expected_version)
    return Response.json(
      {
        detail:
          "This follow-up changed. Keep your draft and save another version.",
      },
      { status: 409 },
    );
  const id = previous?.artifact.id ?? crypto.randomUUID();
  const text = String(body.text ?? "");
  // Synthetic fixture conversion only; production uses a non-rendering HTML parser.
  const plain =
    body.format === "html"
      ? text
          .replace(/<\/(p|div|li)>/g, "\n")
          .replace(/<[^>]*>/g, "")
          .replace(/\n$/, "")
      : text;
  const created: Saved = {
    contact_id: previous?.contact_id ?? list![1],
    plain_text: plain,
    artifact: {
      id,
      title: "Follow-up · Alex Morgan",
      kind: "message",
      sensitivity: "private",
      archived_at: null,
      row_version: (previous?.artifact.row_version ?? 0) + 1,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      latest_version: (previous?.version.version ?? 0) + 1,
      review_status: "unreviewed",
      document_type_id: null,
    },
    version: {
      id: crypto.randomUUID(),
      artifact_id: id,
      version: (previous?.version.version ?? 0) + 1,
      payload: {
        ...body,
        ...(previous?.version.payload?.connection_note
          ? {
              connection_note: true,
              contact_research: previous.version.payload.contact_research,
            }
          : {}),
      },
      input_version_ids: previous ? [previous.version.id] : [],
      content_sha256: `synthetic-${id}`,
      created_at: new Date().toISOString(),
    },
  };
  store[id] = created;
  localStorage.setItem(storageKey, JSON.stringify(store));
  localStorage.setItem(receiptKey, JSON.stringify(created));
  return Response.json(created, { status: method === "POST" ? 201 : 200 });
}
