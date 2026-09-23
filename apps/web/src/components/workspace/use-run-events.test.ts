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
