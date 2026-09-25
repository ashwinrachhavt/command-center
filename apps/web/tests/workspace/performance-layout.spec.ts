import { expect, test } from "@playwright/test";

test("short chat viewports keep Send visible while long drafts scroll in the field", async ({
  page,
}) => {
  for (const viewport of [
    { width: 720, height: 450 },
    { width: 320, height: 568 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto("/agents");
    const message = page.getByRole("textbox", { name: "Message your agent" });
    await expect(
      page.getByRole("heading", { name: "What would you like to work on?" }),
    ).toBeInViewport({ ratio: 1 });
    await message.fill("Keep this long synthetic draft readable. ".repeat(100));
    await expect(
      page.getByRole("button", { name: "Run agent", exact: true }),
    ).toBeInViewport({ ratio: 1 });
    expect(
      await message.evaluate(
        (element) => element.scrollHeight > element.clientHeight,
      ),
    ).toBe(true);
    expect(
      await page.evaluate(() => document.documentElement.scrollHeight),
    ).toBeLessThanOrEqual(viewport.height);
  }
});

test("the editor engine is requested only when a writing surface opens", async ({
  page,
}) => {
  const requests: string[] = [];
  page.on("request", (request) => requests.push(request.url()));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Briefing", exact: true }),
  ).toBeVisible();
  expect(requests.some((url) => url.includes("/tiptap-writer"))).toBe(false);
  await page.goto("/actions");
  await page.getByRole("button", { name: /New proposal/ }).click();
  await expect(
    page.getByRole("button", { name: "Bold", exact: true }),
  ).toBeVisible();
  expect(requests.some((url) => url.includes("/tiptap-writer"))).toBe(true);
});

test("workspace search sends one parallel request group after typing pauses", async ({
  page,
}) => {
  await page.goto("/");
  await page.evaluate(() => {
    const target = window as typeof window & { searchRequests: string[] };
    target.searchRequests = [];
    const original = window.fetch;
    window.fetch = (input, init) => {
      const url = String(input);
      if (/\/api\/backend\/(companies|contacts|opportunities)\?q=/.test(url)) {
        target.searchRequests.push(url);
      }
      return original(input, init);
    };
  });
  await page
    .getByRole("button", { name: "Search workspace", exact: true })
    .click();
  await page
    .getByRole("textbox", { name: "Search your workspace", exact: true })
    .pressSequentially("Northstar", { delay: 15 });
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          (window as typeof window & { searchRequests: string[] })
            .searchRequests.length,
      ),
    )
    .toBe(3);
  const requests = await page.evaluate(
    () =>
      (window as typeof window & { searchRequests: string[] }).searchRequests,
  );
  expect(requests.every((url) => url.includes("q=Northstar&limit=5"))).toBe(
    true,
  );
});

test("all task views and long actions remain inside a 320px workspace", async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 700 });
  await page.goto("/");
  const waiting = page.getByRole("tab", { name: /^Waiting/ });
  const bounds = await waiting.boundingBox();
  expect(bounds).not.toBeNull();
  expect(bounds!.x).toBeGreaterThanOrEqual(16);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(304);
  await waiting.click();
  await expect(
    page.getByText("Wait for interview availability", { exact: true }),
  ).toBeVisible();
  for (const route of ["/browser", "/memory"]) {
    await page.goto(route);
    await expect(page.locator("h1")).toBeVisible();
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
      .toBeLessThanOrEqual(320);
  }
});

test("RTL navigation docks at the leading edge and tabs use RTL keyboard order", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");
  await page.evaluate(() => {
    document.documentElement.dir = "rtl";
  });
  const sidebar = page.locator('[data-slot="sidebar-container"]');
  await expect.poll(async () => (await sidebar.boundingBox())!.x).toBe(1056);
  const tabs = page.getByRole("tablist", { name: "Task views" });
  await expect(tabs).toHaveCSS("direction", "rtl");
  await page.getByRole("tab", { name: /^Today/ }).focus();
  await page.keyboard.press("ArrowLeft");
  await expect(page.getByRole("tab", { name: /^Upcoming/ })).toBeFocused();
});

test("wide tables expose a scroll cue and their actions remain reachable", async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 700 });
  await page.goto("/companies");
  const table = page.getByRole("region", { name: "Scrollable table" });
  await expect(table).toBeVisible();
  await expect(
    page.getByText("Scroll horizontally to see all columns."),
  ).toBeVisible();
  const open = page.getByRole("button", {
    name: "Open Northstar",
    exact: true,
  });
  await open.focus();
  await expect(open).toBeInViewport();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/record=company-1/);
});

test("long labels wrap without hiding actions on narrow screens", async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 800 });
  for (const route of [
    "/",
    "/agents",
    "/contacts",
    "/agent-settings",
    "/memory",
    "/activity",
  ]) {
    await page.goto(route);
    await expect(page.locator("h1")).toBeVisible();
    await page.evaluate(() => {
      const nodes: Text[] = [];
      const walker = document.createTreeWalker(
        document.body,
        NodeFilter.SHOW_TEXT,
      );
      let node: Node | null;
      while ((node = walker.nextNode())) {
        if (
          node.parentElement?.closest("button,h1,h2") &&
          !node.parentElement.closest("svg,.sr-only") &&
          /[a-z]/i.test(node.textContent ?? "")
        ) {
          nodes.push(node as Text);
        }
      }
      for (const text of nodes)
        text.textContent = `⟦${text.textContent?.trim()} · erweiterte Beschriftung⟧`;
    });
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(320);
    const clippedActions = await page
      .locator("main button")
      .evaluateAll((buttons) =>
        buttons
          .filter((button) => !button.closest('[data-slot="table-container"]'))
          .filter((button) => {
            const rect = button.getBoundingClientRect();
            return rect.width && (rect.x < -1 || rect.right > innerWidth + 1);
          })
          .map(
            (button) => button.getAttribute("aria-label") ?? button.textContent,
          ),
      );
    expect(clippedActions, route).toEqual([]);
  }
});
