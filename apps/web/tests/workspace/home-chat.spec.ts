import { expect, test } from "@playwright/test";

for (const viewport of [
  { width: 1440, height: 760 },
  { width: 1280, height: 540 },
  { width: 390, height: 844 },
]) {
  test(`long messages and composer fit the viewport at ${viewport.width}x${viewport.height}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await page.goto("/?session=session-opportunity-1&long_chat=1");
    const messages = page.getByRole("region", {
      name: "Conversation messages",
      exact: true,
    });
    const finalLine = page.getByText("Final line of the saved response.", {
      exact: true,
    });
    await expect(finalLine).toBeAttached();
    await messages.focus();
    await page.keyboard.press("Home");
    await expect
      .poll(() => messages.evaluate((element) => element.scrollTop))
      .toBe(0);
    await expect(page.getByText(/Start of pasted source/)).toBeInViewport();
    await page.keyboard.press("End");
    await finalLine.scrollIntoViewIfNeeded();
    await expect(finalLine).toBeInViewport();
    const geometry = await messages.evaluate((element) => {
      let scrollParents = 0;
      for (
        let parent = element.parentElement;
        parent;
        parent = parent.parentElement
      ) {
        if (
          /auto|scroll/.test(getComputedStyle(parent).overflowY) &&
          parent.scrollHeight > parent.clientHeight + 1
        )
          scrollParents++;
      }
      return {
        scrollParents,
        bottom: element.getBoundingClientRect().bottom,
        height: element.clientHeight,
        pageHeight: document.documentElement.scrollHeight,
        pageWidth: document.documentElement.scrollWidth,
      };
    });
    const composer = page.getByRole("form", { name: "Chat composer" });
    const composerBox = (await composer.boundingBox())!;
    expect(geometry.scrollParents).toBe(0);
    expect(geometry.height).toBeGreaterThan(100);
    expect(geometry.bottom).toBeLessThanOrEqual(composerBox.y + 1);
    expect(composerBox.y + composerBox.height).toBeLessThanOrEqual(
      viewport.height + 1,
    );
    expect(geometry.pageHeight).toBeLessThanOrEqual(viewport.height + 1);
    expect(geometry.pageWidth).toBe(viewport.width);
    const draft = page.getByRole("textbox", { name: "Message your agent" });
    await draft.fill("A long pasted draft.\n".repeat(80));
    expect((await draft.boundingBox())!.height).toBeLessThanOrEqual(161);
    expect((await messages.boundingBox())!.height).toBeGreaterThan(80);
    await draft.fill("Keep my next instruction.");
    await page.screenshot({
      path: `/tmp/command-center-chat-layout-${viewport.width}-${viewport.height}.png`,
    });
  });
}

test("both desktop sidebars collapse independently and remember their state", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/?session=session-opportunity-1");
  const messages = page.getByRole("region", {
    name: "Conversation messages",
    exact: true,
  });
  const chats = page.getByRole("button", {
    name: "Toggle conversation history",
  });
  const nav = page.getByRole("button", { name: "Toggle Sidebar" });
  const draft = page.getByRole("textbox", { name: "Message your agent" });
  await draft.fill("Keep this draft while collapsing panels.");
  const before = (await messages.boundingBox())!.width;
  await chats.click();
  await expect(chats).toHaveAttribute("aria-expanded", "false");
  await expect(
    page.getByRole("complementary", { name: "Conversation history" }),
  ).toHaveCount(0);
  await nav.click();
  await expect(nav).toHaveAttribute("aria-expanded", "false");
  await expect
    .poll(async () => (await messages.boundingBox())!.width)
    .toBeGreaterThan(before + 400);
  await expect(draft).toHaveValue("Keep this draft while collapsing panels.");
  await page.reload();
  await expect(chats).toHaveAttribute("aria-expanded", "false");
  await expect(nav).toHaveAttribute("aria-expanded", "false");
  await expect(page).toHaveURL(/session=session-opportunity-1/);
  await chats.click();
  await nav.click();
  await expect(
    page.getByRole("complementary", { name: "Conversation history" }),
  ).toBeVisible();
  await expect(
    page.getByRole("navigation", { name: "Main navigation" }),
  ).toBeInViewport();
});

test("mobile conversation history opens as a drawer and returns focus on close", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/?session=session-question");
  const chats = page.getByRole("button", {
    name: "Toggle conversation history",
  });
  await expect(chats).toHaveAttribute("aria-expanded", "false");
  await chats.click();
  const drawer = page.getByRole("dialog", {
    name: "Conversations",
    exact: true,
  });
  await expect(drawer).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(drawer).toHaveCount(0);
  await expect(chats).toBeFocused();
  await expect(
    page.getByRole("textbox", { name: "Message your agent" }),
  ).toBeInViewport();
});

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
