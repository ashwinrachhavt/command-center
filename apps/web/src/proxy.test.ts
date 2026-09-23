import { beforeEach, expect, it, vi } from "vitest";

const { protect } = vi.hoisted(() => ({ protect: vi.fn() }));
vi.mock("@clerk/nextjs/server", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@clerk/nextjs/server")>()),
  clerkMiddleware: (handler: unknown) => handler,
}));

import middleware from "./proxy";

const run = middleware as unknown as (
  auth: { protect: typeof protect },
  request: { nextUrl: { pathname: string } },
) => Promise<void>;

beforeEach(() => {
  protect.mockReset();
});

it.each(["/", "/contacts", "/companies", "/settings"])(
  "authenticates %s before streaming workspace content",
  async (pathname) => {
    await run({ protect }, { nextUrl: { pathname } });
    expect(protect).toHaveBeenCalledOnce();
  },
);

it.each(["/sign-in", "/sign-up", "/health", "/api/backend/contacts"])(
  "leaves %s to its public or API authentication handling",
  async (pathname) => {
    await run({ protect }, { nextUrl: { pathname } });
    expect(protect).not.toHaveBeenCalled();
  },
);

it("does not render past an authentication failure", async () => {
  protect.mockRejectedValue(new Error("Synthetic session failure"));
  await expect(
    run({ protect }, { nextUrl: { pathname: "/contacts" } }),
  ).rejects.toThrow("Synthetic session failure");
});
