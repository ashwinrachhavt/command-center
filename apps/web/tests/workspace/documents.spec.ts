import { expect, test } from "@playwright/test";

test("long version history loads summaries first and only reads the chosen bodies", async ({
  page,
}) => {
  await page.goto("/artifacts?record=artifact-1&long-history=1");
  await page.getByRole("tab", { name: "Content & versions" }).click();
  await expect(
    page.getByText("History checkpoint 30", { exact: true }),
  ).toBeVisible();
  const reads = () =>
    page.evaluate(
      async () =>
        (await fetch("/api/backend/test/version-reads")).json() as Promise<
          string[]
        >,
    );
  expect((await reads()).filter((path) => path.includes("/versions/"))).toEqual(
    ["artifacts/artifact-1/versions/long-version-30"],
  );
  await page.getByRole("button", { name: "Load older", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Load older", exact: true }),
  ).toHaveCount(0);
  expect(
    (await reads()).filter((path) => path.includes("/versions/")),
  ).toHaveLength(1);
  await page.getByLabel("Artifact version").click();
  await page.getByRole("option", { name: /^Version 1 ·/ }).click();
  await expect(
    page.getByText("History checkpoint 1", { exact: true }),
  ).toBeVisible();
  expect((await reads()).filter((path) => path.includes("/versions/"))).toEqual(
    [
      "artifacts/artifact-1/versions/long-version-30",
      "artifacts/artifact-1/versions/long-version-1",
    ],
  );
});

test("all imported career proposals remain reachable beyond the first hundred facts", async ({
  page,
}) => {
  await page.goto("/settings?many-facts=1");
  await expect(page.getByText("Showing 20 of 105 facts")).toBeVisible();
  for (let loaded = 40; loaded <= 100; loaded += 20) {
    await page.getByRole("button", { name: "Load more facts" }).click();
    await expect(
      page.getByText(`Showing ${loaded} of 105 facts`),
    ).toBeVisible();
  }
  await page.getByRole("button", { name: "Load more facts" }).click();
  await expect(
    page.getByText("Synthetic imported skill 105", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Showing 105 of 105 facts")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Load more facts" }),
  ).toHaveCount(0);
});

test("document intake uploads originals and retries conversion with one request key", async ({
  page,
}) => {
  await page.goto("/artifacts");
  await expect(
    page.getByRole("heading", { name: "Document intake" }),
  ).toBeVisible();
  const failed = page
    .locator("div")
    .filter({ hasText: "interview-brief.docx" })
    .filter({ has: page.getByRole("button", { name: "Retry" }) })
    .first();
  await failed.getByRole("button", { name: "Retry" }).click();
  await expect(
    page
      .getByText("interview-brief.docx", { exact: true })
      .locator("..")
      .getByText("Queued", { exact: true }),
  ).toBeVisible();
  const keys = await page.evaluate(async () =>
    fetch("/api/backend/test/document-request-keys").then((response) =>
      response.json(),
    ),
  );
  expect(keys.retry).toHaveLength(2);
  expect(new Set(keys.retry).size).toBe(1);

  await page.getByRole("button", { name: "Upload document" }).click();
  await page.getByLabel("Document", { exact: true }).setInputFiles({
    name: "candidate-notes.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("Synthetic candidate notes."),
  });
  await page.getByLabel("Document type").click();
  await page.getByRole("option", { name: "Resume" }).click();
  await page.getByRole("button", { name: "Upload original" }).click();
  await expect(page).toHaveURL(/inspect=artifacts%3Aartifact-upload-/);
  expect(
    (
      await page.evaluate(async () =>
        fetch("/api/backend/test/document-request-keys").then((response) =>
          response.json(),
        ),
      )
    ).upload,
  ).toHaveLength(1);
});

test("new original versions do not change the exact default resume", async ({
  page,
}) => {
  await page.goto("/settings");
  await expect(page.getByText(/Current: synthetic-resume\.pdf/)).toContainText(
    "resume-version-1",
  );
  await page.goto("/artifacts?record=artifact-resume");
  await page.getByRole("tab", { name: "Content & versions" }).click();
  await page.getByRole("button", { name: "Upload original" }).click();
  await page.getByLabel("Document", { exact: true }).setInputFiles({
    name: "synthetic-resume-v2.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF synthetic version two"),
  });
  await page.getByRole("button", { name: "Upload original" }).click();
  await page.goto("/settings");
  await expect(page.getByText(/Current: synthetic-resume\.pdf/)).toContainText(
    "resume-version-1",
  );
});

test("completed extraction opens its canonical task conversation with the exact version", async ({
  page,
}) => {
  await page.goto("/artifacts");
  const completed = page
    .locator("div")
    .filter({ hasText: "synthetic-resume.pdf" })
    .filter({
      has: page.getByRole("button", { name: "Suggest profile facts" }),
    })
    .first();
  await completed
    .getByRole("button", { name: "Suggest profile facts" })
    .click();
  await expect(page).toHaveURL(
    /\/tasks\?record=task-document-review&tab=conversation/,
  );
  await expect(page.getByText(/resume-extraction-version-1/)).toBeVisible();
  await expect(page.getByText(/Do not approve any facts/)).toBeVisible();
  await expect(page.getByText(/You → Application/)).toBeVisible();
});

test("fact review keeps approved and pending revisions distinct and rejects stale review", async ({
  page,
}) => {
  await page.goto("/settings");
  await expect(
    page.getByText("Product engineer", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Staff product engineer", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Pending proposal", { exact: true }),
  ).toBeVisible();

  await page.getByLabel("Review note (optional)").fill("Checked the source.");
  await page.getByRole("button", { name: "Approve exact revision" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Fact changed after this review was opened",
  );
  await expect(page.getByLabel("Review note (optional)")).toHaveValue(
    "Checked the source.",
  );
  await page.getByRole("button", { name: "Approve exact revision" }).click();
  await expect(page.getByText("Pending proposal", { exact: true })).toHaveCount(
    0,
  );
  await expect(
    page
      .getByLabel("Active approved Headline")
      .getByText("Staff product engineer"),
  ).toBeVisible();
});

test("fact evidence opens the pinned extraction version", async ({ page }) => {
  await page.goto("/settings");
  await page.getByRole("button", { name: "Open pinned source" }).last().click();
  await expect(page).toHaveURL(
    /inspect=artifacts%3Aartifact-resume-extracted%3Acontent%3Aresume-extraction-version-1/,
  );
  await expect(
    page
      .getByRole("tabpanel", { name: "Content & versions" })
      .getByText("Product engineer with accessible systems experience."),
  ).toBeVisible();
});

test("exports the selected immutable editable version and downloads its PDF derivative", async ({
  page,
}) => {
  await page.goto("/artifacts?record=artifact-1");
  await page.getByRole("tab", { name: "Content & versions" }).click();
  await page.getByLabel("Artifact version").click();
  await page.getByRole("option", { name: /Version 2/ }).click();
  await page.getByRole("button", { name: "Export version 2 to PDF" }).click();

  await expect(page.getByText("PDF from version 2")).toBeVisible();
  const downloadButton = page.getByRole("button", { name: "Download PDF" });
  await expect(downloadButton).toBeVisible();
  const download = page.waitForEvent("download");
  await downloadButton.click();
  await expect((await download).suggestedFilename()).toBe(
    "synthetic-document.pdf",
  );
});

test("human edits pin their base version and retain its reviewed metadata", async ({
  page,
}) => {
  await page.goto("/artifacts?record=artifact-1");
  await page.getByRole("tab", { name: "Content & versions" }).click();
  await page.getByLabel("Artifact version").click();
  await page.getByRole("option", { name: /Version 2/ }).click();
  await page.getByRole("button", { name: "New version" }).click();
  await expect(page.getByLabel("Artifact version")).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "New version" }),
  ).toBeDisabled();
  await page
    .getByRole("textbox", { name: "New version content", exact: true })
    .fill("Human-reviewed edit.");
  await page.getByRole("button", { name: "Save version" }).click();
  await expect(page.getByText("Human-reviewed edit.")).toBeVisible();
});

test("an original file stays available and opens its extracted text without a blank edit", async ({
  page,
}) => {
  await page.goto("/artifacts?record=artifact-resume");
  await page.getByRole("tab", { name: "Content & versions" }).click();
  await expect(page.getByText("This version is empty.")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "New version" }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: /Download original/ }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Open extracted text" }).click();
  await expect(page).toHaveURL(/inspect=artifacts/);
  await expect(
    page.getByText("Product engineer with accessible systems experience.", {
      exact: true,
    }),
  ).toBeVisible();
});

test("document drafts recover through refresh with their original editing base", async ({
  page,
}) => {
  await page.goto("/artifacts?record=artifact-1");
  await page.getByRole("tab", { name: "Content & versions" }).click();
  await page.getByLabel("Artifact version").click();
  await page.getByRole("option", { name: /^Version 2/ }).click();
  await page.getByRole("button", { name: "New version", exact: true }).click();
  const writer = page.getByRole("textbox", {
    name: "New version content",
    exact: true,
  });
  await writer.fill("A working note that should survive refresh.");
  await expect(page.getByTestId("draft-status")).toContainText("Draft saved");
  const before = await page.evaluate(async () =>
    (await fetch("/api/backend/artifacts/artifact-1/version-history")).json(),
  );
  expect(before.total).toBe(2);
  await page.reload();
  await page.getByRole("tab", { name: "Content & versions" }).click();
  await page.getByRole("button", { name: "New version", exact: true }).click();
  await expect(writer).toContainText(
    "A working note that should survive refresh.",
  );
  await expect(page.getByText(/Editing from version 2\./)).toBeVisible();
  await page.getByRole("button", { name: "Save version", exact: true }).click();
  await expect(writer).toHaveCount(0);
  await expect(
    page.getByText("A working note that should survive refresh.", {
      exact: true,
    }),
  ).toBeVisible();
  const after = await page.evaluate(async () =>
    (await fetch("/api/backend/artifacts/artifact-1/version-history")).json(),
  );
  expect(after.total).toBe(3);
});
