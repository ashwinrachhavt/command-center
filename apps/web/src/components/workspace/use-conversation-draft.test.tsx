import { act, renderHook } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { useConversationDraft } from "./use-conversation-draft";

const auth = vi.hoisted(() => ({ userId: "synthetic-owner-a" }));
vi.mock("@clerk/nextjs", () => ({ useAuth: () => auth }));
beforeEach(() => {
  sessionStorage.clear();
  auth.userId = "synthetic-owner-a";
});

it("isolates drafts by owner and thread and restores the original draft", () => {
  const { result, rerender, unmount } = renderHook(
    ({ scope }) => useConversationDraft(scope),
    { initialProps: { scope: "new" } },
  );
  act(() => result.current[1]("Owner A unfinished draft"));
  rerender({ scope: "thread-two" });
  expect(result.current[0]).toBe("");
  act(() => result.current[1]("Second thread draft"));
  auth.userId = "synthetic-owner-b";
  rerender({ scope: "new" });
  expect(result.current[0]).toBe("");
  act(() => result.current[1]("Owner B draft"));
  auth.userId = "synthetic-owner-a";
  rerender({ scope: "new" });
  expect(result.current[0]).toBe("Owner A unfinished draft");
  unmount();
  const recovered = renderHook(() => useConversationDraft("thread-two"));
  expect(recovered.result.current[0]).toBe("Second thread draft");
});

it("acknowledging a sent draft preserves text typed while sending", () => {
  const { result } = renderHook(() => useConversationDraft("thread"));
  act(() => result.current[1]("First message"));
  const submitted = result.current[0];
  act(() => result.current[1]("Next message"));
  act(() =>
    result.current[1]((current) => (current === submitted ? "" : current)),
  );
  expect(result.current[0]).toBe("Next message");
});
