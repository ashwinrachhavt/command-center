import { expect, test, type Page } from "@playwright/test";

async function openHistory(page: Page, options = "") {
  await page.goto(`/settings?career-history${options}`);
  await page.getByRole("button", { name: "Propose edit" }).click();
  await expect(page.getByTestId("draft-status")).toContainText("Draft saved");
  await page.getByRole("button", { name: "Map experience fields" }).click();
  await expect(page.getByLabel("Company (required)")).toHaveValue(
    "Synthetic Orbit",
  );
}

test("maps imported history, recovers writing and approves only the saved revision", async ({
  page,
}) => {
  await openHistory(page);
  await expect(page.getByLabel("Start date", { exact: true })).toHaveValue(
    "2020",
  );
  await expect(page.getByLabel("End date", { exact: true })).toBeEmpty();
  await expect(page.getByLabel("Current status")).toContainText("Unknown");
  await page.getByLabel("Job title").fill("Senior engineer");
  await page
    .getByRole("textbox", { name: "Responsibilities and achievements" })
    .fill("Built accessible tools.");
  await expect(page.getByTestId("draft-status")).toContainText("Draft saved");
  await page.reload();
  await page.getByRole("button", { name: "Propose edit" }).click();
  await expect(page.getByLabel("Job title")).toHaveValue("Senior engineer");
  await expect(
    page.getByRole("textbox", { name: "Responsibilities and achievements" }),
  ).toContainText("Built accessible tools.");
  await page
    .getByRole("button", { name: "Save proposal", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const proposed = page.getByLabel("Current proposal Experience");
  await expect(proposed).toContainText("2020 — End unknown");
  await expect(page.getByLabel("Active approved Experience")).toContainText(
    "No approved value is active",
  );
  await page.getByRole("button", { name: "Approve exact revision" }).click();
  await expect(page.getByLabel("Active approved Experience")).toContainText(
    "Senior engineer",
  );
  const data = await page.evaluate(async () =>
    (await fetch("/api/backend/profile/facts")).json(),
  );
  expect(data.items[0].current.career.current).toBeNull();
  expect(data.items[0].current.context).toBeNull();
  expect(data.items[0].current.source_version_id).toBe("synthetic-source-v1");
});

test("recovers a lost proposal reply after reload without creating another revision", async ({
  page,
}) => {
  await openHistory(page, "&lose-fact-reply");
  await page
    .getByRole("button", { name: "Save proposal", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText(
    "Synthetic response lost",
  );
  await page.reload();
  await page.getByRole("button", { name: "Propose edit" }).click();
  await page.getByRole("button", { name: "Recover saved proposal" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const data = await page.evaluate(async () =>
    (await fetch("/api/backend/profile/facts")).json(),
  );
  expect(data.items[0].row_version).toBe(2);
  expect(data.items[0].active).toBeNull();
});

test("education editor fits mobile and keeps current status an explicit choice", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/settings?career-history");
  await page.getByRole("button", { name: "Propose fact", exact: true }).click();
  await expect(page.getByTestId("draft-status")).toContainText("Draft saved");
  await page.getByRole("combobox", { name: "Field", exact: true }).click();
  await page.getByRole("option", { name: "Education", exact: true }).click();
  await page.getByLabel("School (required)").fill("Synthetic College");
  await page.getByLabel("Degree", { exact: true }).fill("BSc");
  await page.getByLabel("Field of study").fill("Computer science");
  await page.getByLabel("Current status").click();
  await page.getByRole("option", { name: "I currently study here" }).click();
  await expect(page.getByLabel("End date", { exact: true })).toBeDisabled();
  await page
    .getByRole("textbox", { name: "Education notes" })
    .fill("Studying accessible software.");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/career-mobile.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Save proposal", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByLabel("Current proposal Education")).toContainText(
    "Present",
  );
  await expect(
    page.getByRole("button", { name: "Propose fact", exact: true }),
  ).toBeFocused();
});

test("Escape keeps the working draft and returns keyboard focus to its opener", async ({
  page,
}) => {
  await openHistory(page);
  await page.getByLabel("Job title").fill("Keyboard draft");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Propose edit" }),
  ).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByLabel("Job title")).toHaveValue("Keyboard draft");
});

test("a newer review requires an explicit new editing base and preserves the approved entry", async ({
  page,
}) => {
  await openHistory(page);
  await page.getByLabel("Job title").fill("My proposed role");
  await page.evaluate(async () =>
    fetch("/api/backend/profile/facts/synthetic-career/reviews", {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({
        expected_version: 1,
        revision_id: "synthetic-career-v1",
        decision: "approved",
      }),
    }),
  );
  await page
    .getByRole("button", { name: "Save proposal", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("Fact changed");
  await expect(page.getByLabel("Job title")).toHaveValue("My proposed role");
  await page
    .getByRole("button", { name: "Use latest revision as base" })
    .click();
  await page
    .getByRole("button", { name: "Save proposal", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByLabel("Current proposal Experience")).toContainText(
    "My proposed role",
  );
  const data = await page.evaluate(async () =>
    (await fetch("/api/backend/profile/facts")).json(),
  );
  expect(data.items[0].active.id).toBe("synthetic-career-v1");
});

test("recovering an earlier proposal keeps newer typing as a separate working draft", async ({
  page,
}) => {
  await openHistory(page, "&lose-fact-reply");
  await page
    .getByRole("button", { name: "Save proposal", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText(
    "Synthetic response lost",
  );
  await page.getByLabel("Job title").fill("Later edit");
  await expect(page.getByTestId("draft-status")).toContainText("Draft saved");
  await page.reload();
  await page.getByRole("button", { name: "Propose edit" }).click();
  await page.getByRole("button", { name: "Recover saved proposal" }).click();
  await expect(page.getByLabel("Job title")).toHaveValue("Later edit");
  await expect(
    page.getByRole("button", { name: "Save proposal", exact: true }),
  ).toBeEnabled();
  const first = await page.evaluate(async () =>
    (await fetch("/api/backend/profile/facts")).json(),
  );
  expect(first.items[0].row_version).toBe(2);
  expect(first.items[0].current.career.role).toBe("Engineer");
  await page
    .getByRole("button", { name: "Save proposal", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const second = await page.evaluate(async () =>
    (await fetch("/api/backend/profile/facts")).json(),
  );
  expect(second.items[0].row_version).toBe(3);
  expect(second.items[0].current.career.role).toBe("Later edit");
});
