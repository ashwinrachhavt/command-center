import { expect, test } from "@playwright/test";

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
