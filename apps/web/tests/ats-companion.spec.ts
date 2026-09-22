import { expect, test, type Page } from "@playwright/test";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { buildSync } from "esbuild";

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
const reactFixtureScript = buildSync({
  bundle: true,
  entryPoints: [path.resolve(__dirname, "fixtures/ats-react.tsx")],
  format: "iife",
  platform: "browser",
  write: false,
}).outputFiles[0].text;
const greenhouseFixtureScript = buildSync({
  bundle: true,
  entryPoints: [path.resolve(__dirname, "fixtures/ats-greenhouse-react.tsx")],
  format: "iife",
  platform: "browser",
  write: false,
}).outputFiles[0].text;

async function installBridge(page: Page) {
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

async function installStatic(page: Page, fixture: string) {
  await page.goto("/fixtures/application.html");
  await page.setContent(
    readFileSync(
      path.resolve(__dirname, `../public/fixtures/${fixture}`),
      "utf8",
    ),
    { waitUntil: "load" },
  );
  await installBridge(page);
}

async function installReact(page: Page) {
  await page.goto("/fixtures/application.html");
  await page.setContent(
    '<!doctype html><html lang="en"><head><title>React ATS fixture</title></head><body><div id="root"></div></body></html>',
  );
  await page.addScriptTag({ content: reactFixtureScript });
  await expect(page.locator("#ashby-form")).toBeVisible();
  await installBridge(page);
}

async function installGreenhouse(page: Page, mode = "valid") {
  await page.goto("/fixtures/application.html");
  await page.setContent(
    `<!doctype html><html lang="en"><head><title>Greenhouse React fixture</title></head><body><div id="root" data-mode="${mode}"></div></body></html>`,
  );
  await page.addScriptTag({ content: greenhouseFixtureScript });
  await expect(page.locator(".select__input")).toBeVisible();
  await installBridge(page);
}

async function message<T>(page: Page, payload: unknown): Promise<T> {
  return page.evaluate(
    (nextPayload) =>
      new Promise<unknown>((resolve) => {
        const bridge = window as unknown as {
          companion: (
            message: unknown,
            sender: unknown,
            respond: (data: unknown) => void,
          ) => void;
        };
        bridge.companion(nextPayload, { id: "synthetic-extension" }, resolve);
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

async function chooseGreenhouseOption(page: Page, label: string) {
  await page.locator(".select__input").press("ArrowDown");
  await page.getByRole("option", { name: label, exact: true }).click();
  await expect(page.locator(".select__input")).toHaveAttribute(
    "aria-expanded",
    "false",
  );
}

test("inspects and fills only the visible same-origin iCIMS application frame", async ({
  page,
}) => {
  await installStatic(page, "application-icims-frame.html");
  const snapshot = await inspect(page);
  const email = named(snapshot, "Email");

  expect(snapshot.fields.map((field) => field.label)).toEqual(["Email"]);
  expect(email.type).toBe("email");

  const result = await message<ApplyResult>(page, {
    version: 2,
    action: "apply",
    command: command(snapshot, { [email.id]: "candidate@example.test" }),
    files: {},
  });

  expect(result.field_results[email.id].status).toBe("filled");
  await expect(
    page.frameLocator("#application-frame").locator("#email"),
  ).toHaveValue("candidate@example.test");
  await expect(
    page.frameLocator("#application-frame").locator("#outcome"),
  ).toHaveText("Not advanced");
});

test("rejects an iCIMS capture after the frame document reloads at the same URL", async ({
  page,
}) => {
  await installStatic(page, "application-icims-frame.html");
  const snapshot = await inspect(page);
  const email = named(snapshot, "Email");
  const frameElement = await page.locator("#application-frame").elementHandle();
  const originalUrl = (await frameElement?.contentFrame())?.url();

  await page.locator("#application-frame").evaluate((element) => {
    const frame = element as HTMLIFrameElement;
    frame.srcdoc = frame.srcdoc.replace(
      "Original document",
      "Replacement document",
    );
  });
  await expect(
    page.frameLocator("#application-frame").locator("#document-marker"),
  ).toHaveText("Replacement document");
  const reloadedUrl = (await frameElement?.contentFrame())?.url();
  expect(originalUrl).toBe("about:srcdoc");
  expect(reloadedUrl).toBe("about:srcdoc");

  const result = await message<ApplyResult>(page, {
    version: 2,
    action: "apply",
    command: command(snapshot, { [email.id]: "must-not-write@example.test" }),
    files: {},
  });

  expect(result.state).toBe("rejected");
  expect(result.field_results[email.id].status).toBe("rejected");
  await expect(
    page.frameLocator("#application-frame").locator("#email"),
  ).toHaveValue("");
});

test("applies reviewed values to React state and uploads only the explicit Ashby resume field", async ({
  page,
}) => {
  await installReact(page);
  const snapshot = await inspect(page);
  const name = named(snapshot, "Full name");
  const workMode = named(snapshot, "Preferred work arrangement");
  const relocate = named(snapshot, "Open to relocation");
  const autofill = named(snapshot, "Autofill from resume");
  const resume = named(snapshot, "Resume");
  const bytes = Buffer.from("%PDF-1.4\nSynthetic ATS resume bytes\n", "utf8");
  const versionId = "00000000-0000-4000-8000-000000000987";

  const result = await message<ApplyResult>(page, {
    version: 2,
    action: "apply",
    command: command(
      snapshot,
      {
        [name.id]: "Synthetic Candidate",
        [workMode.id]: "hybrid",
        [relocate.id]: "true",
      },
      { [resume.id]: versionId },
    ),
    files: {
      [resume.id]: {
        version_id: versionId,
        filename: "reviewed-resume.pdf",
        media_type: "application/pdf",
        size_bytes: bytes.length,
        sha256: createHash("sha256").update(bytes).digest("hex"),
        data_base64: bytes.toString("base64"),
      },
    },
  });

  expect(result.state).toBe("applied");
  expect(result.field_results).toMatchObject({
    [name.id]: { status: "filled" },
    [workMode.id]: { status: "filled" },
    [relocate.id]: { status: "filled" },
    [resume.id]: { status: "uploaded" },
  });
  expect(result.field_results[autofill.id]).toBeUndefined();
  await expect(page.locator("#candidate-name")).toHaveValue(
    "Synthetic Candidate",
  );
  await expect(page.locator('input[value="hybrid"]')).toBeChecked();
  await expect(page.locator("#relocate")).toBeChecked();
  expect(
    await page
      .locator("#actual-resume")
      .evaluate((input: HTMLInputElement) => input.files?.[0]?.name),
  ).toBe("reviewed-resume.pdf");
  expect(
    await page
      .locator("#autofill-resume")
      .evaluate((input: HTMLInputElement) => input.files?.length),
  ).toBe(0);
  await expect(page.locator("#react-state")).toHaveText(
    JSON.stringify({
      name: "Synthetic Candidate",
      workMode: "hybrid",
      relocate: true,
      autofillFilename: "",
      resumeFilename: "reviewed-resume.pdf",
      submitted: false,
    }),
  );
});

test("keeps Lever location manual when canonical selectedLocation is unproven", async ({
  page,
}) => {
  await installStatic(page, "application-lever-location.html");
  const snapshot = await inspect(page);
  const location = named(snapshot, "Current location");

  expect(location.type).toBe("unsupported");
  expect(location.unsupported_reason).toMatch(/manual|selection/i);

  const result = await message<ApplyResult>(page, {
    version: 2,
    action: "apply",
    command: command(snapshot, { [location.id]: "Seattle, Washington" }),
    files: {},
  });

  expect(result.field_results[location.id].status).toBe("unsupported");
  await expect(page.locator("#location-input")).toHaveValue("");
  await expect(page.locator("#selected-location")).toHaveValue("");
  await expect(page.locator("#outcome")).toHaveText("Not submitted");
});

test("selects one exact Greenhouse option and updates canonical React state", async ({
  page,
}) => {
  await installGreenhouse(page);
  const snapshot = await inspect(page);
  const country = named(snapshot, "Country");

  expect(country).toMatchObject({
    type: "select",
    options: ["Canada", "United States"],
    option_labels: {
      Canada: "Canada",
      "United States": "United States",
    },
    value_state: "empty",
  });
  await expect(page.locator(".select__input")).toHaveValue("");
  await expect(page.locator(".select__input")).toHaveAttribute(
    "aria-expanded",
    "false",
  );

  const result = await message<ApplyResult>(page, {
    version: 2,
    action: "apply",
    command: command(snapshot, { [country.id]: "United States" }),
    files: {},
  });

  expect(result.field_results[country.id].status).toBe("filled");
  await expect(page.locator(".select__single-value")).toHaveText(
    "United States",
  );
  await expect(page.locator("#greenhouse-state")).toHaveText(
    JSON.stringify({
      selected: "United States",
      headline: "",
      submitted: false,
    }),
  );
  await page.locator(".select__input").press("ArrowDown");
  await expect(
    page.getByRole("option", { name: "United States", exact: true }),
  ).toHaveClass(/select__option--is-selected/);
  await page.locator(".select__input").press("Escape");
});

test("preserves existing and newer Greenhouse selections", async ({ page }) => {
  await installGreenhouse(page);
  await chooseGreenhouseOption(page, "Canada");
  let snapshot = await inspect(page);
  let country = named(snapshot, "Country");
  expect(country.value_state).toBe("present");

  let result = await message<ApplyResult>(page, {
    version: 2,
    action: "apply",
    command: command(snapshot, { [country.id]: "United States" }),
    files: {},
  });
  expect(result.field_results[country.id].status).toBe("preserved");
  await expect(page.locator(".select__single-value")).toHaveText("Canada");

  await installGreenhouse(page);
  snapshot = await inspect(page);
  country = named(snapshot, "Country");
  await chooseGreenhouseOption(page, "Canada");
  result = await message<ApplyResult>(page, {
    version: 2,
    action: "apply",
    command: command(snapshot, { [country.id]: "United States" }, {}, [
      country.id,
    ]),
    files: {},
  });
  expect(result.field_results[country.id].status).toBe("preserved");
  await expect(page.locator(".select__single-value")).toHaveText("Canada");
});

test("rejects Greenhouse option drift before touching a native field", async ({
  page,
}) => {
  await installGreenhouse(page);
  const snapshot = await inspect(page);
  const country = named(snapshot, "Country");
  const headline = named(snapshot, "Professional headline");
  await page.locator("#drift-options").click();

  const result = await message<ApplyResult>(page, {
    version: 2,
    action: "apply",
    command: command(snapshot, {
      [country.id]: "United States",
      [headline.id]: "Must not be written",
    }),
    files: {},
  });

  expect(result.state).toBe("rejected");
  expect(result.field_results).toMatchObject({
    [country.id]: { status: "rejected" },
    [headline.id]: { status: "rejected" },
  });
  await expect(page.locator("#headline")).toHaveValue("");
  await expect(page.locator(".select__single-value")).toHaveCount(0);
});

test("keeps duplicate-label Greenhouse choices unsupported", async ({
  page,
}) => {
  await installGreenhouse(page, "duplicate");
  const snapshot = await inspect(page);
  const country = named(snapshot, "Country");

  expect(country.type).toBe("unsupported");
  expect(country.unsupported_reason).toMatch(/duplicate|unique|manual/i);
  await expect(page.locator(".select__input")).toHaveAttribute(
    "aria-expanded",
    "false",
  );
});

test("applies only a valid numeric value within captured range and step", async ({
  page,
}) => {
  await installStatic(page, "application-number.html");
  let snapshot = await inspect(page);
  let years = named(snapshot, "Years of relevant experience");

  expect(years).toMatchObject({
    type: "number",
    numeric_constraints: {
      minimum: "1.5",
      maximum: "10.5",
      step: "0.5",
      step_base: "1.5",
    },
  });
  let result = await message<ApplyResult>(page, {
    version: 2,
    action: "apply",
    command: command(snapshot, { [years.id]: "3.5" }),
    files: {},
  });
  expect(result.field_results[years.id].status).toBe("filled");
  await expect(page.locator("#years")).toHaveValue("3.5");

  await installStatic(page, "application-number.html");
  snapshot = await inspect(page);
  years = named(snapshot, "Years of relevant experience");
  result = await message<ApplyResult>(page, {
    version: 2,
    action: "apply",
    command: command(snapshot, { [years.id]: "3.7" }),
    files: {},
  });
  expect(result.field_results[years.id].status).toBe("rejected");
  await expect(page.locator("#years")).toHaveValue("");
  await expect(page.locator("#outcome")).toHaveText("Not submitted");
});

test("rejects changed numeric constraints before any other field is written", async ({
  page,
}) => {
  await installStatic(page, "application-number.html");
  const snapshot = await inspect(page);
  const years = named(snapshot, "Years of relevant experience");
  const headline = named(snapshot, "Professional headline");
  await page.locator("#years").evaluate((element) => {
    element.setAttribute("min", "2");
    element.setAttribute("step", "1");
  });

  const result = await message<ApplyResult>(page, {
    version: 2,
    action: "apply",
    command: command(snapshot, {
      [years.id]: "3.5",
      [headline.id]: "Must not be written",
    }),
    files: {},
  });

  expect(result.state).toBe("rejected");
  expect(result.field_results).toMatchObject({
    [years.id]: { status: "rejected" },
    [headline.id]: { status: "rejected" },
  });
  await expect(page.locator("#years")).toHaveValue("");
  await expect(page.locator("#headline")).toHaveValue("");
  await expect(page.locator("#outcome")).toHaveText("Not submitted");
});
