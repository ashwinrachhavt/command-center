import { expect, test, type Page } from "@playwright/test";

async function savedState(page: Page) {
  return page.evaluate(async () =>
    (await fetch("/api/backend/test/library")).json(),
  );
}

test("a new note opens ready to keep writing, with no extra setup", async ({
  page,
}) => {
  await page.goto("/notes");
  await page.getByRole("button", { name: "New note", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog
    .getByRole("textbox", { name: /^Title/ })
    .fill("Questions for my next interview");
  await dialog
    .getByRole("textbox", { name: "Content", exact: true })
    .fill("How does the team make decisions?");
  await dialog
    .getByRole("button", { name: "Create note", exact: true })
    .click();
  await expect(dialog).toHaveCount(0);
  await expect(
    page.getByRole("textbox", { name: "Note content", exact: true }),
  ).toContainText("make decisions");
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Questions for my next interview" }),
  ).toBeVisible();
});

test("renaming a note preserves its working copy and next checkpoint", async ({
  page,
}) => {
  await page.goto("/notes?note=note-library-interview");
  const writer = page.getByRole("textbox", {
    name: "Note content",
    exact: true,
  });
  await writer.fill("My working thought survives renaming.");
  await page.getByRole("button", { name: "Edit details", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog
    .getByRole("textbox", { name: /^Title/ })
    .fill("The next conversation");
  await dialog.getByRole("button", { name: "Save changes" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(writer).toContainText("survives renaming");
  await page
    .getByRole("button", { name: "Save checkpoint", exact: true })
    .click();
  await expect(page.getByText(/Current base: version 2/)).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("typing during a slow checkpoint remains in the live draft", async ({
  page,
}) => {
  await page.goto("/notes?note=note-library-interview");
  const writer = page.getByRole("textbox", {
    name: "Note content",
    exact: true,
  });
  await writer.fill("The checkpoint text.");
  await expect(page.getByTestId("draft-status")).toContainText("Draft saved");
  await page.evaluate(() => {
    const original = window.fetch;
    const control = window as unknown as { releaseCheckpoint?: () => void };
    window.fetch = async (...args) => {
      const result = await original(...args);
      if (String(args[0]).endsWith("/versions") && args[1]?.method === "POST")
        await new Promise<void>((resolve) => {
          control.releaseCheckpoint = resolve;
        });
      return result;
    };
  });
  await page
    .getByRole("button", { name: "Save checkpoint", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Saving version…" }),
  ).toBeVisible();
  await writer.fill("A newer thought while that checkpoint is saving.");
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          typeof (window as unknown as { releaseCheckpoint?: () => void })
            .releaseCheckpoint,
      ),
    )
    .toBe("function");
  await page.evaluate(() =>
    (
      window as unknown as { releaseCheckpoint: () => void }
    ).releaseCheckpoint(),
  );
  await expect(page.getByText(/Current base: version 2/)).toBeVisible();
  await expect(writer).toContainText("A newer thought");
  await expect(page.getByTestId("draft-status")).toContainText("Draft saved");
  expect(
    (await savedState(page)).versions["note-library-interview"][0].payload.text,
  ).toContain("The checkpoint text");
  await page.reload();
  await expect(writer).toContainText("A newer thought");
});

test("notes preserve working writing across navigation and reload, then save explicit checkpoints", async ({
  page,
}) => {
  await page.goto("/notes");
  await page
    .getByRole("button", { name: /Northstar · interview notes/ })
    .click();
  const writer = page.getByRole("textbox", {
    name: "Note content",
    exact: true,
  });
  await expect(writer).toContainText("developer ownership");
  await writer.fill("A new thought that should survive leaving this note.");
  await expect(page.getByTestId("draft-status")).toContainText("Draft saved");
  expect(
    (await savedState(page)).versions["note-library-interview"],
  ).toHaveLength(1);
  await page.getByRole("button", { name: /Ideas worth returning to/ }).click();
  await expect(writer).toContainText("half-formed");
  await page
    .getByRole("button", { name: /Northstar · interview notes/ })
    .click();
  await expect(writer).toContainText("should survive");
  await page.reload();
  await expect(writer).toContainText("should survive");
  await page
    .getByRole("button", { name: "Save checkpoint", exact: true })
    .click();
  await expect(page.getByText(/Current base: version 2/)).toBeVisible();
  await expect(writer).toContainText("should survive");
  await writer.fill("Continue writing after the checkpoint.");
  await expect(page.getByTestId("draft-status")).toContainText("Draft saved");
  await page.reload();
  await expect(writer).toContainText("Continue writing");
  await page
    .getByRole("button", { name: "Save checkpoint", exact: true })
    .click();
  await expect(page.getByText(/Current base: version 3/)).toBeVisible();
  const state = await savedState(page);
  expect(state.versions["note-library-interview"]).toHaveLength(3);
  expect(state.versions["note-library-interview"][1].payload.text).toContain(
    "should survive",
  );
});

test("a note becomes a linked task and the task opens its source in context", async ({
  page,
}) => {
  await page.goto("/notes?note=note-library-interview");
  await page.getByRole("button", { name: "Create task", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog
    .getByRole("textbox", { name: /^Title/ })
    .fill("Ask about developer ownership");
  await dialog
    .getByRole("button", { name: "Create task", exact: true })
    .click();
  await expect(dialog).toHaveCount(0);
  await page
    .getByRole("button", { name: /Ask about developer ownership Open/ })
    .click();
  await expect(
    page.getByRole("region", { name: "Linked documents" }),
  ).toBeVisible();
  await page
    .getByRole("region", { name: "Linked documents" })
    .getByRole("button", { name: /Northstar/ })
    .click();
  await expect(
    page.getByRole("tab", { name: "Content & versions" }),
  ).toHaveAttribute("data-state", "active");
  expect((await savedState(page)).tasks).toHaveLength(1);
  expect(new URL(page.url()).searchParams.get("note")).toBe(
    "note-library-interview",
  );
});

test("library searches saved content, filters document types, and keeps original documents accessible", async ({
  page,
}) => {
  await page.goto("/library");
  await page
    .getByRole("textbox", { name: "Search library" })
    .fill("developer ownership");
  await expect(
    page.getByRole("button", { name: /Northstar · interview notes/ }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: /Ideas worth returning to/ }),
  ).toHaveCount(0);
  await page.getByRole("textbox", { name: "Search library" }).fill("");
  await page.getByRole("combobox", { name: "Document type filter" }).click();
  await page.getByRole("option", { name: "Resume", exact: true }).click();
  await expect(
    page.getByRole("button", { name: /Synthetic resume/ }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: /Northstar · interview notes/ }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: /Synthetic resume/ }).click();
  await expect(
    page.getByText("Your original file is stored intact.", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Open extracted text", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Extracted text preview" }),
  ).toContainText("Product engineer with accessible systems experience.");
});

test("notes fit a narrow screen and return keyboard focus to the list", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/notes");
  await page
    .getByRole("button", { name: /Northstar · interview notes/ })
    .click();
  await expect(
    page.getByRole("heading", { name: "Northstar · interview notes" }),
  ).toBeFocused();
  await expect(
    page.getByRole("textbox", { name: "Note content" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("button", { name: "All notes", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "ALL NOTES", exact: true }),
  ).toBeFocused();
  await expect(page.getByRole("textbox", { name: "Note content" })).toHaveCount(
    0,
  );
});
