import { expect, test } from "@playwright/test";

test("saved account status and selection work without an automatic provider pull", async ({
  page,
}) => {
  await page.goto("/connections");
  await expect(
    page.getByRole("heading", { name: "Connected apps", exact: true }),
  ).toBeVisible();
  const gmail = page.getByRole("region", { name: "Gmail", exact: true });
  await expect(
    gmail.getByText("alex@example.com", { exact: false }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("region", { name: "Linear", exact: true })
      .getByText("Needs attention"),
  ).toBeVisible();
  expect(
    await page.evaluate(async () =>
      (await fetch("/api/backend/test/connections")).json(),
    ),
  ).toEqual([]);
  await gmail.getByRole("button", { name: "Use for outreach" }).click();
  const sam = gmail
    .getByRole("listitem")
    .filter({ hasText: "sam@example.com" });
  await expect(
    sam.getByText("Outreach account", { exact: true }),
  ).toBeVisible();
  const alex = gmail
    .getByRole("listitem")
    .filter({ hasText: "alex@example.com" });
  await expect(
    alex.getByRole("button", { name: "Use for outreach" }),
  ).toBeEnabled();
  expect(
    await page.evaluate(async () =>
      (await fetch("/api/backend/test/connections")).json(),
    ),
  ).toEqual([
    {
      route:
        "integrations/composio/accounts/22222222-2222-4222-8222-222222222222/select",
      body: { purpose: "outreach", expected_version: 1 },
    },
  ]);
});

test("OAuth return waits for an explicit account check", async ({ page }) => {
  await page.goto("/connections?connected=1");
  await expect(page.getByText("Finish connecting your app")).toBeVisible();
  expect(
    await page.evaluate(async () =>
      (await fetch("/api/backend/test/connections")).json(),
    ),
  ).toEqual([]);
  await page.getByRole("button", { name: "Refresh accounts" }).click();
  await expect(page.getByText("Finish connecting your app")).toHaveCount(0);
  await expect(page).toHaveURL(/\/connections$/);
  expect(
    await page.evaluate(async () =>
      (await fetch("/api/backend/test/connections")).json(),
    ),
  ).toEqual([{ route: "integrations/composio/accounts/sync", body: {} }]);
});

test("setup guidance is keyboard accessible and fits a narrow screen", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/connections");
  const setup = page
    .getByRole("region", { name: "Notion", exact: true })
    .getByRole("button", { name: "View setup" });
  await setup.focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("dialog", { name: "Set up Notion" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.keyboard.press("Escape");
  await expect(setup).toBeFocused();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("Connect uses the chosen app and follows its authorization URL", async ({
  page,
}) => {
  await page.route("https://provider.example/**", (route) =>
    route.fulfill({ body: "Synthetic provider authorization" }),
  );
  await page.goto("/connections");
  await page
    .getByRole("region", { name: "Google Calendar", exact: true })
    .getByRole("button", { name: "Connect", exact: true })
    .click();
  await expect(page).toHaveURL("https://provider.example/authorize");
});
