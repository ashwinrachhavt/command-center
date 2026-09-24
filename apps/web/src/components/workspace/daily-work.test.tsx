import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import * as apiModule from "@/lib/api";
import { DailyTasks, WorkQueues } from "./daily-work";
import { Overview } from "./overview";
import type { WorkQueueItem } from "./work-item-details";

const open = vi.hoisted(() => vi.fn());
vi.mock("./context", () => ({ useWorkspaceContext: () => ({ open }) }));
vi.mock("./work-item-details", () => ({
  WorkItemDetails: ({
    item,
    close,
  }: {
    item: WorkQueueItem;
    close: () => void;
  }) => (
    <div role="dialog" aria-label={item.title} data-item-id={item.id}>
      <button onClick={close}>Close details</button>
    </div>
  ),
}));
vi.mock("./record-editor", () => ({
  stages: ["researching", "interviewing"],
  RecordEditor: ({ resource }: { resource: string }) => (
    <div role="dialog" aria-label={`New ${resource}`} />
  ),
}));

type DailyTask = apiModule.Schema["DailyTaskRead"];
const task: DailyTask = {
  id: "task-1",
  title: "Prepare synthetic follow-up",
  state: "open",
  priority: 2,
  row_version: 7,
  created_at: "2026-09-20T10:00:00Z",
  updated_at: "2026-09-22T10:00:00Z",
  rationale: "Review the research before writing.",
  due_date: "2026-09-21",
  due_at: null,
  due_status: "overdue",
  completed_at: null,
};
const work = (
  kind: WorkQueueItem["kind"],
  overrides: Partial<WorkQueueItem> = {},
): WorkQueueItem => ({
  id: `${kind}-1`,
  kind,
  title: `Synthetic ${kind}`,
  state: "waiting_for_user",
  updated_at: "2026-09-22T10:00:00Z",
  task_id: null,
  opportunity_id: null,
  run_id: null,
  artifact_id: null,
  version_id: null,
  action_kind: null,
  detail: "Saved context for this work",
  ...overrides,
});
const daily = (items = [task], extra = {}) => ({
  items,
  total: items.length,
  limit: 6,
  offset: 0,
  timezone: "America/Los_Angeles",
  today: "2026-09-22",
  counts: { today: 1, upcoming: 0, unscheduled: 0, waiting: 0, snoozed: 0 },
  ...extra,
});
const page = (items: WorkQueueItem[] = [], extra = {}) => ({
  items,
  total: items.length,
  limit: 6,
  offset: 0,
  ...extra,
});

function mount(child: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return {
    client,
    ...render(
      <QueryClientProvider client={client}>{child}</QueryClientProvider>,
    ),
  };
}
function queryRoute(path: string) {
  return new URL(path, "https://synthetic.invalid/");
}
function defaults(path: string) {
  if (path === "me") return { timezone: "America/Los_Angeles" };
  if (path === "dashboard")
    return {
      counts: { tasks: 1, opportunities: 1 },
      stages: { researching: 1 },
      tasks: [task],
    };
  if (path.startsWith("dashboard/tasks?")) return daily();
  if (path.startsWith("dashboard/work?")) return page();
  if (path.startsWith("activity?")) return page();
  throw new Error(`Unexpected read ${path}`);
}
beforeEach(() => open.mockReset());

it("mounts the daily work on Overview and keeps new-task creation explicit", async () => {
  const api = vi
    .spyOn(apiModule, "api")
    .mockImplementation(async (path) => defaults(path));
  mount(<Overview />);
  expect(
    await screen.findByRole("button", { name: task.title }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: /^Needs attention/ }),
  ).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: /^Running/ })).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: /^Recent outputs/ }),
  ).toBeInTheDocument();
  expect(api.mock.calls.every(([, options]) => !options?.method)).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "New task" }));
  expect(screen.getByRole("dialog", { name: "New tasks" })).toBeInTheDocument();
  expect(api.mock.calls.every(([, options]) => !options?.method)).toBe(true);
});

it("uses the saved timezone, truthful due labels and contextual task opening", async () => {
  const api = vi
    .spyOn(apiModule, "api")
    .mockImplementation(async (path) => defaults(path));
  mount(<DailyTasks />);
  fireEvent.click(await screen.findByRole("button", { name: task.title }));
  expect(open).toHaveBeenCalledExactlyOnceWith("tasks", task.id);
  expect(screen.getByText(/Overdue/)).toBeInTheDocument();
  expect(screen.getByText("Sep 21")).toHaveAttribute("datetime", "2026-09-21");
  expect(
    screen.getByText(/Due today and overdue · America\/Los_Angeles/),
  ).toBeInTheDocument();
  const path = api.mock.calls.find(([path]) =>
    path.startsWith("dashboard/tasks?"),
  )![0];
  expect(queryRoute(path).searchParams.get("timezone")).toBe(
    "America/Los_Angeles",
  );
  expect(queryRoute(path).searchParams.get("view")).toBe("today");
  expect(api.mock.calls.every(([, options]) => !options?.method)).toBe(true);
});

it("formats instant deadlines in the requested timezone without shifting date-only deadlines", async () => {
  vi.spyOn(apiModule, "api").mockImplementation(async (path) =>
    path.startsWith("dashboard/tasks?")
      ? daily([
          {
            ...task,
            due_date: null,
            due_at: "2026-09-23T01:30:00Z",
            due_status: "today",
          },
        ])
      : defaults(path),
  );
  mount(<DailyTasks />);
  const deadline = await screen.findByText(/Sep 22.*6:30/);
  expect(deadline).toHaveAttribute("datetime", "2026-09-23T01:30:00Z");
  expect(screen.queryByText(/Overdue/)).not.toBeInTheDocument();
});

it("paginates tasks and resets to the first page when changing view", async () => {
  const api = vi.spyOn(apiModule, "api").mockImplementation(async (path) => {
    if (!path.startsWith("dashboard/tasks?")) return defaults(path);
    const params = queryRoute(path).searchParams;
    return daily(
      [
        {
          ...task,
          title: `${params.get("view")} page ${params.get("offset")}`,
        },
      ],
      {
        total: 8,
        counts: {
          today: 8,
          upcoming: 1,
          unscheduled: 0,
          waiting: 0,
          snoozed: 0,
        },
      },
    );
  });
  mount(<DailyTasks />);
  await screen.findByRole("button", { name: "today page 0" });
  fireEvent.click(
    within(
      screen.getByRole("navigation", { name: "Today tasks pages" }),
    ).getByRole("button", { name: "Next" }),
  );
  expect(
    await screen.findByRole("button", { name: "today page 6" }),
  ).toBeInTheDocument();
  fireEvent.mouseDown(screen.getByRole("tab", { name: /^Upcoming/ }), {
    button: 0,
    ctrlKey: false,
  });
  expect(
    await screen.findByRole("button", { name: "upcoming page 0" }),
  ).toBeInTheDocument();
  expect(api.mock.calls.every(([, options]) => !options?.method)).toBe(true);
});

it("retains the exact completion request after an uncertain failure and disables pending changes", async () => {
  let finish: (value: unknown) => void = () => {};
  let calls = 0;
  const api = vi
    .spyOn(apiModule, "api")
    .mockImplementation(async (path, options) => {
      if (options?.method === "PATCH") {
        calls += 1;
        if (calls === 1) throw new Error("Connection lost");
        return new Promise((resolve) => {
          finish = resolve;
        });
      }
      return defaults(path);
    });
  mount(<DailyTasks />);
  const button = await screen.findByRole("button", {
    name: `Complete ${task.title}`,
  });
  fireEvent.click(button);
  await waitFor(() => expect(calls).toBe(1));
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
  await waitFor(() => expect(button).toBeDisabled());
  const writes = api.mock.calls.filter(
    ([, options]) => options?.method === "PATCH",
  );
  expect(writes).toHaveLength(2);
  expect(writes[0]).toEqual(writes[1]);
  expect(writes[0][1]).toMatchObject({
    method: "PATCH",
    body: { state: "done", expected_version: 7 },
    key: expect.any(String),
  });
  await act(async () => finish({ ...task, state: "done", row_version: 8 }));
});

it("resumes snoozed tasks without claiming a timed reminder or starting an agent", async () => {
  const api = vi
    .spyOn(apiModule, "api")
    .mockImplementation(async (path, options) => {
      if (options?.method === "PATCH") return { ...task, state: "in_progress" };
      if (path.startsWith("dashboard/tasks?"))
        return queryRoute(path).searchParams.get("view") === "snoozed"
          ? daily([{ ...task, state: "snoozed" }])
          : daily([]);
      return defaults(path);
    });
  mount(<DailyTasks />);
  await screen.findByText("No tasks due today");
  fireEvent.mouseDown(screen.getByRole("tab", { name: /^Snoozed/ }), {
    button: 0,
    ctrlKey: false,
  });
  fireEvent.click(
    await screen.findByRole("button", { name: `Resume ${task.title}` }),
  );
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      `tasks/${task.id}`,
      expect.objectContaining({
        body: { state: "in_progress", expected_version: 7 },
      }),
    ),
  );
  expect(
    api.mock.calls.some(([path]) =>
      /agent-runs|conversations|gmail/.test(path),
    ),
  ).toBe(false);
  expect(screen.getByText(/Paused until you resume them/)).toBeInTheDocument();
});

it("keeps waiting tasks separate and resumes them without starting an agent", async () => {
  let resumed = false;
  const api = vi
    .spyOn(apiModule, "api")
    .mockImplementation(async (path, options) => {
      if (options?.method === "PATCH") {
        resumed = true;
        return { ...task, state: "in_progress", row_version: 8 };
      }
      if (path.startsWith("dashboard/tasks?"))
        return daily(
          queryRoute(path).searchParams.get("view") === "waiting" && !resumed
            ? [{ ...task, state: "waiting" }]
            : [],
          {
            counts: {
              today: 0,
              upcoming: 0,
              unscheduled: 0,
              waiting: resumed ? 0 : 1,
              snoozed: 0,
            },
          },
        );
      return defaults(path);
    });
  mount(<DailyTasks />);
  await screen.findByText("No tasks due today");
  fireEvent.mouseDown(screen.getByRole("tab", { name: /^Waiting\s*1/ }), {
    button: 0,
    ctrlKey: false,
  });
  fireEvent.click(
    await screen.findByRole("button", { name: `Resume ${task.title}` }),
  );
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      `tasks/${task.id}`,
      expect.objectContaining({
        method: "PATCH",
        body: { state: "in_progress", expected_version: 7 },
        key: expect.any(String),
      }),
    ),
  );
  await waitFor(() =>
    expect(
      screen.queryByRole("button", { name: task.title }),
    ).not.toBeInTheDocument(),
  );
  expect(api.mock.calls.filter(([, options]) => options?.method)).toHaveLength(
    1,
  );
  expect(
    api.mock.calls.some(([path]) =>
      /agent-runs|conversations|gmail/.test(path),
    ),
  ).toBe(false);
});

it("opens questions in their conversation, outputs at their exact version and actions in the existing review", async () => {
  const question = work("question", { task_id: "task-2", run_id: "run-2" });
  const output = work("artifact", {
    state: "unreviewed",
    artifact_id: "document-3",
    version_id: "version-4",
    task_id: "task-3",
  });
  const action = work("action", {
    state: "proposed",
    action_kind: "gmail_send",
    task_id: "task-2",
  });
  const api = vi
    .spyOn(apiModule, "api")
    .mockImplementation(async (path) =>
      page(
        queryRoute(path).searchParams.get("lane") === "attention"
          ? [question, action]
          : queryRoute(path).searchParams.get("lane") === "outputs"
            ? [output]
            : [],
      ),
    );
  mount(<WorkQueues />);
  fireEvent.click(
    await screen.findByRole("button", { name: `Open ${question.title}` }),
  );
  expect(open).toHaveBeenLastCalledWith("tasks", "task-2", {
    tab: "conversation",
  });
  fireEvent.click(screen.getByRole("button", { name: `Open ${output.title}` }));
  expect(open).toHaveBeenLastCalledWith("artifacts", "document-3", {
    tab: "content",
    versionId: "version-4",
  });
  fireEvent.click(screen.getByRole("button", { name: `Open ${action.title}` }));
  expect(
    await screen.findByRole("dialog", { name: action.title }),
  ).toHaveAttribute("data-item-id", action.id);
  expect(open).toHaveBeenCalledTimes(2);
  expect(api.mock.calls.every(([, options]) => !options?.method)).toBe(true);
});

it("opens opportunity work contextually and standalone/browser work in details", async () => {
  const opportunity = work("run", { opportunity_id: "opportunity-2" });
  const standalone = work("run", {
    id: "standalone",
    title: "Independent research",
  });
  const browser = work("browser", {
    state: "outcome_unknown",
    task_id: "task-2",
  });
  vi.spyOn(apiModule, "api").mockImplementation(async (path) =>
    page(
      queryRoute(path).searchParams.get("lane") === "attention"
        ? [opportunity, standalone, browser]
        : [],
    ),
  );
  mount(<WorkQueues />);
  fireEvent.click(
    await screen.findByRole("button", { name: `Open ${opportunity.title}` }),
  );
  expect(open).toHaveBeenCalledExactlyOnceWith(
    "opportunities",
    "opportunity-2",
    { tab: "conversation" },
  );
  fireEvent.click(
    screen.getByRole("button", { name: `Open ${standalone.title}` }),
  );
  expect(
    await screen.findByRole("dialog", { name: standalone.title }),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Close details" }));
  fireEvent.click(
    screen.getByRole("button", { name: `Open ${browser.title}` }),
  );
  expect(
    await screen.findByRole("dialog", { name: browser.title }),
  ).toBeInTheDocument();
  expect(open).toHaveBeenCalledTimes(1);
});

it("keeps failed lanes visible and retries independently without hiding running work", async () => {
  let attentionCalls = 0;
  const api = vi.spyOn(apiModule, "api").mockImplementation(async (path) => {
    const lane = queryRoute(path).searchParams.get("lane");
    if (lane === "attention" && ++attentionCalls === 1)
      throw new Error("Queue unavailable");
    return page(lane === "running" ? [work("run", { state: "running" })] : []);
  });
  mount(<WorkQueues />);
  const attention = screen.getByRole("region", { name: "Needs attention" });
  expect(
    await within(attention).findByText("Queue unavailable"),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Open Synthetic run" }),
  ).toBeInTheDocument();
  expect(
    within(attention).queryByText("Nothing needs your attention"),
  ).not.toBeInTheDocument();
  fireEvent.click(within(attention).getByRole("button", { name: "Try again" }));
  expect(
    await within(attention).findByText("Nothing needs your attention"),
  ).toBeInTheDocument();
  expect(
    api.mock.calls.filter(
      ([path]) => queryRoute(path).searchParams.get("lane") === "running",
    ),
  ).toHaveLength(1);
});

it("paginates each work lane independently and makes empty later pages recoverable", async () => {
  const api = vi.spyOn(apiModule, "api").mockImplementation(async (path) => {
    const params = queryRoute(path).searchParams;
    return params.get("lane") === "attention"
      ? page(params.get("offset") === "0" ? [work("action")] : [], {
          total: params.get("offset") === "0" ? 8 : 1,
        })
      : page();
  });
  mount(<WorkQueues />);
  await screen.findByRole("button", { name: "Open Synthetic action" });
  fireEvent.click(
    within(
      screen.getByRole("navigation", { name: "Needs attention pages" }),
    ).getByRole("button", { name: "Next" }),
  );
  expect(
    await screen.findByText("Return to the previous page to see your work."),
  ).toBeInTheDocument();
  const pages = screen.getByRole("navigation", {
    name: "Needs attention pages",
  });
  expect(within(pages).getByRole("button", { name: "Previous" })).toBeEnabled();
  expect(within(pages).getByRole("button", { name: "Next" })).toBeDisabled();
  expect(
    api.mock.calls.filter(
      ([path]) => queryRoute(path).searchParams.get("lane") === "outputs",
    ),
  ).toHaveLength(1);
});
