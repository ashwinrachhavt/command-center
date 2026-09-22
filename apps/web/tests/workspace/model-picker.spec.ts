import { expect, test } from "@playwright/test";

test("model picker searches live provider catalogs and preserves selection", async ({
  page,
}) => {
  await page.goto("/agents");
  const picker = page.getByRole("button", { name: "Switch AI model" });
  await picker.click();
  await expect(
    page.getByRole("button", { name: /Synthetic Embedding/ }),
  ).toBeDisabled();
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
  await page.getByRole("tab", { name: "Cohere" }).click();
  await expect(
    page.getByText("Cohere API key is not configured."),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: /Synthetic Pro/ })).toHaveCount(
    0,
  );
});
