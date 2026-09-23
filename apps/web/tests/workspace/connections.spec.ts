import { expect, test } from "@playwright/test";

for (const width of [1440, 390]) {
  test(`LinkedIn connects and verifies after OAuth at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto("/connections");
    await expect(page).toHaveTitle("Command Center · Synthetic preview");
    const card = page.getByRole("region", { name: "LinkedIn", exact: true });
    await expect(
      card.getByText("Not connected", { exact: true }),
    ).toBeVisible();
    await expect(
      card.getByText(/Messages and connection requests are not supported/),
    ).toBeVisible();
    const returnUrl = new URL(
      "/connections?connected=1&toolkit=linkedin",
      page.url(),
    ).href;
    await page.route("https://provider.example/**", (route) =>
      route.fulfill({
        contentType: "text/html",
        body: `<a href="${returnUrl}">Finish LinkedIn authorization</a>`,
      }),
    );
    await card.getByRole("button", { name: "Connect", exact: true }).click();
    await expect(page).toHaveURL("https://provider.example/authorize");
    await page
      .getByRole("link", { name: "Finish LinkedIn authorization" })
      .click();
    await expect(page).toHaveURL(/\/connections$/);
    await expect(card.getByText("Connected", { exact: true })).toBeVisible();
    await expect(
      card.getByText("Alex Synthetic", { exact: true }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await card.scrollIntoViewIfNeeded();
    await page.screenshot({
      path: `/tmp/command-center-linkedin-${width}.png`,
    });
    expect(errors).toEqual([]);
  });
}

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

for (const width of [1440, 390]) {
  test(`OAuth return verifies and displays Gmail automatically at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.route("**/api/backend/integrations/composio/accounts", (route) =>
      route.fulfill({ json: [] }),
    );
    await page.goto(
      "/connections?connected=1&status=success&connected_account_id=ca_synthetic",
    );
    await expect(page).toHaveTitle("Command Center · Synthetic preview");
    await expect(page).toHaveURL(/\/connections$/);
    await expect(
      page
        .getByRole("region", { name: "Gmail", exact: true })
        .getByText("Connected", { exact: true }),
    ).toBeVisible();
    expect(
      await page.evaluate(async () =>
        (await fetch("/api/backend/test/connections")).json(),
      ),
    ).toEqual([{ route: "integrations/composio/accounts/sync", body: {} }]);
    await page.screenshot({
      path: `/tmp/command-center-gmail-return-${width}.png`,
    });
    expect(errors).toEqual([]);
  });
}

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

test("Connect follows authorization and verifies when returning without callback parameters", async ({
  page,
}) => {
  await page.goto("/connections");
  const returnUrl = page.url();
  await page.route("https://provider.example/**", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: `<a href="${returnUrl}">Finish authorization</a>`,
    }),
  );
  await page
    .getByRole("region", { name: "Google Calendar", exact: true })
    .getByRole("button", { name: "Connect", exact: true })
    .click();
  await expect(page).toHaveURL("https://provider.example/authorize");
  await page.getByRole("link", { name: "Finish authorization" }).click();
  await expect(page).toHaveURL(returnUrl);
  await expect(
    page.getByRole("heading", { name: "Connected apps", exact: true }),
  ).toBeVisible();
  await expect
    .poll(async () =>
      page.evaluate(async () =>
        (await (await fetch("/api/backend/test/connections")).json()).filter(
          (item: { route: string }) => item.route.endsWith("/sync"),
        ),
      ),
    )
    .toEqual([{ route: "integrations/composio/accounts/sync", body: {} }]);
});
