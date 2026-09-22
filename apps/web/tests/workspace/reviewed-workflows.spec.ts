import { expect, test } from "@playwright/test";

test("only an explicitly reviewed exact action revision is queued", async ({
  page,
}) => {
  await page.goto("/actions");
  await page
    .getByRole("button", { name: /Synthetic Northstar introduction/ })
    .click();
  await expect(
    page.getByText("recruiter@example.com", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("alex@example.com", { exact: false }).first(),
  ).toBeVisible();
  const approve = page.getByRole("button", { name: "Approve & queue" });
  await expect(approve).toBeDisabled();
  await page
    .getByRole("textbox", { name: "Review reason" })
    .fill("Reviewed the synthetic recipient and exact text.");
  await expect(approve).toBeDisabled();
  await page.getByRole("checkbox", { name: /I reviewed this account/ }).check();
  await approve.click();
  await expect(
    page.getByRole("button", { name: "Revoke approval" }),
  ).toBeVisible();
  const requests = await page.evaluate(async () =>
    (await fetch("/api/backend/test/workflow-requests")).json(),
  );
  expect(requests).toHaveLength(1);
  expect(requests[0].body).toMatchObject({
    expected_version: 1,
    revision_id: "44444444-4444-4444-8444-444444444444",
    decision: "approved",
  });
});

test("a concurrent revision invalidates the review checkbox and preserves the proposal", async ({
  page,
}) => {
  await page.goto("/actions");
  await page
    .getByRole("button", { name: /Synthetic Northstar introduction/ })
    .click();
  await page
    .getByRole("textbox", { name: "Review reason" })
    .fill("Synthetic review");
  await page.getByRole("checkbox", { name: /I reviewed this account/ }).check();
  await page.evaluate(() =>
    fetch("/api/backend/test/action-conflict", { method: "POST" }),
  );
  await page.getByRole("button", { name: "Approve & queue" }).click();
  await expect(
    page.getByText("Revised text that requires a fresh review."),
  ).toBeVisible();
  await expect(
    page.getByRole("checkbox", { name: /I reviewed this account/ }),
  ).not.toBeChecked();
  await expect(
    page.getByRole("button", { name: "Approve & queue" }),
  ).toBeDisabled();
  await expect(page.getByRole("alert")).toContainText(
    "Review the current version",
  );
});

test("unknown external outcomes offer receipt reconciliation without another send", async ({
  page,
}) => {
  await page.goto("/actions");
  await page.evaluate(() =>
    fetch("/api/backend/test/action-unknown", { method: "POST" }),
  );
  await page
    .getByRole("button", { name: /Synthetic Northstar introduction/ })
    .click();
  await page.getByRole("button", { name: "Check provider receipt" }).click();
  await expect(
    page.getByRole("button", { name: "Approve & queue" }),
  ).toHaveCount(0);
  const requests = await page.evaluate(async () =>
    (await fetch("/api/backend/test/workflow-requests")).json(),
  );
  expect(requests.map((item: { route: string }) => item.route)).toEqual([
    "reviewed-actions/33333333-3333-4333-8333-333333333333/reconcile",
  ]);
});

test("spending defaults need no setup and custom limits retain accounting", async ({
  page,
}) => {
  await page.goto("/settings");
  await expect(page.getByText(/No setup needed/)).toBeVisible();
  await page.getByText("Customize spending limits", { exact: true }).click();
  const monthly = page.getByRole("textbox", { name: "Monthly limit (USD)" });
  await expect(monthly).toHaveValue("");
  await expect(
    page.getByLabel("Enable paid calls within these limits"),
  ).not.toBeChecked();
  await monthly.fill("1.00");
  await page
    .getByRole("textbox", { name: "Default work limit (USD)" })
    .fill("0.20");
  await page
    .getByLabel("Rate card", { exact: true })
    .selectOption("22222222-2222-4222-8222-222222222222");
  await page.getByLabel("Enable paid calls within these limits").check();
  await page.getByRole("button", { name: "Save limits" }).click();
  await expect(page.getByText("$0.94", { exact: true })).toBeVisible();
  await expect(page.getByText("$0.03", { exact: true })).toBeVisible();
  await monthly.fill("0.05");
  await page.getByRole("button", { name: "Save limits" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "cannot be below reserved, accounted, or unknown spend",
  );
});

test("connected operations are discoverable without inventing prices", async ({
  page,
}) => {
  await page.goto("/settings");
  await page.getByText("Customize spending limits", { exact: true }).click();
  await page
    .getByRole("button", { name: "New rate card", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Connected tool rate", exact: true })
    .click();
  await page
    .getByRole("combobox", { name: "Connected tool ID" })
    .selectOption("GMAIL_GET_PROFILE");
  await expect(
    page.getByRole("textbox", { name: "Maximum / call (USD)" }),
  ).toHaveValue("");
  await expect(
    page.getByRole("textbox", { name: "Input / million tokens (USD)" }),
  ).toHaveValue("");
});
