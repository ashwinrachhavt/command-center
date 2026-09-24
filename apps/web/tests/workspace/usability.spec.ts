import { expect, test } from "@playwright/test";

test("recording a review updates the Library badge without a reload", async ({
  page,
}) => {
  await page.goto("/library?view=generated");
  const memo = page.getByRole("button", { name: /Platform research memo/ });
  await expect(memo).toContainText("Needs review");
  await memo.click();
  const reader = page.getByRole("dialog", {
    name: "Related workspace",
    exact: true,
  });
  await reader
    .getByRole("textbox", { name: "Review reason", exact: true })
    .fill("Checked the sources and next steps.");
  await reader
    .getByRole("button", { name: "Record review", exact: true })
    .click();
  await expect(
    page.getByText("Review recorded for this version", { exact: true }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(memo).toContainText("Approved");
});

test("a generated binary remains downloadable without an upload record", async ({
  page,
}) => {
  await page.goto("/library?binary-generated=1");
  await page.getByRole("button", { name: /Platform research memo/ }).click();
  const reader = page.getByRole("dialog", {
    name: "Related workspace",
    exact: true,
  });
  const completed = page.waitForEvent("download");
  await reader
    .getByRole("button", {
      name: "Download Platform research memo",
      exact: true,
    })
    .click();
  const download = await completed;
  expect(await download.failure()).toBeNull();
  expect(download.suggestedFilename()).toBe("synthetic-document.txt");
});

test("Notes ignores collection filters that are hidden in its writing view", async ({
  page,
}) => {
  await page.goto("/library");
  await page.getByRole("combobox", { name: "Review status filter" }).click();
  await page.getByRole("option", { name: "Approved", exact: true }).click();
  await page
    .getByRole("navigation", { name: "Library collections" })
    .getByRole("link", { name: "Notes", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: /Northstar · interview notes/ }),
  ).toBeVisible();
});

test("Assistant opens agent work with a visible composer and consolidated navigation", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.goto("/agents");
  await expect(
    page.getByRole("heading", { name: "Assistant", exact: true }),
  ).toBeVisible();
  const composer = page.getByRole("textbox", { name: "Message your agent" });
  await expect(composer).toBeVisible();
  const box = await composer.boundingBox();
  expect(box!.y + box!.height).toBeLessThanOrEqual(720);
  const navigation = page.getByRole("navigation", { name: "Main navigation" });
  for (const name of [
    "Applications",
    "Roles",
    "Jobs",
    "Reviewed actions",
    "Notes",
  ])
    await expect(
      navigation.getByRole("link", { name, exact: true }),
    ).toHaveCount(0);
  await navigation
    .getByRole("link", { name: "Opportunities", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "Opportunity views" })
    .getByRole("link", { name: "Applications", exact: true })
    .click();
  await expect(page).toHaveURL(/\/applications$/);
});

for (const width of [1440, 390]) {
  test(`structured artifacts remain readable at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/library?structured-generated=1");
    await page.getByRole("button", { name: /Platform research memo/ }).click();
    const reader = page.getByRole("dialog", {
      name: "Related workspace",
      exact: true,
    });
    await expect(
      reader.getByText("After the interview", { exact: true }),
    ).toBeVisible();
    await expect(reader.getByText("0", { exact: true })).toBeVisible();
    await expect(reader.getByText("No", { exact: true })).toBeVisible();
    await expect(reader.getByText("This version is empty.")).toHaveCount(0);
    expect(
      await reader.evaluate(
        (element) => element.scrollWidth <= element.clientWidth,
      ),
    ).toBe(true);
  });

  test(`Library separates originals and opens reviewable work in a readable canvas at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/library?view=generated");
    const memo = page.getByRole("button", { name: /Platform research memo/ });
    await expect(memo).toContainText("Needs review");
    await expect(
      page.getByRole("button", { name: /Synthetic resume/ }),
    ).toHaveCount(0);
    await memo.click();
    const reader = page.getByRole("dialog", {
      name: "Related workspace",
      exact: true,
    });
    await expect(
      reader.getByRole("heading", { name: "Platform research", exact: true }),
    ).toBeVisible();
    const box = await reader.boundingBox();
    expect(box!.width).toBeGreaterThan(width * 0.7);
    await page.keyboard.press("Escape");
    await expect(reader).toHaveCount(0);
    await expect(memo).toBeFocused();
    await page.goto("/documents");
    await expect(
      page.getByRole("heading", { name: "Document Vault", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: /Synthetic resume/ }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: /Platform research memo/ }),
    ).toHaveCount(0);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  });
}

test("agent configuration exposes current skills and links to real memory and connectors", async ({
  page,
}) => {
  await page.goto("/agent-settings");
  const navigation = page.getByRole("navigation", {
    name: "Agent configuration",
  });
  await navigation.getByRole("link", { name: "Skills", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Available skills" }),
  ).toBeVisible();
  await navigation
    .getByRole("link", { name: "Workflows", exact: true })
    .click();
  await expect(
    page.getByRole("link", { name: /Prepare an application/ }),
  ).toHaveAttribute("href", "/applications");
  await navigation.getByRole("link", { name: "Memory", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Workspace memory", exact: true }),
  ).toBeVisible();
  await navigation
    .getByRole("link", { name: "Connectors", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Connected apps", exact: true }),
  ).toBeVisible();
});
