import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { waitFor } from "@testing-library/dom";
import { afterEach, expect, it, vi } from "vitest";
import type { components } from "./api-types";

type JobIdentity = components["schemas"]["JobIdentity"];
type Snapshot = components["schemas"]["SnapshotCreate"];
type Preparation = components["schemas"]["ApplicationPreparationRead"];
type Draft = {
  snapshot: Snapshot;
  pageUrl: string;
  structurePageUrl?: string;
  structure?: Record<string, unknown> | null;
  preparation?: Preparation;
  autofill?: {
    stage: string;
    previousId: string | null;
    jobIdentity?: JobIdentity;
  };
};
type ScriptRequest = { files?: string[]; target: { tabId: number } };
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
const executePopup = new Function(
  "chrome",
  "fetch",
  `return (async () => {${read("popup.js")}\n})();`,
);
const contracts = new Function(
  `${read("contracts.js")}\nreturn CommandCenterContracts;`,
)();
const originalUrl = "https://boards.greenhouse.io/synthetic/jobs/123";
const laterUrl = originalUrl + "/application";
const originalIdentity: JobIdentity = {
  platform: "greenhouse",
  organization: "synthetic",
  posting_id: "123",
  canonical_url: originalUrl,
};
const otherIdentity: JobIdentity = {
  ...originalIdentity,
  posting_id: "456",
  canonical_url: originalUrl.replace("123", "456"),
};
const button = (id: string) => document.getElementById(id) as HTMLButtonElement;

function snapshot(url: string, title = "Synthetic current role"): Snapshot {
  const page = new URL(url);
  return {
    id: randomUUID(),
    protocol_version: 2,
    page_url: page.origin + page.pathname,
    title,
    fields: [
      {
        id: "f0",
        label: "Full name",
        type: "text",
        required: true,
        autocomplete: "name",
        accept: "",
        options: [],
        option_labels: {},
        value_state: "empty",
      },
    ],
  };
}

function preparation(
  capture: Snapshot,
  identity: JobIdentity | null,
): Preparation {
  return {
    id: randomUUID(),
    snapshot_id: capture.id,
    task_id: randomUUID(),
    artifact_id: randomUUID(),
    opportunity_id: null,
    version_id: randomUUID(),
    version: 1,
    resume: null,
    cover_letter: null,
    cover_letter_upload_fields: [],
    replace_fields: [],
    upload_fields: [],
    job_identity: identity,
    fields: capture.fields.map((field) => ({
      field_id: field.id,
      status: "needs_input",
      value: null,
      reason: "Synthetic manual answer",
      evidence: [],
    })),
    created_at: "2026-09-22T12:00:00Z",
  };
}

async function fixture(
  options: {
    reader?: "agent-browser" | "direct";
    previousUrl?: string;
    url?: string;
    previousIdentity?: JobIdentity | null;
    observedIdentity?: unknown;
    previousStructure?: Record<string, unknown>;
    structurePageUrl?: string;
    losePrepare?: boolean;
    expand?: boolean;
    recapturedIdentity?: unknown;
  } = {},
) {
  vi.stubGlobal("CommandCenterContracts", contracts);
  const previousUrl = options.previousUrl ?? originalUrl;
  const previousSnapshot = snapshot(previousUrl, "Synthetic previous role");
  const previousPreparation = preparation(
    previousSnapshot,
    options.previousIdentity === undefined
      ? originalIdentity
      : options.previousIdentity,
  );
  const storage: { applicationDraft?: Draft; [key: string]: unknown } = {
    connection: {
      base: "http://localhost:8000",
      token: "synthetic-device-token",
    },
    pageReader: options.reader ?? "agent-browser",
    applicationDraft: {
      snapshot: previousSnapshot,
      pageUrl: previousUrl,
      preparation: previousPreparation,
      structure: options.previousStructure,
      structurePageUrl: options.structurePageUrl,
    },
  };
  const tab = { id: 7, url: options.url ?? laterUrl };
  const snapshots: Snapshot[] = [];
  const readerState: { identity: unknown; override?: unknown } = {
    identity:
      options.observedIdentity === undefined
        ? originalIdentity
        : options.observedIdentity,
  };
  const structure = () => {
    if (Object.hasOwn(readerState, "override")) return readerState.override;
    const current = snapshots.at(-1) ?? snapshot(tab.url);
    return {
      engine: "agent-browser",
      page_url: current.page_url,
      full_url: tab.url,
      title: current.title,
      controls: [{ label: "Full name", type: "text", required: true }],
      job_context: null,
      job_identity:
        snapshots.length > 1 && Object.hasOwn(options, "recapturedIdentity")
          ? options.recapturedIdentity
          : readerState.identity,
    };
  };
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
        async (
          _id: number,
          message: { action: string; id?: string; snapshot_id?: string },
        ) => {
          if (message.action === "inspect") {
            const current = snapshot(tab.url);
            snapshots.push(current);
            return structuredClone(current);
          }
          if (message.action === "expand-history" && options.expand)
            return {
              operation_id: message.id,
              snapshot_id: message.snapshot_id,
              state: "expanded",
              counts: { experience: 1, education: 0 },
              added: { experience: 1, education: 0 },
              message: "Synthetic row expansion",
            };
          throw new Error("Unexpected mutation in identity fixture");
        },
      ),
    },
    scripting: {
      executeScript: vi.fn(async (request: ScriptRequest) =>
        request.files?.includes("page-structure.js")
          ? [{ frameId: 0, result: structuredClone(structure()) }]
          : [],
      ),
    },
    runtime: {
      sendNativeMessage: vi.fn(async () => ({
        ok: true,
        structure: structuredClone(structure()),
      })),
    },
  };
  const calls: { path: string; body: Record<string, unknown>; key?: string }[] =
    [];
  const receipts = new Map<string, Preparation>();
  const preparations = new Map([[previousPreparation.id, previousPreparation]]);
  let losePrepare = options.losePrepare;
  const fetch = vi.fn(async (url: string, init: RequestInit = {}) => {
    const endpoint = url.split("/api/v1/browser/")[1];
    const body = init.body ? JSON.parse(init.body as string) : {};
    const key = (init.headers as Record<string, string>)["Idempotency-Key"];
    calls.push({ path: endpoint, body, key });
    let result: unknown;
    if (["device/resumes", "device/cover-letters"].includes(endpoint))
      result = { items: [], default_version_id: null };
    else if (endpoint.endsWith("/generation"))
      result = {
        state: "idle",
        conversation_id: null,
        run_id: null,
        error_code: null,
      };
    else if (endpoint === "snapshots") result = body;
    else if (endpoint.endsWith("/preparations")) {
      if (!receipts.has(key)) {
        const previous = preparations.get(body.continue_preparation_id);
        const current = snapshots.find((row) => endpoint.includes(row.id));
        if (!current)
          throw new Error("Preparation did not use an exact captured snapshot");
        const prepared = preparation(
          current,
          body.job_identity ?? previous?.job_identity ?? null,
        );
        if (previous) prepared.task_id = previous.task_id;
        if (options.expand)
          prepared.history_targets = { experience: 1, education: 0 };
        receipts.set(key, prepared);
        preparations.set(prepared.id, prepared);
      }
      if (losePrepare) {
        losePrepare = false;
        throw new Error("Synthetic lost preparation reply");
      }
      result = receipts.get(key);
    } else if (endpoint.endsWith("/autofill")) {
      result = [...preparations.values()].find((row) =>
        endpoint.includes(row.id),
      );
    } else throw new Error(`Unexpected fixture request: ${endpoint}`);
    return new Response(JSON.stringify(result), {
      headers: { "Content-Type": "application/json" },
    });
  });
  const reopen = async () => {
    document.documentElement.innerHTML = popupHtml;
    await executePopup(chrome, fetch);
  };
  const click = async (id = "autofill") => {
    expect(button(id)).not.toBeDisabled();
    button(id).click();
    await waitFor(() => expect(button("discard-draft")).not.toBeDisabled());
  };
  await reopen();
  return {
    tab,
    storage,
    chrome,
    calls,
    receipts,
    snapshots,
    previousPreparation,
    readerState,
    reopen,
    click,
    prepareCalls: () =>
      calls.filter((call) => call.path.endsWith("/preparations")),
  };
}

afterEach(() => vi.unstubAllGlobals());

it.each(["agent-browser", "direct"] as const)(
  "continues a recognized job automatically using the actual %s reader",
  async (reader) => {
    const f = await fixture({ reader });
    expect(f.calls.filter((call) => call.key)).toEqual([]);
    if (reader === "direct") {
      expect(document.getElementById("reader-status")).toHaveTextContent(
        "Reads the application in this Chrome tab",
      );
      expect(document.getElementById("reader-status")).not.toHaveTextContent(
        "AgentBrowser",
      );
    }
    await f.click();
    expect(f.prepareCalls()).toHaveLength(1);
    expect(f.prepareCalls()[0].body).toMatchObject({
      continue_preparation_id: f.previousPreparation.id,
      job_identity: originalIdentity,
    });
    expect(f.prepareCalls()[0].body).not.toHaveProperty("continue_on_new_page");
    expect(
      f.calls.find((call) => call.path === "snapshots")?.body,
    ).not.toHaveProperty("full_url");
    expect(f.storage.applicationDraft?.preparation?.task_id).toBe(
      f.previousPreparation.task_id,
    );
    expect(document.getElementById("application-choice")).not.toBeVisible();
    expect(document.getElementById("reader-status")).toHaveTextContent(
      reader === "direct" ? "Read by Direct browser" : "Read by AgentBrowser",
    );
    if (reader === "direct") {
      expect(f.chrome.runtime.sendNativeMessage).not.toHaveBeenCalled();
      expect(f.chrome.scripting.executeScript).toHaveBeenCalledWith({
        target: { tabId: 7 },
        files: ["page-structure.js"],
      });
      expect(f.storage.applicationDraft?.structure?.engine).toBe(
        "direct-browser",
      );
    } else expect(f.chrome.runtime.sendNativeMessage).toHaveBeenCalledOnce();
  },
);

it.each([
  otherIdentity,
  { ...originalIdentity, organization: "another-synthetic" },
  { ...originalIdentity, platform: "lever" as const },
])(
  "starts a separate application when a recognized tuple changes: %j",
  async (identity) => {
    const f = await fixture({ observedIdentity: identity });
    await f.click();
    expect(f.prepareCalls()[0].body.continue_preparation_id).toBeNull();
    expect(f.prepareCalls()[0].body).not.toHaveProperty("continue_on_new_page");
    expect(f.storage.applicationDraft?.preparation?.task_id).not.toBe(
      f.previousPreparation.task_id,
    );
    expect(document.getElementById("application-choice")).not.toBeVisible();
    expect(document.getElementById("autofill-status")).toHaveTextContent(
      "Different job detected",
    );
    expect(document.getElementById("application-title")).toHaveTextContent(
      "Synthetic current role",
    );
  },
);

it.each([originalUrl, originalUrl + "?gh_jid=456"])(
  "does not merge a changed known identity even when the page is %s",
  async (url) => {
    const f = await fixture({ url, observedIdentity: otherIdentity });
    await f.click();
    expect(f.prepareCalls()[0].body.continue_preparation_id).toBeNull();
  },
);

it("compares the tuple rather than canonical URL or page title", async () => {
  const f = await fixture({
    observedIdentity: { ...originalIdentity, canonical_url: originalUrl + "/" },
  });
  await f.click();
  expect(f.prepareCalls()[0].body.continue_preparation_id).toBe(
    f.previousPreparation.id,
  );
});

it.each([
  { previousIdentity: null, observedIdentity: originalIdentity },
  { previousIdentity: originalIdentity, observedIdentity: null },
  { previousIdentity: null, observedIdentity: null },
])(
  "retains an explicit choice when either identity is unknown: %j",
  async (options) => {
    const f = await fixture(options);
    await f.click();
    expect(f.prepareCalls()).toEqual([]);
    expect(document.getElementById("application-choice")).toBeVisible();
    await f.reopen();
    expect(document.getElementById("application-choice")).toBeVisible();
    await f.click("continue-application");
    expect(f.prepareCalls()[0].body).toMatchObject({
      continue_preparation_id: f.previousPreparation.id,
      continue_on_new_page: true,
    });
    if (options.observedIdentity)
      expect(f.prepareCalls()[0].body.job_identity).toEqual(originalIdentity);
    else expect(f.prepareCalls()[0].body).not.toHaveProperty("job_identity");
  },
);

it("carries saved identity through unknown pages and reuses the newest preparation", async () => {
  const f = await fixture({ observedIdentity: null });
  await f.click();
  await f.click("continue-application");
  const carried = f.storage.applicationDraft?.preparation;
  expect(carried?.job_identity).toEqual(originalIdentity);
  f.tab.url = originalUrl + "/review";
  f.readerState.identity = originalIdentity;
  await f.click();
  expect(f.prepareCalls()[1].body.continue_preparation_id).toBe(carried?.id);
  expect(f.prepareCalls()[1].body).not.toHaveProperty("continue_on_new_page");
  expect(f.storage.applicationDraft?.preparation?.task_id).toBe(
    f.previousPreparation.task_id,
  );
});

it.each([true, false])(
  "uses legacy reader identity only with its exact URL binding (%s)",
  async (bound) => {
    const f = await fixture({
      previousIdentity: null,
      previousStructure: {
        page_url: originalUrl,
        job_identity: originalIdentity,
      },
      structurePageUrl: bound ? originalUrl : originalUrl + "?another=job",
    });
    await f.click();
    if (bound)
      expect(f.prepareCalls()[0].body.continue_preparation_id).toBe(
        f.previousPreparation.id,
      );
    else expect(f.prepareCalls()).toEqual([]);
  },
);

it("prefers the saved preparation identity over previous reader metadata", async () => {
  const f = await fixture({
    previousIdentity: otherIdentity,
    previousStructure: {
      page_url: originalUrl,
      job_identity: originalIdentity,
    },
    structurePageUrl: originalUrl,
  });
  await f.click();
  expect(f.prepareCalls()[0].body.continue_preparation_id).toBeNull();
});

it.each([
  { ...originalIdentity, platform: "unknown" },
  { ...originalIdentity, organization: "" },
  { ...originalIdentity, posting_id: "x".repeat(201) },
  {
    ...originalIdentity,
    canonical_url: "http://boards.greenhouse.io/synthetic/jobs/123",
  },
  { ...originalIdentity, canonical_url: originalUrl + "?private=value" },
  { ...originalIdentity, canonical_url: originalUrl + "#fragment" },
  { ...originalIdentity, canonical_url: " " + originalUrl },
  {
    ...originalIdentity,
    canonical_url:
      "https://user:secret@boards.greenhouse.io/synthetic/jobs/123",
  },
  {
    ...originalIdentity,
    canonical_url: "https://boards.greenhouse.io:444/synthetic/jobs/123",
  },
])(
  "treats malformed identity as unknown and omits it from requests: %j",
  async (observedIdentity) => {
    const f = await fixture({ observedIdentity });
    await f.click();
    expect(f.prepareCalls()).toEqual([]);
    await f.click("new-application");
    expect(f.prepareCalls()[0].body).not.toHaveProperty("job_identity");
  },
);

it.each(["agent-browser", "direct"] as const)(
  "rejects missing and malformed %s reader results before writes",
  async (reader) => {
    for (const override of [
      null,
      {},
      {
        engine: "agent-browser",
        page_url: "https://wrong.example/apply",
        full_url: laterUrl,
        title: "Wrong",
        controls: [],
      },
      {
        engine: "agent-browser",
        page_url: laterUrl,
        full_url: laterUrl,
        title: "x".repeat(301),
        controls: [{}],
      },
      {
        engine: "agent-browser",
        page_url: laterUrl,
        full_url: laterUrl,
        title: "Synthetic",
        controls: Array(101).fill({}),
      },
    ]) {
      const f = await fixture({ reader });
      f.readerState.override = override;
      await f.click();
      expect(f.calls.filter((call) => call.key)).toEqual([]);
      expect(document.getElementById("message")).toHaveTextContent(
        "no usable form structure",
      );
    }
  },
);

it.each(["agent-browser", "direct"] as const)(
  "rejects a query-only URL change during the %s read before writes",
  async (reader) => {
    const f = await fixture({ reader, url: originalUrl + "?gh_jid=123" });
    f.readerState.override = {
      engine: "agent-browser",
      page_url: originalUrl,
      full_url: originalUrl + "?gh_jid=456",
      title: "Synthetic next role",
      controls: [{ label: "Full name", type: "text" }],
      job_identity: otherIdentity,
    };
    await f.click();
    expect(f.calls.filter((call) => call.key)).toEqual([]);
    expect(document.getElementById("message")).toHaveTextContent(
      "no usable form structure",
    );
  },
);

it("retains the exact observed identity and receipt after a lost reply and reopen", async () => {
  const f = await fixture({ losePrepare: true });
  await f.click();
  const original = structuredClone(f.prepareCalls()[0]);
  expect(f.storage.applicationDraft?.autofill?.stage).toBe("prepare");
  f.readerState.identity = otherIdentity;
  await f.reopen();
  await f.click();
  expect(f.prepareCalls()).toEqual([original, original]);
  expect(f.receipts.size).toBe(1);
  expect(f.chrome.runtime.sendNativeMessage).toHaveBeenCalledOnce();
  expect(f.storage.applicationDraft?.autofill?.stage).toBe("done");
});

it.each(["tab", "url"])(
  "keeps the exact pending %s guard despite recognized identity",
  async (change) => {
    const f = await fixture({ losePrepare: true });
    await f.click();
    if (change === "tab") f.tab.id += 1;
    else f.tab.url += "?step=other";
    await f.reopen();
    await f.click();
    expect(f.prepareCalls()).toHaveLength(1);
    expect(document.getElementById("message")).toHaveTextContent(
      "captured application tab",
    );
  },
);

it.each([originalIdentity, null])(
  "prepares expanded rows with only fresh observed identity: %j",
  async (identity) => {
    const f = await fixture({ expand: true, recapturedIdentity: identity });
    await f.click();
    expect(f.prepareCalls()).toHaveLength(2);
    expect(f.prepareCalls()[1].body.continue_preparation_id).toBe(
      [...f.receipts.values()][0].id,
    );
    if (identity)
      expect(f.prepareCalls()[1].body.job_identity).toEqual(identity);
    else expect(f.prepareCalls()[1].body).not.toHaveProperty("job_identity");
    expect(f.prepareCalls()[1].body).not.toHaveProperty("continue_on_new_page");
    expect(f.storage.applicationDraft?.preparation?.task_id).toBe(
      f.previousPreparation.task_id,
    );
  },
);
