import { expect, test } from "@playwright/test";

for (const viewport of [
  { width: 1600, height: 1000 },
  { width: 390, height: 844 },
]) {
  test(`sidebar opens full pages while body links retain context at ${viewport.width}px`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto("/");
    for (const [name, route] of [
      ["Contacts", "contacts"],
      ["Companies", "companies"],
      ["Opportunities", "opportunities"],
    ]) {
      if (viewport.width < 768)
        await page.getByRole("button", { name: "Toggle Sidebar" }).click();
      await page
        .getByRole("navigation", { name: "Main navigation" })
        .getByRole("link", { name, exact: true })
        .click();
      await expect(page).toHaveURL(new RegExp(`/${route}$`));
      await expect(
        page.getByRole("heading", { name, exact: true }),
      ).toBeVisible();
      await expect(
        page.getByLabel("Related workspace", { exact: true }),
      ).toHaveCount(0);
      await expect(
        page.getByRole("textbox", { name: `Search ${route}` }),
      ).toBeVisible();
    }
    await page
      .getByRole("button", { name: /Staff Product Engineer Build/ })
      .click();
    await page.getByRole("tab", { name: "Contacts", exact: true }).click();
    await page.getByRole("button", { name: "Open linked contact" }).click();
    await expect(page).toHaveURL(
      /\/opportunities\?record=opportunity-1&inspect=contacts/,
    );
    await expect(
      page.getByRole("heading", { name: "Alex Morgan" }),
    ).toBeVisible();
    const history = page.getByRole("region", {
      name: "Imported contact history",
    });
    await expect(
      history.getByText("01 Jan 2025", { exact: true }),
    ).toBeVisible();
    await expect(
      history.getByText("Source row 1", { exact: false }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Close related workspace" }).click();
    await expect(
      page.getByRole("heading", { name: "Staff Product Engineer" }),
    ).toBeVisible();
    if (viewport.width < 768)
      await page.getByRole("button", { name: "Toggle Sidebar" }).click();
    await page
      .getByRole("navigation", { name: "Main navigation" })
      .getByRole("link", { name: "Briefing", exact: true })
      .click();
    await expect(page).toHaveURL(/\/$/);
    expect(errors).toEqual([]);
  });
}

test("AI Elements renders a saved run with formatted text", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/agents");
  await page.getByText("Earlier runs", { exact: true }).click();
  await page.getByRole("button", { name: /Northstar research/ }).click();
  await expect(
    page.getByRole("heading", { name: "Company brief" }),
  ).toBeVisible();
  await expect(
    page.getByText("Northstar builds developer tools."),
  ).toBeVisible();
  await expect(
    page
      .getByRole("listitem")
      .filter({ hasText: "Ask about the platform roadmap." }),
  ).toBeVisible();
  await expect(page.getByText("**Northstar**", { exact: true })).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("related records preserve selection, search, tabs, and browser history", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1600, height: 1000 });
  await page.goto("/opportunities");
  await page
    .getByRole("textbox", { name: "Search opportunities" })
    .fill("Staff");
  await page
    .getByRole("button", { name: /Staff Product Engineer Build/ })
    .click();
  await page.getByRole("tab", { name: "Contacts", exact: true }).click();
  await page
    .getByRole("button", { name: "Browse contacts", exact: true })
    .click();
  await expect(page).toHaveURL(
    /\/opportunities\?record=opportunity-1&inspect=contacts/,
  );
  await page.getByRole("button", { name: "Alex Morgan" }).click();
  await page.getByRole("button", { name: "View company" }).click();
  await expect(
    page.getByRole("heading", { name: "Northstar", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Staff Product Engineer" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Back to previous context" }).click();
  await expect(
    page.getByRole("heading", { name: "Alex Morgan" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Close related workspace" }).click();
  await expect(
    page.getByRole("complementary", { name: "Related workspace" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("textbox", { name: "Search opportunities" }),
  ).toHaveValue("Staff");
  await expect(
    page.getByRole("tab", { name: "Contacts", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await page.goBack();
  await expect(
    page.getByRole("heading", { name: "Alex Morgan" }),
  ).toBeVisible();
});

test("appearance choices persist and system mode follows the device", async ({
  page,
}) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/opportunities?record=opportunity-1");
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.getByRole("button", { name: "Appearance", exact: true }).click();
  await page.getByRole("button", { name: "Light theme" }).click();
  await page.getByRole("button", { name: "Teal", exact: true }).click();
  await expect(page.locator("html")).not.toHaveClass(/dark/);
  await expect(page.locator("html")).toHaveAttribute("data-palette", "teal");
  await page.reload();
  await expect(page.locator("html")).not.toHaveClass(/dark/);
  await expect(page.locator("html")).toHaveAttribute("data-palette", "teal");
  await page.getByRole("button", { name: "Appearance", exact: true }).click();
  await page.getByRole("button", { name: "System theme" }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.emulateMedia({ colorScheme: "light" });
  await expect(page.locator("html")).not.toHaveClass(/dark/);
});

test("mobile keeps an explicit origin and returns focus after closing", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/opportunities?record=opportunity-1");
  await page.getByRole("tab", { name: "Contacts", exact: true }).click();
  const trigger = page.getByRole("button", { name: "Open linked contact" });
  await trigger.click();
  await expect(page.getByText("Alongside opportunities")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Alex Morgan" }),
  ).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(
    390,
  );
  await page.keyboard.press("Escape");
  await expect(trigger).toBeFocused();
  await expect(
    page.getByRole("heading", { name: "Staff Product Engineer" }),
  ).toBeVisible();
});

test("an unavailable related record leaves the parent usable", async ({
  page,
}) => {
  await page.goto(
    "/opportunities?record=opportunity-1&inspect=contacts:missing",
  );
  await expect(page.getByRole("alert")).toContainText("Record not found");
  await page.getByRole("button", { name: "Close related workspace" }).click();
  await expect(
    page.getByRole("heading", { name: "Staff Product Engineer" }),
  ).toBeVisible();
});

test("all appearance palettes keep readable text in both modes", async ({
  page,
}) => {
  await page.goto("/opportunities");
  await page.getByRole("button", { name: "Appearance", exact: true }).click();
  for (const mode of ["Light", "Dark"]) {
    await page.getByRole("button", { name: `${mode} theme` }).click();
    for (const palette of ["Graphite", "Teal", "Blue", "Violet"]) {
      await page.getByRole("button", { name: palette, exact: true }).click();
      const contrasts = await page.evaluate(() => {
        const css = getComputedStyle(document.documentElement);
        const luminance = (token: string) => {
          const hex = css.getPropertyValue(token).trim().slice(1);
          const channels = [0, 2, 4]
            .map((offset) => parseInt(hex.slice(offset, offset + 2), 16) / 255)
            .map((channel) =>
              channel <= 0.04045
                ? channel / 12.92
                : ((channel + 0.055) / 1.055) ** 2.4,
            );
          return (
            channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722
          );
        };
        return [
          ["--foreground", "--background"],
          ["--muted-foreground", "--background"],
          ["--primary-foreground", "--primary"],
        ].map(
          ([a, b]) =>
            (Math.max(luminance(a), luminance(b)) + 0.05) /
            (Math.min(luminance(a), luminance(b)) + 0.05),
        );
      });
      for (const contrast of contrasts)
        expect(contrast, `${mode} ${palette}`).toBeGreaterThanOrEqual(4.5);
    }
  }
});
