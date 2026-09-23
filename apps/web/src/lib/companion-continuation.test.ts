import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, expect, it, vi } from "vitest";
import { waitFor } from "@testing-library/dom";
import type { components } from "./api-types";

type Snapshot = components["schemas"]["SnapshotCreate"];
type Preparation = components["schemas"]["ApplicationPreparationRead"];
type Operation = {
  stage: string;
  previousId: string | null;
  previousApplication?: { id: string; title: string; pageUrl: string } | null;
  continueOnNewPage?: boolean;
  tabId: number;
  pageUrl: string;
  resumeVersionId: string | null;
  coverLetterVersionId?: string | null;
  attachResume: boolean;
  attachCoverLetter?: boolean;
};
type Draft = {
  snapshot: Snapshot;
  pageUrl: string;
  preparation?: Preparation;
  structure?: { job_context: unknown } | null;
  autofill?: Operation;
  receipts?: Record<string, string>;
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
const executePopup = new Function(
  "chrome",
  "fetch",
  `return (async () => {${read("popup.js")}\n})();`,
);
const contracts = new Function(
  `${read("contracts.js")}\nreturn CommandCenterContracts;`,
)();
const previousUrl = "https://careers.example.test/apply?job=alpha";
const nextUrl = "https://careers.example.test/apply?job=beta";
const button = (id: string) => document.getElementById(id) as HTMLButtonElement;

function snapshot(url: string, title = "Synthetic application"): Snapshot {
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

function preparation(capture: Snapshot): Preparation {
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
    fields: capture.fields.map((field) => ({
      field_id: field.id,
      status: "needs_input",
      value: null,
      reason: "Synthetic fixture requires manual input.",
      evidence: [],
    })),
    created_at: "2026-09-22T12:00:00Z",
  };
}

async function fixture(options: { url?: string; losePrepare?: boolean } = {}) {
  vi.stubGlobal("CommandCenterContracts", contracts);
  const previousSnapshot = snapshot(previousUrl, "Synthetic previous role");
  const previousPreparation = preparation(previousSnapshot);
  const storage: { applicationDraft?: Draft; [key: string]: unknown } = {
    connection: {
      base: "http://localhost:8000",
      token: "synthetic-device-token",
    },
    pageReader: "agent-browser",
    applicationDraft: {
      snapshot: previousSnapshot,
      pageUrl: previousUrl,
      preparation: previousPreparation,
    },
  };
  const tab = { id: 7, url: options.url ?? nextUrl };
  const currentSnapshot = snapshot(tab.url);
  const structure = {
    engine: "agent-browser",
    page_url: currentSnapshot.page_url,
    full_url: tab.url,
    title: currentSnapshot.title,
    controls: [{ id: "f0" }],
    job_context: null,
  };
  const chrome = {
    storage: {
      local: {
        setAccessLevel: vi.fn(async () => {}),
        get: vi.fn(async () => structuredClone(storage)),
        set: vi.fn(async (values: Record<string, unknown>) => {
          Object.assign(storage, structuredClone(values));
        }),
        remove: vi.fn(async (keys: string | string[]) => {
          for (const key of [keys].flat()) delete storage[key];
        }),
      },
    },
    tabs: {
      query: vi.fn(async () => [{ ...tab }]),
      sendMessage: vi.fn(async (_id: number, message: { action: string }) => {
        if (message.action !== "inspect")
          throw new Error("Unexpected page mutation in continuation fixture");
        return structuredClone(currentSnapshot);
      }),
    },
    scripting: { executeScript: vi.fn(async () => []) },
    runtime: {
      sendNativeMessage: vi.fn(async () => ({ ok: true, structure })),
    },
  };
  const calls: { path: string; body: Record<string, unknown>; key?: string }[] =
    [];
  const receipts = new Map<string, Preparation>();
  let losePrepare = options.losePrepare;
  const fetch = vi.fn(async (url: string, init: RequestInit = {}) => {
    const path = url.split("/api/v1/browser/")[1];
    const body = init.body ? JSON.parse(init.body as string) : {};
    const key = (init.headers as Record<string, string>)["Idempotency-Key"];
    calls.push({ path, body, key });
    let result: unknown;
    if (["device/resumes", "device/cover-letters"].includes(path)) {
      result = { items: [], default_version_id: null };
    } else if (path.endsWith("/generation")) {
      result = {
        state: "idle",
        conversation_id: null,
        run_id: null,
        error_code: null,
      };
    } else if (path === "snapshots") {
      result = body;
    } else if (path.endsWith("/preparations")) {
      if (!receipts.has(key)) receipts.set(key, preparation(currentSnapshot));
      if (losePrepare) {
        losePrepare = false;
        throw new Error("Synthetic lost preparation reply");
      }
      result = receipts.get(key);
    } else if (path.endsWith("/autofill")) {
      result = [...receipts.values()].find((item) => path.includes(item.id));
    } else {
      throw new Error(`Unexpected fixture request: ${path}`);
    }
    return new Response(JSON.stringify(result), {
      headers: { "Content-Type": "application/json" },
    });
  });
  const reopen = async () => {
    document.documentElement.innerHTML = popupHtml;
    await executePopup(chrome, fetch);
  };
  const click = async (id: string) => {
    expect(button(id)).not.toBeDisabled();
    button(id).click();
    await waitFor(() => expect(button("discard-draft")).not.toBeDisabled());
  };
  const prepareCalls = () =>
    calls.filter((call) => call.path.endsWith("/preparations"));
  await reopen();
  return {
    storage,
    tab,
    chrome,
    calls,
    receipts,
    currentSnapshot,
    structure,
    previousPreparation,
    prepareCalls,
    reopen,
    click,
  };
}

afterEach(() => vi.unstubAllGlobals());

it("keeps query-distinct jobs separate until a persistent explicit choice", async () => {
  const state = await fixture();
  await state.click("autofill");
  expect(state.storage.applicationDraft).toMatchObject({
    snapshot: state.currentSnapshot,
    structure: state.structure,
    pageUrl: nextUrl,
    autofill: {
      stage: "choose_application",
      tabId: 7,
      pageUrl: nextUrl,
      previousId: null,
      previousApplication: {
        id: state.previousPreparation.id,
        title: "Synthetic previous role",
        pageUrl: previousUrl,
      },
    },
  });
  expect(state.calls.filter((call) => call.key)).toEqual([]);
  expect(document.getElementById("application-choice")).toBeVisible();
  expect(document.activeElement).toBe(
    document.getElementById("application-choice-title"),
  );
  expect(
    document.getElementById("application-choice-context"),
  ).toHaveTextContent("Synthetic previous role · careers.example.test");
  for (const id of ["resume", "prepare", "share", "refresh", "disconnect"])
    expect(button(id)).toBeDisabled();
  expect(document.getElementById("fields")).toHaveProperty("inert", true);
  expect(document.getElementById("proposals")).toHaveProperty("inert", true);

  await state.reopen();
  expect(document.getElementById("application-choice")).toBeVisible();
  expect(document.activeElement).toBe(
    document.getElementById("application-choice-title"),
  );
  expect(state.chrome.tabs.sendMessage).toHaveBeenCalledTimes(1);
  expect(state.calls.filter((call) => call.key)).toEqual([]);
  await state.click("continue-application");
  expect(state.prepareCalls()[0].body).toMatchObject({
    continue_preparation_id: state.previousPreparation.id,
    continue_on_new_page: true,
  });
  expect(state.storage.applicationDraft?.autofill?.stage).toBe("done");
});

it("starts a separate application only after the new-application choice", async () => {
  const state = await fixture();
  await state.click("autofill");
  await state.click("new-application");
  expect(state.prepareCalls()).toHaveLength(1);
  expect(state.prepareCalls()[0].body).toMatchObject({
    continue_preparation_id: null,
  });
  expect(state.prepareCalls()[0].body).not.toHaveProperty(
    "continue_on_new_page",
  );
});

it("retains explicit continuation and the exact request across a lost reply and reopen", async () => {
  const state = await fixture({ losePrepare: true });
  await state.click("autofill");
  await state.click("continue-application");
  expect(state.storage.applicationDraft?.autofill).toMatchObject({
    stage: "prepare",
    previousId: state.previousPreparation.id,
    continueOnNewPage: true,
  });
  expect(document.getElementById("message")).toHaveTextContent(
    "lost preparation reply",
  );
  const firstRequest = structuredClone(state.prepareCalls()[0]);
  await state.reopen();
  expect(document.getElementById("application-choice")).not.toBeVisible();
  await state.click("autofill");
  expect(state.prepareCalls()).toEqual([firstRequest, firstRequest]);
  expect(state.receipts.size).toBe(1);
  expect(state.chrome.tabs.sendMessage).toHaveBeenCalledTimes(1);
  expect(state.storage.applicationDraft?.autofill?.stage).toBe("done");
});

it.each(["tab", "url"])(
  "requires the exact captured %s before applying a choice",
  async (change) => {
    const state = await fixture();
    await state.click("autofill");
    if (change === "tab") state.tab.id += 1;
    else state.tab.url += "&step=2";
    await state.click("continue-application");
    expect(state.calls.filter((call) => call.key)).toEqual([]);
    expect(state.storage.applicationDraft?.autofill?.stage).toBe(
      "choose_application",
    );
    expect(document.getElementById("message")).toHaveTextContent(
      "captured application tab",
    );
  },
);

it("requires an explicit choice for cross-origin continuation", async () => {
  const state = await fixture({ url: "https://apply.example.test/step/2" });
  await state.click("autofill");
  expect(state.prepareCalls()).toEqual([]);
  await state.click("continue-application");
  expect(state.prepareCalls()[0].body.continue_on_new_page).toBe(true);
});

it("keeps automatic continuation and the legacy request body for the exact same URL", async () => {
  const state = await fixture({ url: previousUrl });
  await state.click("autofill");
  expect(state.prepareCalls()[0].body).toEqual({
    opportunity_id: null,
    resume_version_id: null,
    cover_letter_version_id: null,
    continue_preparation_id: state.previousPreparation.id,
    job_context: null,
  });
  expect(document.getElementById("application-choice")).not.toBeVisible();
});

it("resumes a legacy saved operation without changing its preparation request", async () => {
  const state = await fixture();
  state.storage.applicationDraft = {
    snapshot: state.currentSnapshot,
    pageUrl: nextUrl,
    receipts: { "auto-prepare": "synthetic-legacy-receipt" },
    autofill: {
      stage: "prepare",
      previousId: null,
      tabId: 7,
      pageUrl: nextUrl,
      resumeVersionId: null,
      attachResume: false,
    },
  };
  await state.reopen();
  await state.click("autofill");
  expect(state.prepareCalls()[0]).toMatchObject({
    key: "synthetic-legacy-receipt",
    body: {
      opportunity_id: null,
      resume_version_id: null,
      cover_letter_version_id: null,
      continue_preparation_id: null,
      job_context: null,
    },
  });
  expect(state.prepareCalls()[0].body).not.toHaveProperty(
    "continue_on_new_page",
  );
});

it("can discard a pending choice and capture a fresh application", async () => {
  const state = await fixture();
  await state.click("autofill");
  await state.click("discard-draft");
  expect(state.storage.applicationDraft).toBeUndefined();
  expect(document.getElementById("application-choice")).not.toBeVisible();
  await state.click("autofill");
  expect(state.prepareCalls()[0].body.continue_preparation_id).toBeNull();
  expect(state.prepareCalls()[0].body).not.toHaveProperty(
    "continue_on_new_page",
  );
});
