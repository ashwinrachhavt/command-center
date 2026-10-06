import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";
import { buildSync } from "esbuild";
import type { components } from "../src/lib/api-types";

// Regression: ISSUE-001 — Ashby Yes/No buttons were absent from captured forms.
// Found by /qa on 2026-09-24.
// Report: .local/extension-qa/qa-report.md
type Snapshot = components["schemas"]["SnapshotCreate"];
type Result = { field_results: Record<string, { status: string }> };
const script = (name: string) =>
  readFileSync(path.resolve(__dirname, `../../extension/${name}`), "utf8");
const fixture = buildSync({
  stdin: {
    contents: `import React from 'react'; import {createRoot} from 'react-dom/client';
      function Question() {
        const [answer, setAnswer] = React.useState(null);
        return <form onSubmit={event => { event.preventDefault(); window.submits++; }}>
          <div className="ashby-application-form-field-entry">
            <label className="_required_synthetic_1">Available for an interview?</label>
            <div className="ashby-application-form-input-yesno">
              {['yes','no'].map(value => <button key={value} data-option={value}
                aria-pressed={answer === value} onClick={() => setAnswer(value)}>
                {value === 'yes' ? 'Yes' : 'No'}</button>)}
              <input type="checkbox" hidden readOnly checked={answer === 'yes'} />
            </div>
          </div>
          <output>{answer ?? 'unanswered'}</output><button type="submit">Submit</button>
        </form>;
      }
      window.submits = 0; createRoot(document.getElementById('root')).render(<Question/>);`,
    loader: "jsx",
    resolveDir: path.resolve(__dirname, ".."),
  },
  bundle: true,
  format: "iife",
  write: false,
}).outputFiles[0].text;

async function install(page: Page) {
  await page.goto("/fixtures/application.html");
  await page.setContent('<div id="root"></div>');
  await page.addScriptTag({ content: fixture });
  await expect(
    page.getByRole("button", { name: "Yes", exact: true }),
  ).toBeVisible();
  await page.evaluate(() => {
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
  });
  await page.addScriptTag({ content: script("contracts.js") });
  await page.addScriptTag({ content: script("content.js") });
}

function message<T>(page: Page, payload: unknown): Promise<T> {
  return page.evaluate(
    (payload) =>
      new Promise<unknown>((resolve) => {
        const bridge = window as unknown as {
          companion: (
            message: unknown,
            sender: unknown,
            reply: (value: unknown) => void,
          ) => void;
        };
        bridge.companion(payload, { id: "synthetic" }, resolve);
      }),
    payload,
  ) as Promise<T>;
}
const inspect = (page: Page) =>
  message<Snapshot>(page, { version: 2, action: "inspect" });
const apply = (
  page: Page,
  snapshot: Snapshot,
  value: string,
  replace = false,
) =>
  message<Result>(page, {
    version: 2,
    action: "apply",
    command: {
      snapshot_id: snapshot.id,
      page_url: snapshot.page_url,
      fields: { [snapshot.fields[0].id]: value },
      uploads: {},
      replace_fields: replace ? [snapshot.fields[0].id] : [],
      preparation_version_id: null,
    },
    files: {},
  });

test("captures one required question and fills an explicit No through React without submitting", async ({
  page,
}) => {
  await install(page);
  const snapshot = await inspect(page);
  expect(snapshot.fields).toHaveLength(1);
  expect(snapshot.fields[0]).toMatchObject({
    label: "Available for an interview?",
    type: "radio",
    required: true,
    options: ["yes", "no"],
    value_state: "empty",
  });
  const result = await apply(page, snapshot, "no");
  expect(result.field_results.f0.status).toBe("filled");
  await expect(page.locator("output")).toHaveText("no");
  await expect(
    page.getByRole("button", { name: "No", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  expect(
    await page.evaluate(
      () => (window as unknown as { submits: number }).submits,
    ),
  ).toBe(0);
});

test("preserves an existing No and allows only an explicitly reviewed replacement", async ({
  page,
}) => {
  await install(page);
  await page.getByRole("button", { name: "No", exact: true }).click();
  let snapshot = await inspect(page);
  expect(snapshot.fields[0].value_state).toBe("present");
  expect((await apply(page, snapshot, "yes")).field_results.f0.status).toBe(
    "preserved",
  );
  await expect(page.locator("output")).toHaveText("no");
  snapshot = await inspect(page);
  expect(
    (await apply(page, snapshot, "yes", true)).field_results.f0.status,
  ).toBe("filled");
  await expect(page.locator("output")).toHaveText("yes");
});

test("preserves an answer changed after capture even when replacement was requested", async ({
  page,
}) => {
  await install(page);
  const snapshot = await inspect(page);
  await page.getByRole("button", { name: "No", exact: true }).click();
  expect(
    (await apply(page, snapshot, "yes", true)).field_results.f0.status,
  ).toBe("preserved");
  await expect(page.locator("output")).toHaveText("no");
});

for (const change of ["disabled", "removed", "relabeled"] as const) {
  test(`rejects a ${change} choice after capture`, async ({ page }) => {
    await install(page);
    const snapshot = await inspect(page);
    await page
      .getByRole("button", { name: "No", exact: true })
      .evaluate((element, change) => {
        if (change === "disabled")
          (element as HTMLButtonElement).disabled = true;
        if (change === "removed") element.remove();
        if (change === "relabeled") element.textContent = "Unknown";
      }, change);
    expect((await apply(page, snapshot, "yes")).field_results.f0.status).toBe(
      "rejected",
    );
    await expect(page.locator("output")).toHaveText("unanswered");
  });
}

test("does not report success when the site does not retain a selection", async ({
  page,
}) => {
  await install(page);
  const snapshot = await inspect(page);
  await page
    .getByRole("button", { name: "No", exact: true })
    .evaluate((element) => {
      element.addEventListener("click", (event) => event.stopPropagation());
    });
  expect((await apply(page, snapshot, "no")).field_results.f0.status).toBe(
    "outcome_unknown",
  );
  await expect(page.locator("output")).toHaveText("unanswered");
});
