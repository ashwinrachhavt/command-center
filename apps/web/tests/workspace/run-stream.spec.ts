import { expect, test } from "@playwright/test";

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

  await expect(primary.getByText("Live activity disconnected", { exact: true })).toBeVisible();
  await expect(primary.getByRole("heading", { name: "Streaming answer" })).toBeVisible();
  await expect(primary).toContainText("Grounded");
  await expect(secondary).toContainText("Independent second stream.");
  await expect(primary).not.toContainText("Independent second stream.");
  await expect(secondary).not.toContainText("Streaming answer");

  await primary.getByRole("button", { name: "Retry stream" }).click();
  await expect(primary.getByText("Live activity complete", { exact: true })).toBeVisible();
  await expect(primary).toContainText("Grounded evidence is ready.");
  await expect(primary).toContainText("150 tokens");
  await expect(primary.getByText("Duplicate should not render")).toHaveCount(0);
  await expect(primary.getByRole("button", { name: /Document read.*Completed/ })).toHaveCount(1);

  await primary.getByRole("button", { name: /Document read.*Completed/ }).click();
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
