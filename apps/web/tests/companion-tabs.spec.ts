import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";

const read = (name: string) =>
  readFileSync(path.resolve(__dirname, `../../extension/${name}`), "utf8");

test("ten panels retain independent drafts and serialize expensive capture work", async ({
  context,
}) => {
  const storage: Record<string, unknown> = {
    connection: { base: "http://localhost:8000", token: "synthetic-only" },
  };
  let captures = 0;
  let inFlight = 0;
  let peak = 0;
  const pages = await Promise.all(
    Array.from({ length: 10 }, async (_, index) => {
      const id = index + 1;
      const url = `https://jobs.example.test/apply/${id}`;
      storage[`applicationDraft:${id}`] = {
        snapshot: {
          id: `snapshot-${id}`,
          page_url: url,
          title: `Application ${id}`,
          fields: [
            {
              id: "f0",
              label: "Answer",
              type: "textarea",
              required: false,
              options: [],
              option_labels: {},
              value_state: "empty",
            },
          ],
        },
        pageUrl: url,
        values: { f0: `Draft ${id}` },
        touched: {},
        receipts: {},
        replaceFields: [],
        uploadFields: [],
        preparation: {
          id: `preparation-${id}`,
          task_id: `task-${id}`,
          fields: [
            {
              field_id: "f0",
              status: "needs_input",
              value: null,
              evidence: [],
            },
          ],
        },
      };
      const page = await context.newPage();
      await page.exposeFunction(
        "readStore",
        (keys: string[] | string | null) =>
          keys === null
            ? storage
            : Object.fromEntries(
                (typeof keys === "string" ? [keys] : keys)
                  .filter((k) => k in storage)
                  .map((k) => [k, storage[k]]),
              ),
      );
      await page.exposeFunction(
        "writeStore",
        (values: Record<string, unknown>) => {
          Object.assign(storage, values);
        },
      );
      await page.exposeFunction("removeStore", (keys: string[] | string) => {
        for (const key of typeof keys === "string" ? [keys] : keys)
          delete storage[key];
      });
      await page.exposeFunction("capture", async () => {
        inFlight++;
        peak = Math.max(peak, inFlight);
        await new Promise((resolve) => setTimeout(resolve, 30));
        inFlight--;
        captures++;
      });
      await page.goto("/health");
      await page.setContent(
        read("popup.html").replace(/<script[\s\S]*?<\/script>/g, ""),
      );
      await page.evaluate(
        ({ id, url }) => {
          const bridge = window as unknown as {
            readStore: (keys: unknown) => Promise<unknown>;
            writeStore: (values: unknown) => Promise<void>;
            removeStore: (keys: unknown) => Promise<void>;
            capture: () => Promise<void>;
          };
          Object.assign(window, {
            CommandCenterContracts: new Proxy({}, { get: () => () => true }),
            chrome: {
              storage: {
                local: {
                  setAccessLevel: async () => {},
                  get: bridge.readStore,
                  set: bridge.writeStore,
                  remove: bridge.removeStore,
                },
              },
              permissions: { contains: async () => true },
              tabs: {
                query: async () => [{ id, windowId: id, url }],
                sendMessage: async () => ({ fields: [], page_url: url }),
              },
              scripting: { executeScript: bridge.capture },
            },
          });
          window.fetch = async (input) =>
            new Response(
              JSON.stringify(
                String(input).endsWith("/generation")
                  ? {
                      state: "idle",
                      run_id: null,
                      conversation_id: null,
                      error_code: null,
                    }
                  : { items: [], default_version_id: null },
              ),
              { status: 200 },
            );
        },
        { id, url },
      );
      await page.addScriptTag({ type: "module", content: read("popup.js") });
      await expect(page.getByLabel("Answer", { exact: true })).toHaveValue(
        `Draft ${id}`,
      );
      return page;
    }),
  );
  await Promise.all(
    pages.map((page, index) =>
      page.getByLabel("Answer", { exact: true }).fill(`Edited ${index + 1}`),
    ),
  );
  await expect
    .poll(
      () =>
        Object.entries(storage).filter(
          ([key, value]) =>
            key.startsWith("applicationDraft:") &&
            (value as { values: { f0: string } }).values.f0.startsWith(
              "Edited ",
            ),
        ).length,
    )
    .toBe(10);
  for (let index = 0; index < 10; index++)
    expect(
      (storage[`applicationDraft:${index + 1}`] as { values: { f0: string } })
        .values.f0,
    ).toBe(`Edited ${index + 1}`);
  await Promise.all(pages.map((page) => page.locator("#autofill").click()));
  await expect.poll(() => captures).toBe(10);
  expect(peak).toBe(1);
  expect(storage.applicationDraft).toBeUndefined();
  await pages[0].locator("#discard-draft").click();
  await expect.poll(() => storage["applicationDraft:1"]).toBeUndefined();
  expect(storage["applicationDraft:2"]).toBeDefined();
});
