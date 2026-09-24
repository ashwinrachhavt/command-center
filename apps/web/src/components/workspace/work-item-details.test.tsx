import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Run, Schema } from "@/lib/api";
import { WorkItemDetails, type WorkQueueItem } from "./work-item-details";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ isLoaded: true, userId: "synthetic-owner" }),
}));

const updated = "2026-09-22T12:00:00Z";
const action: Schema["ActionRead"] = {
  id: "11111111-1111-4111-8111-111111111111",
  row_version: 3,
  kind: "gmail_send",
  state: "proposed",
  account: {
    id: "22222222-2222-4222-8222-222222222222",
    row_version: 1,
    toolkit: "gmail",
    display_name: "Synthetic mail account",
    provider_identity: { email: "owner@example.test" },
    connection_status: "ACTIVE",
    identity_verified_at: updated,
    selected_purpose: "outreach",
  },
  task_id: null,
  opportunity_id: null,
  current: {
    id: "33333333-3333-4333-8333-333333333333",
    version: 2,
    tool_slug: "gmail_send",
    toolkit_version: "synthetic-version",
    payload: {
      kind: "gmail_send",
      to: ["recipient@example.test"],
      subject: "Synthetic proposal",
      body: "Saved message for review.",
    },
    payload_hash: "synthetic-hash",
    source_version_id: null,
    source_content_sha256: null,
    attachments: [],
    expected_remote_revision: null,
    observed_target: null,
    expires_at: null,
    delivery: null,
    scheduled_for: null,
    review_state: "unreviewed",
    reason: "A synthetic follow-up is ready for review.",
    created_at: updated,
  },
  approved_revision_id: null,
  attempt: null,
  conditional_update_notice: null,
  created_at: updated,
  updated_at: updated,
};

const run: Run = {
  id: "44444444-4444-4444-8444-444444444444",
  row_version: 2,
  created_at: updated,
  updated_at: updated,
  title: "Synthetic standalone research",
  prompt: "Find the next useful step.",
  profile: "research",
  state: "completed",
  output: "The saved research result.",
  error_code: null,
  completed_at: updated,
  session_id: null,
  input_sequence: 0,
  consumed_sequence: 0,
};

const question: Schema["QuestionRead"] = {
  id: "66666666-6666-4666-8666-666666666666",
  row_version: 1,
  run_id: run.id,
  session_id: "77777777-7777-4777-8777-777777777777",
  interrupt_id: "synthetic-interrupt",
  branch_id: "synthetic-branch",
  role: "research",
  tool_call_id: "synthetic-tool-call",
  prompt: "Which synthetic topic should I research?",
  state: "open",
  answer: null,
  created_at: updated,
  answered_at: null,
};

function item(
  kind: WorkQueueItem["kind"],
  overrides: Partial<WorkQueueItem> = {},
): WorkQueueItem {
  return {
    id: kind === "action" ? action.id : run.id,
    kind,
    title: "Synthetic work item",
    state: kind === "action" ? "proposed" : "completed",
    updated_at: updated,
    task_id: null,
    opportunity_id: null,
    run_id: null,
    artifact_id: null,
    version_id: null,
    detail: "A saved summary to review.",
    action_kind: null,
    ...overrides,
  };
}

function mount(
  work: WorkQueueItem,
  reads: Array<Response | Promise<Response>> = [],
  questions: Schema["QuestionRead"][] = [],
) {
  const close = vi.fn();
  const requests: Array<{ path: string; method: string }> = [];
  const fetch = vi
    .spyOn(global, "fetch")
    .mockImplementation(async (input, init) => {
      const path = String(input);
      requests.push({ path, method: init?.method || "GET" });
      if (path.endsWith(`/reviewed-actions/${action.id}`))
        return reads.shift() ?? Response.json(action);
      if (path.endsWith(`/agent-runs/${run.id}`))
        return reads.shift() ?? Response.json(run);
      if (path.endsWith(`/agent-runs/${run.id}/steps`))
        return Response.json([]);
      if (path.endsWith(`/agent-runs/${run.id}/questions`))
        return Response.json(questions);
      if (path.endsWith(`/agent-runs/${run.id}/artifacts?limit=100`))
        return Response.json({ items: [], total: 0, limit: 100, offset: 0 });
      throw new Error(`Unexpected synthetic request: ${path}`);
    });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <WorkItemDetails item={work} close={close} />
    </QueryClientProvider>,
  );
  return { close, requests, fetch, client };
}

describe("contextual reviewed actions", () => {
  it("fetches the exact action and reuses its explicit approval controls without writing", async () => {
    const { requests, close } = mount(item("action"));
    expect(
      await screen.findByRole("dialog", { name: "Send an email" }),
    ).toBeVisible();
    expect(screen.getByText("Saved message for review.")).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Approve & send" }),
    ).toBeDisabled();
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    expect(requests.length).toBeGreaterThan(0);
    expect(
      requests.every(
        (request) =>
          request.method === "GET" &&
          request.path === `/api/backend/reviewed-actions/${action.id}`,
      ),
    ).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(close).toHaveBeenCalledOnce();
  });

  it("keeps an accessible action dialog open while the exact read is pending", async () => {
    let resolve!: (response: Response) => void;
    const pending = new Promise<Response>((done) => {
      resolve = done;
    });
    const { requests } = mount(item("action"), [pending]);
    expect(screen.getByRole("dialog", { name: "Review action" })).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Loading reviewed action",
    );
    expect(
      screen.queryByRole("button", { name: "Approve & queue" }),
    ).not.toBeInTheDocument();
    await act(async () => {
      resolve(Response.json(action));
    });
    expect(
      await screen.findByRole("dialog", { name: "Send an email" }),
    ).toBeVisible();
    expect(requests.every((request) => request.method === "GET")).toBe(true);
  });

  it("shows a failed owned action read and retries the same exact action", async () => {
    const { requests } = mount(item("action"), [
      Response.json({ detail: "Action unavailable" }, { status: 404 }),
    ]);
    expect(await screen.findByText("Action unavailable")).toBeVisible();
    expect(screen.getByRole("dialog", { name: "Review action" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(
      await screen.findByRole("dialog", { name: "Send an email" }),
    ).toBeVisible();
    expect(
      requests.every(
        (request) =>
          request.method === "GET" &&
          request.path.endsWith(`/reviewed-actions/${action.id}`),
      ),
    ).toBe(true);
  });
});

describe("standalone run details", () => {
  it.each(["run", "question"] as const)(
    "uses the exact linked run for a %s and shows existing activity and output",
    async (kind) => {
      const work = item(kind, {
        id: "55555555-5555-4555-8555-555555555555",
        run_id: run.id,
      });
      const { requests } = mount(work);
      expect(await screen.findByText(run.output!)).toBeVisible();
      expect(
        screen.getByRole("region", { name: `${run.title} activity` }),
      ).toBeVisible();
      expect(requests[0]).toEqual({
        path: `/api/backend/agent-runs/${run.id}`,
        method: "GET",
      });
      expect(requests.every((request) => request.method === "GET")).toBe(true);
      expect(
        screen.queryByRole("button", { name: "Cancel work" }),
      ).not.toBeInTheDocument();
    },
  );

  it("uses a run item's own ID when no separate run ID is provided", async () => {
    const { requests } = mount(item("run"));
    expect(await screen.findByText(run.output!)).toBeVisible();
    expect(requests[0].path).toBe(`/api/backend/agent-runs/${run.id}`);
  });

  it("does not infer a run ID from a question with no linked run", () => {
    const { fetch } = mount(item("question"));
    expect(
      screen.getByText("This item has no linked agent run."),
    ).toBeVisible();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("opens the existing saved-question UI without sending an answer or resuming work", async () => {
    const { requests } = mount(
      item("question", { id: question.id, run_id: run.id }),
      [Response.json({ ...run, state: "waiting_for_user", output: null })],
      [question],
    );
    expect(await screen.findByText(question.prompt)).toBeVisible();
    expect(
      screen.getByRole("textbox", { name: "Answer Research question" }),
    ).toHaveValue("");
    expect(screen.getByRole("button", { name: "Answer" })).toBeDisabled();
    expect(
      requests.some((request) =>
        request.path.endsWith(`/agent-runs/${run.id}/questions`),
      ),
    ).toBe(true);
    expect(requests.every((request) => request.method === "GET")).toBe(true);
  });

  it("shows accessible loading and supports retrying an unavailable run", async () => {
    let resolve!: (response: Response) => void;
    const pending = new Promise<Response>((done) => {
      resolve = done;
    });
    const { requests } = mount(item("run"), [pending]);
    expect(
      screen.getByRole("dialog", { name: "Synthetic work item" }),
    ).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Loading agent activity",
    );
    await act(async () => {
      resolve(Response.json({ detail: "Run unavailable" }, { status: 404 }));
    });
    expect(await screen.findByText("Run unavailable")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText(run.output!)).toBeVisible();
    expect(requests.every((request) => request.method === "GET")).toBe(true);
  });

  it("retains saved output when a later refresh fails", async () => {
    const { client } = mount(item("run"), [
      Response.json(run),
      Response.json({ detail: "Refresh unavailable" }, { status: 404 }),
    ]);
    expect(await screen.findByText(run.output!)).toBeVisible();
    await act(async () => {
      await client.invalidateQueries({ queryKey: ["agent-run", run.id] });
    });
    expect(await screen.findByText("Refresh unavailable")).toBeVisible();
    expect(screen.getByText(run.output!)).toBeVisible();
  });
});

it("shows the saved browser summary and an explicit Browser link without claiming a connection or executing commands", () => {
  const work = item("browser", {
    title: "Synthetic browser fill",
    state: "outcome_unknown",
    detail: "The last saved fill requires manual review.",
  });
  const { fetch } = mount(work);
  expect(screen.getByRole("dialog", { name: work.title })).toBeVisible();
  expect(screen.getByText("Outcome unknown")).toBeVisible();
  expect(screen.getByText(work.detail)).toBeVisible();
  expect(screen.getByText("Sep 22")).toHaveAttribute("datetime", updated);
  expect(screen.getByRole("link", { name: "Open Browser" })).toHaveAttribute(
    "href",
    "/browser",
  );
  expect(
    screen.queryByText(/disconnected|connecting|progress/i),
  ).not.toBeInTheDocument();
  expect(fetch).not.toHaveBeenCalled();
});
