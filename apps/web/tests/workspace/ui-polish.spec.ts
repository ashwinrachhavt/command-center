import { expect, test, type Locator, type Page } from "@playwright/test";

async function hold(page: Page, target: Locator) {
  await target.scrollIntoViewIfNeeded();
  const box = await target.boundingBox();
  if (!box) throw new Error("Missing control bounds");
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
}

async function releaseAway(page: Page) {
  await page.mouse.move(0, 0);
  await page.mouse.up();
}

test("press feedback leaves disabled controls and writing tools steady", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.goto("/");
  const upload = page.getByRole("button", {
    name: "Upload document",
    exact: true,
  });
  await hold(page, upload);
  await expect(upload).toHaveCSS("scale", "0.96");
  await releaseAway(page);
  await expect(upload).toHaveCSS("scale", "none");

  const create = page.getByRole("button", { name: "Create task", exact: true });
  await expect(create).toBeDisabled();
  await hold(page, create);
  await expect(create).toHaveCSS("scale", "none");
  await releaseAway(page);

  await page.goto("/actions");
  await page.getByRole("button", { name: /New proposal/ }).click();
  const bold = page.getByRole("button", { name: "Bold", exact: true });
  await hold(page, bold);
  await expect(bold).toHaveCSS("scale", "none");
  await page.mouse.up();
  await expect(bold).toHaveAttribute("aria-pressed", "true");
});

test("a popup can reverse its exit and still dismiss with focus restored", async ({
  page,
}) => {
  await page.goto("/");
  const trigger = page.getByRole("button", { name: "Appearance", exact: true });
  const popup = page.locator('[data-slot="popover-content"]');
  await trigger.click();
  await expect(popup).toBeVisible();
  // Close and reopen while the exit is still in flight.
  await trigger.evaluate(async (button: HTMLButtonElement) => {
    button.click();
    await new Promise<void>((resolve) =>
      requestAnimationFrame(() => resolve()),
    );
    await new Promise<void>((resolve) =>
      requestAnimationFrame(() => resolve()),
    );
    button.click();
  });
  await page.waitForTimeout(250);
  await expect(popup).toHaveCount(1);
  await expect(popup).toHaveCSS("opacity", "1");
  await page.keyboard.press("Escape");
  await expect(popup).toHaveCount(0);
  await expect(trigger).toBeFocused();
  await expect(page.locator("body")).not.toHaveCSS("pointer-events", "none");
});

test("accent changes commit without starting page-wide color transitions", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Appearance", exact: true }).click();
  await page.getByRole("button", { name: "Light theme", exact: true }).click();
  await page.getByRole("button", { name: "Blue", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-palette", "blue");
  const colorTransitions = await page.evaluate(
    () =>
      document
        .getAnimations()
        .filter(
          (animation) =>
            animation instanceof CSSTransition &&
            /color|background|border|shadow/.test(animation.transitionProperty),
        ).length,
  );
  expect(colorTransitions).toBe(0);
  await page.keyboard.press("Escape");
  await expect(page.locator('[data-slot="popover-content"]')).toHaveCount(0);
  // The suppression stylesheet is transient, so later interactions still respond.
  await expect(
    page.getByRole("button", { name: "Upload document", exact: true }),
  ).toHaveCSS("transition-duration", "0.15s");
});

test("reduced motion keeps press feedback still and sheets dismissible", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  const upload = page.getByRole("button", {
    name: "Upload document",
    exact: true,
  });
  await hold(page, upload);
  await expect(upload).toHaveCSS("scale", "none");
  await releaseAway(page);
  const toggle = page.getByRole("button", { name: "Toggle Sidebar" });
  await toggle.click();
  await expect(
    page.getByRole("navigation", { name: "Main navigation" }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(
    page.locator('[data-sidebar="sidebar"][data-mobile="true"]'),
  ).toHaveCount(0);
  await expect(toggle).toBeFocused();
});
