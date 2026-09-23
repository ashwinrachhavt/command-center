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
  await expect(activity).toContainText("Paragraph 12:");
  await expect
    .poll(() =>
      scroller.evaluate(
        (element) => element.scrollHeight > element.clientHeight,
      ),
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
  await expect(activity).toContainText("Paragraph 55:");
  expect(await scroller.evaluate((element) => element.scrollTop)).toBeLessThan(
    25,
  );
  await page.getByRole("button", { name: "Scroll to latest message" }).click();
  await expect(activity).toContainText("Paragraph 69:");
  await expect(activity.locator("[data-sd-animate]")).toHaveCount(0);
  await expect
    .poll(() =>
      scroller.evaluate(
        (element) =>
          element.scrollHeight - element.clientHeight - element.scrollTop,
      ),
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
  await expect(activity).toContainText("Paragraph 69:");
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

  await primary.getByRole("button", { name: "Retry stream" }).click();
  await expect(
    primary.getByText("Live activity complete", { exact: true }),
  ).toBeVisible();
  await expect(primary).toContainText("Grounded evidence is ready.");
  await expect(primary).toContainText("150 tokens");
  await expect(primary.getByText("Duplicate should not render")).toHaveCount(0);
  await expect(
    primary.getByRole("button", { name: /Document read.*Completed/ }),
  ).toHaveCount(1);

  await primary
    .getByRole("button", { name: /Document read.*Completed/ })
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
