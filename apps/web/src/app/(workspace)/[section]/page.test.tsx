import { beforeEach, expect, it, vi } from "vitest";

const { protect } = vi.hoisted(() => ({ protect: vi.fn() }));
vi.mock("@clerk/nextjs/server", () => ({ auth: { protect } }));
vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
}));
vi.mock("@/components/workspace/section-view", () => ({
  SectionView: () => null,
}));

import SectionPage from "./page";

beforeEach(() => {
  protect.mockReset();
});

it.each(["favicon.ico", "missing.png", "unknown"])(
  "returns not found for %s without requiring middleware auth context",
  async (section) => {
    await expect(
      SectionPage({ params: Promise.resolve({ section }) }),
    ).rejects.toThrow("NEXT_NOT_FOUND");
    expect(protect).not.toHaveBeenCalled();
  },
);

it("still requires authentication for a valid workspace section", async () => {
  protect.mockRejectedValue(new Error("Sign in required"));
  await expect(
    SectionPage({ params: Promise.resolve({ section: "contacts" }) }),
  ).rejects.toThrow("Sign in required");
  expect(protect).toHaveBeenCalledOnce();
});
