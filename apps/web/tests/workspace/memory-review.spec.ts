import { expect, test } from "@playwright/test";

test("an agent memory proposal preserves prior context until exact approval", async ({
  page,
}) => {
  await page.goto("/memory");

  await expect(
    page.getByRole("heading", { name: "Workspace memory" }),
  ).toBeVisible();
  await expect(
    page.getByText("1 memory proposal needs your review."),
  ).toBeVisible();
  await expect(
    page.getByText("Use concise synthetic summaries with one clear next step."),
  ).toBeVisible();
  await expect(
    page.getByText("This preference recurred during the synthetic task."),
  ).toBeVisible();
  await expect(
    page.getByText("Use short synthetic status updates."),
  ).toBeVisible();

  await page.getByRole("button", { name: "Approve exact wording" }).click();

  await expect(page.getByText("Needs review")).toHaveCount(0);
  await expect(page.getByText("approved", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Revoke from future retrieval" }),
  ).toBeVisible();

  const review = await page.evaluate(() =>
    fetch("/api/backend/test/latest-memory-review").then((response) =>
      response.json(),
    ),
  );
  expect(review).toMatchObject({
    revision_id: "memory-revision-proposed",
    decision: "approved",
    expected_version: 2,
  });
});
