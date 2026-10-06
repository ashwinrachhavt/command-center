import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";

// Regression: ISSUE-002 — Overview failed with the recovery instruction below the fold.
// Found by /qa on 2026-09-24.
// Report: .local/extension-qa/qa-report.md
const read = (name: string) =>
  readFileSync(path.resolve(__dirname, `../../extension/${name}`), "utf8");
const posting =
  "https://jobs.ashbyhq.com/synthetic/12345678-1234-1234-1234-123456789abc";

async function install(page: Page, url: string, mode = "empty") {
  await page.goto("/fixtures/application.html");
  await page.setContent(
    read("popup.html").replace(/<script[\s\S]*?<\/script>/g, ""),
  );
  await page.addStyleTag({ content: read("popup.css") });
  await page.evaluate(
    ({ url, mode }) => {
      const state = {
        url,
        navigations: [] as string[],
        injections: 0,
        captures: 0,
        pendingUrl: "",
        polls: 0,
        granted: !mode.startsWith("access-"),
        permissionRequests: [] as string[][],
      };
      Object.assign(window, {
        qaState: state,
        chrome: {
          permissions: {
            async contains() {
              return state.granted;
            },
            async request({ origins }: { origins: string[] }) {
              state.permissionRequests.push(origins);
              if (mode === "access-denied") return false;
              state.granted = true;
              if (mode === "access-changed")
                state.url = "https://example.test/other";
              return true;
            },
          },
          storage: {
            local: {
              async setAccessLevel() {},
              async get() {
                return {
                  connection: {
                    base: "http://localhost:8000",
                    token: "synthetic-only",
                  },
                };
              },
              async set() {},
              async remove() {},
            },
          },
          tabs: {
            async query() {
              if (state.pendingUrl && ++state.polls > 2) {
                state.url = state.pendingUrl;
                state.pendingUrl = "";
              }
              return [
                {
                  id: 1,
                  url: mode === "hidden-url" ? undefined : state.url,
                  pendingUrl: state.pendingUrl,
                },
              ];
            },
            async update(_id: number, options: { url: string }) {
              state.navigations.push(options.url);
              if (mode === "delayed") {
                state.pendingUrl = options.url;
                return;
              }
              state.url =
                mode === "changed" ? "https://example.test/other" : options.url;
            },
            async sendMessage() {
              state.captures++;
              return {
                id: "12345678-1234-1234-1234-123456789abc",
                protocol_version: 2,
                page_url: state.url,
                title: "Synthetic posting",
                fields: [],
              };
            },
          },
          scripting: {
            async executeScript(options: { files?: string[] }) {
              if (mode === "denied")
                throw new Error("Cannot access contents of the page");
              if (options.files) state.injections++;
              return [{ result: true }];
            },
          },
        },
      });
      window.fetch = async () =>
        new Response(JSON.stringify({ default_version_id: null, items: [] }), {
          status: 200,
        });
    },
    { url, mode },
  );
  await page.addScriptTag({ content: read("contracts.js") });
  await page.addScriptTag({ type: "module", content: read("popup.js") });
  await expect(page.locator("#autofill")).toBeEnabled();
}

test("requests only the current site's access from a persistent panel, then continues capture", async ({
  page,
}) => {
  await install(page, `${posting}/application?source=test`, "access-needed");
  await page.locator("#autofill").click();
  await expect(page.locator("#autofill-status")).toContainText(
    "No application fields are ready",
  );
  expect(
    await page.evaluate(
      () => (window as unknown as { qaState: unknown }).qaState,
    ),
  ).toMatchObject({
    permissionRequests: [["https://jobs.ashbyhq.com/*"]],
    injections: 1,
    captures: 1,
  });
  await page.locator("#autofill").click();
  expect(
    await page.evaluate(
      () =>
        (window as unknown as { qaState: { permissionRequests: string[][] } })
          .qaState.permissionRequests,
    ),
  ).toHaveLength(1);
});

test("permission denial stops capture with a retry instruction", async ({
  page,
}) => {
  await install(page, `${posting}/application`, "access-denied");
  await page.locator("#autofill").click();
  await expect(page.locator("#autofill-status")).toContainText(
    "Allow access to jobs.ashbyhq.com",
  );
  expect(
    await page.evaluate(
      () => (window as unknown as { qaState: unknown }).qaState,
    ),
  ).toMatchObject({ injections: 0, captures: 0 });
});

test("does not capture another page when the active page changes during permission approval", async ({
  page,
}) => {
  await install(page, `${posting}/application`, "access-changed");
  await page.locator("#autofill").click();
  await expect(page.locator("#autofill-status")).toContainText(
    "active page changed",
  );
  expect(
    await page.evaluate(
      () => (window as unknown as { qaState: unknown }).qaState,
    ),
  ).toMatchObject({ injections: 0, captures: 0 });
});

test("distinguishes a hidden tab URL from an unsupported browser page", async ({
  page,
}) => {
  await install(page, `${posting}/application`, "hidden-url");
  await page.locator("#autofill").click();
  await expect(page.locator("#autofill-status")).toContainText(
    "Chrome has not shared this tab",
  );
  await install(page, "chrome://extensions/");
  await page.locator("#autofill").click();
  await expect(page.locator("#autofill-status")).toContainText(
    "Chrome settings and extension pages cannot be filled",
  );
});

test("declares tab metadata and optional site access without granting every website at install", () => {
  const manifest = JSON.parse(read("manifest.json"));
  expect(manifest.permissions).toContain("tabs");
  expect(manifest.optional_host_permissions).toEqual([
    "https://*/*",
    "http://*/*",
  ]);
  expect(manifest.host_permissions).toEqual([
    "http://localhost:8000/*",
    "http://127.0.0.1:8000/*",
  ]);
});

test("enters only the same Ashby posting's application and explains an empty form inline", async ({
  page,
}) => {
  await install(page, posting);
  await page.locator("#autofill").click();
  await expect(page.locator("#autofill-status")).toContainText(
    "Open the Application tab",
  );
  const state = await page.evaluate(
    () => (window as unknown as { qaState: unknown }).qaState,
  );
  expect(state).toMatchObject({
    url: `${posting}/application`,
    navigations: [`${posting}/application`],
    injections: 1,
    captures: 1,
  });
  await expect(page.locator("#autofill-status")).not.toContainText(
    "see the message below",
  );
});

test("does not navigate an application step or an unrelated site", async ({
  page,
}) => {
  for (const url of [`${posting}/application`, "https://example.test/job"]) {
    await install(page, url);
    await page.locator("#autofill").click();
    await expect(page.locator("#autofill-status")).toContainText(
      /Open the Application tab|No supported application controls/,
    );
    expect(
      await page.evaluate(
        () =>
          (window as unknown as { qaState: { navigations: string[] } }).qaState
            .navigations,
      ),
    ).toEqual([]);
  }
});

test("waits for the application navigation to commit and preserves its query", async ({
  page,
}) => {
  await install(page, `${posting}/?utm_source=synthetic`, "delayed");
  await page.locator("#autofill").click();
  await expect(page.locator("#autofill-status")).toContainText(
    "No application fields are ready",
  );
  expect(
    await page.evaluate(
      () => (window as unknown as { qaState: unknown }).qaState,
    ),
  ).toMatchObject({
    url: `${posting}/application?utm_source=synthetic`,
    captures: 1,
    injections: 1,
    polls: 3,
  });
});

test("stops if the active page changes while opening the application", async ({
  page,
}) => {
  await install(page, posting, "changed");
  await page.locator("#autofill").click();
  await expect(page.locator("#autofill-status")).toContainText(
    "The active page changed",
  );
  expect(
    await page.evaluate(
      () =>
        (window as unknown as { qaState: { captures: number } }).qaState
          .captures,
    ),
  ).toBe(0);
});

test("shows the actionable capture failure beside Autofill", async ({
  page,
}) => {
  await install(page, `${posting}/application`, "denied");
  await page.locator("#autofill").click();
  await expect(page.locator("#autofill-status")).toContainText(
    "extension icon",
  );
  await expect(page.locator("#autofill-status")).toHaveText(
    await page.locator("#message").innerText(),
  );
});
