import { expect, test } from "@playwright/test";

for (const width of [1440, 390]) {
  test(`activity capsules collapse, reopen by keyboard and fit at ${width}px`, async ({
    page,
  }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.setViewportSize({ width, height: 900 });
    await page.emulateMedia({
      reducedMotion: "reduce",
      colorScheme: width === 1440 ? "dark" : "light",
    });
    await page.goto("/?session=session-stream");
    const activity = page.getByRole("region", {
      name: "Grounded application guidance activity",
    });
    await expect(
      activity.getByText("Work complete", { exact: true }),
    ).toBeVisible();
    const capsule = activity.getByRole("button", {
      name: "Show activity details",
    });
    await expect(capsule).toHaveAttribute("aria-expanded", "false");
    await expect(activity).toContainText("Grounded evidence is ready.");
    expect((await capsule.boundingBox())!.height).toBeLessThanOrEqual(44);
    await capsule.focus();
    await page.keyboard.press("Enter");
    const tool = activity.getByRole("button", {
      name: "Reading document Completed",
    });
    await expect(tool).toBeVisible();
    await expect(tool).toHaveAttribute("aria-expanded", "false");
    await tool.focus();
    await page.keyboard.press("Enter");
    await expect(
      activity.getByText("cited_versions", { exact: false }),
    ).toBeVisible();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBe(width);
    await page.screenshot({
      path: `/tmp/command-center-capsules-${width}.png`,
    });
    await activity
      .getByRole("button", { name: "Hide activity details" })
      .click();
    await expect(tool).toHaveCount(0);
    await expect(activity).toContainText("Grounded evidence is ready.");
    expect(errors).toEqual([]);
    await page.screenshot({
      path: `/tmp/command-center-capsules-${width}-collapsed.png`,
    });
  });
}
