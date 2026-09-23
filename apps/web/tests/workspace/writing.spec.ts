import { expect, test, type Page } from "@playwright/test";

async function compose(page: Page) {
  await page.goto("/actions");
  await page.getByRole("button", { name: /New proposal/ }).click();
  await expect(page.getByTestId("draft-status")).toContainText("Draft saved");
  return page.getByRole("textbox", { name: "Message", exact: true });
}

test("restores an earlier working copy without proposing or approving an action", async ({
  page,
}) => {
  const message = await compose(page);
  await message.fill("First useful idea");
  await expect(page.getByTestId("draft-status")).toContainText("Draft saved");
  await message.fill("A different direction");
  await expect(page.getByTestId("draft-status")).toContainText("Draft saved");
  await page.reload();
  await page.getByRole("button", { name: /New proposal/ }).click();
  await expect(message).toContainText("A different direction");
  await page.getByText("Earlier drafts", { exact: true }).click();
  await page.getByRole("button", { name: /copy 1$/ }).click();
  await page.getByRole("button", { name: "Restore this draft" }).click();
  await expect(message).toContainText("First useful idea");
  await expect(page.getByTestId("draft-status")).toContainText("Draft saved");
  await page.getByText("Previous copy kept in this tab").click();
  await page.getByRole("button", { name: "Restore previous copy" }).click();
  await expect(message).toContainText("A different direction");
  expect(
    await page.evaluate(async () =>
      (await fetch("/api/backend/test/workflow-requests")).json(),
    ),
  ).toEqual([]);
});

test("writes formatted email, recovers after reload and creates only a deliberate checkpoint", async ({
  page,
}) => {
  const message = await compose(page);
  await page
    .getByLabel("Account", { exact: true })
    .selectOption("11111111-1111-4111-8111-111111111111");
  await page.getByLabel("To", { exact: true }).fill("synthetic@example.test");
  await page.getByLabel("Subject", { exact: true }).fill("A useful follow-up");
  await message.fill("Hello from my workspace");
  await message.press("End");
  await page.getByRole("button", { name: "Bold", exact: true }).click();
  await page.keyboard.type(" with a clear next step");
  await expect(message.locator("strong")).toContainText("clear next step");
  await page
    .getByText("Sources, attachments and review note", { exact: true })
    .click();
  await page
    .getByLabel("Reason", { exact: true })
    .fill("Prepared a synthetic introduction for review.");
  await expect(page.getByTestId("draft-status")).toContainText("Draft saved");
  let requests = await page.evaluate(async () =>
    (await fetch("/api/backend/test/workflow-requests")).json(),
  );
  expect(requests).toEqual([]);
  await page.reload();
  await page.getByRole("button", { name: /New proposal/ }).click();
  await expect(message).toContainText("clear next step");
  await expect(page.getByLabel("Subject", { exact: true })).toHaveValue(
    "A useful follow-up",
  );
  await page
    .getByRole("button", { name: "Save proposal", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  requests = await page.evaluate(async () =>
    (await fetch("/api/backend/test/workflow-requests")).json(),
  );
  expect(requests).toHaveLength(1);
  expect(requests[0].route).toBe("reviewed-actions");
  expect(requests[0].body.payload).toMatchObject({
    is_html: true,
    subject: "A useful follow-up",
  });
  expect(requests[0].body.payload.body).toContain("<strong>");
  const saved = await page.evaluate(async () =>
    (await fetch("/api/backend/writing-drafts/action-new")).json(),
  );
  expect(saved.data).toBeNull();
});

test("two tabs preserve both copies and require a deliberate conflict choice", async ({
  page,
  context,
}) => {
  const first = await compose(page);
  const other = await context.newPage();
  const second = await compose(other);
  await first.fill("Writing in the first tab");
  await expect(page.getByTestId("draft-status")).toContainText("Draft saved");
  await second.fill("Writing in the second tab");
  await expect(other.getByTestId("draft-status")).toContainText(
    "Two copies need your attention",
  );
  await expect(second).toContainText("Writing in the second tab");
  await other.getByText("Saved copy", { exact: true }).click();
  await expect(
    other.getByText(/Body:.*Writing in the first tab/),
  ).toBeVisible();
  await other.getByRole("button", { name: "Use saved copy" }).click();
  await expect(second).toContainText("Writing in the first tab");
  await other.getByText("Previous copy kept in this tab").click();
  await other.getByRole("button", { name: "Restore previous copy" }).click();
  await expect(second).toContainText("Writing in the second tab");
  await expect(other.getByTestId("draft-status")).toContainText("Draft saved");
});

test("the writer fits a narrow screen and link editing remains keyboard accessible", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const message = await compose(page);
  await message.fill("Read this note");
  await message.press("ControlOrMeta+a");
  await page.getByRole("button", { name: "Add or edit link" }).click();
  await page
    .getByRole("textbox", { name: "Link address" })
    .fill("javascript:alert(1)");
  await page.getByRole("button", { name: "Apply link" }).click();
  await expect(page.getByRole("alert")).toContainText("Use an https");
  await page
    .getByRole("textbox", { name: "Link address" })
    .fill("https://example.com/note");
  await page.getByRole("button", { name: "Apply link" }).click();
  await expect(message).toBeFocused();
  await expect(message.locator("a")).toHaveAttribute(
    "href",
    "https://example.com/note",
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("opening mail tools and typing a query never fetches mail before an explicit pull", async ({
  page,
}) => {
  await page.goto("/actions");
  const requests = () =>
    page.evaluate(async () =>
      (await fetch("/api/backend/test/workflow-requests")).json(),
    );
  expect(await requests()).toEqual([]);
  await page.getByRole("button", { name: "Pull email", exact: true }).click();
  await page
    .getByRole("textbox", { name: "Email search" })
    .fill("from:taylor@example.com");
  expect(await requests()).toEqual([]);
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Pull email", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Synthetic project note" }),
  ).toBeVisible();
  await page.getByText("Read pulled message", { exact: true }).click();
  await expect(
    page.getByText("Here is the context you explicitly asked to pull."),
  ).toBeVisible();
  const sent = await requests();
  expect(sent).toHaveLength(1);
  expect(sent[0]).toMatchObject({
    route: "gmail/search",
    body: {
      query: "from:taylor@example.com",
      max_results: 10,
      account_id: "11111111-1111-4111-8111-111111111111",
    },
  });
});
