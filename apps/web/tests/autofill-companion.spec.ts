import { expect, test, type Page } from "@playwright/test";
import { createHash, randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import type { components } from "../src/lib/api-types";
type Snapshot = components["schemas"]["SnapshotCreate"];
type Preparation = components["schemas"]["ApplicationPreparationRead"];
type Revision = components["schemas"]["PreparationRevision"];
type Fill = components["schemas"]["FillCreate"];
type PageStructure = {
  job_context: components["schemas"]["JobContextCreate"] | null;
};
type FixtureWindow = {
  fixtureGet: () => Promise<unknown>;
  fixtureSet: (value: unknown) => Promise<unknown>;
  fixtureRemove: (keys: unknown) => Promise<unknown>;
  fixtureMessage: (message: unknown) => Promise<unknown>;
  fixtureInspect: () => Promise<unknown>;
  fixtureReadStructure: () => Promise<unknown>;
};

const read = (name: string) =>
  readFileSync(path.resolve(__dirname, `../../extension/${name}`), "utf8");
const readStructure = (page: Page) =>
  page.evaluate<PageStructure>(read("page-structure.js"));
const popup = read("popup.html").replace(/<script[\s\S]*?<\/script>/g, "");
const bytes = Buffer.from("Synthetic resume for browser verification.");
const resume = {
  version_id: randomUUID(),
  artifact_id: randomUUID(),
  title: "Synthetic resume",
  version: 1,
  filename: "resume.txt",
  media_type: "text/plain",
  size_bytes: bytes.length,
  sha256: createHash("sha256").update(bytes).digest("hex"),
};

const letterBytes = Buffer.from("Synthetic cover letter for this application.");
const letter = {
  ...resume,
  version_id: randomUUID(),
  artifact_id: randomUUID(),
  title: "Synthetic cover letter",
  filename: "cover-letter.txt",
  size_bytes: letterBytes.length,
  sha256: createHash("sha256").update(letterBytes).digest("hex"),
};

async function fixture(
  page: Page,
  options: {
    missing?: boolean;
    lostPrepare?: boolean;
    lostResult?: boolean;
    unknown?: boolean;
    readerError?: boolean;
    captureDenied?: boolean;
    pageReader?: "direct" | "agent-browser";
    coverLetter?: boolean;
  } = {},
) {
  const job = await page.context().newPage();
  await job.goto("/fixtures/application.html");
  await job.setContent(`<h1>Synthetic Engineer</h1><form><label>Full name<input name="name" autocomplete="name"></label>
    <label>Email<input name="email" type="email" value="existing@example.test"></label>
    <label>Why this role?<textarea name="essay"></textarea></label>
    <label>Resume<input type="file" accept="text/plain"></label>${options.coverLetter ? '<label>Cover letter<input name="cover-letter" type="file" accept="text/plain"></label>' : ""}<button>Submit</button></form>`);
  await job.evaluate(() => {
    Object.assign(window, {
      chrome: {
        runtime: {
          id: "synthetic",
          onMessage: {
            addListener(listener: unknown) {
              Object.assign(window, { companion: listener });
            },
          },
        },
      },
    });
    document.querySelector("form")!.addEventListener("submit", (event) => {
      event.preventDefault();
      throw new Error("Submission is forbidden in this fixture");
    });
  });
  await job.addScriptTag({ content: read("contracts.js") });
  await job.addScriptTag({ content: read("content.js") });
  const storage: Record<string, unknown> = {
    ...(options.pageReader ? { pageReader: options.pageReader } : {}),
    connection: {
      base: "http://localhost:8000",
      token: "synthetic-device-token",
    },
  };
  const calls: {
    route: string;
    body: Record<string, unknown>;
    key?: string;
  }[] = [];
  let applied = 0,
    nativeReads = 0,
    preparationCount = 0;
  const snapshots = new Map<string, Snapshot>();
  const preparations = new Map<string, Preparation>();
  const taskId = randomUUID();
  const actorId = randomUUID(),
    deviceId = randomUUID();
  let losePrepare = options.lostPrepare,
    loseResult = options.lostResult;
  const receipts = new Map<string, Preparation>();
  await page.exposeFunction("fixtureGet", () => storage);
  await page.exposeFunction("fixtureSet", (values: Record<string, unknown>) =>
    Object.assign(storage, values),
  );
  await page.exposeFunction("fixtureRemove", (keys: string | string[]) => {
    for (const key of [keys].flat()) delete storage[key];
  });
  await page.exposeFunction(
    "fixtureMessage",
    async (message: { action: string }) => {
      if (message.action === "apply") {
        applied += 1;
        if (options.unknown) throw new Error("Lost tab response");
      }
      return job.evaluate(
        (payload) =>
          new Promise((resolve) => {
            (
              window as unknown as {
                companion: (
                  message: unknown,
                  sender: unknown,
                  reply: (value: unknown) => void,
                ) => void;
              }
            ).companion(payload, { id: "synthetic" }, resolve);
          }),
        message,
      );
    },
  );
  await page.exposeFunction("fixtureInspect", async () => {
    nativeReads += 1;
    if (options.readerError)
      return { ok: false, error: "AgentBrowser is unavailable." };
    return {
      ok: true,
      structure: await job.evaluate(read("page-structure.js")),
    };
  });
  await page.exposeFunction("fixtureReadStructure", () => readStructure(job));
  await page.route("http://localhost:8000/api/v1/browser/**", async (route) => {
    const request = route.request();
    if (request.method() === "OPTIONS") {
      await route.fulfill({
        headers: {
          "access-control-allow-origin": "*",
          "access-control-allow-headers": "*",
          "access-control-allow-methods": "*",
        },
      });
      return;
    }
    const pathname = new URL(request.url()).pathname.split(
      "/api/v1/browser/",
    )[1];
    const body: Record<string, unknown> = request.postDataJSON() ?? {};
    const key = request.headers()["idempotency-key"];
    calls.push({ route: pathname, body, key });
    const respond = async (data: unknown) =>
      route.fulfill({
        json: data,
        headers: { "access-control-allow-origin": "*" },
      });
    if (pathname === "device/resumes")
      return respond({
        default_version_id: options.missing ? null : resume.version_id,
        items: options.missing ? [] : [resume],
      });
    if (pathname === "device/cover-letters")
      return respond({
        default_version_id: null,
        items: options.coverLetter ? [letter] : [],
      });
    if (pathname === "snapshots") {
      const snapshot = body as Snapshot;
      snapshots.set(snapshot.id, snapshot);
      return respond(body);
    }
    if (pathname.endsWith("/preparations")) {
      let prepared = receipts.get(key!);
      if (!prepared) {
        const snapshot = snapshots.get(pathname.split("/")[2])!;
        prepared = {
          id: randomUUID(),
          snapshot_id: snapshot.id,
          task_id: taskId,
          artifact_id: randomUUID(),
          opportunity_id: null,
          version_id: randomUUID(),
          version: 1,
          resume: body.resume_version_id ? resume : null,
          cover_letter: body.cover_letter_version_id ? letter : null,
          cover_letter_upload_fields: [],
          upload_fields: [],
          replace_fields: [],
          created_at: "2026-09-22T12:00:00Z",
          fields: snapshot.fields.map((field) => ({
            field_id: field.id,
            status:
              field.value_state === "present"
                ? "preserved"
                : field.label === "Full name" && !options.missing
                  ? "suggested"
                  : "needs_input",
            value:
              field.label === "Full name" &&
              field.value_state === "empty" &&
              !options.missing
                ? "Synthetic Applicant"
                : null,
            reason: "Synthetic reviewed fact.",
            evidence: [],
          })),
        };
        preparations.set(prepared.id, prepared);
        receipts.set(key!, prepared);
        preparationCount += 1;
      }
      if (losePrepare) {
        losePrepare = false;
        return route.abort();
      }
      return respond(prepared);
    }
    if (pathname.endsWith("/autofill")) {
      const prepared = preparations.get(pathname.split("/")[2])!;
      prepared.version_id = randomUUID();
      prepared.version += 1;
      prepared.upload_fields =
        prepared.resume && body.attach_resume ? ["f3"] : [];
      prepared.cover_letter_upload_fields =
        prepared.cover_letter && body.attach_cover_letter ? ["f4"] : [];
      return respond(prepared);
    }
    if (pathname.endsWith("/revisions")) {
      const prepared = preparations.get(pathname.split("/")[2])!;
      prepared.version_id = randomUUID();
      prepared.version += 1;
      prepared.fields = prepared.fields.map((field) => ({
        ...field,
        value: (body as Revision).fields?.[field.field_id] || null,
      }));
      prepared.upload_fields = (body as Revision).upload_fields ?? [];
      prepared.cover_letter_upload_fields =
        (body as Revision).cover_letter_upload_fields ?? [];
      prepared.cover_letter = body.cover_letter_version_id ? letter : null;
      return respond(prepared);
    }
    if (pathname === "device/commands")
      return respond({
        ...body,
        id: randomUUID(),
        owner_id: actorId,
        device_id: deviceId,
        state: "pending",
        created_at: "2026-09-22T12:00:00Z",
        expires_at: "2026-09-22T12:30:00Z",
        completed_at: null,
        page_url: job.url(),
        form_fields: snapshots.get((body as Fill).snapshot_id)!.fields,
        upload_files: Object.fromEntries(
          Object.entries((body as Fill).uploads ?? {}).map(
            ([id, versionId]) => [
              id,
              Object.fromEntries(
                Object.entries(
                  versionId === letter.version_id ? letter : resume,
                ).filter(
                  ([key]) => !["artifact_id", "title", "version"].includes(key),
                ),
              ),
            ],
          ),
        ),
      });
    if (pathname.endsWith("/claim")) return respond({ state: "claimed" });
    if (pathname.endsWith("/result")) {
      if (loseResult) {
        loseResult = false;
        return route.abort();
      }
      return respond({ state: body.state });
    }
    if (pathname.includes("/files/"))
      return route.fulfill({
        body: pathname.endsWith("/f4") ? letterBytes : bytes,
        headers: { "access-control-allow-origin": "*" },
      });
    if (pathname.endsWith("/generation"))
      return respond({
        state: "idle",
        run_id: null,
        conversation_id: null,
        error_code: null,
      });
    throw new Error(`Unexpected request ${pathname}`);
  });
  async function open() {
    await page.goto("/health");
    await page.setContent(popup);
    await page.addStyleTag({ content: read("popup.css") });
    await page.evaluate(
      ({ url, captureDenied }) => {
        const w = window as unknown as FixtureWindow;
        Object.assign(window, {
          chrome: {
            storage: {
              local: {
                setAccessLevel: async () => {},
                get: () => w.fixtureGet(),
                set: (v: unknown) => w.fixtureSet(v),
                remove: (k: unknown) => w.fixtureRemove(k),
              },
            },
            tabs: {
              query: async () => [{ id: 7, url }],
              sendMessage: (_: unknown, msg: unknown) => w.fixtureMessage(msg),
            },
            scripting: {
              executeScript: async ({ files }: { files?: string[] }) => {
                if (captureDenied)
                  throw new Error(
                    "Cannot access contents of the page. Extension manifest must request permission to access this host.",
                  );
                return files?.includes("page-structure.js")
                  ? [{ frameId: 0, result: await w.fixtureReadStructure() }]
                  : [];
              },
            },
            runtime: { sendNativeMessage: () => w.fixtureInspect() },
          },
        });
      },
      { url: job.url(), captureDenied: options.captureDenied },
    );
    await page.addScriptTag({ content: read("contracts.js") });
    await page.addScriptTag({ content: read("popup.js"), type: "module" });
    await expect(
      page.getByRole("button", {
        name: /Autofill this page|Continue autofill/,
      }),
    ).toBeEnabled();
  }
  await open();
  if (options.coverLetter)
    await page.locator(".optional-letter summary").click();
  return {
    job,
    calls,
    storage,
    open,
    count: () => ({ applied, nativeReads, preparationCount }),
  };
}

test("a blocked capture explains how to grant tab access without preparing or filling", async ({
  page,
}) => {
  const f = await fixture(page, { captureDenied: true });
  await page.getByRole("button", { name: /Autofill this page/ }).click();
  await expect(page.locator("#message")).toContainText(
    "Chrome needs permission to read this tab",
  );
  await expect(page.locator("#message")).toContainText(
    "Click the Command Center extension icon on the application page",
  );
  expect(f.count()).toEqual({
    applied: 0,
    nativeReads: 0,
    preparationCount: 0,
  });
  expect(f.calls.some((call) => call.route === "snapshots")).toBe(false);
});

test("one click reads structure, fills and uploads exact resume, then applies an edited answer on a fresh capture", async ({
  page,
}) => {
  const f = await fixture(page);
  await f.job.evaluate(() => {
    const source = document.createElement("script");
    source.type = "application/ld+json";
    source.textContent = JSON.stringify({
      "@context": "https://schema.org",
      "@type": "JobPosting",
      title: "Synthetic Engineer",
      hiringOrganization: { name: "Synthetic Northstar" },
      description:
        "<p>Build accessible tools.</p><textarea>private draft</textarea><input value='private email'><script>window.descriptionExecuted = true</script>",
    });
    document.head.append(source);
  });
  await page.getByRole("button", { name: /Autofill this page/ }).click();
  await expect(page.locator("#autofill-status")).toContainText(
    "2 filled or attached",
  );
  await expect(f.job.getByLabel("Full name")).toHaveValue(
    "Synthetic Applicant",
  );
  await expect(f.job.getByLabel("Email", { exact: true })).toHaveValue(
    "existing@example.test",
  );
  expect(
    await f.job
      .getByLabel("Resume", { exact: true })
      .evaluate((node: HTMLInputElement) => node.files?.[0]?.name),
  ).toBe("resume.txt");
  expect(f.count()).toEqual({
    applied: 1,
    nativeReads: 0,
    preparationCount: 1,
  });
  expect(
    f.calls.find((call) => call.route.endsWith("/preparations"))?.body
      .job_context,
  ).toEqual({
    job_title: "Synthetic Engineer",
    company_name: "Synthetic Northstar",
    text: "Build accessible tools.",
    extraction_method: "json_ld",
    truncated: false,
  });
  expect(await f.job.evaluate(() => "descriptionExecuted" in window)).toBe(
    false,
  );
  await page
    .getByLabel("Why this role?", { exact: true })
    .fill("My reviewed answer for this role.");
  await page.getByRole("button", { name: /Save review and fill/ }).click();
  await expect(f.job.getByLabel("Why this role?", { exact: true })).toHaveValue(
    "My reviewed answer for this role.",
  );
  expect(f.count().preparationCount).toBe(2);
  expect(
    f.calls.filter((call) => call.route.endsWith("/preparations"))[1].body
      .continue_preparation_id,
  ).toBeTruthy();
  expect(
    f.calls.filter((call) => call.route === "device/commands")[1].body.uploads,
  ).toEqual({});
});

test("description reader ignores ambiguous job lists and bounds a single source", async ({
  page,
}) => {
  await page.goto("/fixtures/application.html");
  await page.setContent(
    "<h1>Job search</h1><p>Unrelated account details must not become a description.</p>",
  );
  expect((await readStructure(page)).job_context).toBeNull();
  await page.evaluate(() => {
    const source = document.createElement("script");
    source.type = "application/ld+json";
    source.textContent = JSON.stringify({
      "@graph": [
        { "@type": "JobPosting", description: "First role" },
        { "@type": "JobPosting", description: "Second role" },
      ],
    });
    document.head.append(source);
  });
  expect((await readStructure(page)).job_context).toBeNull();
  await page.evaluate(() => {
    document.querySelector('script[type="application/ld+json"]')!.textContent =
      JSON.stringify({
        "@type": "JobPosting",
        title: { unexpected: "data" },
        hiringOrganization: { name: { unexpected: "data" } },
        description: "Useful requirement. ".repeat(2000),
      });
  });
  const context = (await readStructure(page)).job_context;
  expect(context!.text).toHaveLength(30000);
  expect(context!.truncated).toBe(true);
  expect(context!.job_title).toBe("");
  expect(context!.company_name).toBe("");
});

test("semantic descriptions exclude forms and editing surfaces", async ({
  page,
}) => {
  await page.goto("/fixtures/application.html");
  await page.setContent(`<h1>Synthetic Product Engineer</h1><section id="job_description"><p>Build reliable systems.</p>
    <form>Private form text <input value="private value"><textarea>Private answer</textarea></form>
    <div contenteditable="true">Unfinished note</div><span hidden>Hidden data</span>
    <p>Work with a thoughtful team.</p></section>`);
  const context = (await readStructure(page)).job_context;
  expect(context!.extraction_method).toBe("semantic_dom");
  expect(context!.text).toContain("Build reliable systems.");
  expect(context!.text).toContain("Work with a thoughtful team.");
  expect(context!.text).not.toMatch(/Private|private|Unfinished|Hidden/);
});

test("an interrupted preparation resumes its saved request after reopening", async ({
  page,
}) => {
  const f = await fixture(page, { lostPrepare: true });
  await page.getByRole("button", { name: /Autofill this page/ }).click();
  await expect(page.locator("#message")).toContainText("Failed to fetch");
  await expect(page.getByLabel("Résumé", { exact: true })).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Start over on this page" }),
  ).toBeVisible();
  await f.open();
  await page.getByRole("button", { name: "Continue autofill" }).click();
  await expect(page.locator("#autofill-status")).toContainText(
    "2 filled or attached",
  );
  const calls = f.calls.filter((call) => call.route.endsWith("/preparations"));
  expect(calls[0].key).toBe(calls[1].key);
  expect(f.count()).toEqual({
    applied: 1,
    nativeReads: 0,
    preparationCount: 1,
  });
});

test("filled fields are collapsed and replacing one remains an explicit reviewed action", async ({
  page,
}) => {
  const f = await fixture(page);
  await page.getByRole("button", { name: /Autofill this page/ }).click();
  await expect(page.locator("#autofill-status")).toContainText(
    "2 filled or attached",
  );
  await expect(page.getByLabel("Full name", { exact: true })).not.toBeVisible();
  await page.locator(".completed-fields summary").click();
  const row = page
    .locator(".field-review")
    .filter({ has: page.getByLabel("Full name", { exact: true }) });
  await expect(row.getByLabel("Full name", { exact: true })).toBeDisabled();
  await row
    .getByRole("checkbox", { name: "Replace the value already on this page" })
    .check();
  await row
    .getByLabel("Full name", { exact: true })
    .fill("My explicitly revised name");
  await page.getByRole("button", { name: /Save review and fill/ }).click();
  await expect(f.job.getByLabel("Full name", { exact: true })).toHaveValue(
    "My explicitly revised name",
  );
  expect(
    f.calls.filter((call) => call.route === "device/commands")[1].body
      .replace_fields,
  ).toEqual(["f0"]);
});

test("a lost result acknowledgement retries reporting without replaying the page fill", async ({
  page,
}) => {
  const f = await fixture(page, { lostResult: true });
  await page.getByRole("button", { name: /Autofill this page/ }).click();
  await expect(page.locator("#message")).toContainText("Failed to fetch");
  await page.getByRole("button", { name: "Continue autofill" }).click();
  await expect(page.locator("#autofill-status")).toContainText(
    "2 filled or attached",
  );
  expect(f.count().applied).toBe(1);
  const reports = f.calls.filter((call) => call.route.endsWith("/result"));
  expect(reports[0].key).toBe(reports[1].key);
});

test("uncertain page execution cannot replay and missing facts do not create fill commands", async ({
  page,
}) => {
  const f = await fixture(page, { unknown: true });
  await page.getByRole("button", { name: /Autofill this page/ }).click();
  await expect(page.locator("#autofill-status")).toContainText(
    "uncertain outcome",
  );
  await page.getByRole("button", { name: "Continue autofill" }).click();
  await expect(page.locator("#message")).toContainText(
    "Check the application page",
  );
  expect(f.count().applied).toBe(1);
});

test("missing facts leave a useful saved preparation without an empty fill", async ({
  page,
}) => {
  const f = await fixture(page, { missing: true });
  await page.getByRole("button", { name: /Autofill this page/ }).click();
  await expect(page.locator("#autofill-status")).toContainText(
    "No approved answers match",
  );
  expect(f.calls.some((call) => call.route === "device/commands")).toBe(false);
  expect(f.count().preparationCount).toBe(1);
  await expect(page.getByLabel("Full name", { exact: true })).toBeEnabled();
});

test("AgentBrowser failure is explicit and never falls back or creates a preparation", async ({
  page,
}) => {
  const f = await fixture(page, {
    readerError: true,
    pageReader: "agent-browser",
  });
  await page.getByRole("button", { name: /Autofill this page/ }).click();
  await expect(page.locator("#message")).toContainText(
    "AgentBrowser is unavailable",
  );
  expect(f.count().preparationCount).toBe(0);
  expect(f.count().applied).toBe(0);
  await page.getByText("Capture settings", { exact: true }).click();
  await page.getByLabel("Page reader").selectOption("direct");
  await page.getByRole("button", { name: /Autofill this page/ }).click();
  await expect(page.locator("#autofill-status")).toContainText(
    "2 filled or attached",
  );
  await expect(page.locator("#reader-status")).toContainText("Direct browser");
  expect(f.count().nativeReads).toBe(1);
});

test("unknown query-distinct jobs wait for an explicit new-application choice", async ({
  page,
}) => {
  const f = await fixture(page);
  await page.getByRole("button", { name: /Autofill this page/ }).click();
  await expect(page.locator("#autofill-status")).toContainText(
    "2 filled or attached",
  );
  await f.job.evaluate(() =>
    history.replaceState(null, "", "?job=another-role"),
  );
  await f.open();
  await page.getByRole("button", { name: /Autofill this page/ }).click();
  await expect(
    page.getByRole("button", {
      name: "Continue this application",
      exact: true,
    }),
  ).toBeVisible();
  const startNew = page.getByRole("button", {
    name: "Start a new application",
    exact: true,
  });
  await expect(startNew).toBeEnabled();
  expect(f.count().preparationCount).toBe(1);
  expect(f.count().applied).toBe(1);
  await startNew.click();
  await expect
    .poll(
      () =>
        f.calls.filter((call) => call.route.endsWith("/preparations")).length,
    )
    .toBe(2);
  const calls = f.calls.filter((call) => call.route.endsWith("/preparations"));
  expect(calls[1].body.continue_preparation_id).toBeNull();
  expect(calls[1].body.continue_on_new_page).toBeUndefined();
});

test("cover-letter selection survives a lost preparation reply and uploads distinct exact files", async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const app = await fixture(page, { coverLetter: true, lostPrepare: true });
  await page
    .getByLabel("Cover letter · optional", { exact: true })
    .selectOption(letter.version_id);
  await page
    .getByRole("button", { name: "Autofill this page →", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Continue autofill", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByLabel("Cover letter · optional", { exact: true }),
  ).toBeDisabled();
  await app.open();
  await expect(
    page.getByLabel("Cover letter · optional", { exact: true }),
  ).toHaveValue(letter.version_id);
  await page
    .getByRole("button", { name: "Continue autofill", exact: true })
    .click();
  await expect
    .poll(() =>
      app.job
        .getByLabel("Cover letter", { exact: true })
        .evaluate(async (input: HTMLInputElement) => input.files?.[0]?.text()),
    )
    .toBe(letterBytes.toString());
  expect(
    await app.job
      .getByLabel("Resume", { exact: true })
      .evaluate(async (input: HTMLInputElement) => input.files?.[0]?.text()),
  ).toBe(bytes.toString());
  const prepares = app.calls.filter((call) =>
    call.route.endsWith("/preparations"),
  );
  expect(prepares).toHaveLength(2);
  expect(prepares[0]).toEqual(prepares[1]);
  expect(prepares[0].body.cover_letter_version_id).toBe(letter.version_id);
  const command = app.calls.find((call) => call.route === "device/commands")!;
  expect(command.body.uploads).toEqual({
    f3: resume.version_id,
    f4: letter.version_id,
  });
  await expect(page.locator("#autofill-status")).toContainText(
    "1 question needs your input",
  );
  expect(app.count().applied).toBe(1);
  // A later answer review recaptures the filled page and preserves the attached letter.
  await page
    .getByLabel("Why this role?")
    .fill("My reviewed fit for this role.");
  await page
    .getByRole("button", { name: "Save review and fill answers", exact: true })
    .click();
  await expect(app.job.getByLabel("Why this role?")).toHaveValue(
    "My reviewed fit for this role.",
  );
  const lastCommand = app.calls
    .filter((call) => call.route === "device/commands")
    .at(-1)!;
  expect(lastCommand.body.uploads).toEqual({});
  expect(app.count().applied).toBe(2);
  await expect(page.locator("#autofill-status")).toBeEmpty();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("cover-letter-companion.png"),
    fullPage: true,
  });
});
