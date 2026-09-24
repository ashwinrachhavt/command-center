import { expect, test } from "@playwright/test";

test("reviews a document type and configured title separately while preserving the original filename", async ({
  page,
}) => {
  await page.goto("/settings");
  await page
    .getByRole("combobox", { name: "Renaming", exact: true })
    .selectOption("task");
  await page.getByRole("button", { name: "Save document settings" }).click();
  await expect(page.getByText("Document settings saved.")).toBeVisible();
  await page.goto("/artifacts?record=artifact-resume");
  await page.getByRole("tab", { name: "Content & versions" }).click();
  const panel = page.getByRole("region", {
    name: "Document classification",
    exact: true,
  });
  await expect(
    panel.getByRole("button", { name: "Classify with Jev" }),
  ).toBeDisabled();
  await panel.getByRole("checkbox", { name: /Send this document/ }).check();
  await panel.getByRole("button", { name: "Classify with Jev" }).click();
  await expect(panel.getByText("simulation result")).toBeVisible();
  await expect(panel.getByText("94.0%")).toBeVisible();
  await expect(
    panel.getByText("Application policy", { exact: true }),
  ).toBeVisible();
  await expect(panel.getByRole("button", { name: "Apply name" })).toHaveCount(
    0,
  );
  await panel.getByRole("button", { name: "Review type" }).click();
  await panel
    .getByLabel("Reason for this review")
    .fill("Reviewed the synthetic experience and education sections.");
  await panel.getByRole("button", { name: "Confirm type" }).click();
  await expect(
    panel.getByRole("region", { name: "Rename document preview" }),
  ).toBeVisible();
  await panel.getByRole("button", { name: "Apply name" }).click();
  await expect(
    page.getByText("Vault title updated. Original filename preserved."),
  ).toBeVisible();
  const saved = await page.evaluate(async () =>
    (await fetch("/api/backend/test/document-decisions")).json(),
  );
  expect(saved.filenames).toContain("synthetic-resume.pdf");
  expect(saved.renames["artifact-resume"].state).toBe("applied");
});

test("mobile document review stays readable and the inspect pane shows exact questions", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/artifacts?record=artifact-resume");
  await page.getByRole("tab", { name: "Content & versions" }).click();
  const panel = page.getByRole("region", {
    name: "Document classification",
    exact: true,
  });
  await panel.getByRole("checkbox", { name: /Send this document/ }).check();
  await panel.getByRole("button", { name: "Classify with Jev" }).click();
  await panel.getByText("Inspect this decision", { exact: true }).click();
  await expect(
    panel.getByText("Exact typed questions", { exact: true }),
  ).toBeVisible();
  await expect(
    panel.getByText(/Which catalog purpose is supported/),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
  await page.screenshot({
    path: "/tmp/command-center-document-review-mobile.png",
    fullPage: true,
  });
});

test("one assessment displays research, claim, output and action checks with their explicit context", async ({
  page,
}) => {
  await page.goto("/artifacts?record=artifact-resume");
  await page.getByRole("tab", { name: "Content & versions" }).click();
  const panel = page.getByRole("region", {
    name: "Document classification",
    exact: true,
  });
  await panel
    .getByText("Add research or agent checks", { exact: true })
    .click();
  await panel
    .getByRole("textbox", { name: "Research question", exact: true })
    .fill("What is the evidence of accessible systems work?");
  await panel
    .getByRole("textbox", { name: "Claim to check", exact: true })
    .fill("This source describes accessible systems.");
  await panel
    .getByRole("textbox", { name: "Original agent request", exact: true })
    .fill("Summarize the saved source.");
  await panel
    .getByRole("textbox", { name: "Policy to check", exact: true })
    .fill("Every claim must be supported by this source.");
  await panel
    .getByRole("textbox", { name: "Proposed action", exact: true })
    .fill("Save an internal summary for review.");
  await panel.getByRole("checkbox", { name: /Send this document/ }).check();
  await panel.getByRole("button", { name: "Classify with Jev" }).click();
  await expect(
    panel.getByText("Research and agent checks", { exact: true }),
  ).toBeVisible();
  await expect(
    panel.getByText("Score: 1.70 / 2", { exact: true }),
  ).toBeVisible();
  await expect(
    panel.getByText("Score: 1.40 / 2", { exact: true }),
  ).toBeVisible();
  await expect(panel.getByText("85.0%", { exact: true })).toBeVisible();
  await expect(
    panel.getByText(/A semantic match never authorizes a tool call/),
  ).toBeVisible();
  const saved = await page.evaluate(async () =>
    (await fetch("/api/backend/test/document-decisions")).json(),
  );
  expect(
    saved.decisions["artifact-resume"].input_manifest.analysis_context
      .proposed_action,
  ).toBe("Save an internal summary for review.");
  expect(Object.keys(saved.decisions["artifact-resume"].answers)).toHaveLength(
    13,
  );
});
