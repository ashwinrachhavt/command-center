import { expect, test, type Page } from "@playwright/test";

type RequestRecord = {
  route: string;
  method: string;
  key: string;
  body?: Record<string, unknown>;
};

async function requests(page: Page): Promise<RequestRecord[]> {
  return page.evaluate(async () =>
    (await fetch("/api/backend/test/briefing-requests")).json(),
  );
}

async function savedTasks(page: Page, title: string) {
  return page.evaluate(async (query) => {
    const result = await fetch(
      `/api/backend/tasks?q=${encodeURIComponent(query)}`,
    );
    return result.json() as Promise<{
      items: { id: string; title: string; rationale: string; state: string }[];
    }>;
  }, title);
}

for (const width of [1440, 390]) {
  test(`Briefing opens saved work without starting agents or connectors at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("console", (message) => {
      // This Vite-only harness mounts next-themes' SSR initialization script.
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
    await page.goto("/");
    for (const title of [
      "Briefing",
      "Capture something",
      "What matters today",
      "Needs a decision",
      "Running",
      "Recent outputs",
      "What changed",
    ])
      await expect(
        page.getByRole("heading", { name: new RegExp(`^${title}`) }),
      ).toBeVisible();
    await expect(
      page.getByRole("button", {
        name: "Prepare for the technical conversation",
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Create task", exact: true }),
    ).toBeDisabled();
    await expect(
      page.getByRole("button", { name: "Upload document", exact: true }),
    ).toBeVisible();
    const reads = await requests(page);
    expect(reads.length).toBeGreaterThan(0);
    expect(reads.every((request) => request.method === "GET")).toBe(true);
    expect(
      reads.some(({ route }) =>
        /agents\/|agent-runs|agent-sessions|integrations|connections|gmail|research\//.test(
          route,
        ),
      ),
    ).toBe(false);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBe(width);
    await expect(page.locator("vite-error-overlay")).toHaveCount(0);
    await page.screenshot({
      path: `/tmp/command-center-briefing-${width === 1440 ? "desktop" : "mobile"}.png`,
      fullPage: true,
    });
    await page
      .getByRole("link", { name: "Ask assistant", exact: true })
      .click();
    await expect(page).toHaveURL(/\/agents$/);
    await expect(
      page.getByRole("heading", { name: "Assistant", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("textbox", { name: "Message your agent" }),
    ).toBeInViewport();
    if (width < 768)
      await page.getByRole("button", { name: "Toggle Sidebar" }).click();
    const navigation = page.getByRole("navigation", {
      name: "Main navigation",
    });
    await expect(
      navigation.getByRole("link", { name: "Assistant", exact: true }),
    ).toHaveAttribute("href", "/agents");
    await navigation
      .getByRole("link", { name: "Briefing", exact: true })
      .click();
    await expect(page).toHaveURL(/\/$/);
    await expect(
      page.getByRole("heading", { name: "Briefing", exact: true }),
    ).toBeVisible();
    expect(errors).toEqual([]);
  });
}

test("capture preserves context, opens the task alongside Briefing and completes it", async ({
  page,
}) => {
  await page.goto("/");
  const title = "Prepare a synthetic interview brief";
  const content = `  ${title}\nReview the platform roadmap and https://example.com/role.\nKeep this full context.  `;
  const capture = page.getByRole("textbox", {
    name: "What would you like to move forward?",
  });
  await capture.fill("   ");
  await expect(
    page.getByRole("button", { name: "Create task", exact: true }),
  ).toBeDisabled();
  await capture.fill(content);
  await page.getByRole("button", { name: "Create task", exact: true }).click();
  await expect(
    page.getByRole("status").filter({ hasText: `Captured: ${title}` }),
  ).toBeVisible();
  await expect(capture).toHaveValue("");
  const saved = await savedTasks(page, title);
  expect(saved.items).toHaveLength(1);
  expect(saved.items[0]).toMatchObject({
    title,
    rationale: content,
    state: "open",
  });
  expect(
    (await requests(page)).find(
      ({ route, method }) => route === "tasks" && method === "POST",
    )?.body,
  ).toEqual({ title, rationale: content, priority: 1 });
  await page.getByRole("button", { name: "Open task", exact: true }).click();
  await expect(page).toHaveURL(
    new RegExp(
      `inspect=tasks%3A${saved.items[0].id}|inspect=tasks:${saved.items[0].id}`,
    ),
  );
  await expect(
    page.getByRole("heading", { name: title, exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Briefing", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Close related workspace" }).click();
  await page.getByRole("tab", { name: /^Unscheduled/ }).click();
  await page
    .getByRole("button", { name: `Complete ${title}`, exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: title, exact: true }),
  ).toHaveCount(0);
  expect((await savedTasks(page, title)).items[0]).toMatchObject({
    rationale: content,
    state: "done",
  });
});

test("document upload opens in place without submitting work", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Upload document", exact: true })
    .click();
  await expect(
    page.getByRole("dialog", { name: "Upload documents", exact: true }),
  ).toBeVisible();
  await expect(page).toHaveURL(/\/$/);
  expect((await requests(page)).every(({ method }) => method === "GET")).toBe(
    true,
  );
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("dialog", { name: "Upload documents", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "Briefing", exact: true }),
  ).toBeVisible();
});

test("capture retries an uncertain response with the same key and one saved task", async ({
  page,
}) => {
  await page.goto("/?capture_retry=1");
  const content =
    "Retain a synthetic capture\nThe full context survives an uncertain response.";
  const capture = page.getByRole("textbox", {
    name: "What would you like to move forward?",
  });
  await capture.fill(content);
  await page.getByRole("button", { name: "Create task", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Your text is still here; try again.",
  );
  await expect(capture).toHaveValue(content);
  await page.getByRole("button", { name: "Create task", exact: true }).click();
  await expect(
    page
      .getByRole("status")
      .filter({ hasText: "Captured: Retain a synthetic capture" }),
  ).toBeVisible();
  const writes = (await requests(page)).filter(
    ({ route, method }) => route === "tasks" && method === "POST",
  );
  expect(writes).toHaveLength(3);
  expect(writes[0].key).not.toBe("");
  expect(new Set(writes.map(({ key }) => key)).size).toBe(1);
  expect(
    (await savedTasks(page, "Retain a synthetic capture")).items,
  ).toHaveLength(1);
});

test("waiting work stays separate until explicitly resumed", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("tab", { name: /^Waiting/ }).click();
  await expect(
    page.getByRole("button", {
      name: "Wait for interview availability",
      exact: true,
    }),
  ).toBeVisible();
  await page
    .getByRole("button", {
      name: "Resume Wait for interview availability",
      exact: true,
    })
    .click();
  await expect(
    page.getByText("No waiting tasks", { exact: true }),
  ).toBeVisible();
  await page.getByRole("tab", { name: /^Unscheduled/ }).click();
  await expect(
    page.getByRole("button", {
      name: "Wait for interview availability",
      exact: true,
    }),
  ).toBeVisible();
  expect(
    (await savedTasks(page, "Wait for interview availability")).items[0].state,
  ).toBe("in_progress");
  expect(
    (await requests(page)).filter(({ method }) => method !== "GET"),
  ).toEqual([
    { route: "tasks/task-waiting", method: "PATCH", key: expect.any(String) },
  ]);
});
