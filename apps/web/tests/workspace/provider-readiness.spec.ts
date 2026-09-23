import { expect, test } from "@playwright/test";

test("a ready Gemini profile runs without OpenAI", async ({ page }) => {
  await page.goto("/agents");

  await expect(page.getByText("Gemini · Synthetic preview")).toBeVisible();
  await page
    .getByRole("textbox", { name: "Message your agent" })
    .fill("Run this synthetic Gemini request.");
  const run = page.getByRole("button", { name: "Run agent" });
  await expect(run).toBeEnabled();
  await run.click();
  await expect(
    page.getByText("Message saved to your conversation"),
  ).toBeVisible();
});

test("a mixed profile stays blocked when a specialist provider is missing", async ({
  page,
}) => {
  await page.goto("/agents");

  await page.getByRole("combobox", { name: "Choose agent" }).click();
  await page
    .getByRole("option", { name: "Mixed provider profile · setup required" })
    .click();
  await page
    .getByRole("textbox", { name: "Message your agent" })
    .fill("This request must remain blocked.");

  await expect(page.getByRole("button", { name: "Run agent" })).toBeDisabled();
  await expect(
    page.getByText(/Configure MISTRAL_API_KEY to start/),
  ).toBeVisible();
});

test("settings shows each server-side model provider status", async ({
  page,
}) => {
  await page.goto("/settings");

  for (const name of ["OpenAI", "Gemini", "Mistral", "Cohere"]) {
    await expect(
      page.getByRole("heading", { name, exact: true }),
    ).toBeVisible();
  }
  await expect(
    page
      .getByRole("heading", { name: "Gemini", exact: true })
      .locator("..")
      .locator("..")
      .getByText("Configured", { exact: true }),
  ).toBeVisible();
});
