import { expect, test } from "@playwright/test";

test("document generation recovers its original request after reload, then edits and exports the saved draft", async ({
  page,
}) => {
  await page.goto("/applications?application=task-tracker-1");
  await page.evaluate(async () => {
    await fetch("/api/backend/applications/task-tracker-1/job-context", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": "synthetic-requirements",
      },
      body: JSON.stringify({
        expected_version: 1,
        job_title: "Product Engineer",
        company_name: "Northstar",
        text: "Build accessible collaboration tools.",
      }),
    });
  });
  await page.reload();
  const materials = page.getByRole("region", {
    name: "Application documents",
    exact: true,
  });
  await materials.getByText("Writing preferences", { exact: true }).click();
  const preferences = materials.getByRole("textbox", {
    name: "Application writing preferences",
    exact: true,
  });
  await expect(preferences).toHaveAttribute("contenteditable", "true");
  await preferences.fill("Emphasize accessible product work.");
  await expect(materials.getByTestId("draft-status")).toContainText(
    "Draft saved",
  );
  await page.evaluate(() =>
    fetch("/api/backend/test/application-material-lost-reply"),
  );
  await materials
    .getByRole("button", { name: "Draft cover letter", exact: true })
    .click();
  await expect(materials.getByRole("alert")).toBeVisible();
  await page.reload();
  await materials
    .getByRole("button", { name: "Recover cover letter request", exact: true })
    .click();
  await expect(
    materials.getByText("Queued for your agent", { exact: true }),
  ).toBeVisible();
  const state = await page.evaluate(async () =>
    (await fetch("/api/backend/test/application-tracker")).json(),
  );
  expect(state.materials["task-tracker-1"]).toHaveLength(1);
  expect(state.materialRequests).toHaveLength(3);
  expect(state.materialRequests[1]).toEqual(state.materialRequests[0]);
  expect(state.materialRequests[2]).toEqual(state.materialRequests[0]);
  expect(state.materialRequests[0].body).toMatchObject({
    kind: "cover-letter",
    resume_version_id: "resume-version-1",
    instructions: "Emphasize accessible product work.",
  });
  await page.evaluate(() =>
    fetch("/api/backend/test/application-material-complete"),
  );
  await materials
    .getByRole("button", { name: "Open draft & export", exact: true })
    .click();
  const panel = page.getByRole("complementary", { name: "Related workspace", exact: true });
  await expect(
    panel.getByText("I build accessible collaboration tools.", { exact: true }),
  ).toBeVisible();
  await panel.getByRole("button", { name: "New version", exact: true }).click();
  const writer = panel.getByRole("textbox", {
    name: "New version content",
    exact: true,
  });
  await expect(writer).toHaveAttribute("contenteditable", "true");
  await writer.fill("Dear Northstar team,\n\nMy revised application letter.");
  await expect(panel.getByTestId("draft-status")).toContainText("Draft saved");
  await panel
    .getByRole("button", { name: "Save version", exact: true })
    .click();
  await expect(
    panel.getByText("My revised application letter.", { exact: true }),
  ).toBeVisible();
  await panel
    .getByRole("button", { name: "Export version 2 to PDF", exact: true })
    .click();
  await expect(
    panel.getByRole("button", { name: "Download PDF", exact: true }),
  ).toBeVisible();
});

test("generation waits for saved requirements and fits a narrow application page", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/applications?application=task-tracker-1");
  const materials = page.getByRole("region", {
    name: "Application documents",
    exact: true,
  });
  await expect(
    materials.getByRole("button", { name: "Draft cover letter", exact: true }),
  ).toBeDisabled();
  await expect(
    materials.getByRole("button", { name: "Tailor résumé", exact: true }),
  ).toBeDisabled();
  await expect(
    materials.getByText(
      "Save a job-description checkpoint above before generating.",
      { exact: true },
    ),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
