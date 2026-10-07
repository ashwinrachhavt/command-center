import { expect, test } from "@playwright/test";

test("a steady stream stays connected, keeps typing responsive, and lets the reader scroll back", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/tasks?record=task-stream&smooth_stream=1");
  await page.getByRole("tab", { name: "Conversation", exact: true }).click();
  const timeline = page.getByRole("log", { name: "Work conversation" });
  const scroller = timeline.getByRole("region", {
    name: "Conversation messages",
    exact: true,
  });
  const activity = timeline.getByRole("region", {
    name: "Grounded application guidance activity",
  });
  await expect(activity).toContainText("Paragraph 12:", { timeout: 20000 });
  await expect
    .poll(
      () =>
        scroller.evaluate(
          (element) => element.scrollHeight > element.clientHeight,
        ),
      { timeout: 20000 },
    )
    .toBe(true);
  await expect(activity.locator('[aria-busy="true"]')).toHaveCount(1);
  await expect(activity.locator("[data-sd-animate]").first()).toBeAttached();
  const message = page.getByRole("textbox", { name: "Message", exact: true });
  await message.fill(
    "Keep the draft concise while I read the earlier context.",
  );
  await expect(message).toHaveValue(
    "Keep the draft concise while I read the earlier context.",
  );
  await scroller.focus();
  await scroller.press("Home");
  await expect(
    page.getByRole("button", { name: "Scroll to latest message" }),
  ).toBeVisible();
  await expect(activity).toContainText("Paragraph 55:", { timeout: 20000 });
  expect(await scroller.evaluate((element) => element.scrollTop)).toBeLessThan(
    25,
  );
  await page.getByRole("button", { name: "Scroll to latest message" }).click();
  await expect(activity).toContainText("Paragraph 69:", { timeout: 20000 });
  await expect(activity.locator("[data-sd-animate]")).toHaveCount(0);
  await expect
    .poll(
      () =>
        scroller.evaluate(
          (element) =>
            element.scrollHeight - element.clientHeight - element.scrollTop,
        ),
      { timeout: 20000 },
    )
    .toBeLessThan(5);
  const state = await page.evaluate(async () =>
    (await fetch("/api/backend/test/stream-state")).json(),
  );
  expect(state.attempts["run-stream-a"]).toBe(1);
  expect(state.after["run-stream-a"]).toEqual([0]);
});

test("reduced motion streams the same text without word animation", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/tasks?record=task-stream&smooth_stream=1");
  await page.getByRole("tab", { name: "Conversation", exact: true }).click();
  const activity = page.getByRole("region", {
    name: "Grounded application guidance activity",
  });
  await expect(activity).toContainText("Paragraph 10:");
  await expect(activity.locator('[aria-busy="true"]')).toHaveCount(1);
  await expect(activity.locator("[data-sd-animate]")).toHaveCount(0);
  await expect(activity).toContainText("Paragraph 69:", { timeout: 20000 });
});

test("replays a disconnected run stream without duplicating tools or mixing runs", async ({
  page,
}) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  await page.goto("/tasks?record=task-stream");
  await page.getByRole("tab", { name: "Conversation", exact: true }).click();

  const primary = page.getByRole("region", {
    name: "Grounded application guidance activity",
  });
  const secondary = page.getByRole("region", {
    name: "Independent background check activity",
  });

  await expect(
    primary.getByText("Live activity disconnected", { exact: true }),
  ).toBeVisible();
  await expect(
    primary.getByRole("heading", { name: "Streaming answer" }),
  ).toBeVisible();
  await expect(primary).toContainText("Grounded");
  await expect(secondary).toContainText("Independent second stream.");
  await expect(primary).not.toContainText("Independent second stream.");
  await expect(secondary).not.toContainText("Streaming answer");

  // Event delivery reconnects automatically from the saved cursor; work is not resubmitted.
  await expect(
    primary.getByText("Work complete", { exact: true }),
  ).toBeVisible();
  await expect(primary).toContainText("Grounded evidence is ready.");
  const capsule = primary.getByRole("button", {
    name: "Show activity details",
  });
  await expect(capsule).toHaveAttribute("aria-expanded", "false");
  await capsule.focus();
  await page.keyboard.press("Enter");
  const expandedHeader = primary.getByRole("button", {
    name: "Hide activity details",
  });
  await expect(expandedHeader).toHaveAttribute("aria-controls", /.+/);
  const contentId = await expandedHeader.getAttribute("aria-controls");
  const content = primary.locator('[data-slot="chain-of-thought-content"]');
  await expect(content).toHaveAttribute("id", contentId!);
  await expect(primary).toContainText("150 tokens");
  await expect(primary.getByText("Duplicate should not render")).toHaveCount(0);
  await expect(
    primary.getByRole("button", { name: /Reading document.*Completed/ }),
  ).toHaveCount(1);

  await primary
    .getByRole("button", { name: /Reading document.*Completed/ })
    .click();
  await expect(primary).toContainText("resume-version-1");
  await expect(primary).toContainText("cited_versions");
  await expect(primary).not.toContainText("**Grounded");

  const streamState = await page.evaluate(async () => {
    const response = await fetch("/api/backend/test/stream-state");
    return response.json();
  });
  expect(streamState.attempts["run-stream-a"]).toBe(2);
  expect(streamState.after["run-stream-a"]).toEqual([0, 2]);
  expect(streamState.attempts["run-stream-b"]).toBe(1);
  expect(pageErrors).toEqual([]);
});

for (const dir of ["ltr", "rtl"] as const) {
  test(`chat activity timeline remains keyboard accessible on a narrow ${dir} screen`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: 320, height: 740 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.addInitScript((direction) => {
      document.addEventListener(
        "DOMContentLoaded",
        () => {
          document.documentElement.setAttribute("dir", direction);
        },
        { once: true },
      );
    }, dir);
    await page.goto("/agents?session=session-stream");
    const activity = page.getByRole("region", {
      name: "Grounded application guidance activity",
    });
    await expect(
      activity.getByText("Work complete", { exact: true }),
    ).toBeVisible();
    const toggle = activity.getByRole("button", {
      name: "Show activity details",
    });
    await toggle.focus();
    await page.keyboard.press("Space");
    const step = activity.locator('[data-slot="chain-of-thought-step"]');
    await expect(step).toHaveCount(1);
    await expect(step).toHaveAttribute("data-status", "complete");
    await expect(step).toHaveCSS("direction", dir);
    const tool = step.getByRole("button", {
      name: "Reading document Completed",
    });
    await tool.focus();
    await page.keyboard.press("Enter");
    await expect(step).toContainText("resume-version-1");
    await expect(step).toContainText("cited_versions");
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(320);
    const bounds = await tool.boundingBox();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(320);
    await activity
      .getByRole("button", { name: "Hide activity details" })
      .click();
    await expect(tool).not.toBeVisible();
    await expect(
      activity.getByRole("heading", { name: "Streaming answer" }),
    ).toBeVisible();
  });
}
