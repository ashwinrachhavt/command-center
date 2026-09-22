import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";

const script = readFileSync(
  path.resolve(__dirname, "../../extension/content.js"),
  "utf8",
);
import type { components } from "../src/lib/api-types";
type Snapshot = components["schemas"]["SnapshotCreate"];
const contracts = readFileSync(
  path.resolve(__dirname, "../../extension/contracts.js"),
  "utf8",
);

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

test.beforeEach(async ({ page }) => {
  await page.goto("/fixtures/application.html");
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
  await page.addScriptTag({ content: script });
});

test("shares field descriptions, fills once, and never submits", async ({
  page,
}) => {
  await page.locator("#name").fill("Existing private value");
  const snapshot = await message<Snapshot>(page, {
    version: 1,
    action: "inspect",
  });
  expect(snapshot.fields).toHaveLength(4);
  expect(JSON.stringify(snapshot)).not.toContain("Existing private value");
  expect(JSON.stringify(snapshot)).not.toContain("synthetic-secret");
  const command = {
    snapshot_id: snapshot.id,
    page_url: snapshot.page_url,
    fields: {
      f0: "Synthetic Person",
      f1: "synthetic@example.com",
      f2: "Staff Engineer",
    },
  };
  expect(
    await message(page, { version: 1, action: "apply", command }),
  ).toMatchObject({
    state: "applied",
  });
  await expect(page.locator("#name")).toHaveValue("Synthetic Person");
  await expect(page.locator("#role")).toHaveValue("Staff Engineer");
  await expect(page.locator("#outcome")).toHaveText("Not submitted");
  expect(
    await message(page, { version: 1, action: "apply", command }),
  ).toMatchObject({
    state: "rejected",
  });
});

test("rejects a changed field before applying any values", async ({ page }) => {
  const snapshot = await message<Snapshot>(page, {
    version: 1,
    action: "inspect",
  });
  await page.locator("label[for=email]").evaluate((element) => {
    element.textContent = "Bank account";
  });
  const result = await message(page, {
    version: 1,
    action: "apply",
    command: {
      snapshot_id: snapshot.id,
      page_url: snapshot.page_url,
      fields: { f0: "Never written", f1: "Never written" },
    },
  });
  expect(result).toMatchObject({ state: "rejected" });
  await expect(page.locator("#name")).toHaveValue("");
});

test("rejects navigation within the same page", async ({ page }) => {
  const snapshot = await message<Snapshot>(page, {
    version: 1,
    action: "inspect",
  });
  await page.evaluate(() =>
    history.pushState({}, "", "?different-application=1"),
  );
  expect(
    await message(page, {
      version: 1,
      action: "apply",
      command: {
        snapshot_id: snapshot.id,
        page_url: snapshot.page_url,
        fields: { f0: "Never written" },
      },
    }),
  ).toMatchObject({ state: "rejected" });
  await expect(page.locator("#name")).toHaveValue("");
});

test("rejects malformed and incompatible messages before touching the form", async ({
  page,
}) => {
  const snapshot = await message<Snapshot>(page, {
    version: 1,
    action: "inspect",
  });
  for (const payload of [
    null,
    {},
    { version: 2, action: "inspect" },
    { version: 1, action: "apply" },
    {
      version: 1,
      action: "apply",
      command: {
        snapshot_id: snapshot.id,
        page_url: snapshot.page_url,
        fields: { f0: 123 },
      },
    },
    {
      version: 1,
      action: "apply",
      command: {
        snapshot_id: snapshot.id,
        page_url: snapshot.page_url,
        fields: { f0: "x".repeat(5001) },
      },
    },
  ]) {
    expect(await message(page, payload)).toMatchObject({ state: "rejected" });
    await expect(page.locator("#name")).toHaveValue("");
  }
});
