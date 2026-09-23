import { expect, test } from "@playwright/test";

test("contact writing recovers, saves and copies a LinkedIn message, then prepares the exact email version", async ({
  page,
  context,
}) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/contacts?record=contact-1");
  await page.getByRole("button", { name: "Follow up", exact: true }).click();
  await page
    .getByRole("button", { name: "Write follow-up", exact: true })
    .click();
  const message = page.getByRole("textbox", {
    name: "Follow-up message",
    exact: true,
  });
  await expect(page.getByTestId("draft-status")).toContainText("Draft saved");
  await page
    .getByRole("textbox", { name: "Subject or reminder" })
    .fill("Continue our platform conversation");
  await message.fill(
    "Hi Alex, I enjoyed our conversation. Could we explore a next step?",
  );
  await expect(page.getByTestId("draft-status")).toContainText("Draft saved");
  await page.reload();
  await page.getByRole("button", { name: "Follow up", exact: true }).click();
  await expect(
    page.getByText("No saved follow-ups yet.", { exact: false }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Write follow-up", exact: true })
    .click();
  await expect(message).toContainText("Could we explore a next step?");
  await page
    .getByRole("button", { name: "Save follow-up", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByRole("button", { name: "Copy message", exact: true }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
    "Hi Alex, I enjoyed our conversation. Could we explore a next step?",
  );
  await expect(
    page.getByRole("link", { name: "Open LinkedIn" }),
  ).toHaveAttribute("href", /linkedin\.com/);
  await expect(
    page.getByRole("link", { name: "Open mail app" }),
  ).toHaveAttribute("href", /^mailto:alex%40example.com\?/);
  const saved = await page.evaluate(async () =>
    (await fetch("/api/backend/contacts/contact-1/follow-ups")).json(),
  );
  expect(saved.total).toBe(1);
  await page
    .getByRole("button", { name: "Prepare email", exact: true })
    .click();
  await expect(page.getByLabel("To", { exact: true })).toHaveValue(
    "alex@example.com",
  );
  await expect(page.getByLabel("Subject", { exact: true })).toHaveValue(
    "Continue our platform conversation",
  );
  await page
    .getByLabel("Account", { exact: true })
    .selectOption("11111111-1111-4111-8111-111111111111");
  await page
    .getByRole("button", { name: "Save proposal", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const requests = await page.evaluate(async () =>
    (await fetch("/api/backend/test/workflow-requests")).json(),
  );
  expect(requests).toHaveLength(1);
  expect(requests[0].route).toBe("reviewed-actions");
  expect(requests[0].body.source_version_id).toBe(saved.items[0].version_id);
  expect(requests[0].body.payload.body).toContain(
    "Could we explore a next step?",
  );
  await page.getByRole("button", { name: "Edit draft", exact: true }).click();
  await expect(message).toContainText("Could we explore a next step?");
  await message.fill("A newer follow-up for another day.");
  await page
    .getByRole("button", { name: "Save follow-up", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const latest = await page.evaluate(async () =>
    (await fetch("/api/backend/contacts/contact-1/follow-ups")).json(),
  );
  expect(latest.total).toBe(1);
  expect(latest.items[0].version).toBe(2);
  expect(latest.items[0].version_id).not.toBe(
    requests[0].body.source_version_id,
  );
});

test("follow-up writer stays usable on mobile and closes without discarding text", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/contacts?record=contact-1");
  await page.getByRole("button", { name: "Follow up", exact: true }).click();
  await page
    .getByRole("button", { name: "Write follow-up", exact: true })
    .click();
  const message = page.getByRole("textbox", {
    name: "Follow-up message",
    exact: true,
  });
  await message.fill("A short note to keep moving.");
  await page.getByRole("button", { name: "Close writer", exact: true }).click();
  await page
    .getByRole("button", { name: "Write follow-up", exact: true })
    .click();
  await expect(message).toContainText("A short note to keep moving.");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
