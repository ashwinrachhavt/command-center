import { expect, test } from "@playwright/test";
import { tmpdir } from "node:os";
import { join } from "node:path";

for (const viewport of [
  { width: 1440, height: 1000 },
  { width: 390, height: 844 },
]) {
  test(`composer model picker searches and preserves selection at ${viewport.width}px`, async ({
    page,
  }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("console", (message) => {
      // next-themes' SSR script produces this known client-only preview warning.
      if (
        message.type() === "error" &&
        !message
          .text()
          .startsWith(
            "Encountered a script tag while rendering React component.",
          )
      )
        errors.push(message.text());
    });
    await page.setViewportSize(viewport);
    await page.goto("/agents");
    await expect(page).toHaveTitle(/Command Center/);
    const picker = page.getByRole("button", { name: "Switch AI model" });
    const actions = page.getByRole("group", { name: "Message actions" });
    await expect(
      actions.getByRole("button", { name: "Switch AI model" }),
    ).toBeVisible();
    const inputBox = (await page
      .getByRole("textbox", { name: "Message your agent" })
      .boundingBox())!;
    const pickerBox = (await picker.boundingBox())!;
    const sendBox = (await actions
      .getByRole("button", { name: "Run agent" })
      .boundingBox())!;
    expect(pickerBox.y).toBeGreaterThanOrEqual(inputBox.y + inputBox.height);
    expect(pickerBox.x + pickerBox.width).toBeLessThanOrEqual(sendBox.x);
    await picker.focus();
    await picker.press("Enter");
    const menu = page.getByRole("dialog");
    await expect(menu).toBeVisible();
    expect((await menu.boundingBox())!.y).toBeLessThan(pickerBox.y);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(viewport.width);
    await expect(
      page.getByRole("button", { name: /Synthetic Embedding/ }),
    ).toBeDisabled();
    await page.screenshot({
      path: join(tmpdir(), `command-center-model-picker-${viewport.width}.png`),
      animations: "disabled",
    });
    await page.getByRole("textbox", { name: "Search models" }).fill("pro");
    await expect(
      page.getByRole("button", { name: "Synthetic Flash", exact: true }),
    ).toHaveCount(0);
    await page.getByRole("button", { name: /Synthetic Pro/ }).click();
    await expect(picker).toContainText("gemini-synthetic-pro");
    await picker.click();
    await page.getByRole("button", { name: "Refresh models" }).click();
    await expect(
      page.getByRole("button", { name: /Synthetic Pro/ }),
    ).toHaveAttribute("aria-pressed", "true");
    await page.keyboard.press("Escape");
    await expect(picker).toBeFocused();
    await picker.press("Enter");
    await page.getByRole("tab", { name: "Cohere" }).click();
    await expect(
      page.getByText("Cohere API key is not configured."),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: /Synthetic Pro/ }),
    ).toHaveCount(0);
    await page.getByRole("tab", { name: "Gemini" }).click();
    const longModel = "synthetic-very-long-custom-model-".repeat(4).slice(0, 100);
    await page
      .getByRole("textbox", { name: "Custom model ID" })
      .fill(longModel);
    await page.getByRole("button", { name: "Use", exact: true }).click();
    await expect(picker).toContainText(longModel);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(viewport.width);
    const longBox = (await picker.boundingBox())!;
    const finalSend = (await actions
      .getByRole("button", { name: "Run agent" })
      .boundingBox())!;
    expect(longBox.x + longBox.width).toBeLessThanOrEqual(finalSend.x);
    expect(errors).toEqual([]);
  });
}
