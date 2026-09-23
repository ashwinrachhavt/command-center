import { expect, test } from "@playwright/test";

test("contact rows default to a quick note and deeper enrichment is explicit", async ({
  page,
}) => {
  await page.goto("/contacts");
  await page
    .getByRole("button", { name: "Draft connection note", exact: true })
    .first()
    .click();
  await expect(
    page.getByRole("button", { name: "Copy note", exact: true }).first(),
  ).toBeVisible();
  const requests = await page.evaluate(() =>
    JSON.parse(localStorage.getItem("synthetic-record-work-requests") ?? "[]"),
  );
  expect(requests).toHaveLength(1);
  expect(requests[0].body.connection_note).toBe(true);
  expect(requests[0].body.research_requested).not.toBe(true);
  await expect(
    page.getByRole("button", { name: "Enrich contact", exact: true }).first(),
  ).toBeVisible();
  await page.getByRole("button", { name: "Batch enrich", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Enrich selected contacts" });
  await expect(dialog).toContainText("Choose up to 10 people");
  await dialog.getByRole("checkbox").first().check();
  await dialog.getByRole("button", { name: "Enrich 1", exact: true }).click();
  await expect(
    dialog.getByRole("button", { name: "Open task", exact: true }),
  ).toBeVisible();
  const all = await page.evaluate(() =>
    JSON.parse(localStorage.getItem("synthetic-record-work-requests") ?? "[]"),
  );
  expect(all).toHaveLength(2);
  expect(all[1].body.research_requested).toBe(true);
});

test("batch selection fits mobile and resets when the contact search changes", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/contacts");
  await page.getByRole("button", { name: "Batch enrich", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Enrich selected contacts" });
  const selection = dialog.getByRole("checkbox").first();
  await selection.check();
  await expect(
    dialog.getByRole("button", { name: "Enrich 1", exact: true }),
  ).toBeEnabled();
  const bounds = await selection.boundingBox();
  expect(bounds?.width).toBe(bounds?.height);
  expect(
    await dialog.evaluate(
      (element) => element.scrollWidth <= element.clientWidth,
    ),
  ).toBe(true);
  await dialog.getByRole("button", { name: "Close", exact: true }).click();
  await page.getByRole("textbox", { name: "Search contacts" }).fill("Alex");
  await page.getByRole("button", { name: "Batch enrich", exact: true }).click();
  await expect(selection).not.toBeChecked();
  await expect(
    dialog.getByRole("button", { name: "Enrich selected", exact: true }),
  ).toBeDisabled();
});

test("an agent-generated contact draft is saved, editable and recoverable without delivery", async ({
  page,
}) => {
  await page.goto("/contacts?record=contact-1");
  await page.getByRole("button", { name: "Follow up", exact: true }).click();
  expect(
    await page.evaluate(() =>
      JSON.parse(
        localStorage.getItem("synthetic-record-work-requests") ?? "[]",
      ),
    ),
  ).toHaveLength(0);
  await page.getByRole("button", { name: "Draft with agent" }).click();
  await expect(
    page
      .getByRole("region", { name: "Agent follow-up drafting" })
      .getByRole("status"),
  ).toContainText("Queued for your agent");
  await page.getByRole("button", { name: "Review generated draft" }).click();
  await expect(
    page.getByRole("region", { name: "Saved follow-up" }),
  ).toContainText("Would you be open to a short conversation?");
  await page.getByRole("button", { name: "Edit draft", exact: true }).click();
  await page
    .getByRole("textbox", { name: "Follow-up message", exact: true })
    .fill("Hi Alex, here is my own version of the introduction.");
  await page
    .getByRole("button", { name: "Save follow-up", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.reload();
  await page.getByRole("button", { name: "Follow up", exact: true }).click();
  await page.getByRole("button", { name: "Review generated draft" }).click();
  await expect(
    page
      .getByRole("region", { name: "Saved follow-up" })
      .frameLocator("iframe")
      .locator("body"),
  ).toContainText("my own version");
  const drafts = await page.evaluate(() =>
    Object.values(
      JSON.parse(localStorage.getItem("synthetic-follow-ups") ?? "{}"),
    ),
  );
  expect(drafts).toHaveLength(1);
  const delivery = await page.evaluate(async () =>
    (await fetch("/api/backend/test/workflow-requests")).json(),
  );
  expect(delivery).toHaveLength(0);
});

test("company enrichment opens beside the row, shows a cited brief and retains task context", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/companies");
  await page
    .getByRole("button", { name: "Enrich company", exact: true })
    .click();
  const panel = page.getByLabel("Related workspace", { exact: true });
  await expect(panel).toBeVisible();
  await expect(
    panel.getByRole("region", { name: "Company research" }),
  ).toContainText("Northstar builds developer tools");
  await panel.getByRole("button", { name: "the careers page" }).click();
  await expect(page.getByRole("dialog")).toContainText(
    "https://example.com/careers",
  );
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(
    panel.getByRole("button", { name: "the careers page" }),
  ).toBeFocused();
  await expect(page.getByRole("table")).toContainText(
    "Northstar builds developer tools",
  );
  await panel.getByRole("button", { name: "Open work", exact: true }).click();
  await expect(page).toHaveURL((url) =>
    url.searchParams
      .getAll("inspect")
      .some((value) => value.endsWith(":conversation")),
  );
  await expect(
    panel.getByRole("tab", { name: "Conversation", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await page.getByRole("button", { name: "Back to previous context" }).click();
  await expect(
    panel.getByRole("region", { name: "Company research" }),
  ).toContainText("platform engineering opportunities");
  await page.getByRole("button", { name: "Close related workspace" }).click();
  await expect(page).toHaveURL(/\/companies$/);
  expect(
    await page.evaluate(() =>
      JSON.parse(
        localStorage.getItem("synthetic-record-work-requests") ?? "[]",
      ),
    ),
  ).toHaveLength(1);
});

test("an interrupted start keeps the same request across reload and does not queue another task", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/contacts?record=contact-1&work_fail_start=1");
  await page.getByRole("button", { name: "Follow up", exact: true }).click();
  await page.getByRole("button", { name: "Draft with agent" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Synthetic response interrupted",
  );
  await page.reload();
  await page.getByRole("button", { name: "Follow up", exact: true }).click();
  await page.getByRole("button", { name: "Draft with agent" }).click();
  await page.getByRole("button", { name: "Review generated draft" }).click();
  const requests = await page.evaluate(() =>
    JSON.parse(localStorage.getItem("synthetic-record-work-requests") ?? "[]"),
  );
  expect(requests).toHaveLength(3);
  expect(
    new Set(requests.map((request: { key: string }) => request.key)).size,
  ).toBe(1);
  expect(
    await page.evaluate(() =>
      JSON.parse(localStorage.getItem("synthetic-record-work") ?? "[]"),
    ),
  ).toHaveLength(1);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
