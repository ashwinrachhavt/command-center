import type { Schema } from "../../src/lib/api";

// Synthetic server persistence shared across reloads and tabs in one browser context.
export async function writingFixture(url: URL, init?: RequestInit) {
  const route = url.pathname.replace("/api/backend/", "");
  const match = route.match(
    /^writing-drafts\/([a-zA-Z0-9_-]+)(\/(?:clear|recovery)(?:\/[^/]+)?)?$/,
  );
  if (!match) return null;
  const key = `synthetic-writing-server:${match[1]}`;
  const recoveryKey = `${key}:recovery`;
  let copies: Schema["RecoveryRead"][] = JSON.parse(
    localStorage.getItem(recoveryKey) ?? "[]",
  );
  if (match[2]?.startsWith("/recovery")) {
    const id = match[2].split("/")[2];
    if (id) {
      const copy = copies.find((item) => item.id === id);
      return copy
        ? Response.json(copy)
        : Response.json({ detail: "Missing copy" }, { status: 404 });
    }
    const before = Number(url.searchParams.get("before") ?? Infinity);
    const items = copies.filter((copy) => copy.row_version < before);
    return Response.json({
      items: items
        .slice(0, 10)
        .map(({ id, row_version, created_at }) => ({
          id,
          row_version,
          created_at,
        })),
      total: copies.length,
      next_before: items.length > 10 ? items[9].row_version : null,
    });
  }
  const saved = localStorage.getItem(key);
  let draft: Schema["DraftRead"] = saved
    ? JSON.parse(saved)
    : {
        scope_key: match[1],
        data: null,
        row_version: 0,
        updated_at: null,
        last_save_key: null,
      };
  if (init?.method && init.method !== "GET") {
    const body = JSON.parse(String(init.body));
    const receipt = new Headers(init.headers).get("Idempotency-Key");
    if (receipt !== draft.last_save_key) {
      if (body.expected_version !== draft.row_version)
        return Response.json({ detail: "Draft changed" }, { status: 409 });
      const previous = draft;
      draft = {
        ...draft,
        data: match[2] ? null : body.data,
        row_version: draft.row_version + 1,
        last_save_key: receipt,
        updated_at: new Date().toISOString(),
      };
      localStorage.setItem(key, JSON.stringify(draft));
      const retained = match[2] === "/clear" ? previous : draft;
      if (
        retained.data &&
        copies[0]?.row_version !== retained.row_version &&
        (match[2] === "/clear" ||
          previous.data === null ||
          !copies.length ||
          Date.now() - Date.parse(copies[0].created_at) >= 300_000)
      ) {
        copies = [
          {
            id: crypto.randomUUID(),
            data: retained.data,
            row_version: retained.row_version,
            created_at: new Date().toISOString(),
          },
          ...copies,
        ].slice(0, 20);
        localStorage.setItem(recoveryKey, JSON.stringify(copies));
      }
    }
  }
  return Response.json(draft);
}
