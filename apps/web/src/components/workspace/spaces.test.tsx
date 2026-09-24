import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { SpaceDetail } from "@/lib/api";
import { QuickCapture } from "./briefing";
import { Spaces } from "./spaces";

const { open } = vi.hoisted(() => ({ open: vi.fn() }));
vi.mock("./context", () => ({ useWorkspaceContext: () => ({ open }) }));
vi.mock("./daily-work", () => ({
  DailyTasks: () => null,
  WorkQueues: () => null,
}));
vi.mock("./activity-list", () => ({ ActivityList: () => null }));
vi.mock("next/link", () => ({
  default: ({ children, ...props }: React.ComponentProps<"a">) => (
    <a {...props}>{children}</a>
  ),
}));

const active: SpaceDetail = {
  id: "space-active",
  title: "Synthetic research",
  purpose: "Understand the next useful step.",
  state: "active",
  row_version: 3,
  archived_at: null,
  created_at: "2026-09-24T00:00:00Z",
  updated_at: "2026-09-24T00:00:00Z",
  links: [],
};
const archived: SpaceDetail = {
  ...active,
  id: "space-archived",
  title: "Synthetic archive",
  state: "archived",
  archived_at: active.created_at,
};
const task = {
  id: "task-capture",
  title: "Read the research",
  state: "open",
  row_version: 1,
  priority: 1,
  rationale: "Read the research\nKeep this context.",
  created_at: active.created_at,
  updated_at: active.created_at,
  due_date: null,
  completed_at: null,
};

function mount(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={client}>{ui}</QueryClientProvider>,
  );
  return { client, ...view };
}

function mockCapture(failures = 0) {
  const writes: {
    path: string;
    key: string | null;
    body: Record<string, unknown>;
  }[] = [];
  vi.spyOn(global, "fetch").mockImplementation(async (input, init) => {
    const path = String(input).replace("/api/backend/", "");
    if (init?.method === "POST") {
      writes.push({
        path,
        key: new Headers(init.headers).get("Idempotency-Key"),
        body: JSON.parse(String(init.body)),
      });
      if (failures-- > 0) throw new TypeError("Connection lost");
      return Response.json(
        path.startsWith("spaces/")
          ? { task, space: { ...active, row_version: 4 } }
          : task,
      );
    }
    return Response.json({
      items: [active, archived],
      total: 2,
      limit: 100,
      offset: 0,
    });
  });
  return writes;
}

async function selectSpace(name: string) {
  const user = userEvent.setup();
  const trigger = await screen.findByRole("combobox", {
    name: "Space (optional)",
  });
  await waitFor(() => expect(trigger).toBeEnabled());
  fireEvent.keyDown(trigger, { key: "ArrowDown" });
  await user.click(await screen.findByRole("option", { name }));
}

describe("Space capture", () => {
  it("keeps ordinary capture available without a Space", async () => {
    const writes = mockCapture();
    mount(<QuickCapture />);
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: task.rationale },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create task" }));
    await screen.findByText("Captured:");
    expect(writes).toHaveLength(1);
    expect(writes[0]).toMatchObject({
      path: "tasks",
      body: {
        title: "Read the research",
        rationale: task.rationale,
        priority: 1,
      },
    });
  });

  it("creates one task atomically in the selected active Space and opens the saved task", async () => {
    const writes = mockCapture();
    mount(<QuickCapture />);
    await selectSpace("Synthetic research");
    expect(
      screen.queryByRole("option", { name: "Synthetic archive" }),
    ).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: task.rationale },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create task" }));
    await screen.findByText("Captured:");
    expect(writes).toHaveLength(1);
    expect(writes[0]).toMatchObject({
      path: "spaces/space-active/tasks?expected_version=3",
      body: {
        title: "Read the research",
        rationale: task.rationale,
        priority: 1,
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Open task" }));
    expect(open).toHaveBeenCalledWith("tasks", task.id);
  });

  it("retains the Space target, version, key and draft after a lost response", async () => {
    const writes = mockCapture(2);
    const view = mount(<QuickCapture space={active} />);
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: task.rationale },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create task" }));
    await screen.findByRole("alert");
    expect(screen.getByRole("textbox")).toHaveValue(task.rationale);
    view.rerender(
      <QueryClientProvider client={view.client}>
        <QuickCapture space={{ ...active, row_version: 4 }} />
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Create task" }));
    await screen.findByText("Captured:");
    expect(writes).toHaveLength(3);
    expect(new Set(writes.map((write) => write.key)).size).toBe(1);
    expect(new Set(writes.map((write) => write.path))).toEqual(
      new Set(["spaces/space-active/tasks?expected_version=3"]),
    );
  });

  it("uses a new request identity when the destination changes", async () => {
    const writes = mockCapture(2);
    const view = mount(<QuickCapture space={active} />);
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: task.rationale },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create task" }));
    await screen.findByRole("alert");
    view.rerender(
      <QueryClientProvider client={view.client}>
        <QuickCapture space={{ ...active, id: "another-space" }} />
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Create task" }));
    await screen.findByText("Captured:");
    expect(writes[2].path).toBe(
      "spaces/another-space/tasks?expected_version=3",
    );
    expect(writes[2].key).not.toBe(writes[0].key);
  });

  it("blocks capture in an archived Space", () => {
    const writes = mockCapture();
    mount(<QuickCapture space={archived} />);
    expect(screen.getByRole("textbox")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Create task" })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Upload document" }),
    ).toBeDisabled();
    expect(writes).toHaveLength(0);
  });
});

describe("Spaces page", () => {
  it("creates, edits, archives and restores a Space with its version fence", async () => {
    let current: SpaceDetail | null = null;
    const writes: { path: string; body: Record<string, unknown> }[] = [];
    vi.spyOn(global, "fetch").mockImplementation(async (input, init) => {
      const url = new URL(String(input), "http://localhost");
      const path = url.pathname.replace("/api/backend/", "");
      if (init?.method !== "GET") {
        const body = JSON.parse(String(init?.body));
        writes.push({ path, body });
        current = current
          ? { ...current, row_version: current.row_version + 1 }
          : {
              ...active,
              title: body.title,
              purpose: body.purpose,
              row_version: 1,
            };
        if (init?.method === "PATCH") {
          current.title = body.title;
          current.purpose = body.purpose;
        }
        if (path.endsWith("/archive")) current.state = "archived";
        if (path.endsWith("/restore")) current.state = "active";
        return Response.json(current);
      }
      if (path === "spaces")
        return Response.json({
          items:
            current && current.state === url.searchParams.get("state")
              ? [current]
              : [],
          total: current ? 1 : 0,
          limit: 25,
          offset: 0,
        });
      return Response.json(current);
    });
    mount(<Spaces />);
    fireEvent.click(screen.getByRole("button", { name: "New Space" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), {
      target: { value: "Synthetic planning" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Purpose" }), {
      target: { value: "Make the next step clear." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create Space" }));
    await screen.findByRole("heading", { name: "Synthetic planning" });
    fireEvent.click(screen.getByRole("button", { name: "Edit Space" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Purpose" }), {
      target: { value: "Keep the decision with its evidence." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(writes[1].body).toMatchObject({
      expected_version: 1,
      purpose: "Keep the decision with its evidence.",
    });
    fireEvent.click(screen.getByRole("button", { name: "Archive Space" }));
    await screen.findByRole("button", { name: "Restore Space" });
    expect(
      screen.queryByRole("button", { name: "Create task" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Link existing record" }),
    ).not.toBeInTheDocument();
    expect(writes[2].body).toEqual({ expected_version: 2 });
    fireEvent.click(screen.getByRole("button", { name: "Restore Space" }));
    await screen.findByRole("button", { name: "Archive Space" });
    expect(writes[3].body).toEqual({ expected_version: 3 });
    expect(
      screen.getByRole("button", { name: "Link existing record" }),
    ).toBeEnabled();
  });
});
