import { expect, test } from "@playwright/test";

test("job description working edits survive reload and checkpoint separately", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/applications?application=task-tracker-1");
  const section = page.getByRole("region", {
    name: "Job description",
    exact: true,
  });
  await section
    .getByRole("button", { name: "Add job description", exact: true })
    .click();
  const editor = section.getByRole("textbox", {
    name: "Job description content",
    exact: true,
  });
  await expect(section).toBeFocused();
  await editor.fill("Build accessible tools with a thoughtful product team.");
  await expect(section.getByTestId("draft-status")).toContainText(
    "Draft saved",
  );
  await page.reload();
  await expect(editor).toContainText("Build accessible tools");
  await expect(section).toContainText("version 1");
  await section
    .getByRole("button", { name: "Save checkpoint", exact: true })
    .click();
  await expect(section).toContainText("version 2");
  await section
    .getByRole("button", { name: "Close writer", exact: true })
    .click();
  await section
    .getByRole("button", { name: "Edit description", exact: true })
    .click();
  await expect(editor).toHaveAttribute("contenteditable", "true");
  await editor.fill("Keep this unfinished second draft across reloads.");
  await expect(section.getByTestId("draft-status")).toContainText(
    "Draft saved",
  );
  await page.reload();
  await section.getByText("Read saved requirements", { exact: true }).click();
  await expect(
    section.getByText(
      "Build accessible tools with a thoughtful product team.",
      { exact: true },
    ),
  ).toBeVisible();
  await section
    .getByRole("button", { name: "Edit description", exact: true })
    .click();
  await expect(editor).toContainText("Keep this unfinished second draft");
  const state = await page.evaluate(async () =>
    (await fetch("/api/backend/test/application-tracker")).json(),
  );
  expect(state.contexts["task-tracker-1"].version).toBe(2);
  expect(state.contexts["task-tracker-1"].text).toBe(
    "Build accessible tools with a thoughtful product team.",
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("saved application opens from the list and reloads its exact answers", async ({
  page,
}) => {
  await page.goto("/applications");
  await page
    .getByRole("button", { name: /Product Engineer · Northstar/ })
    .click();
  await expect(
    page.getByRole("heading", { name: "Saved answers · version 2" }),
  ).toBeVisible();
  await expect(
    page.getByText("I build dependable tools that help small teams work well."),
  ).toBeVisible();
  await expect(
    page.getByRole("button", {
      name: /synthetic-resume.pdf · selected résumé/,
    }),
  ).toBeVisible();
  await expect(page.getByText("Latest fill attempt: Applied")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Mark as submitted", exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByText("I build dependable tools that help small teams work well."),
  ).toBeVisible();
  await page.getByRole("link", { name: "Review saved preparation" }).click();
  await expect(
    page.getByRole("textbox", { name: /Why this role/ }),
  ).toHaveValue("I build dependable tools that help small teams work well.");
  await expect(
    page.getByRole("button", { name: "Prepare again", exact: true }),
  ).toBeVisible();
});

test("lost status response retries the same receipt and preserves task state", async ({
  page,
}) => {
  await page.goto("/applications?application=task-tracker-1");
  await page.evaluate(() => fetch("/api/backend/test/application-lost-reply"));
  await page
    .getByRole("button", { name: "Mark as submitted", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Retry status update" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Retry status update" }).click();
  await expect(
    page.getByRole("combobox", { name: "Application status", exact: true }),
  ).toContainText("Submitted");
  const state = await page.evaluate(async () =>
    (await fetch("/api/backend/test/application-tracker")).json(),
  );
  expect(state.requests).toHaveLength(3);
  expect(state.requests[0]).toEqual(state.requests[1]);
  expect(state.requests[0]).toEqual(state.requests[2]);
  expect(state.applications[0].row_version).toBe(2);
  expect(state.applications[0].task.state).toBe("open");
  await page.reload();
  await expect(
    page.getByRole("combobox", { name: "Application status", exact: true }),
  ).toContainText("Submitted");
});

test("search and status filters narrow the list without changing progress", async ({
  page,
}) => {
  await page.goto("/applications");
  await page
    .getByRole("combobox", { name: "Filter application status" })
    .click();
  await page.getByRole("option", { name: "Interviewing", exact: true }).click();
  await expect(
    page.getByRole("button", { name: /Frontend Engineer · Harbor/ }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: /Product Engineer · Northstar/ }),
  ).toHaveCount(0);
  await page
    .getByRole("textbox", { name: "Search applications" })
    .fill("no match here");
  await expect(
    page.getByText("No matching applications", { exact: true }),
  ).toBeVisible();
});

test("application detail keeps the task editable and works at mobile width", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/applications?application=task-tracker-1");
  await page.getByRole("button", { name: "Edit next step" }).click();
  const dialog = page.getByRole("dialog");
  await dialog
    .getByRole("textbox", { name: /^Title/ })
    .fill("Follow up with the hiring team");
  await dialog.getByRole("button", { name: "Save changes" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "Follow up with the hiring team" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page
    .getByRole("button", { name: "All applications", exact: true })
    .click();
  await expect(
    page.getByRole("textbox", { name: "Search applications" }),
  ).toBeVisible();
});
