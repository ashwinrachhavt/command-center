import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { PropsWithChildren } from "react";
import { type AgentMessage, type Page } from "@/lib/api";
import {
  appendSavedMessage,
  sessionMessageKey,
  useSessionMessages,
} from "./use-session-messages";

const message = (sequence: number, sessionId = "session-a"): AgentMessage => ({
  id: `${sessionId}-${sequence}`,
  session_id: sessionId,
  sequence,
  run_id: "run-a",
  author: "user",
  profile: "lead",
  content: `Saved ${sequence}`,
  created_at: "2026-09-21T00:00:00Z",
  updated_at: "2026-09-21T00:00:00Z",
  row_version: 1,
});
function setup() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return {
    client,
    wrapper: ({ children }: PropsWithChildren) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  };
}

it("reads 250 messages once, then uses a stable incremental cursor across run state changes", async () => {
  const saved = Array.from({ length: 250 }, (_, index) => message(index + 1));
  vi.spyOn(global, "fetch").mockImplementation((input) => {
    const after = Number(
      new URL(String(input), "http://localhost").searchParams.get(
        "after_sequence",
      ),
    );
    return Promise.resolve(
      Response.json({
        items: saved.filter((item) => item.sequence > after).slice(0, 100),
        total: saved.length,
      }),
    );
  });
  const { client, wrapper } = setup();
  const { result, rerender } = renderHook(
    ({ active }) => ({ ...useSessionMessages("session-a", active) }),
    { wrapper, initialProps: { active: true } },
  );
  await waitFor(() => expect(result.current.data?.items).toHaveLength(250));
  expect(fetch).toHaveBeenCalledTimes(3);
  rerender({ active: false });
  expect(result.current.data?.items).toHaveLength(250);
  expect(fetch).toHaveBeenCalledTimes(3);
  saved.push(message(251));
  await act(() =>
    client.invalidateQueries({ queryKey: sessionMessageKey("session-a") }),
  );
  await waitFor(() => expect(result.current.data?.items).toHaveLength(251));
  expect(String(vi.mocked(fetch).mock.calls[3][0])).toContain(
    "after_sequence=250",
  );
});

it("does not skip messages between the confirmed cursor and an optimistically inserted saved reply", async () => {
  const { client, wrapper } = setup();
  client.setQueryData(sessionMessageKey("session-a"), {
    items: [message(1)],
    total: 1,
  });
  appendSavedMessage(client, message(4));
  vi.spyOn(global, "fetch").mockResolvedValue(
    Response.json({ items: [message(2), message(3), message(4)], total: 3 }),
  );
  const { result } = renderHook(
    () => ({ ...useSessionMessages("session-a") }),
    { wrapper },
  );
  await act(() => result.current.refetch());
  expect(String(vi.mocked(fetch).mock.calls[0][0])).toContain(
    "after_sequence=1",
  );
  await waitFor(() =>
    expect(result.current.data?.items.map((item) => item.sequence)).toEqual([
      1, 2, 3, 4,
    ]),
  );
});

it("aborts old session pages and never paints a late response in a different session", async () => {
  let late!: (response: Response) => void;
  let signal: AbortSignal | undefined;
  vi.spyOn(global, "fetch").mockImplementation((input, init) => {
    if (String(input).includes("session-a")) {
      signal = init?.signal as AbortSignal;
      return new Promise((resolve) => {
        late = resolve;
      });
    }
    return Promise.resolve(
      Response.json({ items: [message(1, "session-b")], total: 1 }),
    );
  });
  const { wrapper } = setup();
  const { result, rerender } = renderHook(
    ({ id }) => ({ ...useSessionMessages(id) }),
    { wrapper, initialProps: { id: "session-a" } },
  );
  await waitFor(() => expect(signal).toBeDefined());
  rerender({ id: "session-b" });
  await waitFor(() =>
    expect(result.current.data?.items[0].session_id).toBe("session-b"),
  );
  expect(signal?.aborted).toBe(true);
  await act(async () =>
    late(
      Response.json({
        items: Array.from({ length: 100 }, (_, index) => message(index + 1)),
        total: 100,
      }),
    ),
  );
  expect(result.current.data?.items[0].session_id).toBe("session-b");
  expect(fetch).toHaveBeenCalledTimes(2);
});

it("keeps cached messages visible when an incremental refresh fails", async () => {
  const { client, wrapper } = setup();
  client.setQueryData<Page<AgentMessage>>(sessionMessageKey("session-a"), {
    items: [message(1)],
    total: 1,
    limit: 100,
    offset: 0,
  });
  vi.spyOn(global, "fetch").mockResolvedValue(
    Response.json({ detail: "Synthetic refresh failure" }, { status: 409 }),
  );
  const { result } = renderHook(
    () => ({ ...useSessionMessages("session-a") }),
    { wrapper },
  );
  await act(() => result.current.refetch());
  await waitFor(() =>
    expect(result.current.error?.message).toBe("Synthetic refresh failure"),
  );
  expect(result.current.data?.items).toEqual([message(1)]);
});
