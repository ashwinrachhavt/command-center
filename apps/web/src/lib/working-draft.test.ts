import { afterEach, expect, it, vi } from "vitest";
import { ApiError, type Schema } from "./api";
import { WorkingDraft } from "./working-draft";

type Content = { text: string };
type Saved = Schema["DraftRead"];
const initial: Content = { text: "" };
const stores: WorkingDraft<Content>[] = [];
afterEach(() => {
  stores.forEach((store) => store.stop());
  stores.length = 0;
  sessionStorage.clear();
});

function server() {
  let remote: Saved = {
    scope_key: "email-new",
    data: null,
    row_version: 0,
    updated_at: null,
    last_save_key: null,
  };
  const read = vi.fn(async () => structuredClone(remote));
  const write = vi.fn(
    async (request: {
      key: string;
      expectedVersion: number;
      data: Content | null;
    }) => {
      if (remote.last_save_key === request.key) return structuredClone(remote);
      if (remote.row_version !== request.expectedVersion)
        throw new ApiError(409, "Changed");
      remote = {
        ...remote,
        data: request.data,
        last_save_key: request.key,
        row_version: remote.row_version + 1,
      };
      return structuredClone(remote);
    },
  );
  return { read, write };
}
function storage(): Storage {
  const data = new Map<string, string>();
  return {
    getItem: (key) => data.get(key) ?? null,
    setItem: (key, value) => {
      data.set(key, value);
    },
    removeItem: (key) => {
      data.delete(key);
    },
    clear: () => data.clear(),
    key: (index) => [...data.keys()][index] ?? null,
    get length() {
      return data.size;
    },
  };
}
function writer(
  transport: ReturnType<typeof server>,
  local = storage(),
  actor = "synthetic-owner",
) {
  const store = new WorkingDraft(actor, "email-new", initial, {
    storage: local,
    transport,
  });
  stores.push(store);
  return store;
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((yes) => {
    resolve = yes;
  });
  return { promise, resolve };
}

it("serializes saves and keeps typing newer than an acknowledgement", async () => {
  const remote = server();
  const originalWrite = remote.write.getMockImplementation()!;
  const first = deferred<Saved>();
  remote.write.mockImplementationOnce(() => first.promise);
  const draft = writer(remote);
  await draft.start();
  draft.edit({ text: "First sentence" });
  const flush = draft.flush();
  draft.edit({ text: "First sentence. Still writing." });
  first.resolve(await originalWrite(remote.write.mock.calls[0][0]));
  await flush;
  expect(draft.getSnapshot().data.text).toBe("First sentence. Still writing.");
  expect(
    remote.write.mock.calls.map(([request]) => request.expectedVersion),
  ).toEqual([0, 1]);
  expect((await remote.read()).data).toEqual(draft.getSnapshot().data);
});

it("recovers a lost acknowledgement after refresh, including newer local text", async () => {
  const remote = server();
  const local = storage();
  const originalWrite = remote.write.getMockImplementation()!;
  remote.write.mockImplementationOnce(async (request) => {
    await originalWrite(request);
    throw new TypeError("Connection interrupted after commit");
  });
  const first = writer(remote, local);
  await first.start();
  first.edit({ text: "Saved remotely" });
  await expect(first.flush()).rejects.toThrow("interrupted");
  first.edit({ text: "Saved remotely, then kept writing" });
  first.stop();
  const reopened = writer(remote, local);
  await reopened.start();
  expect(reopened.getSnapshot()).toMatchObject({
    recovered: true,
    data: { text: "Saved remotely, then kept writing" },
  });
  await reopened.flush();
  expect(remote.write).toHaveBeenCalledTimes(2);
  expect(remote.write.mock.calls[1][0].expectedVersion).toBe(1);
  expect(local.length).toBe(0);
});

it("retries an uncertain write with its original key and body before saving later text", async () => {
  const remote = server();
  remote.write.mockRejectedValueOnce(new TypeError("Offline"));
  const draft = writer(remote);
  await draft.start();
  draft.edit({ text: "First copy" });
  await expect(draft.flush()).rejects.toThrow("Offline");
  draft.edit({ text: "Newer copy" });
  await draft.flush();
  expect(remote.write.mock.calls[0][0]).toEqual(remote.write.mock.calls[1][0]);
  expect(remote.write.mock.calls[2][0].data).toEqual({ text: "Newer copy" });
});

it("isolates tabs, rejects stale edits and retains the replaced conflict copy", async () => {
  const remote = server();
  const first = writer(remote);
  const second = writer(remote);
  await Promise.all([first.start(), second.start()]);
  first.edit({ text: "First tab" });
  second.edit({ text: "Second tab" });
  await first.flush();
  await expect(second.flush()).rejects.toThrow("Changed");
  expect(second.getSnapshot()).toMatchObject({
    status: "conflict",
    data: { text: "Second tab" },
    remote: { text: "First tab" },
  });
  await second.resolveConflict("local");
  expect((await remote.read()).data).toEqual({ text: "Second tab" });
  expect(second.getSnapshot().recovery).toEqual({ text: "First tab" });
  second.recoverOtherCopy();
  expect(second.getSnapshot().data).toEqual({ text: "First tab" });
  expect(second.getSnapshot().recovery).toEqual({ text: "Second tab" });
});

it("does not erase typing that arrives while checkpoint cleanup is in flight", async () => {
  const remote = server();
  const originalWrite = remote.write.getMockImplementation()!;
  const draft = writer(remote);
  await draft.start();
  const checkpoint = { text: "Checkpoint" };
  draft.edit(checkpoint);
  await draft.flush();
  const clear = deferred<Saved>();
  remote.write.mockImplementationOnce(() => clear.promise);
  const clearing = draft.clearIfUnchanged(checkpoint);
  await vi.waitFor(() => expect(remote.write).toHaveBeenCalledTimes(2));
  draft.edit({ text: "Checkpoint plus another sentence" });
  clear.resolve(await originalWrite(remote.write.mock.calls[1][0]));
  expect(await clearing).toBe(false);
  await draft.flush();
  expect((await remote.read()).data).toEqual({
    text: "Checkpoint plus another sentence",
  });
  expect(remote.write.mock.calls[2][0].expectedVersion).toBe(2);
});

it("retains an uncertain checkpoint across refresh without substituting newer writing", async () => {
  const remote = server();
  const local = storage();
  const first = writer(remote, local);
  await first.start();
  first.edit({ text: "Checkpoint" });
  await first.flush();
  const request = first.request(
    "POST",
    "reviewed-actions",
    { body: "Checkpoint" },
    first.getSnapshot().data,
  );
  first.edit({ text: "Newer writing" });
  first.stop();
  const reopened = writer(remote, local);
  await reopened.start();
  expect(
    reopened.request(
      "POST",
      "reviewed-actions",
      { body: "Newer writing" },
      reopened.getSnapshot().data,
    ),
  ).toEqual(request);
  expect(reopened.getSnapshot().data.text).toBe("Newer writing");
});

it("never loads another actor's tab recovery", async () => {
  const local = storage();
  const first = writer(server(), local, "first-owner");
  await first.start();
  first.edit({ text: "Private first draft" });
  first.stop();
  const second = writer(server(), local, "second-owner");
  await second.start();
  expect(second.getSnapshot().data).toEqual(initial);
  expect(second.getSnapshot().recovered).toBe(false);
});

it("does not issue a later write after its owning writer closes", async () => {
  const remote = server();
  const first = deferred<Saved>();
  const originalWrite = remote.write.getMockImplementation()!;
  remote.write.mockImplementationOnce(() => first.promise);
  const draft = writer(remote);
  await draft.start();
  draft.edit({ text: "First" });
  const flush = draft.flush();
  draft.edit({ text: "Newer" });
  draft.stop();
  first.resolve(await originalWrite(remote.write.mock.calls[0][0]));
  await flush;
  expect(remote.write).toHaveBeenCalledTimes(1);
  expect(draft.getSnapshot().data.text).toBe("Newer");
});

it("an old acknowledgement cannot delete the reopened writer's recovery journal", async () => {
  const remote = server();
  const local = storage();
  const reply = deferred<Saved>();
  const originalWrite = remote.write.getMockImplementation()!;
  remote.write.mockImplementationOnce(() => reply.promise);
  const first = writer(remote, local);
  await first.start();
  first.edit({ text: "Original request" });
  const saving = first.flush();
  first.stop();
  const reopened = writer(remote, local);
  await reopened.start();
  reopened.edit({ text: "Reopened and still writing" });
  reply.resolve(await originalWrite(remote.write.mock.calls[0][0]));
  await saving;
  reopened.stop();
  const refreshed = writer(remote, local);
  await refreshed.start();
  expect(refreshed.getSnapshot().data.text).toBe("Reopened and still writing");
  await refreshed.flush();
  expect((await remote.read()).data).toEqual({
    text: "Reopened and still writing",
  });
});

it("a corrected draft can be saved after a definitive validation rejection", async () => {
  const remote = server();
  remote.write.mockRejectedValueOnce(new ApiError(422, "Draft too large"));
  const draft = writer(remote);
  await draft.start();
  draft.edit({ text: "Large draft" });
  await expect(draft.flush()).rejects.toThrow("too large");
  draft.edit({ text: "Short draft" });
  await draft.flush();
  expect(remote.write.mock.calls[1][0].data).toEqual({ text: "Short draft" });
  expect(remote.write.mock.calls[1][0].key).not.toBe(
    remote.write.mock.calls[0][0].key,
  );
});

it("same-value updates and undoing back to the saved copy do not leave an unsaved status", async () => {
  const draft = writer(server());
  await draft.start();
  draft.edit({ text: "" });
  expect(draft.getSnapshot().status).toBe("saved");
  draft.edit({ text: "A change" });
  draft.edit({ text: "" });
  expect(draft.getSnapshot().status).toBe("saved");
});
