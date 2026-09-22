import { expect, test } from "@playwright/test";

test("restores an opportunity conversation with specialist activity and outputs", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));

  await page.goto("/opportunities?record=opportunity-1");
  await page.getByRole("tab", { name: "Conversation", exact: true }).click();

  await expect(
    page.getByText("Summarize the interview context."),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Interview brief" }),
  ).toBeVisible();
  const continuedInstruction = page.getByText("Add compensation questions.");
  await expect(continuedInstruction.locator("..")).toContainText("Applied");
  await expect(page.getByText("Research specialist")).toBeVisible();
  await expect(page.getByText("Northstar interview brief · v2")).toBeVisible();

  await page
    .getByRole("button", { name: "Northstar interview brief · v2" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Northstar interview brief" }),
  ).toBeVisible();
  await expect(
    page.getByRole("tab", { name: "Content & versions" }),
  ).toHaveAttribute("aria-selected", "true");
  await expect(
    page.getByRole("combobox", { name: "Artifact version" }),
  ).toContainText("Version 2");
  await expect(page.getByText("Pinned version two content.")).toBeVisible();
  await expect(page.getByText("Latest version three content.")).toHaveCount(0);
  await page.getByRole("button", { name: "Close related workspace" }).click();
  await expect(
    page.getByRole("tab", { name: "Conversation", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await expect(
    page.getByText("Summarize the interview context."),
  ).toBeVisible();

  await page.getByRole("tab", { name: "Overview", exact: true }).click();
  await page.getByRole("tab", { name: "Conversation", exact: true }).click();
  await expect(
    page.getByText("Summarize the interview context."),
  ).toBeVisible();
  await page.reload();
  await page.getByRole("tab", { name: "Conversation", exact: true }).click();
  await expect(
    page.getByText("Summarize the interview context."),
  ).toBeVisible();

  await page.goto("/opportunities?record=opportunity-2");
  await page.getByRole("tab", { name: "Conversation", exact: true }).click();
  await expect(page.getByText("Summarize the interview context.")).toHaveCount(
    0,
  );
  await expect(page.getByText("No conversation yet")).toBeVisible();
  await page
    .getByRole("textbox", { name: "Message" })
    .fill("Opportunity-only draft");
  await page.goto("/tasks?record=task-1");
  await page.getByRole("tab", { name: "Conversation", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Message" })).toHaveValue("");
  expect(errors).toEqual([]);
});

test("preserves a newly typed draft and fetches terminal run details", async ({
  page,
}) => {
  await page.goto("/tasks?record=task-1");
  await page.getByRole("tab", { name: "Conversation", exact: true }).click();

  const composer = page.getByRole("textbox", { name: "Message" });
  await composer.fill("First delayed message.");
  await page.getByRole("button", { name: "Send message" }).click();
  await composer.fill("Keep this next message.");
  await expect(composer).toHaveValue("Keep this next message.");
  await expect(page.getByText("First delayed message.")).toBeVisible();
  await expect(composer).toHaveValue("Keep this next message.");

  const completed = await page.evaluate(async () => {
    const response = await fetch("/api/backend/test/complete-active-run", {
      method: "POST",
    });
    return response.ok;
  });
  expect(completed).toBe(true);
  await expect(page.getByText("Final specialist result")).toBeVisible({
    timeout: 7_000,
  });
  await expect(
    page.getByRole("heading", { name: "Final run outcome" }),
  ).toBeVisible();
});

test("a missing pinned artifact version does not show the latest content", async ({
  page,
}) => {
  await page.goto(
    "/opportunities?record=opportunity-1&inspect=artifacts%3Aartifact-1%3Acontent%3Amissing-version",
  );
  await expect(page.getByRole("alert")).toContainText(
    "Pinned artifact version is unavailable",
  );
  await expect(page.getByText("Latest version three content.")).toHaveCount(0);
});

test("sends a task message, appends steering, and cancels one active run", async ({
  page,
}) => {
  await page.goto("/tasks?record=task-1");
  await page.getByRole("tab", { name: "Conversation", exact: true }).click();

  const address = page.getByRole("combobox", { name: "Address" });
  await expect(address).toContainText("Lead");
  await address.click();
  await expect(page.getByRole("option", { name: "Research" })).toBeVisible();
  await expect(page.getByRole("option", { name: "Application" })).toBeVisible();
  await expect(page.getByRole("option", { name: "Outreach" })).toBeVisible();
  await page.keyboard.press("Escape");

  const composer = page.getByRole("textbox", { name: "Message" });
  await composer.fill("Prepare a concise interview plan.");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(
    page.getByText("Prepare a concise interview plan."),
  ).toBeVisible();
  await expect(page.getByText("1 active run")).toBeVisible();
  await expect(address).toBeDisabled();

  await composer.fill("Focus on the platform roadmap.");
  await page.getByRole("button", { name: "Send instruction" }).click();
  await expect(page.getByText("Focus on the platform roadmap.")).toBeVisible();
  await expect(page.getByText("1 active run")).toBeVisible();
  await expect(page.getByText(/saved.*next safe/i)).toBeVisible();

  await page.getByRole("button", { name: "Cancel work" }).click();
  await expect(page.getByText("Cancelled", { exact: true })).toBeVisible();
  await expect(page.getByText("1 active run")).toHaveCount(0);
});

test("conversation controls fit a mobile task inspector without page errors", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));

  await page.goto("/tasks?record=task-1");
  await page.getByRole("tab", { name: "Conversation", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Message" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(
    390,
  );
  expect(errors).toEqual([]);
});
