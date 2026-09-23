import { api, ApiError, type Schema } from "./api";
import { requestSignature } from "./retained-intent";

type SavedDraft = Schema["DraftRead"];
type Pending<T> = {
  key: string;
  expectedVersion: number;
  data: T | null;
  clearing?: T;
};
type Journal<T> = {
  base: number;
  data: T;
  pending?: Pending<T>;
  intent?: {
    signature: string;
    key: string;
    method: "POST" | "PATCH";
    target: string;
    body: unknown;
    snapshot: T;
  };
};
export type DraftState<T> = {
  data: T;
  status: "loading" | "ready" | "saving" | "saved" | "error" | "conflict";
  error?: string;
  recoveryWarning?: string;
  recovered: boolean;
  editorRevision: number;
  remote?: T | null;
  recovery?: T | null;
};
type Transport<T> = {
  read: () => Promise<SavedDraft>;
  write: (request: Pending<T>) => Promise<SavedDraft>;
};
function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === "object")
    return Object.fromEntries(
      Object.entries(value)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, canonical(item)]),
    );
  return value;
}
const equal = (left: unknown, right: unknown) =>
  JSON.stringify(canonical(left)) === JSON.stringify(canonical(right));

/** One working copy; server CAS serializes tabs, a tab-local journal survives refresh.
 * Session storage is intentionally isolated between tabs, even when a tab is duplicated.
 * Neither autosave nor recovery creates a checkpoint or grants action authority.
 */
export class WorkingDraft<T extends object> {
  private state: DraftState<T>;
  private listeners = new Set<() => void>();
  private journal: Journal<T>;
  private serverData: T | null = null;
  private loaded = false;
  private hasJournal = false;
  private active = true;
  private initialization?: Promise<void>;
  private timer?: ReturnType<typeof setTimeout>;
  private inFlight?: Promise<void>;
  private storage?: Storage;
  private readonly storageKey: string;
  private readonly transport: Transport<T>;

  constructor(
    readonly actor: string,
    readonly scope: string,
    private initial: T,
    options: { storage?: Storage; transport?: Transport<T> } = {},
  ) {
    this.storageKey = `cc-writing-v1:${actor}:${scope}`;
    this.state = {
      data: initial,
      status: "loading",
      recovered: false,
      editorRevision: 0,
    };
    this.journal = { data: initial, base: 0 };
    try {
      this.storage = options.storage ?? window.sessionStorage;
      const raw = this.storage.getItem(this.storageKey);
      if (raw) {
        const journal = JSON.parse(raw) as Journal<T>;
        if (
          Number.isInteger(journal.base) &&
          journal.base >= 0 &&
          journal.data &&
          typeof journal.data === "object" &&
          !Array.isArray(journal.data)
        ) {
          this.journal = journal;
          this.hasJournal = true;
          this.state = { ...this.state, data: journal.data, recovered: true };
        }
      }
      const recovery = this.storage.getItem(`${this.storageKey}:recovery`);
      if (recovery)
        this.state.recovery = (JSON.parse(recovery) as { data: T | null }).data;
    } catch {
      this.state.recoveryWarning =
        "Tab recovery is unavailable. Keep this page open until your draft is saved.";
    }
    const path = `writing-drafts/${scope}`;
    this.transport = options.transport ?? {
      read: () => api<SavedDraft>(path),
      write: (request) =>
        api<SavedDraft>(request.data === null ? `${path}/clear` : path, {
          method: request.data === null ? "POST" : "PUT",
          key: request.key,
          body: {
            expected_version: request.expectedVersion,
            ...(request.data === null ? {} : { data: request.data }),
          },
        }),
    };
  }

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };
  getSnapshot = () => this.state;
  get hasCheckpoint() {
    return !!this.journal.intent;
  }
  private emit(patch: Partial<DraftState<T>>) {
    this.state = { ...this.state, ...patch };
    this.listeners.forEach((listener) => listener());
  }
  private persist() {
    if (!this.active) return;
    try {
      if (this.dirty || this.journal.pending || this.journal.intent)
        this.storage?.setItem(this.storageKey, JSON.stringify(this.journal));
      else this.storage?.removeItem(this.storageKey);
    } catch {
      this.emit({
        recoveryWarning:
          "Tab recovery is unavailable. Keep this page open until your draft is saved.",
      });
    }
  }
  private get dirty() {
    return !equal(this.journal.data, this.serverData ?? this.initial);
  }

  async load() {
    try {
      const remote = await this.transport.read();
      this.loaded = true;
      this.serverData = remote.data as T | null;
      if (this.hasJournal) {
        const pending = this.journal.pending;
        if (pending && remote.last_save_key === pending.key) {
          if (
            pending.data === null &&
            equal(this.journal.data, pending.clearing)
          )
            this.journal.data = this.initial;
          this.journal.base = remote.row_version;
          this.journal.pending = undefined;
        } else if (equal(this.journal.data, remote.data ?? this.initial)) {
          this.journal.base = remote.row_version;
          this.journal.pending = undefined;
        } else if (remote.row_version !== this.journal.base) {
          this.emit({
            status: "conflict",
            remote: this.serverData,
            error:
              "This draft changed in another tab. Your writing is still here.",
          });
          return;
        }
      } else {
        this.journal = {
          base: remote.row_version,
          data: this.serverData ?? this.initial,
        };
      }
      this.emit({
        data: this.journal.data,
        editorRevision: this.state.editorRevision + 1,
        status: this.dirty ? "ready" : "saved",
        error: undefined,
      });
      this.persist();
      if (this.dirty || this.journal.pending) this.schedule();
    } catch (error) {
      this.emit({ status: "error", error: message(error) });
    }
  }

  edit(update: T | ((current: T) => T)) {
    const next =
      typeof update === "function" ? update(this.journal.data) : update;
    if (equal(next, this.journal.data)) return;
    this.hasJournal = true;
    this.journal.data = next;
    this.emit({
      data: this.journal.data,
      ...(["saved", "ready"].includes(this.state.status)
        ? {
            status:
              this.dirty || this.journal.pending
                ? ("ready" as const)
                : ("saved" as const),
          }
        : {}),
    });
    this.persist();
    this.schedule();
  }
  private schedule() {
    clearTimeout(this.timer);
    if (
      this.active &&
      this.loaded &&
      this.state.status !== "conflict" &&
      this.state.status !== "error"
    )
      this.timer = setTimeout(() => {
        void this.flush().catch(() => {});
      }, 800);
  }
  start() {
    this.active = true;
    this.initialization ??= this.load();
    return this.initialization;
  }
  stop() {
    this.active = false;
    clearTimeout(this.timer);
  }

  private async sendPending() {
    const pending = this.journal.pending!;
    this.emit({ status: "saving", error: undefined });
    try {
      const saved = await this.transport.write(pending);
      this.serverData = saved.data as T | null;
      this.journal.base = saved.row_version;
      this.journal.pending = undefined;
      if (pending.data === null && equal(this.journal.data, pending.clearing)) {
        this.journal.data = this.initial;
        this.emit({ editorRevision: this.state.editorRevision + 1 });
      }
      this.persist();
      this.emit({
        data: this.journal.data,
        status: this.dirty ? "ready" : "saved",
      });
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        let remote: T | null | undefined;
        try {
          remote = (await this.transport.read()).data as T | null;
        } catch {
          /* local copy survives */
        }
        this.emit({
          status: "conflict",
          remote,
          error:
            "This draft changed in another tab. Your writing is still here.",
        });
      } else {
        if (
          error instanceof ApiError &&
          [400, 413, 422].includes(error.status)
        ) {
          // A rejected validation never committed; a corrected draft needs a new request.
          this.journal.pending = undefined;
          this.persist();
        }
        this.emit({ status: "error", error: message(error) });
      }
      throw error;
    }
  }

  async flush(): Promise<void> {
    clearTimeout(this.timer);
    while (this.inFlight) await this.inFlight;
    if (!this.active)
      throw new Error("The writer has closed. Your draft remains in this tab.");
    if (!this.loaded) {
      await this.load();
      if (!this.loaded) throw new Error(this.state.error);
    }
    if (this.state.status === "conflict") throw new Error(this.state.error);
    if (!this.dirty && !this.journal.pending) {
      this.emit({ status: "saved", error: undefined });
      return;
    }
    const work = async () => {
      while (this.dirty || this.journal.pending) {
        if (!this.active) return;
        this.journal.pending ??= {
          key: crypto.randomUUID(),
          expectedVersion: this.journal.base,
          data: this.journal.data,
        };
        this.persist();
        await this.sendPending();
      }
    };
    this.inFlight = work();
    try {
      await this.inFlight;
    } finally {
      this.inFlight = undefined;
    }
  }

  /** Clear only the exact checkpointed text; later typing remains a working draft. */
  async clearIfUnchanged(checkpoint: T): Promise<boolean> {
    await this.flush();
    if (this.serverData === null && !this.dirty) return true;
    if (!equal(this.journal.data, checkpoint)) return false;
    this.journal.pending = {
      key: crypto.randomUUID(),
      expectedVersion: this.journal.base,
      data: null,
      clearing: checkpoint,
    };
    this.persist();
    this.inFlight = this.sendPending();
    try {
      await this.inFlight;
    } finally {
      this.inFlight = undefined;
    }
    if (this.dirty) {
      this.schedule();
      return false;
    }
    return true;
  }

  request(
    method: "POST" | "PATCH",
    target: string,
    body: unknown,
    snapshot: T,
  ) {
    const signature = requestSignature(method, target, body);
    // Until acknowledged, retry the same checkpoint even if the writer has moved on.
    if (!this.journal.intent) {
      this.journal.intent = {
        signature,
        key: crypto.randomUUID(),
        method,
        target,
        body,
        snapshot,
      };
      this.persist();
      this.emit({});
    }
    return this.journal.intent;
  }
  resetIntent() {
    this.journal.intent = undefined;
    this.persist();
    this.emit({});
  }

  async resolveConflict(choice: "local" | "remote") {
    const remote = await this.transport.read();
    // Retain the copy being replaced for explicit, reversible conflict recovery.
    try {
      const recovery =
        choice === "remote" ? this.journal.data : (remote.data as T | null);
      this.storage?.setItem(
        `${this.storageKey}:recovery`,
        JSON.stringify({
          data: recovery,
          savedAt: new Date().toISOString(),
        }),
      );
      this.emit({ recovery });
    } catch {
      throw new Error(
        "Could not keep the other copy. Copy it somewhere safe before resolving this conflict.",
      );
    }
    this.serverData = remote.data as T | null;
    this.journal.base = remote.row_version;
    this.journal.pending = undefined;
    this.journal.intent = undefined;
    if (choice === "remote")
      this.journal.data = this.serverData ?? this.initial;
    this.emit({
      data: this.journal.data,
      editorRevision: this.state.editorRevision + 1,
      status: "ready",
      error: undefined,
      remote: undefined,
    });
    this.persist();
    await this.flush();
    this.emit({ status: "saved" });
  }

  recoverOtherCopy() {
    const recovery = this.state.recovery;
    if (!recovery) return;
    this.restoreRecovery(recovery);
  }

  restoreRecovery(recovery: T) {
    if (!this.loaded || this.state.status === "conflict")
      throw new Error(
        "Resolve the saved draft before restoring an earlier copy.",
      );
    const current = this.journal.data;
    this.storage?.setItem(
      `${this.storageKey}:recovery`,
      JSON.stringify({ data: current, savedAt: new Date().toISOString() }),
    );
    this.edit(recovery);
    this.emit({
      recovery: current,
      editorRevision: this.state.editorRevision + 1,
    });
  }
}

function message(error: unknown) {
  return error instanceof Error
    ? error.message
    : "Your draft could not be saved.";
}
