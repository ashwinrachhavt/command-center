import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Schema, WorkspaceRecord } from "@/lib/api";
import { RecordDetail } from "./record-detail";
import { TaskActionHub } from "./task-action-hub";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ isLoaded: true, userId: "synthetic-task-owner" }),
}));

const task: Schema["TaskRead"] = {
  id: "synthetic-task",
  row_version: 7,
  created_at: "2026-09-22T10:00:00Z",
  updated_at: "2026-09-22T10:00:00Z",
  title: "Draft a message to a synthetic contact",
  state: "open",
  priority: 2,
  rationale: "Keep the next step clear before the weekly review.",
  due_date: "2026-09-23",
  completed_at: null,
};

function mountHub(overrides: Record<string, unknown> = {}, isPending = false) {
  const onStatusChange = vi.fn();
  const onOpenConversation = vi.fn();
  render(
    <TaskActionHub
      record={{ ...task, ...overrides } as WorkspaceRecord}
      onStatusChange={onStatusChange}
      onOpenConversation={onOpenConversation}
      isPending={isPending}
    />,
  );
  return { onStatusChange, onOpenConversation };
}

describe("task actions", () => {
  it.each([
    ["open", "Start task", "in_progress"],
    ["snoozed", "Resume task", "in_progress"],
    ["waiting", "Resume task", "in_progress"],
    ["in_progress", "Complete task", "done"],
    ["done", "Reopen task", "open"],
    ["cancelled", "Reopen task", "open"],
  ])("uses an explicit action for a %s task", (state, action, nextState) => {
    const callbacks = mountHub({ state });
    expect(callbacks.onStatusChange).not.toHaveBeenCalled();
    expect(callbacks.onOpenConversation).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: action }));
    expect(callbacks.onStatusChange).toHaveBeenCalledExactlyOnceWith(nextState);
    expect(callbacks.onOpenConversation).not.toHaveBeenCalled();
    if (["done", "cancelled"].includes(state)) {
      expect(
        screen.queryByRole("button", { name: "Complete task" }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "Snooze" }),
      ).not.toBeInTheDocument();
    }
  });

  it.each(["open", "snoozed", "waiting"])(
    "can complete a %s task directly",
    (state) => {
      const { onStatusChange } = mountHub({ state });
      fireEvent.click(screen.getByRole("button", { name: "Complete task" }));
      expect(onStatusChange).toHaveBeenCalledExactlyOnceWith("done");
    },
  );

  it.each(["open", "in_progress", "snoozed", "waiting"])(
    "can cancel a %s task without starting agent work",
    (state) => {
      const { onStatusChange, onOpenConversation } = mountHub({ state });
      fireEvent.click(screen.getByRole("button", { name: "Cancel task" }));
      expect(onStatusChange).toHaveBeenCalledExactlyOnceWith("cancelled");
      expect(onOpenConversation).not.toHaveBeenCalled();
    },
  );

  it.each(["open", "in_progress"])(
    "snoozes a %s task without claiming a scheduled reminder",
    (state) => {
      const { onStatusChange } = mountHub({ state });
      fireEvent.click(screen.getByRole("button", { name: "Snooze" }));
      expect(onStatusChange).toHaveBeenCalledExactlyOnceWith("snoozed");
      expect(
        screen.queryByText(/tomorrow|remind|hour|until/i),
      ).not.toBeInTheDocument();
    },
  );

  it.each(["open", "in_progress", "snoozed"])(
    "marks a %s task as waiting without opening agent work",
    (state) => {
      const { onStatusChange, onOpenConversation } = mountHub({ state });
      fireEvent.click(screen.getByRole("button", { name: "Mark waiting" }));
      expect(onStatusChange).toHaveBeenCalledExactlyOnceWith("waiting");
      expect(onOpenConversation).not.toHaveBeenCalled();
    },
  );

  it.each([
    "Draft outreach",
    "Research a company",
    "Review a lead",
    "Prepare an application",
    "Follow up tomorrow",
  ])(
    "opens the conversation without inventing an agent action for %s",
    (title) => {
      const { onStatusChange, onOpenConversation } = mountHub({ title });
      expect(
        screen.getByRole("button", { name: "Start task" }),
      ).toBeInTheDocument();
      expect(
        screen.queryByRole("button", {
          name: /Draft|Research|Prep|\bAI\b|Notes/i,
        }),
      ).not.toBeInTheDocument();
      fireEvent.click(
        screen.getByRole("button", { name: "Open conversation" }),
      );
      expect(onOpenConversation).toHaveBeenCalledExactlyOnceWith();
      expect(onStatusChange).not.toHaveBeenCalled();
    },
  );

  it.each(["open", "in_progress", "snoozed", "waiting", "done", "cancelled"])(
    "disables every hub action while a %s task update is pending",
    (state) => {
      const callbacks = mountHub({ state }, true);
      for (const button of screen.getAllByRole("button")) {
        expect(button).toBeDisabled();
        fireEvent.click(button);
      }
      expect(callbacks.onStatusChange).not.toHaveBeenCalled();
      expect(callbacks.onOpenConversation).not.toHaveBeenCalled();
    },
  );

  it("retains rationale, explicit low priority, due date and status", () => {
    mountHub({ priority: 0 });
    expect(screen.getByText("Open")).toBeInTheDocument();
    expect(screen.getByText("Low priority")).toBeInTheDocument();
    expect(screen.getByText("Due Sep 23")).toHaveAttribute(
      "datetime",
      "2026-09-23",
    );
    expect(screen.getByText(task.rationale!)).toBeInTheDocument();
  });

  it("shows unknown status and incomplete metadata without inventing a transition", () => {
    const { onOpenConversation } = mountHub({
      state: "waiting_for_review",
      priority: 22,
      due_date: "invalid",
      rationale: null,
    });
    expect(screen.getByText("Waiting for review")).toBeInTheDocument();
    expect(screen.getByText("Priority not set")).toBeInTheDocument();
    expect(screen.getByText("No due date")).toBeInTheDocument();
    expect(screen.getByText("No rationale added yet.")).toBeInTheDocument();
    expect(
      screen.queryByRole("group", { name: "Task status actions" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open conversation" }));
    expect(onOpenConversation).toHaveBeenCalledExactlyOnceWith();
  });
});

function mountInspector(patchHandlers: Array<() => Promise<void>> = []) {
  let record = { ...task };
  const patches: RequestInit[] = [];
  const requests: Array<{ path: string; method: string }> = [];
  const emptyPage = { items: [], total: 0, limit: 30, offset: 0 };
  vi.spyOn(global, "fetch").mockImplementation(async (input, init) => {
    const url = new URL(String(input), "http://localhost");
    const route = url.pathname;
    requests.push({ path: route + url.search, method: init?.method || "GET" });
    if (route.endsWith(`/tasks/${task.id}`)) {
      if (init?.method === "PATCH") {
        patches.push(init);
        await patchHandlers.shift()?.();
        const body = JSON.parse(String(init.body));
        record = {
          ...record,
          state: body.state,
          row_version: record.row_version + 1,
        };
      }
      return Response.json(record);
    }
    if (
      route.endsWith("/activity") ||
      route.endsWith("/artifacts") ||
      route.endsWith("/agent-sessions")
    )
      return Response.json(emptyPage);
    if (route.endsWith("/agents/profiles")) return Response.json([]);
    throw new Error(`Unexpected synthetic request: ${route}`);
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <RecordDetail resource="tasks" id={task.id} onClose={vi.fn()} />
    </QueryClientProvider>,
  );
  return { patches, requests, client };
}

describe("task inspector integration", () => {
  it("marks waiting and resumes with the current record version without starting agent work", async () => {
    const { patches, requests } = mountInspector();
    fireEvent.click(
      await screen.findByRole("button", { name: "Mark waiting" }),
    );
    const resume = await screen.findByRole("button", { name: "Resume task" });
    expect(screen.getByText("Waiting")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Mark waiting" }),
    ).not.toBeInTheDocument();
    fireEvent.click(resume);
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "Resume task" }),
      ).not.toBeInTheDocument(),
    );
    expect(patches.map((patch) => JSON.parse(String(patch.body)))).toEqual([
      { state: "waiting", expected_version: 7 },
      { state: "in_progress", expected_version: 8 },
    ]);
    expect(
      requests
        .filter(({ method }) => method !== "GET")
        .map(({ method }) => method),
    ).toEqual(["PATCH", "PATCH"]);
    expect(
      requests.some(({ path }) =>
        /agent-runs|agent-sessions|agents\/profiles/.test(path),
      ),
    ).toBe(false);
  });

  it("reuses the retained update identity after a lost reply and sends the next current record version", async () => {
    const lostResponse = async () => {
      throw new Error("Synthetic lost response");
    };
    const { patches, requests } = mountInspector([lostResponse, lostResponse]);
    fireEvent.click(await screen.findByRole("button", { name: "Start task" }));
    await waitFor(() => expect(patches).toHaveLength(2));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Start task" })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Start task" }));
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "Start task" }),
      ).not.toBeInTheDocument(),
    );
    expect(
      patches.slice(0, 3).map((patch) => JSON.parse(String(patch.body))),
    ).toEqual([
      { expected_version: 7, state: "in_progress" },
      { expected_version: 7, state: "in_progress" },
      { expected_version: 7, state: "in_progress" },
    ]);
    expect(new Headers(patches[0].headers).get("Idempotency-Key")).toBeTruthy();
    expect(new Headers(patches[0].headers).get("Idempotency-Key")).toBe(
      new Headers(patches[2].headers).get("Idempotency-Key"),
    );
    fireEvent.click(screen.getByRole("button", { name: "Complete task" }));
    await screen.findByRole("button", { name: "Reopen task" });
    expect(JSON.parse(String(patches[3].body))).toEqual({
      expected_version: 8,
      state: "done",
    });
    expect(requests.some((request) => request.method === "POST")).toBe(false);
  });

  it("freezes task actions until the existing update mutation settles", async () => {
    let release!: () => void;
    const pending = new Promise<void>((resolve) => {
      release = resolve;
    });
    const { patches } = mountInspector([() => pending]);
    fireEvent.click(await screen.findByRole("button", { name: "Start task" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Snooze" })).toBeDisabled(),
    );
    expect(
      screen.getByRole("button", { name: "Open conversation" }),
    ).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Snooze" }));
    expect(patches).toHaveLength(1);
    await act(async () => {
      release();
    });
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Complete task" }),
      ).toBeEnabled(),
    );
  });

  it("opens the canonical task conversation without a write, prompt or agent run", async () => {
    const { requests, patches } = mountInspector();
    fireEvent.click(
      await screen.findByRole("button", { name: "Open conversation" }),
    );
    expect(screen.getByRole("tab", { name: "Conversation" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await waitFor(() =>
      expect(
        requests.some((request) =>
          request.path.includes(`agent-sessions?task_id=${task.id}&limit=1`),
        ),
      ).toBe(true),
    );
    expect(patches).toHaveLength(0);
    expect(requests.every((request) => request.method === "GET")).toBe(true);
  });
});
