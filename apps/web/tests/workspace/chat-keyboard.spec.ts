import { expect, test } from "@playwright/test";

for (const scope of ["agents", "tasks"] as const) {
  test(`${scope} chat submits with Enter and preserves multiline and composition input`, async ({
    page,
  }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(scope === "agents" ? "/agents" : "/tasks?record=task-1");
    if (scope === "tasks") {
      await page
        .getByRole("tab", { name: "Conversation", exact: true })
        .click();
    }
    const composer = page.getByRole("textbox", {
      name: scope === "agents" ? "Message your agent" : "Message",
      exact: true,
    });
    const send = page.getByRole("button", {
      name: scope === "agents" ? "Run agent" : "Send message",
      exact: true,
    });
    const submissions: string[] = [];
    let release!: () => void;
    const pending = new Promise<void>((resolve) => {
      release = resolve;
    });
    await page.exposeFunction("holdChatSubmission", (body: string) => {
      submissions.push(body);
      return pending;
    });
    // The workspace preview provides its synthetic backend through window.fetch.
    await page.evaluate(() => {
      const fixtureFetch = window.fetch;
      window.fetch = async (input, init) => {
        if (
          init?.method === "POST" &&
          /\/(agent-runs|messages)$/.test(String(input))
        ) {
          await (
            window as typeof window & {
              holdChatSubmission: (body: string) => Promise<void>;
            }
          ).holdChatSubmission(String(init.body));
        }
        return fixtureFetch(input, init);
      };
    });

    await composer.fill("   ");
    await composer.press("Enter");
    await expect(send).toBeDisabled();
    await composer.fill("First line");
    await expect(send).toBeEnabled();
    await composer.press("Shift+Enter");
    await composer.pressSequentially("Second line");
    await expect(composer).toHaveValue("First line\nSecond line");
    await composer.dispatchEvent("keydown", {
      key: "Enter",
      isComposing: true,
    });
    await composer.dispatchEvent("keydown", { key: "Enter", keyCode: 229 });
    await composer.dispatchEvent("keydown", { key: "Enter", repeat: true });
    expect(submissions).toHaveLength(0);
    await expect(composer).toHaveValue("First line\nSecond line");

    await composer.press("Enter");
    await expect(send).toBeDisabled();
    await expect.poll(() => submissions.length).toBe(1);
    await composer.press("Enter");
    await expect(composer).toHaveValue("First line\nSecond line");
    expect(submissions).toHaveLength(1);
    release();
    await expect(composer).toHaveValue("");
    expect(JSON.parse(submissions[0])).toMatchObject({
      [scope === "agents" ? "prompt" : "content"]: "First line\nSecond line",
    });
    if (scope === "tasks") {
      await expect(page.getByText("1 active run")).toBeVisible();
      await composer.fill("Continue with this instruction.");
      await composer.press("Enter");
      await expect(composer).toHaveValue("");
      await expect(page.getByText(/saved.*next safe/i)).toBeVisible();
      expect(submissions).toHaveLength(2);
    }
    expect(errors).toEqual([]);
  });
}
