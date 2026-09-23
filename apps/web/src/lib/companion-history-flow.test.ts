import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, expect, it, vi } from "vitest";
import { waitFor } from "@testing-library/dom";
import type { components } from "./api-types";

type Snapshot = components["schemas"]["SnapshotCreate"];
type Preparation = components["schemas"]["ApplicationPreparationRead"];
type Targets = { experience: number; education: number };
type Expansion = {
  version: 2;
  action: "expand-history";
  id: string;
  snapshot_id: string;
  targets: Targets;
};
type Draft = {
  snapshot: Snapshot;
  preparation?: Preparation;
  autofill: { stage: string; historyRequest?: Expansion };
};
const read = (name: string) =>
  readFileSync(
    path.resolve(
      path.dirname(fileURLToPath(import.meta.url)),
      "../../../extension",
      name,
    ),
    "utf8",
  );
const popupHtml = read("popup.html").replace(/<script[\s\S]*?<\/script>/g, "");
const execute = new Function(
  "chrome",
  "fetch",
  `return (async()=>{${read("popup.js")}\n})();`,
);
const contracts = new Function(
  `${read("contracts.js")}\nreturn CommandCenterContracts;`,
)();
const button = (id: string) => document.getElementById(id) as HTMLButtonElement;

async function fixture(
  options: {
    state?:
      "expanded" | "unchanged" | "partial" | "rejected" | "outcome_unknown";
    targets?: Targets | null;
    loseExpansion?: boolean;
    loseCapture?: boolean;
    loseHistoryPrepare?: boolean;
    wrongIdentity?: boolean;
    emptyInitial?: "career" | "ordinary";
    wrongRefreshedTask?: boolean;
  } = {},
) {
  vi.stubGlobal("CommandCenterContracts", contracts);
  const tab = { id: 7, url: "https://jobs.example.test/apply?job=one" };
  const storage: { applicationDraft?: Draft; [key: string]: unknown } = {
    connection: {
      base: "http://localhost:8000",
      token: "synthetic-device-token",
    },
    pageReader: "agent-browser",
  };
  const taskId = randomUUID();
  const snapshots: Snapshot[] = [];
  const expansions: Expansion[] = [];
  const calls: { path: string; body: Record<string, unknown>; key?: string }[] =
    [];
  const receipts = new Map<string, Preparation>();
  const makeSnapshot = (): Snapshot => ({
    id: randomUUID(),
    protocol_version: 2,
    page_url: "https://jobs.example.test/apply",
    title: "Synthetic role",
    fields: [
      {
        id: "f0",
        label: "Full name",
        type: "text",
        autocomplete: "name",
        accept: "",
        option_labels: {},
        required: true,
        value_state: "empty",
        options: [],
      },
    ],
  });
  let loseExpansion = options.loseExpansion;
  let loseCapture = options.loseCapture;
  let loseHistoryPrepare = options.loseHistoryPrepare;
  const chrome = {
    storage: {
      local: {
        setAccessLevel: vi.fn(async () => {}),
        get: vi.fn(async () => structuredClone(storage)),
        set: vi.fn(async (values: Record<string, unknown>) =>
          Object.assign(storage, structuredClone(values)),
        ),
        remove: vi.fn(async (keys: string | string[]) => {
          for (const key of [keys].flat()) delete storage[key];
        }),
      },
    },
    tabs: {
      query: vi.fn(async () => [{ ...tab }]),
      sendMessage: vi.fn(
        async (_tabId: number, message: { action: "inspect" } | Expansion) => {
          if (message.action === "inspect") {
            const snapshot = makeSnapshot();
            if (options.emptyInitial && snapshots.length === 0)
              snapshot.fields = [];
            snapshots.push(snapshot);
            return {
              ...structuredClone(snapshot),
              ...(options.emptyInitial === "career" && snapshots.length === 1
                ? { history_expandable: true }
                : {}),
            };
          }
          expansions.push(structuredClone(message));
          if (loseExpansion) {
            loseExpansion = false;
            throw new Error("Synthetic lost expansion reply");
          }
          return {
            operation_id: options.wrongIdentity ? randomUUID() : message.id,
            snapshot_id: message.snapshot_id,
            state: options.state ?? "expanded",
            counts: { experience: 2, education: 1 },
            added:
              options.state === "unchanged"
                ? { experience: 0, education: 0 }
                : { experience: 1, education: 1 },
            message: "Synthetic row result; review the page.",
          };
        },
      ),
    },
    scripting: { executeScript: vi.fn(async () => []) },
    runtime: {
      sendNativeMessage: vi.fn(async () => ({
        ok: true,
        structure: {
          engine: "agent-browser",
          page_url: "https://jobs.example.test/apply",
          title: "Synthetic role",
          controls:
            options.emptyInitial === "career" && snapshots.length === 1
              ? []
              : [{ id: "f0" }],
          job_context: null,
        },
      })),
    },
  };
  const fetch = vi.fn(async (url: string, init: RequestInit = {}) => {
    const route = url.split("/api/v1/browser/")[1];
    const body = init.body ? JSON.parse(init.body as string) : {};
    const key = (init.headers as Record<string, string>)["Idempotency-Key"];
    calls.push({ path: route, body, key });
    let result: unknown;
    if (["device/resumes", "device/cover-letters"].includes(route))
      result = { items: [], default_version_id: null };
    else if (route.endsWith("/generation"))
      result = {
        state: "idle",
        conversation_id: null,
        run_id: null,
        error_code: null,
      };
    else if (route === "snapshots") {
      if (snapshots.length > 1 && loseCapture) {
        loseCapture = false;
        throw new Error("Synthetic lost refreshed capture reply");
      }
      result = body;
    } else if (route.endsWith("/preparations")) {
      if (!receipts.has(key)) {
        const snapshot = snapshots.find((item) => route.includes(item.id))!;
        const prepared: Preparation & { history_targets?: Targets } = {
          id: randomUUID(),
          task_id:
            options.wrongRefreshedTask && snapshots.length > 1
              ? randomUUID()
              : taskId,
          snapshot_id: snapshot.id,
          artifact_id: randomUUID(),
          opportunity_id: null,
          version_id: randomUUID(),
          version: 1,
          resume: null,
          cover_letter: null,
          replace_fields: [],
          upload_fields: [],
          cover_letter_upload_fields: [],
          fields: snapshot.fields.map((field) => ({
            field_id: field.id,
            status: "needs_input",
            value: null,
            reason: "Synthetic unanswered field",
            evidence: [],
          })),
          created_at: "2026-09-22T12:00:00Z",
        };
        if (options.targets !== null)
          prepared.history_targets = options.targets ?? {
            experience: 2,
            education: 1,
          };
        receipts.set(key, prepared);
      }
      if (snapshots.length > 1 && loseHistoryPrepare) {
        loseHistoryPrepare = false;
        throw new Error("Synthetic lost refreshed preparation reply");
      }
      result = receipts.get(key);
    } else if (route.endsWith("/autofill"))
      result = [...receipts.values()].find((item) => route.includes(item.id));
    else throw new Error(`Unexpected fixture request: ${route}`);
    return new Response(JSON.stringify(result), {
      headers: { "Content-Type": "application/json" },
    });
  });
  const reopen = async () => {
    document.documentElement.innerHTML = popupHtml;
    await execute(chrome, fetch);
  };
  const click = async () => {
    expect(button("autofill")).not.toBeDisabled();
    button("autofill").click();
    await waitFor(() => expect(button("discard-draft")).not.toBeDisabled());
  };
  await reopen();
  return {
    storage,
    tab,
    chrome,
    snapshots,
    expansions,
    calls,
    receipts,
    reopen,
    click,
  };
}

afterEach(() => vi.unstubAllGlobals());

it.each(["expanded", "partial"] as const)(
  "recaptures %s rows and continues the same application before authorizing",
  async (state) => {
    const f = await fixture({ state });
    await f.click();
    expect(f.snapshots).toHaveLength(2);
    expect(f.chrome.runtime.sendNativeMessage).toHaveBeenCalledTimes(2);
    const preparations = f.calls.filter((call) =>
      call.path.endsWith("/preparations"),
    );
    const saved = [...f.receipts.values()];
    expect(preparations).toHaveLength(2);
    expect(preparations[1].body).toMatchObject({
      continue_preparation_id: saved[0].id,
      resume_version_id: null,
      cover_letter_version_id: null,
    });
    expect(preparations[1].body).not.toHaveProperty("continue_on_new_page");
    expect(saved[0].task_id).toBe(saved[1].task_id);
    expect(
      f.calls.filter((call) => call.path.endsWith("/autofill")),
    ).toMatchObject([
      {
        path: `device/preparations/${saved[1].id}/autofill`,
        body: { expected_version_id: saved[1].version_id },
      },
    ]);
    expect(f.storage.applicationDraft?.snapshot.id).toBe(f.snapshots[1].id);
    expect(f.storage.applicationDraft?.autofill.stage).toBe("done");
    expect(document.getElementById("history-status")).toHaveTextContent(
      "Synthetic row result",
    );
  },
);

it("retains exact row operation through a lost reply and popup reopen", async () => {
  const f = await fixture({ loseExpansion: true });
  await f.click();
  expect(f.storage.applicationDraft?.autofill.stage).toBe("expand_history");
  expect(f.calls.some((call) => call.path.endsWith("/autofill"))).toBe(false);
  expect(button("resume")).toBeDisabled();
  const original = structuredClone(f.expansions[0]);
  await f.reopen();
  await f.click();
  expect(f.expansions).toEqual([original, original]);
  expect(f.storage.applicationDraft?.autofill.stage).toBe("done");
});

it.each(["loseCapture", "loseHistoryPrepare"] as const)(
  "resumes %s with the same snapshot and request key without adding twice",
  async (failure) => {
    const f = await fixture({ [failure]: true });
    await f.click();
    const failed = structuredClone(f.calls.at(-1));
    await f.reopen();
    await f.click();
    expect(f.expansions).toHaveLength(1);
    expect(f.snapshots).toHaveLength(2);
    expect(f.calls.filter((call) => call.key === failed?.key)).toEqual([
      failed,
      failed,
    ]);
    expect(f.storage.applicationDraft?.autofill.stage).toBe("done");
  },
);

it("uses the original capture when no rows change", async () => {
  const f = await fixture({ state: "unchanged" });
  await f.click();
  expect(f.snapshots).toHaveLength(1);
  expect(f.receipts.size).toBe(1);
  expect(f.storage.applicationDraft?.autofill.stage).toBe("done");
});

it.each(["rejected", "outcome_unknown"] as const)(
  "stops %s row operations without filling or replaying",
  async (state) => {
    const f = await fixture({ state });
    await f.click();
    expect(f.storage.applicationDraft?.autofill.stage).toBe(
      "history_uncertain",
    );
    await f.reopen();
    await f.click();
    expect(f.expansions).toHaveLength(1);
    expect(f.calls.some((call) => call.path.endsWith("/autofill"))).toBe(false);
  },
);

it.each(["tab", "query"])(
  "stops a retry after the %s changes",
  async (kind) => {
    const f = await fixture({ loseExpansion: true });
    await f.click();
    if (kind === "tab") f.tab.id = 99;
    else f.tab.url += "-different";
    await f.reopen();
    await f.click();
    expect(f.expansions).toHaveLength(1);
    expect(f.calls.some((call) => call.path.endsWith("/autofill"))).toBe(false);
  },
);

it.each([null, { experience: 0, education: 0 }])(
  "preserves legacy or zero-target flows (%j)",
  async (targets) => {
    const f = await fixture({ targets });
    await f.click();
    expect(f.expansions).toHaveLength(0);
    expect(f.snapshots).toHaveLength(1);
    expect(f.storage.applicationDraft?.autofill.stage).toBe("done");
  },
);

it("rejects a row response from another operation", async () => {
  const f = await fixture({ wrongIdentity: true });
  await f.click();
  expect(f.calls.some((call) => call.path.endsWith("/autofill"))).toBe(false);
  expect(document.getElementById("message")).toHaveTextContent("did not match");
});

it("supports an empty history step and keeps the local Add hint out of API snapshots", async () => {
  const f = await fixture({ emptyInitial: "career" });
  await f.click();
  expect(f.expansions).toHaveLength(1);
  expect(f.snapshots).toHaveLength(2);
  const shared = f.calls.filter((call) => call.path === "snapshots");
  expect(shared[0].body.fields).toEqual([]);
  for (const call of shared)
    expect(call.body).not.toHaveProperty("history_expandable");
  expect(f.storage.applicationDraft?.autofill.stage).toBe("done");
});

it("does not create an application from an empty ordinary page", async () => {
  const f = await fixture({ emptyInitial: "ordinary" });
  await f.click();
  expect(f.receipts.size).toBe(0);
  expect(f.expansions).toHaveLength(0);
  expect(document.getElementById("message")).toHaveTextContent(
    "No supported application controls",
  );
});

it("does not authorize refreshed answers belonging to another application", async () => {
  const f = await fixture({ wrongRefreshedTask: true });
  await f.click();
  expect(f.calls.some((call) => call.path.endsWith("/autofill"))).toBe(false);
  expect(document.getElementById("message")).toHaveTextContent(
    "do not match this application",
  );
});
