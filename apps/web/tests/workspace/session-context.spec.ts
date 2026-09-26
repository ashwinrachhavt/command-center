import { expect, test } from "@playwright/test";

for (const width of [1440, 390]) {
  test(`thread checkpoints and session memory are visible at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/agents?session=session-opportunity-1&context_checkpoint");
    await page
      .getByRole("button", { name: "Context summarized", exact: true })
      .click();
    await expect(page.getByRole("dialog")).toContainText(
      "Retain the synthetic objective",
    );
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "Context & memory" }).click();
    const context = page.getByRole("dialog");
    await context
      .getByRole("textbox", { name: "Checkpoint name" })
      .fill("Agreed next step");
    await context.getByRole("button", { name: "Save checkpoint" }).click();
    await expect(
      context.getByRole("button", { name: "Agreed next step" }),
    ).toBeVisible();
    await context
      .getByRole("textbox", { name: "Conversation name" })
      .fill("Synthetic research thread");
    await context.getByRole("button", { name: "Rename", exact: true }).click();
    await expect(
      page.getByText("Conversation renamed", { exact: true }),
    ).toBeVisible();
    await context.getByRole("tab", { name: "Memory", exact: true }).click();
    await context
      .getByRole("button", { name: "Add memory", exact: true })
      .click();
    const editor = page.getByRole("dialog", { name: "Add reviewed memory" });
    await editor
      .getByRole("textbox", { name: "Title", exact: true })
      .fill("Synthetic thread preference");
    await editor
      .getByRole("textbox", { name: "Reusable context" })
      .fill("Use concise examples for this thread.");
    await expect(editor).toContainText("This conversation");
    await editor
      .getByRole("button", { name: "Save and confirm memory" })
      .click();
    await expect(context).toContainText("Synthetic thread preference");
    await page.keyboard.press("Escape");
    await expect(
      page.getByRole("button", { name: "Agreed next step", exact: true }),
    ).toBeVisible();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(width);
  });
}

test("history finds scoped threads and keeps drafts separate across navigation and reload", async ({
  page,
}) => {
  await page.goto("/agents?session=session-opportunity-1");
  const composer = page.getByRole("textbox", { name: "Message your agent" });
  await composer.fill("Unsent draft for the opportunity.");
  const search = page.getByRole("textbox", { name: "Search conversations" });
  await search.fill("Streamed");
  await page
    .getByRole("button", { name: /Streamed work conversation/ })
    .click();
  await expect(composer).toHaveValue("");
  await composer.fill("Unsent draft for streamed work.");
  await page.reload();
  await expect(composer).toHaveValue("Unsent draft for streamed work.");
  await page
    .getByRole("button", { name: /Staff Product Engineer conversation/ })
    .click();
  await expect(composer).toHaveValue("Unsent draft for the opportunity.");
});

test("continuing a completed thread renders a checkpoint beside its preserved messages", async ({
  page,
}) => {
  await page.goto("/agents?session=session-opportunity-1");
  await expect(
    page.getByRole("combobox", { name: "Choose agent" }),
  ).toContainText("Research");
  await page
    .getByRole("textbox", { name: "Message your agent" })
    .fill("Continue the synthetic research.");
  await page.getByRole("button", { name: "Run agent", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Conversation continued", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Continue the synthetic research.", { exact: true }),
  ).toBeVisible();
});

test("a context checkpoint arriving during work is rendered and announced", async ({
  page,
}) => {
  await page.goto("/agents?session=session-stream");
  await expect(
    page.getByRole("button", { name: "Context & memory" }),
  ).toBeVisible();
  await expect(
    page.getByText("Prepare grounded application guidance.", { exact: true }),
  ).toBeVisible();
  await page.evaluate(() => {
    const previous = window.fetch;
    window.fetch = async (input, init) => {
      const response = await previous(input, init);
      if (!String(input).includes("/session-stream/checkpoints"))
        return response;
      const body = await response.json();
      body.items.push({
        id: "live-context-checkpoint",
        session_id: "session-stream",
        sequence: 1,
        kind: "compacted",
        title: "Context summarized",
        summary: "Retain the active synthetic task.",
        run_id: null,
        summary_revision: 1,
        created_at: "2026-09-24T12:00:00Z",
      });
      body.total = body.items.length;
      return Response.json(body);
    };
  });
  await expect(
    page.getByRole("button", { name: "Context summarized", exact: true }),
  ).toBeVisible({ timeout: 15000 });
  await expect(
    page.getByText(
      "Conversation context summarized. Your full transcript is preserved.",
      { exact: true },
    ),
  ).toBeVisible();
});
