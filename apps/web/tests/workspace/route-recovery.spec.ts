import { expect, test } from "@playwright/test";

for (const width of [1600, 390]) {
  test(`a failed page stays visible and reloads at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto("/contacts?routeError=1");
    await expect(page).toHaveTitle("Command Center · Synthetic preview");
    await expect(
      page.getByRole("heading", { name: "This page couldn’t load" }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Reload page" })).toBeVisible();
    await page.screenshot({ path: `/tmp/command-center-route-error-${width}.png` });
    // Simulate the transient server/session failure clearing before a retry.
    await page.evaluate(() => history.replaceState({}, "", "/contacts"));
    await page.getByRole("button", { name: "Reload page" }).click();
    await expect(page.getByRole("heading", { name: "Contacts", exact: true })).toBeVisible();
    await expect(page.getByRole("textbox", { name: "Search contacts" })).toBeVisible();
    await page.screenshot({ path: `/tmp/command-center-route-recovered-${width}.png` });
    expect(errors).toEqual([]);
  });
}
