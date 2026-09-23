import { expect, test } from "@playwright/test";

test("keeps human answers while generation and snapshot changes refresh", async ({
  page,
}) => {
  await page.goto("/browser");

  await expect(
    page.getByRole("heading", { name: "Northstar application" }),
  ).toBeVisible();
  await expect(
    page.getByRole("combobox", { name: "Exact resume version" }),
  ).toContainText("synthetic-resume.pdf · v1");

  await page.getByRole("button", { name: "Prepare answers" }).click();
  await expect(page.getByLabel("Full name")).toHaveValue("Synthetic Candidate");
  await expect(
    page.getByText(/Approved fact: Synthetic Candidate/),
  ).toBeVisible();
  await expect(page.getByText("Missing answers")).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Email *" })).toBeDisabled();

  const narrative = page.getByLabel("Why are you interested in this role?");
  await narrative.fill("My reviewed human answer stays here.");
  await page.getByRole("button", { name: "Generate narrative drafts" }).click();
  await expect(page.getByText("Draft generation queued")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Save exact revision & send proposal" }),
  ).toBeDisabled();
  await expect(narrative).toHaveValue("My reviewed human answer stays here.");
  await expect(
    page.getByRole("button", { name: "Generate narrative drafts" }),
  ).toBeEnabled({ timeout: 5_000 });
  await expect(narrative).toHaveValue("My reviewed human answer stays here.");

  await page.getByRole("combobox", { name: "Shared form" }).click();
  await page.getByRole("option", { name: "Second application page" }).click();
  await page.getByLabel("Additional note").fill("Second page draft.");
  await page.getByRole("combobox", { name: "Shared form" }).click();
  await page.getByRole("option", { name: "Northstar application" }).click();
  await expect(narrative).toHaveValue("My reviewed human answer stays here.");
  await page.getByRole("combobox", { name: "Shared form" }).click();
  await page.getByRole("option", { name: "Second application page" }).click();
  await expect(page.getByLabel("Additional note")).toHaveValue(
    "Second page draft.",
  );
});

test("pins an explicit resume, replacement, upload field, and preparation version", async ({
  page,
}) => {
  await page.goto("/browser");

  await page.getByRole("combobox", { name: "Application context" }).click();
  await page.getByRole("option", { name: "Staff Product Engineer" }).click();
  await page.getByRole("combobox", { name: "Exact resume version" }).click();
  await page
    .getByRole("option", { name: "synthetic-product-resume.pdf · v2" })
    .click();
  await page.getByRole("button", { name: "Prepare answers" }).click();

  await page
    .getByRole("checkbox", { name: "Replace existing value for Email" })
    .click();
  await page
    .getByRole("textbox", { name: "Email *" })
    .fill("reviewed@example.test");
  await page
    .getByRole("combobox", {
      name: "Document to upload to Resume",
    })
    .click();
  await page
    .getByRole("option", { name: "Attach selected résumé", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Save exact revision & send proposal" })
    .click();
  await expect(page.getByText(/Fill proposal sent/)).toBeVisible();

  const state = await page.evaluate(async () => {
    const [command, preparation] = await Promise.all([
      fetch("/api/backend/test/latest-browser-command").then((response) =>
        response.json(),
      ),
      fetch("/api/backend/test/latest-browser-preparation").then((response) =>
        response.json(),
      ),
    ]);
    return { command, preparation };
  });
  expect(state.command.fields.f1).toBe("reviewed@example.test");
  expect(state.command.replace_fields).toEqual(["f1"]);
  expect(state.command.uploads).toEqual({
    f3: "resume-version-specialized",
  });
  expect(state.command.preparation_version_id).toBe(
    state.preparation.version_id,
  );
  expect(state.preparation.upload_fields).toEqual(["f3"]);
  expect(state.preparation.resume.version_id).toBe(
    "resume-version-specialized",
  );
  const reviewedFields = Object.fromEntries(
    state.preparation.fields.map(
      (field: { field_id: string; value: string | null }) => [
        field.field_id,
        field.value,
      ],
    ),
  );
  expect(reviewedFields).toMatchObject({
    f0: "Synthetic Candidate",
    f1: "reviewed@example.test",
    f2: null,
  });
});

test("explicitly clears generated suggestions and replacement opt-outs", async ({
  page,
}) => {
  await page.goto("/browser");
  await page.getByRole("button", { name: "Prepare answers" }).click();
  await page.getByRole("button", { name: "Generate narrative drafts" }).click();

  const narrative = page.getByLabel("Why are you interested in this role?");
  await expect(narrative).toHaveValue(
    "Generated grounded narrative from approved facts.",
    { timeout: 5_000 },
  );
  await narrative.fill("");

  const replace = page.getByRole("checkbox", {
    name: "Replace existing value for Email",
  });
  await replace.click();
  await page
    .getByRole("textbox", { name: "Email *" })
    .fill("skip@example.test");
  await replace.click();

  await page
    .getByRole("button", { name: "Save exact revision & send proposal" })
    .click();
  await expect(page.getByText(/Fill proposal sent/)).toBeVisible();

  const state = await page.evaluate(async () => {
    const [command, preparation] = await Promise.all([
      fetch("/api/backend/test/latest-browser-command").then((response) =>
        response.json(),
      ),
      fetch("/api/backend/test/latest-browser-preparation").then((response) =>
        response.json(),
      ),
    ]);
    return { command, preparation };
  });
  const values = Object.fromEntries(
    state.preparation.fields.map(
      (field: { field_id: string; value: string | null }) => [
        field.field_id,
        field.value,
      ],
    ),
  );
  expect(values).toMatchObject({
    f0: "Synthetic Candidate",
    f1: null,
    f2: null,
  });
  expect(state.preparation.replace_fields).toEqual([]);
  expect(state.command.fields).toEqual({ f0: "Synthetic Candidate" });
  expect(state.command.replace_fields).toEqual([]);
});

test("application preparation remains usable on a narrow screen", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));

  await page.goto("/browser");
  await page.getByRole("button", { name: "Prepare answers" }).click();
  await expect(page.getByLabel("Full name")).toHaveValue("Synthetic Candidate");
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(
    390,
  );
  expect(errors).toEqual([]);
});

test("workspace review pins a separate cover letter without changing the selected résumé", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/browser");
  await page
    .getByRole("combobox", { name: "Exact cover-letter version", exact: true })
    .click();
  await page
    .getByRole("option", {
      name: "Northstar cover letter · northstar-letter.pdf",
      exact: true,
    })
    .click();
  await page
    .getByRole("button", { name: "Prepare answers", exact: true })
    .click();
  await page
    .getByRole("combobox", {
      name: "Document to upload to Cover letter",
      exact: true,
    })
    .click();
  await page
    .getByRole("option", { name: "Attach selected cover letter", exact: true })
    .click();
  await page
    .getByRole("button", {
      name: "Save exact revision & send proposal",
      exact: true,
    })
    .click();
  await expect(page.getByText(/Fill proposal sent/)).toBeVisible();
  const state = await page.evaluate(async () => ({
    command: await (
      await fetch("/api/backend/test/latest-browser-command")
    ).json(),
    preparation: await (
      await fetch("/api/backend/test/latest-browser-preparation")
    ).json(),
  }));
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(state.command.uploads).toEqual({ f5: "letter-version-1" });
  expect(state.preparation.cover_letter.version_id).toBe("letter-version-1");
  expect(state.preparation.cover_letter_upload_fields).toEqual(["f5"]);
  expect(state.preparation.resume.version_id).toBe("resume-version-1");
  expect(state.command.preparation_version_id).toBe(
    state.preparation.version_id,
  );
});
