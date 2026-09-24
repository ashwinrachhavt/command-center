import { expect, test } from "@playwright/test";

for (const width of [1440, 390]) {
  test(`Spaces retain purpose and linked context through archive and restore at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto("/spaces");
    await expect(
      page.getByRole("heading", { name: "Spaces", exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "New Space", exact: true }).click();
    await page
      .getByRole("textbox", { name: "Name", exact: true })
      .fill("Synthetic evidence review");
    await page
      .getByRole("textbox", { name: "Purpose", exact: true })
      .fill("Keep the question, evidence, and next step together.");
    await page
      .getByRole("button", { name: "Create Space", exact: true })
      .click();
    await expect(
      page.getByRole("heading", {
        name: "Synthetic evidence review",
        exact: true,
      }),
    ).toBeVisible();
    await page
      .getByRole("textbox", { name: "What would you like to move forward?" })
      .fill("Review the synthetic evidence\nPreserve this exact context.");
    await page
      .getByRole("button", { name: "Create task", exact: true })
      .click();
    await expect(
      page.getByRole("button", {
        name: "Review the synthetic evidence Task · Open",
        exact: true,
      }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Link existing record", exact: true })
      .click();
    const dialog = page.getByRole("dialog", {
      name: "Link an existing record",
    });
    await dialog.getByRole("combobox", { name: "Record type" }).click();
    await page.getByRole("option", { name: "Contacts", exact: true }).click();
    await dialog
      .getByRole("textbox", { name: "Search saved records" })
      .fill("Alex Morgan");
    await dialog
      .getByRole("button", { name: "Link Alex Morgan", exact: true })
      .click();
    await expect(
      dialog.getByRole("button", { name: "Alex Morgan already linked" }),
    ).toBeDisabled();
    await dialog.getByRole("button", { name: "Done", exact: true }).click();
    const contact = page.getByRole("button", {
      name: "Alex Morgan Contact",
      exact: true,
    });
    await expect(contact).toBeVisible();
    await contact.click();
    await expect(page).toHaveURL(/\/spaces\?inspect=contacts/);
    await expect(
      page.getByRole("heading", { name: "Alex Morgan", exact: true }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Close related workspace", exact: true })
      .click();
    await expect(
      page.getByRole("heading", {
        name: "Synthetic evidence review",
        exact: true,
      }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Edit Space", exact: true }).click();
    await page
      .getByRole("textbox", { name: "Purpose", exact: true })
      .fill("Decide the next useful research step.");
    await page
      .getByRole("button", { name: "Save changes", exact: true })
      .click();
    await expect(
      page
        .getByText("Decide the next useful research step.", { exact: true })
        .last(),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Archive Space", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "Restore Space", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Create task", exact: true }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Link existing record", exact: true }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Unlink Alex Morgan", exact: true }),
    ).toHaveCount(0);
    await expect(contact).toBeVisible();
    await page
      .getByRole("button", { name: "Restore Space", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Unlink Alex Morgan", exact: true })
      .click();
    await expect(contact).toHaveCount(0);
    await expect(
      page.getByRole("button", {
        name: "Review the synthetic evidence Task · Open",
        exact: true,
      }),
    ).toBeVisible();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBe(width);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({
      path: `/tmp/command-center-spaces-${width}.png`,
      fullPage: true,
    });
    expect(errors).toEqual([]);
    const mutations = (await page.evaluate(async () =>
      (await fetch("/api/backend/test/space-requests")).json(),
    )) as { path: string; key: string }[];
    expect(mutations).toHaveLength(7);
    expect(mutations.every((request) => Boolean(request.key))).toBe(true);
    expect(
      mutations.filter((request) => /\/tasks\?/.test(request.path)),
    ).toHaveLength(1);
  });
}

test("Briefing capture chooses an active Space and keeps archived Spaces out of the picker", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("combobox", { name: "Space (optional)" }).click();
  await expect(
    page.getByRole("option", { name: "Finished review", exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole("option", { name: "Research planning", exact: true })
    .click();
  await page
    .getByRole("textbox", { name: "What would you like to move forward?" })
    .fill(
      "Follow the saved research\nKeep the source URL: https://example.com/research",
    );
  await page.getByRole("button", { name: "Create task", exact: true }).click();
  await expect(page.getByText("Captured:")).toBeVisible();
  const mutations = (await page.evaluate(async () =>
    (await fetch("/api/backend/test/space-requests")).json(),
  )) as { path: string; body: { rationale: string } }[];
  expect(mutations).toHaveLength(1);
  expect(mutations[0].path).toBe(
    "spaces/space-research/tasks?expected_version=1",
  );
  expect(mutations[0].body.rationale).toBe(
    "Follow the saved research\nKeep the source URL: https://example.com/research",
  );
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("link", { name: "Spaces", exact: true })
    .click();
  await expect(page).toHaveURL(/\/spaces$/);
  await page.getByRole("button", { name: /^Research planning/ }).click();
  await expect(
    page.getByRole("button", {
      name: "Follow the saved research Task · Open",
      exact: true,
    }),
  ).toBeVisible();
});
