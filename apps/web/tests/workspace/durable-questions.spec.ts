import { expect, test } from "@playwright/test";

test("restores branch questions and retries one answer without losing its draft", async ({
  page,
}) => {
  await page.goto("/tasks?record=task-question");
  await page.getByRole("tab", { name: "Conversation", exact: true }).click();

  const activity = page.getByRole("region", {
    name: "Interview plan with saved questions activity",
  });
  await expect(
    activity.getByText("Waiting for user", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Work is paused until you answer the saved question below."),
  ).toBeVisible();

  await page.reload();
  await page.getByRole("tab", { name: "Conversation", exact: true }).click();

  const research = page.getByRole("form", {
    name: "Research needs your answer",
  });
  const application = page.getByRole("form", {
    name: "Application needs your answer",
  });
  await expect(research).toContainText("Branch research");
  await expect(application).toContainText("Branch applicat");

  const answer = research.getByRole("textbox", {
    name: "Answer Research question",
  });
  const applicationAnswer = application.getByRole("textbox", {
    name: "Answer Application question",
  });
  await answer.fill("Prioritize the developer platform roadmap.");
  await applicationAnswer.fill("Emphasize the migration that cut build times.");
  await page.waitForTimeout(2_700);
  await expect(answer).toHaveValue(
    "Prioritize the developer platform roadmap.",
  );
  await expect(applicationAnswer).toHaveValue(
    "Emphasize the migration that cut build times.",
  );

  await page.evaluate(async () => {
    await fetch("/api/backend/test/fail-question-refresh", { method: "POST" });
  });
  await expect(
    page.getByText(
      "Couldn’t refresh saved questions. Your prompts and drafts are still here.",
    ),
  ).toBeVisible({ timeout: 5_000 });
  await expect(answer).toHaveValue(
    "Prioritize the developer platform roadmap.",
  );
  await expect(applicationAnswer).toHaveValue(
    "Emphasize the migration that cut build times.",
  );
  await page.getByRole("button", { name: "Retry questions" }).click();

  await research.getByRole("button", { name: "Answer", exact: true }).click();
  await expect(research.getByRole("alert")).toContainText(
    "Your answer is still here; retry when ready.",
  );
  await expect(answer).toHaveValue(
    "Prioritize the developer platform roadmap.",
  );

  await research.getByRole("button", { name: "Retry answer" }).click();
  await expect(research).toHaveCount(0);
  await expect(application).toBeVisible();
  await expect(applicationAnswer).toHaveValue(
    "Emphasize the migration that cut build times.",
  );
  await expect(
    application.getByRole("button", { name: "Answer", exact: true }),
  ).toBeDisabled();
  await expect(activity.getByText("Queued", { exact: true })).toBeVisible();

  await page.evaluate(async () => {
    await fetch("/api/backend/test/wait-for-next-question", { method: "POST" });
  });
  await expect(
    application.getByRole("button", { name: "Answer", exact: true }),
  ).toBeEnabled({ timeout: 5_000 });
  await expect(applicationAnswer).toHaveValue(
    "Emphasize the migration that cut build times.",
  );

  const state = await page.evaluate(async () => {
    const response = await fetch("/api/backend/test/question-answer-state");
    return response.json();
  });
  expect(state.keys["question-research"]).toHaveLength(2);
  expect(state.keys["question-research"][0]).toBe(
    state.keys["question-research"][1],
  );
  expect(state.keys["question-application"]).toBeUndefined();
  expect(state.questions["run-question"][0]).toMatchObject({
    id: "question-research",
    state: "answered",
    answer: "Prioritize the developer platform roadmap.",
  });
  expect(state.questions["run-question"][1]).toMatchObject({
    id: "question-application",
    state: "open",
    answer: null,
  });
});
