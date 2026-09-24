import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useRunEvents } from "./use-run-events";

afterEach(() => vi.restoreAllMocks());

function openStream() {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({
    start(value) {
      controller = value;
    },
  });
  return {
    response: new Response(body, {
      headers: { "Content-Type": "text/event-stream" },
    }),
    send(
      runId: string,
      sequence: number,
      type: string,
      data: Record<string, unknown>,
    ) {
      controller.enqueue(
        new TextEncoder().encode(
          `event: agent_event\ndata: ${JSON.stringify({ run_id: runId, sequence, type, role: "lead", data, created_at: "2026-09-22T00:00:00Z" })}\n\n`,
        ),
      );
    },
    close: () => controller.close(),
    raw: (value: string) => controller.enqueue(new TextEncoder().encode(value)),
  };
}

it("keeps one connection through status changes and paints a burst once before flushing the final text", async () => {
  const stream = openStream();
  const fetch = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(stream.response);
  let frame: FrameRequestCallback | undefined;
  const paint = vi
    .spyOn(globalThis, "requestAnimationFrame")
    .mockImplementation((callback) => {
      frame = callback;
      return 1;
    });
  const cancel = vi
    .spyOn(globalThis, "cancelAnimationFrame")
    .mockImplementation(() => {});
  const { result, unmount } = renderHook(() => useRunEvents("run-a", true));
  await waitFor(() => expect(result.current.connection).toBe("live"));
  await act(async () => {
    stream.send("run-a", 1, "run-status", { state: "queued" });
    stream.send("run-a", 2, "run-status", { state: "running" });
    for (let index = 0; index < 60; index++)
      stream.send("run-a", index + 3, "text-delta", {
        message_id: "reply",
        delta: "word ",
      });
  });
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(paint).toHaveBeenCalledTimes(1);
  expect(result.current.messages).toEqual([]);
  act(() => frame!(16));
  expect(result.current.messages).toEqual([
    { id: "reply", content: "word ".repeat(60) },
  ]);
  await act(async () => {
    stream.send("run-a", 63, "text-delta", {
      message_id: "reply",
      delta: "done",
    });
    stream.send("run-a", 64, "run-status", { state: "completed" });
    stream.close();
  });
  expect(result.current.connection).toBe("complete");
  expect(result.current.messages[0].content).toBe("word ".repeat(60) + "done");
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(cancel).toHaveBeenCalled();
  unmount();
});

it("flushes completion immediately even when the transport stays open", async () => {
  const stream = openStream();
  vi.spyOn(globalThis, "fetch").mockResolvedValue(stream.response);
  vi.spyOn(globalThis, "requestAnimationFrame").mockImplementation(() => 1);
  vi.spyOn(globalThis, "cancelAnimationFrame").mockImplementation(() => {});
  const { result, unmount } = renderHook(() => useRunEvents("run-a", true));
  await waitFor(() => expect(result.current.connection).toBe("live"));
  await act(async () => {
    stream.send("run-a", 1, "text-delta", {
      message_id: "reply",
      delta: "Complete reply",
    });
    stream.send("run-a", 2, "run-status", { state: "completed" });
  });
  expect(result.current.connection).toBe("complete");
  expect(result.current.messages).toEqual([
    { id: "reply", content: "Complete reply" },
  ]);
  expect(stream.response.body?.locked).toBe(false);
  unmount();
});

it.each([400, 401, 403, 404, 422])(
  "does not automatically retry a permanent HTTP %s",
  async (status) => {
    const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(null, { status }));
    const { result, unmount } = renderHook(() => useRunEvents("run-a", true));
    await waitFor(() => expect(result.current.connection).toBe("disconnected"));
    vi.useFakeTimers();
    try {
      act(() => document.dispatchEvent(new Event("visibilitychange")));
      await act(() => vi.advanceTimersByTimeAsync(60_000));
      expect(fetch).toHaveBeenCalledTimes(1);
      act(() => result.current.retry());
      await act(async () => {});
      expect(fetch).toHaveBeenCalledTimes(2);
    } finally {
      unmount();
      vi.useRealTimers();
    }
  },
);

it("honors Retry-After and pauses reconnect attempts while offline", async () => {
  const stream = openStream();
  const fetch = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(
      new Response(null, { status: 429, headers: { "Retry-After": "10" } }),
    )
    .mockResolvedValueOnce(stream.response);
  vi.useFakeTimers();
  const { result, unmount } = renderHook(() => useRunEvents("run-a", true));
  try {
    await act(async () => {});
    expect(result.current.connection).toBe("disconnected");
    await act(() => vi.advanceTimersByTimeAsync(9_000));
    expect(fetch).toHaveBeenCalledTimes(1);
    const online = vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    act(() => window.dispatchEvent(new Event("offline")));
    await act(() => vi.advanceTimersByTimeAsync(20_000));
    expect(fetch).toHaveBeenCalledTimes(1);
    online.mockReturnValue(true);
    act(() => window.dispatchEvent(new Event("online")));
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(result.current.connection).toBe("live");
    await act(async () => stream.close());
  } finally {
    unmount();
    vi.useRealTimers();
  }
});

it("bounds an unterminated event and does not retry a broken stream protocol", async () => {
  const stream = openStream();
  const fetch = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(stream.response);
  const { result, unmount } = renderHook(() => useRunEvents("run-a", true));
  await waitFor(() => expect(result.current.connection).toBe("live"));
  await act(async () => stream.raw("data: " + "x".repeat(256_001)));
  expect(result.current.connection).toBe("disconnected");
  expect(result.current.connectionError).toContain("event size limit");
  vi.useFakeTimers();
  try {
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    await act(() => vi.advanceTimersByTimeAsync(60_000));
    expect(fetch).toHaveBeenCalledTimes(1);
  } finally {
    unmount();
    vi.useRealTimers();
  }
});

it("fences a late read when switching runs and starts the new cursor at zero", async () => {
  const first = openStream();
  const second = openStream();
  const fetch = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(first.response)
    .mockResolvedValueOnce(second.response);
  vi.spyOn(globalThis, "requestAnimationFrame").mockImplementation(() => 1);
  vi.spyOn(globalThis, "cancelAnimationFrame").mockImplementation(() => {});
  const { result, rerender, unmount } = renderHook(
    ({ id }) => useRunEvents(id, true),
    { initialProps: { id: "run-a" } },
  );
  await waitFor(() => expect(result.current.connection).toBe("live"));
  await act(async () =>
    first.send("run-a", 80, "text-delta", {
      message_id: "old",
      delta: "Old owner text",
    }),
  );
  rerender({ id: "run-b" });
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  await act(async () => {
    first.send("run-a", 81, "text-delta", {
      message_id: "old",
      delta: "Late text",
    });
    first.close();
    second.send("run-b", 1, "text-delta", {
      message_id: "new",
      delta: "New reply",
    });
    second.send("run-b", 2, "run-status", { state: "completed" });
    second.close();
  });
  expect(String(fetch.mock.calls[1][0])).toContain(
    "run-b/events?after_sequence=0",
  );
  expect(result.current.messages).toEqual([
    { id: "new", content: "New reply" },
  ]);
  expect(result.current.connection).toBe("complete");
  unmount();
});

it("reconnects only event delivery from its cursor, deduplicates replay and pauses retries while hidden", async () => {
  const first = openStream();
  const second = openStream();
  const fetch = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(first.response)
    .mockResolvedValueOnce(second.response);
  const { result, unmount } = renderHook(() => useRunEvents("run-a", true));
  await waitFor(() => expect(result.current.connection).toBe("live"));
  vi.useFakeTimers();
  try {
    await act(async () => {
      first.send("run-a", 1, "text-delta", {
        message_id: "reply",
        delta: "Hello",
      });
      first.close();
    });
    expect(result.current.connection).toBe("disconnected");
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    await act(() => vi.advanceTimersByTimeAsync(10_000));
    expect(fetch).toHaveBeenCalledTimes(1);
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(String(fetch.mock.calls[1][0])).toContain("after_sequence=1");
    expect(
      fetch.mock.calls.every(
        ([, init]) => !init?.method || init.method === "GET",
      ),
    ).toBe(true);
    await act(async () => {
      second.send("run-a", 1, "text-delta", {
        message_id: "reply",
        delta: "Hello",
      });
      second.send("run-a", 2, "text-delta", {
        message_id: "reply",
        delta: " again",
      });
      second.send("run-a", 3, "run-status", { state: "completed" });
      second.close();
    });
    expect(result.current.messages).toEqual([
      { id: "reply", content: "Hello again" },
    ]);
    await act(() => vi.advanceTimersByTimeAsync(60_000));
    expect(fetch).toHaveBeenCalledTimes(2);
  } finally {
    unmount();
    vi.useRealTimers();
  }
});
