import { expect, test } from "@playwright/test";

test("explicit discovery reveals a preview and adds a contact before follow-up writing", async ({
  page,
}) => {
  await page.goto("/contacts");
  await page
    .getByRole("button", { name: "Discover contacts", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByRole("heading", { name: "Discover contacts", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(() =>
      JSON.parse(localStorage.getItem("synthetic-discovery-requests") ?? "[]"),
    ),
  ).toHaveLength(0);
  await page
    .getByRole("textbox", { name: "Company domain" })
    .fill("example.com");
  await page
    .getByRole("textbox", { name: "Job title filter" })
    .fill("Engineering lead");
  await page.getByRole("button", { name: "Search Apollo" }).click();
  await expect(dialog.getByText("Alex M***", { exact: true })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Add contact" })).toHaveCount(
    0,
  );
  await page.getByRole("button", { name: "Reveal profile" }).click();
  await expect(
    dialog.getByText("alex@example.com", { exact: true }),
  ).toBeVisible();
  await expect(
    dialog.getByText("Email status reported by apollo: accept all"),
  ).toBeVisible();
  await page.getByRole("button", { name: "Add contact" }).click();
  await page.getByRole("button", { name: "Open contact", exact: true }).click();
  await page.getByRole("button", { name: "Follow up", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Write follow-up", exact: true }),
  ).toBeVisible();
  const requests = await page.evaluate(() =>
    JSON.parse(localStorage.getItem("synthetic-discovery-requests") ?? "[]"),
  );
  expect(requests.map((item: { route: string }) => item.route)).toEqual([
    "contact-discovery/search",
    "contact-discovery/reveal",
    "contact-discovery/import",
  ]);
  expect(requests[1].body.source_version_id).toBeTruthy();
});

test("unknown provider requests keep their identity across reload and explicit fresh retry", async ({
  page,
}) => {
  await page.goto("/contacts?discovery_failure=unknown");
  const search = async () => {
    await page
      .getByRole("button", { name: "Discover contacts", exact: true })
      .click();
    await page
      .getByRole("textbox", { name: "Company domain" })
      .fill("example.com");
    await page.getByRole("button", { name: "Search Apollo" }).click();
    await expect(page.getByRole("alert")).toContainText("outcome is unknown");
  };
  await search();
  await page.reload();
  await search();
  const read = () =>
    page.evaluate(() =>
      JSON.parse(localStorage.getItem("synthetic-discovery-requests") ?? "[]"),
    );
  let requests = await read();
  expect(requests).toHaveLength(2);
  expect(requests[1].key).toBe(requests[0].key);
  await page.getByRole("button", { name: "Start a new request…" }).click();
  await page.getByRole("button", { name: "Make new provider request" }).click();
  await expect(page.getByRole("alert")).toContainText("outcome is unknown");
  await page.getByRole("button", { name: "Retry same request" }).click();
  await expect.poll(async () => (await read()).length).toBe(4);
  requests = await read();
  expect(requests[2].key).not.toBe(requests[1].key);
  expect(requests[3].key).toBe(requests[2].key);
});

test("mobile Hunter discovery and setup remain accessible without implicit provider requests", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/connections?provider_setup=1");
  await page.getByRole("button", { name: "Set up Hunter" }).click();
  await expect(page.getByRole("dialog")).toContainText("HUNTER_API_KEY");
  await page.getByRole("button", { name: "Recheck setup" }).click();
  await page.goto("/contacts");
  await page
    .getByRole("button", { name: "Discover contacts", exact: true })
    .click();
  await page
    .getByRole("combobox", { name: "Discovery provider" })
    .selectOption("hunter");
  await expect(
    page.getByRole("textbox", { name: "Job title filter" }),
  ).toHaveCount(0);
  await page
    .getByRole("textbox", { name: "Company domain" })
    .fill("example.com");
  await page.getByRole("button", { name: "Search Hunter" }).click();
  await expect(page.getByRole("button", { name: "Add contact" })).toBeVisible();
  expect(
    await page
      .getByRole("dialog")
      .evaluate((element) => element.scrollWidth <= element.clientWidth + 1),
  ).toBe(true);
  await page.reload();
  await page
    .getByRole("button", { name: "Discover contacts", exact: true })
    .click();
  await page
    .getByRole("combobox", { name: "Saved discovery" })
    .selectOption({ index: 1 });
  await expect(page.getByRole("button", { name: "Add contact" })).toBeVisible();
  expect(
    await page.evaluate(() =>
      JSON.parse(localStorage.getItem("synthetic-discovery-requests") ?? "[]"),
    ),
  ).toHaveLength(1);
});

test("an existing lead receives only explicitly accepted missing details", async ({
  page,
}) => {
  await page.goto("/contacts?discovery_existing=1");
  await page
    .getByRole("button", { name: "Discover contacts", exact: true })
    .click();
  await page
    .getByRole("combobox", { name: "Discovery provider" })
    .selectOption("hunter");
  await page
    .getByRole("textbox", { name: "Company domain" })
    .fill("example.com");
  await page.getByRole("button", { name: "Search Hunter" }).click();
  await page.getByRole("button", { name: "Add contact" }).click();
  await expect(page.getByRole("dialog")).toContainText(
    "Add email from this result",
  );
  await page.getByRole("button", { name: "Fill missing details" }).click();
  await expect(
    page.getByRole("button", { name: "Fill missing details" }),
  ).toHaveCount(0);
  const requests = await page.evaluate(() =>
    JSON.parse(localStorage.getItem("synthetic-discovery-requests") ?? "[]"),
  );
  expect(requests[2].route).toBe("contact-discovery/fill-missing");
  expect(requests[2].body.fields).toEqual(["email"]);
  expect(requests[2].body.expected_version).toBe(1);
  expect(requests[2].body.source_version_id).toBe(
    requests[1].body.source_version_id,
  );
});
