import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import HomePage from "./page";

const { protect, redirect } = vi.hoisted(() => ({
  protect: vi.fn(),
  redirect: vi.fn((url: string) => {
    throw new Error(`Redirect: ${url}`);
  }),
}));
vi.mock("@clerk/nextjs/server", () => ({ auth: { protect } }));
vi.mock("next/navigation", () => ({ redirect }));
vi.mock("@/components/workspace/section-view", () => ({
  SectionView: ({ section }: { section: string }) => <main>{section}</main>,
}));

beforeEach(() => {
  protect.mockReset();
  redirect.mockClear();
});

it("authenticates the root page and opens Briefing", async () => {
  render(await HomePage({ searchParams: Promise.resolve({}) }));
  expect(protect).toHaveBeenCalledExactlyOnceWith();
  expect(screen.getByRole("main")).toHaveTextContent("briefing");
  expect(redirect).not.toHaveBeenCalled();
});

it.each(["session", "conversation", "run", "agent"])(
  "preserves a legacy %s link and its complete query when opening Assistant",
  async (key) => {
    const params = {
      [key]: "saved-context",
      tag: ["one", "two"],
      unused: undefined,
    };
    await expect(
      HomePage({ searchParams: Promise.resolve(params) }),
    ).rejects.toThrow("Redirect:");
    expect(protect).toHaveBeenCalledExactlyOnceWith();
    expect(redirect).toHaveBeenCalledExactlyOnceWith(
      `/agents?${key}=saved-context&tag=one&tag=two`,
    );
  },
);
