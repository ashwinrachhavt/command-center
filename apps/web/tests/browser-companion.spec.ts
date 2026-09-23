import { expect, test, type Page } from "@playwright/test";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";

import type { components } from "../src/lib/api-types";

type Snapshot = components["schemas"]["SnapshotCreate"];
type FormField = components["schemas"]["FormField"];
type ApplyResult = {
  state: "applied" | "partial" | "rejected" | "failed" | "outcome_unknown";
  field_results: Record<
    string,
    {
      status:
        | "filled"
        | "uploaded"
        | "preserved"
        | "unsupported"
        | "rejected"
        | "failed"
        | "outcome_unknown";
      detail: string;
    }
  >;
  message: string;
};

const extensionScript = readFileSync(
  path.resolve(__dirname, "../../extension/content.js"),
  "utf8",
);
const contracts = readFileSync(
  path.resolve(__dirname, "../../extension/contracts.js"),
  "utf8",
);
const popupScript = readFileSync(
  path.resolve(__dirname, "../../extension/popup.js"),
  "utf8",
);
const popupHtml = readFileSync(
  path.resolve(__dirname, "../../extension/popup.html"),
  "utf8",
).replace(/<script[\s\S]*?<\/script>/g, "");

async function install(page: Page, fixture = "application.html") {
  await page.goto("/fixtures/application.html");
  if (fixture !== "application.html") {
    await page.setContent(
      readFileSync(
        path.resolve(__dirname, `../public/fixtures/${fixture}`),
        "utf8",
      ),
      { waitUntil: "load" },
    );
  }
  await page.evaluate(() => {
    Object.assign(window, {
      chrome: {
        runtime: {
          id: "synthetic-extension",
          onMessage: {
            addListener(listener: unknown) {
              Object.assign(window, { companion: listener });
            },
          },
        },
      },
    });
  });
  await page.addScriptTag({ content: contracts });
  await page.addScriptTag({ content: extensionScript });
}

async function message<T>(page: Page, payload: unknown): Promise<T> {
  return page.evaluate(
    (payload) =>
      new Promise<unknown>((resolve) => {
        const bridge = window as unknown as {
          companion: (
            message: unknown,
            sender: unknown,
            respond: (data: unknown) => void,
          ) => void;
        };
        bridge.companion(payload, { id: "synthetic-extension" }, resolve);
      }),
    payload,
  ) as Promise<T>;
}

const inspect = (page: Page) =>
  message<Snapshot>(page, { version: 2, action: "inspect" });

function named(snapshot: Snapshot, label: string): FormField {
  const field = snapshot.fields.find((candidate) => candidate.label === label);
  if (!field) throw new Error(`Missing synthetic field: ${label}`);
  return field;
}

function command(
  snapshot: Snapshot,
  fields: Record<string, string> = {},
  uploads: Record<string, string> = {},
  replaceFields: string[] = [],
) {
  return {
    snapshot_id: snapshot.id,
    page_url: snapshot.page_url,
    fields,
    uploads,
    replace_fields: replaceFields,
    preparation_version_id: null,
  };
}

test("native controls preserve existing values, fill empty fields once, and never submit", async ({
  page,
}) => {
  await install(page);
  await page.locator("#name").fill("Existing local value");
  const snapshot = await inspect(page);
  const name = named(snapshot, "Full name");
  const email = named(snapshot, "Email address");
  const role = named(snapshot, "Role");

  expect(snapshot.protocol_version).toBe(2);
  expect(name.value_state).toBe("present");
  expect(name.autocomplete).toBe("name");
  expect(role.option_labels).toMatchObject({
    "Staff Engineer": "Staff Engineer",
  });
  expect(JSON.stringify(snapshot)).not.toContain("Existing local value");
  expect(JSON.stringify(snapshot)).not.toContain("synthetic-secret");

  const fill = command(snapshot, {
    [name.id]: "Replacement without permission",
    [email.id]: "synthetic@example.com",
    [role.id]: "Staff Engineer",
  });
  const result = await message<ApplyResult>(page, {
    version: 2,
    action: "apply",
    command: fill,
    files: {},
  });
  expect(result).toMatchObject({
    state: "partial",
    field_results: {
      [name.id]: { status: "preserved" },
      [email.id]: { status: "filled" },
      [role.id]: { status: "filled" },
    },
  });
  await expect(page.locator("#name")).toHaveValue("Existing local value");
  await expect(page.locator("#email")).toHaveValue("synthetic@example.com");
  await expect(page.locator("#role")).toHaveValue("Staff Engineer");
  await expect(page.locator("#outcome")).toHaveText("Not submitted");
  expect(
    await message(page, {
      version: 2,
      action: "apply",
      command: fill,
      files: {},
    }),
  ).toMatchObject({ state: "rejected" });
});

test("late local edits stay preserved unless replacement is explicit", async ({
  page,
}) => {
  await install(page);
  let snapshot = await inspect(page);
  let name = named(snapshot, "Full name");
  await page.locator("#name").fill("Draft typed after sharing");
  let result = await message<ApplyResult>(page, {
    version: 2,
    action: "apply",
    command: command(snapshot, { [name.id]: "Suggested name" }),
    files: {},
  });
  expect(result.field_results[name.id].status).toBe("preserved");
  await expect(page.locator("#name")).toHaveValue("Draft typed after sharing");

  snapshot = await inspect(page);
  name = named(snapshot, "Full name");
  result = await message<ApplyResult>(page, {
    version: 2,
    action: "apply",
    command: command(snapshot, { [name.id]: "Explicit replacement" }, {}, [
      name.id,
    ]),
    files: {},
  });
  expect(result.field_results[name.id].status).toBe("filled");
  await expect(page.locator("#name")).toHaveValue("Explicit replacement");
});

test("radio and checkbox commands use actual values and do not advance", async ({
  page,
}) => {
  await install(page, "application-grouped.html");
  const snapshot = await inspect(page);
  const workMode = named(snapshot, "Preferred work arrangement");
  const relocate = named(snapshot, "Open to relocation");
  expect(workMode).toMatchObject({
    type: "radio",
    options: ["remote", "hybrid", "onsite"],
  });
  expect(workMode.option_labels).toMatchObject({
    remote: "Remote",
    hybrid: "Hybrid",
  });
  expect(relocate.type).toBe("checkbox");

  const result = await message<ApplyResult>(page, {
    version: 2,
    action: "apply",
    command: command(snapshot, {
      [workMode.id]: "hybrid",
      [relocate.id]: "true",
    }),
    files: {},
  });
  expect(result.state).toBe("applied");
  expect(result.field_results[workMode.id].status).toBe("filled");
  expect(result.field_results[relocate.id].status).toBe("filled");
  await expect(page.locator('input[value="hybrid"]')).toBeChecked();
  await expect(page.locator("#relocate")).toBeChecked();
  await expect(page.locator("#outcome")).toHaveText("Not advanced");
});

test("reviewed replacements preserve newer edits and deliberate clears", async ({
  page,
}) => {
  await install(page);
  await page.locator("#name").fill("Value present at review");
  const snapshot = await inspect(page);
  const name = named(snapshot, "Full name");
  const email = named(snapshot, "Email address");
  await page.locator("#name").fill("Newer local edit");
  await page.locator("#email").fill("typed@example.test");
  await page.locator("#email").clear();
  const result = await message<ApplyResult>(page, {
    version: 2,
    action: "apply",
    command: command(
      snapshot,
      {
        [name.id]: "Reviewed replacement",
        [email.id]: "suggested@example.test",
      },
      {},
      [name.id],
    ),
    files: {},
  });
  expect(result.field_results[name.id].status).toBe("preserved");
  expect(result.field_results[email.id].status).toBe("preserved");
  await expect(page.locator("#name")).toHaveValue("Newer local edit");
  await expect(page.locator("#email")).toHaveValue("");
  await expect(page.locator("#outcome")).toHaveText("Not submitted");
});

test("hidden associated file input receives the exact verified resume bytes", async ({
  page,
}) => {
  await install(page, "application-upload.html");
  const snapshot = await inspect(page);
  const resume = named(snapshot, "Upload resume");
  expect(resume).toMatchObject({
    type: "file",
    accept: ".pdf,application/pdf",
    value_state: "empty",
  });
  const bytes = Buffer.from("%PDF-1.4\nSynthetic exact resume bytes\n", "utf8");
  const versionId = "00000000-0000-4000-8000-000000000123";
  const transfer = {
    version_id: versionId,
    filename: "synthetic-resume.pdf",
    media_type: "application/pdf",
    size_bytes: bytes.length,
    sha256: createHash("sha256").update(bytes).digest("hex"),
    data_base64: bytes.toString("base64"),
  };
  const result = await message<ApplyResult>(page, {
    version: 2,
    action: "apply",
    command: command(snapshot, {}, { [resume.id]: versionId }),
    files: { [resume.id]: transfer },
  });
  expect(result.field_results[resume.id].status).toBe("uploaded");
  expect(
    await page.locator("#resume").evaluate(async (input: HTMLInputElement) => {
      const file = input.files?.[0];
      return file
        ? {
            name: file.name,
            type: file.type,
            size: file.size,
            contents: await file.text(),
          }
        : null;
    }),
  ).toEqual({
    name: transfer.filename,
    type: transfer.media_type,
    size: bytes.length,
    contents: bytes.toString("utf8"),
  });
  await expect(page.locator("#outcome")).toHaveText("Not submitted");
});

test("incompatible file accepts are rejected without assigning a file", async ({
  page,
}) => {
  await install(page, "application-upload.html");
  const snapshot = await inspect(page);
  const resume = named(snapshot, "Upload resume");
  const bytes = Buffer.from("synthetic text resume", "utf8");
  const versionId = "00000000-0000-4000-8000-000000000124";
  const result = await message<ApplyResult>(page, {
    version: 2,
    action: "apply",
    command: command(snapshot, {}, { [resume.id]: versionId }),
    files: {
      [resume.id]: {
        version_id: versionId,
        filename: "synthetic-resume.txt",
        media_type: "text/plain",
        size_bytes: bytes.length,
        sha256: createHash("sha256").update(bytes).digest("hex"),
        data_base64: bytes.toString("base64"),
      },
    },
  });
  expect(result).toMatchObject({
    state: "rejected",
    field_results: { [resume.id]: { status: "rejected" } },
  });
  expect(
    await page
      .locator("#resume")
      .evaluate((input: HTMLInputElement) => input.files?.length),
  ).toBe(0);
});

test("resume verification cannot overwrite a file chosen during the async check", async ({
  page,
}) => {
  await install(page, "application-upload.html");
  const input = page.locator("#resume");
  const original = {
    name: "original.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("original"),
  };
  await input.setInputFiles(original);
  const snapshot = await inspect(page);
  const resume = named(snapshot, "Upload resume");
  const bytes = Buffer.from("reviewed resume");
  const versionId = "00000000-0000-4000-8000-000000000125";
  await page.evaluate(() => {
    const originalDigest = crypto.subtle.digest.bind(crypto.subtle);
    let first = true;
    crypto.subtle.digest = async (...args) => {
      if (first) {
        first = false;
        await new Promise<void>((resolve) =>
          Object.assign(window, { releaseVerification: resolve }),
        );
      }
      return originalDigest(...args);
    };
  });
  const pending = message<ApplyResult>(page, {
    version: 2,
    action: "apply",
    command: command(snapshot, {}, { [resume.id]: versionId }, [resume.id]),
    files: {
      [resume.id]: {
        version_id: versionId,
        filename: "reviewed.pdf",
        media_type: "application/pdf",
        size_bytes: bytes.length,
        sha256: createHash("sha256").update(bytes).digest("hex"),
        data_base64: bytes.toString("base64"),
      },
    },
  });
  await expect
    .poll(() => page.evaluate(() => "releaseVerification" in window))
    .toBe(true);
  await input.setInputFiles({
    ...original,
    name: "new-local-choice.pdf",
    buffer: Buffer.from("new choice"),
  });
  await page.evaluate(() =>
    (
      window as unknown as { releaseVerification: () => void }
    ).releaseVerification(),
  );
  const result = await pending;
  expect(result.field_results[resume.id].status).toBe("preserved");
  expect(
    await input.evaluate(
      (element: HTMLInputElement) => element.files?.[0].name,
    ),
  ).toBe("new-local-choice.pdf");
});

test("custom widgets are disclosed as unsupported while native controls remain usable", async ({
  page,
}) => {
  await install(page, "application-custom.html");
  const snapshot = await inspect(page);
  const unsupported = [
    named(snapshot, "Country"),
    named(snapshot, "Available start date"),
    named(snapshot, "Rich text cover letter"),
  ];
  const headline = named(snapshot, "Professional headline");
  for (const field of unsupported) {
    expect(field.type).toBe("unsupported");
    expect(field.unsupported_reason).toBeTruthy();
  }
  const result = await message<ApplyResult>(page, {
    version: 2,
    action: "apply",
    command: command(snapshot, {
      [headline.id]: "Synthetic platform engineer",
    }),
    files: {},
  });
  expect(result.field_results[headline.id].status).toBe("filled");
  await expect(page.locator("#headline")).toHaveValue(
    "Synthetic platform engineer",
  );
});

test("schema changes reject before mutation and dynamic replacement reports unknown outcome", async ({
  page,
}) => {
  await install(page, "application-dynamic.html");
  let snapshot = await inspect(page);
  let title = named(snapshot, "Current title");
  await page.locator('label[for="current-title"]').evaluate((label) => {
    label.textContent = "Bank account";
  });
  let result = await message<ApplyResult>(page, {
    version: 2,
    action: "apply",
    command: command(snapshot, { [title.id]: "Never written" }),
    files: {},
  });
  expect(result.state).toBe("rejected");
  await expect(page.locator("#current-title")).toHaveValue("");

  await page.locator('label[for="current-title"]').evaluate((label) => {
    label.textContent = "Current title";
  });
  snapshot = await inspect(page);
  title = named(snapshot, "Answer replaced during input");
  result = await message<ApplyResult>(page, {
    version: 2,
    action: "apply",
    command: command(snapshot, { [title.id]: "Synthetic answer" }),
    files: {},
  });
  expect(result).toMatchObject({
    state: "outcome_unknown",
    field_results: { [title.id]: { status: "outcome_unknown" } },
  });
  await expect(page.locator("#outcome")).toHaveText("Not advanced");
});

test("changed URL and incompatible protocol are rejected before touching the form", async ({
  page,
}) => {
  await install(page);
  const snapshot = await inspect(page);
  const name = named(snapshot, "Full name");
  await page.evaluate(() =>
    history.pushState({}, "", "?different-application=1"),
  );
  expect(
    await message(page, {
      version: 2,
      action: "apply",
      command: command(snapshot, { [name.id]: "Never written" }),
      files: {},
    }),
  ).toMatchObject({ state: "rejected" });
  await expect(page.locator("#name")).toHaveValue("");
  expect(await message(page, { version: 1, action: "inspect" })).toMatchObject({
    state: "rejected",
  });
});

test("popup follows generation to completion and preserves a local answer", async ({
  page,
}) => {
  await page.setContent(popupHtml);
  await page.evaluate(() => {
    const base = {
      id: "preparation-1",
      snapshot_id: "snapshot-1",
      task_id: "task-1",
      opportunity_id: null,
      artifact_id: "artifact-1",
      version_id: "version-1",
      version: 1,
      resume: null,
      replace_fields: [],
      upload_fields: [],
      fields: [
        {
          field_id: "f0",
          status: "needs_input",
          value: null,
          reason: "Needs an answer.",
          evidence: [],
        },
      ],
      created_at: "2026-09-21T10:00:00Z",
    };
    const storage = {
      connection: {
        base: "http://localhost:8000",
        token: "synthetic-device-token",
      },
      applicationDraft: {
        snapshot: {
          id: "snapshot-1",
          protocol_version: 2,
          page_url: "https://jobs.example.test/apply",
          full_url: "https://jobs.example.test/apply",
          title: "Synthetic application",
          fields: [
            {
              id: "f0",
              label: "Narrative",
              type: "textarea",
              required: true,
              options: [],
              option_labels: {},
              value_state: "empty",
              autocomplete: "",
              accept: "",
              unsupported_reason: null,
            },
          ],
        },
        preparation: base,
        values: { f0: "Keep my local answer." },
        touched: { f0: true },
        replacementTouched: {},
        uploadTouched: {},
        replaceFields: [],
        uploadFields: [],
        resumeVersionId: null,
        receipts: {},
        generation: {
          conversation_id: "session-1",
          run_id: "run-1",
          state: "queued",
          error_code: null,
        },
      },
      claimedCommands: [],
    };
    let generationPoll = 0;
    Object.assign(window, {
      CommandCenterContracts: new Proxy({}, { get: () => () => true }),
      chrome: {
        storage: {
          local: {
            setAccessLevel: async () => undefined,
            get: async () => storage,
            set: async (values: Record<string, unknown>) =>
              Object.assign(storage, values),
            remove: async () => undefined,
          },
        },
        tabs: { query: async () => [] },
        scripting: { executeScript: async () => undefined },
      },
      popupStorage: storage,
    });
    window.fetch = async (input) => {
      const route = new URL(String(input)).pathname;
      if (
        route.endsWith("/device/resumes") ||
        route.endsWith("/device/cover-letters")
      )
        return Response.json({ default_version_id: null, items: [] });
      if (route.endsWith("/generation")) {
        generationPoll += 1;
        return Response.json({
          conversation_id: "session-1",
          run_id: "run-1",
          state:
            generationPoll === 1
              ? "queued"
              : generationPoll === 2
                ? "running"
                : "completed",
          error_code: null,
        });
      }
      if (route.endsWith("/device/preparations/preparation-1"))
        return Response.json({
          ...base,
          version_id: "version-2",
          version: 2,
          fields: [
            {
              field_id: "f0",
              status: "suggested",
              value: "Generated answer must not replace the local edit.",
              reason: "Generated from approved facts.",
              evidence: [],
            },
          ],
        });
      return Response.json(
        { detail: `Unexpected fixture route: ${route}` },
        { status: 404 },
      );
    };
  });
  await page.addScriptTag({ content: popupScript, type: "module" });

  await expect(
    page.getByRole("button", { name: "Generation queued" }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: /Save review/ }),
  ).toBeDisabled();
  await expect(
    page.getByText("Grounded drafts are ready for review."),
  ).toBeVisible({
    timeout: 4_000,
  });
  await expect(page.getByLabel("Narrative")).toHaveValue(
    "Keep my local answer.",
  );
  await expect(
    page.getByRole("button", { name: "Generate grounded drafts" }),
  ).toBeEnabled();
  await expect(page.getByRole("button", { name: /Save review/ })).toBeEnabled();
});
