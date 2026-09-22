import { expect, test } from "@playwright/test";

async function requestKeys(page: import("@playwright/test").Page) {
  return page.evaluate(async () => {
    const response = await fetch("/api/backend/test/lead-request-keys");
    return (await response.json()) as Record<string, string[]>;
  });
}

test("searches, captures, enriches, pins evidence, and drafts outreach", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));

  await page.goto("/opportunities");
  await page.getByRole("button", { name: "Discover leads" }).click();
  await page
    .getByRole("textbox", { name: "Search public job pages" })
    .fill("platform engineer public roles");
  await page.getByRole("button", { name: "Search", exact: true }).click();

  const result = page.getByRole("button", { name: /Platform Engineer/ });
  await expect(result).toBeVisible();
  await result.click();
  await expect(page.getByLabel("Role title")).toHaveValue("Platform Engineer");
  await page.getByLabel("Company name").fill("Meridian Labs");
  await page.getByRole("button", { name: "Capture to CRM" }).click();

  await expect(page).toHaveURL(/record=opportunity-lead-/);
  await expect(
    page.getByRole("heading", { name: "Platform Engineer", exact: true }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Research", exact: true }).click();
  await expect(page.getByText(/Version 1 · search/)).toBeVisible();

  await page.getByRole("button", { name: "Enrich from source" }).click();
  const savedVersion = page.getByRole("button", {
    name: "View saved version 2",
  });
  await expect(savedVersion).toBeVisible();
  await savedVersion.click();
  await expect(page).toHaveURL(/inspect=artifacts%3Aartifact-source-lead-/);
  await expect(
    page.getByRole("tab", { name: "Content & versions" }),
  ).toHaveAttribute("aria-selected", "true");
  await expect(
    page.getByRole("combobox", { name: "Artifact version" }),
  ).toContainText("Version 2");
  await expect(
    page.getByText("Exact immutable evidence for Platform Engineer, version 2."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Close related workspace" }).click();
  await expect(
    page.getByRole("tab", { name: "Research", exact: true }),
  ).toHaveAttribute("aria-selected", "true");

  const request = page.getByLabel("Request");
  await expect(request).toContainText("do not send it");
  await page.getByRole("button", { name: "Draft outreach" }).click();
  await expect(
    page.getByRole("tab", { name: "Conversation", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await expect(page.getByText("You → Outreach")).toBeVisible();
  await expect(
    page.getByText(/Draft a concise outreach message for this opportunity/),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test("retries failed lead requests with the same identities and preserved drafts", async ({
  page,
}) => {
  await page.goto("/opportunities");
  const before = await requestKeys(page);

  await page.getByRole("button", { name: "Discover leads" }).click();
  const query = page.getByRole("textbox", {
    name: "Search public job pages",
  });
  await query.fill("retry provider product engineering");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByText("Public search failed")).toBeVisible();
  await expect(query).toHaveValue("retry provider product engineering");

  let after = await requestKeys(page);
  const failedSearchKeys = (after.search ?? []).slice(
    (before.search ?? []).length,
  );
  expect(new Set(failedSearchKeys).size).toBe(1);
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(
    page.getByRole("button", { name: /Product Engineer/ }),
  ).toBeVisible();
  after = await requestKeys(page);
  const retriedSearchKeys = (after.search ?? []).slice(
    (before.search ?? []).length,
  );
  expect(new Set(retriedSearchKeys).size).toBe(1);

  await page.getByRole("button", { name: /Product Engineer/ }).click();
  await page.getByLabel("Company name").fill("Retry Labs");
  await page.getByRole("button", { name: "Capture to CRM" }).click();
  await expect(page.getByText("Lead capture failed")).toBeVisible();
  await expect(page.getByLabel("Company name")).toHaveValue("Retry Labs");
  const captureBaseline = (before.capture ?? []).length;
  after = await requestKeys(page);
  expect(new Set((after.capture ?? []).slice(captureBaseline)).size).toBe(1);
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page).toHaveURL(/record=opportunity-lead-/);
  after = await requestKeys(page);
  expect(new Set((after.capture ?? []).slice(captureBaseline)).size).toBe(1);

  await page.goto("/opportunities?record=opportunity-2");
  await page.getByRole("tab", { name: "Research", exact: true }).click();
  const enrichBaseline = (after.enrich ?? []).length;
  await page.getByRole("button", { name: "Enrich from source" }).click();
  await expect(page.getByText("Source fetch failed")).toBeVisible();
  await expect(page.getByText(/fields and status are unchanged/)).toBeVisible();
  after = await requestKeys(page);
  expect(new Set((after.enrich ?? []).slice(enrichBaseline)).size).toBe(1);
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "View saved version 1" }),
  ).toBeVisible();
  after = await requestKeys(page);
  expect(new Set((after.enrich ?? []).slice(enrichBaseline)).size).toBe(1);
});
