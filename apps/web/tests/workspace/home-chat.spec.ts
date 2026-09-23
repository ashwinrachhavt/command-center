import { expect, test } from "@playwright/test";

test("Home streams a URL-selected conversation while typing stays responsive", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    // next-themes injects its initial theme script in this client-only Vite
    // preview; React warns that it cannot execute that SSR initialization.
    if (
      message.type() === "error" &&
      !message
        .text()
        .startsWith("Encountered a script tag while rendering React component.")
    )
      errors.push(message.text());
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/?session=session-stream&smooth_stream=1");
  await expect(page).toHaveTitle(/Command Center/);
  await expect(
    page.getByRole("heading", { name: "Home", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Steady reply" }),
  ).toBeVisible();
  const draft = page.getByRole("textbox", { name: "Message your agent" });
  await draft.fill("Keep this next instruction while the answer streams.");
  await expect(draft).toHaveValue(
    "Keep this next instruction while the answer streams.",
  );
  await page.screenshot({ path: "/tmp/command-center-chat-home-desktop.png" });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(draft).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(
    390,
  );
  await page.screenshot({ path: "/tmp/command-center-chat-home-mobile.png" });
  expect(errors).toEqual([]);
});

test("Home reopens saved questions and can cancel a paused run", async ({
  page,
}) => {
  await page.goto("/?session=session-question");
  await expect(
    page.getByRole("form", { name: "Research needs your answer" }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("form", { name: "Research needs your answer" }),
  ).toBeVisible();
  await expect(page.getByText("This run was cancelled.")).toHaveCount(0);
  await page.getByRole("button", { name: "Cancel work" }).click();
  await expect(
    page.getByText(
      "Cancelled. Completed activity remains in this conversation.",
    ),
  ).toBeVisible();
});

test("local client token is copyable once, hideable and revocable", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/settings");
  await page
    .getByRole("textbox", { name: "Client name" })
    .fill("Synthetic desktop client");
  await page.getByRole("button", { name: "Create token" }).click();
  await expect(
    page.getByRole("textbox", { name: "New local client token" }),
  ).toHaveValue("synthetic-preview-token");
  await page.evaluate(() =>
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: {
        writeText: async () => {
          throw new Error("Synthetic denied clipboard");
        },
      },
    }),
  );
  await page.getByRole("button", { name: "Copy token" }).click();
  await expect(
    page.getByText("Copy failed. Select the token and copy it manually."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Hide token" }).click();
  await expect(
    page.getByRole("textbox", { name: "New local client token" }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "Revoke Synthetic desktop client" })
    .click();
  await expect(page.getByText("Revoked", { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});
