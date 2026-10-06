import { expect, test } from "@playwright/test";

for (const width of [1440, 390]) {
  test(`LiveKit transcript keeps earlier messages reachable at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 760 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/agents");
    await page.evaluate(() => {
      const previous = window.fetch;
      window.fetch = async (input, init) => {
        const response = await previous(input, init);
        if (
          (init?.method && init.method !== "GET") ||
          !String(input).includes("/messages")
        )
          return response;
        const body = await response.json();
        if (!body.items?.length) return Response.json(body);
        body.items = Array.from({ length: 40 }, (_, index) => ({
          ...body.items[0],
          id: `scroll-message-${index}`,
          sequence: index + 1,
          author: index % 2 ? "assistant" : "user",
          content: `Saved message ${index + 1}. This synthetic conversation stays readable when the transcript grows.`,
        }));
        body.total = body.items.length;
        return Response.json(body);
      };
    });
    if (width < 768) {
      await page
        .getByRole("button", { name: "Toggle conversation history" })
        .click();
    }
    await page
      .getByRole("button", { name: /Staff Product Engineer conversation/ })
      .click();
    const viewport = page.getByRole("region", {
      name: "Conversation messages",
    });
    const first = page.getByText(/^Saved message 1\./);
    const last = page.getByText(/^Saved message 40\./);
    await expect(last).toBeInViewport();
    await viewport.focus();
    await viewport.press("Home");
    await expect(first).toBeInViewport();
    const latest = page.getByRole("button", {
      name: "Scroll to latest message",
    });
    await expect(latest).toBeVisible();
    await latest.focus();
    await latest.press("Enter");
    await expect(last).toBeInViewport();
    await expect(
      page.getByRole("textbox", { name: "Message your agent" }),
    ).toBeInViewport();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBe(width);
  });
}
