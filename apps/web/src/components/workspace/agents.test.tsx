import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { AgentMessage, AgentSession, Run, RunStep } from "@/lib/api";
import { Agents } from "./agents";

vi.mock("next/navigation", async () => {
  const navigation = await import("../../../tests/fixtures/navigation");
  return {
    ...navigation,
    useRouter: () => ({
      push: (url: string) => {
        window.history.pushState(null, "", url);
        window.dispatchEvent(new PopStateEvent("popstate"));
      },
    }),
  };
});

const base = {
  row_version: 1,
  created_at: "2026-09-21T10:00:00Z",
  updated_at: "2026-09-21T10:00:00Z",
};
const profile = {
  id: "lead",
  name: "Command Center",
  description: "Synthetic profile",
  provider: "openai",
  model: "synthetic-model",
  ready: true,
  missing_credentials: [],
  tools: [],
  skills: [],
  revision: "profile-revision",
};
const session: AgentSession = {
  ...base,
  id: "chat-1",
  title: "Synthetic chat",
  task_id: null,
  opportunity_id: null,
  last_sequence: 2,
};
const run = {
  ...base,
  id: "run-1",
  title: "Synthetic run",
  prompt: "Research safely",
  profile: "lead",
  state: "completed",
  output: "Complete",
  error_code: null,
  completed_at: "2026-09-21T10:01:00Z",
  session_id: session.id,
  input_sequence: 1,
  consumed_sequence: 1,
} as Run;
const savedMessage = (
  sequence: number,
  content: string,
  author: "user" | "assistant" = "user",
): AgentMessage => ({
  ...base,
  id: `m${sequence}`,
  session_id: session.id,
  run_id: run.id,
  sequence,
  author,
  profile: profile.id,
  content,
});
const page = <T,>(
  items: T[],
  total = items.length,
  offset = 0,
  limit = 30,
) => ({ items, total, offset, limit });

beforeEach(() => window.history.replaceState(null, "", "/"));

function mount(
  options: {
    steps?: Response[];
    profiles?: Response[];
    sessions?: AgentSession[];
    initialRun?: Run;
    messages?: AgentMessage[];
    url?: string;
    events?: string;
  } = {},
) {
  window.history.replaceState(null, "", options.url ?? "/?session=chat-1");
  let currentRun = options.initialRun ?? run;
  let currentSessions = options.sessions ?? [session];
  const messages = options.messages ?? [
    savedMessage(1, "Research safely"),
    savedMessage(2, "Complete", "assistant"),
  ];
  const steps = options.steps ?? [];
  const profileReads = options.profiles ?? [];
  let answerCount = 0;
  vi.spyOn(global, "fetch").mockImplementation((input, init) => {
    const url = new URL(String(input), "http://localhost");
    const route = url.pathname.replace("/api/backend/", "");
    const method = init?.method ?? "GET";
    if (route.startsWith("agents/models"))
      return Promise.resolve(
        Response.json([
          {
            id: "synthetic-discovered",
            name: "Discovered model",
            selectable: true,
            description: "Available for agent chat",
          },
          {
            id: "synthetic-embedding",
            name: "Embedding model",
            selectable: false,
            description: "Not supported",
          },
        ]),
      );
    if (route === "integrations")
      return Promise.resolve(
        Response.json({ model_providers: { openai: true } }),
      );
    if (route === "agents/profiles")
      return Promise.resolve(profileReads.shift() ?? Response.json([profile]));
    if (route === "agent-sessions") {
      if (method === "POST") {
        const created = {
          ...session,
          id: "chat-new",
          title: JSON.parse(String(init?.body)).title,
        };
        currentSessions = [created, ...currentSessions];
        return Promise.resolve(Response.json(created));
      }
      const offset = Number(url.searchParams.get("offset"));
      return Promise.resolve(
        Response.json(
          page(
            currentSessions.slice(offset, offset + 30),
            currentSessions.length,
            offset,
          ),
        ),
      );
    }
    if (/agent-sessions\/[^/]+$/.test(route))
      return Promise.resolve(
        Response.json(
          currentSessions.find((item) => route.endsWith(item.id)) ?? session,
        ),
      );
    if (route.endsWith("/messages")) {
      if (method === "POST") {
        const body = JSON.parse(String(init?.body));
        const sessionId = route.split("/")[1];
        const next = {
          ...savedMessage(messages.length + 1, body.content),
          session_id: sessionId,
        };
        messages.push(next);
        currentRun = {
          ...run,
          id: "run-next",
          session_id: sessionId,
          state: "queued",
          output: null,
        };
        return Promise.resolve(Response.json(next));
      }
      const after = Number(url.searchParams.get("after_sequence"));
      return Promise.resolve(
        Response.json(
          page(messages.filter((message) => message.sequence > after)),
        ),
      );
    }
    if (route.endsWith("/runs"))
      return Promise.resolve(Response.json(page([currentRun])));
    if (route.endsWith("/events"))
      return Promise.resolve(
        new Response(
          new ReadableStream({
            start(controller) {
              if (options.events)
                controller.enqueue(new TextEncoder().encode(options.events));
            },
          }),
          { headers: { "Content-Type": "text/event-stream" } },
        ),
      );
    if (route.endsWith("/steps"))
      return Promise.resolve(steps.shift() ?? Response.json([]));
    if (route.endsWith("/artifacts"))
      return Promise.resolve(Response.json(page([])));
    if (route.endsWith("/questions"))
      return Promise.resolve(
        Response.json(
          answerCount
            ? []
            : [
                {
                  ...base,
                  id: "q1",
                  prompt: "Which company?",
                  role: "lead",
                  branch_id: "branch-1",
                  state: "open",
                  answer: null,
                },
              ],
        ),
      );
    if (route.endsWith("/answer")) {
      answerCount++;
      currentRun = { ...currentRun, state: "queued" };
      return Promise.resolve(Response.json({ id: "q1", state: "answered" }));
    }
    if (route.endsWith("/cancel")) {
      currentRun = { ...currentRun, state: "cancelled" };
      return Promise.resolve(Response.json(currentRun));
    }
    if (route === "agent-runs") {
      if (method === "POST") {
        currentRun = { ...run, id: "adopted-run" };
        return Promise.resolve(Response.json(currentRun));
      }
      return Promise.resolve(
        Response.json(page([{ ...run, session_id: null }])),
      );
    }
    if (route.startsWith("agent-runs/"))
      return Promise.resolve(Response.json(currentRun));
    throw new Error(`Unexpected agents request: ${route}`);
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={client}>
      <Agents />
    </QueryClientProvider>,
  );
  return { client, ...view };
}
const writePrompt = (text: string) =>
  fireEvent.change(
    screen.getByRole("textbox", { name: "Message your agent" }),
    { target: { value: text } },
  );
const posts = () =>
  vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method === "POST");

it("defers historical details and retains cached steps across refresh errors", async () => {
  const { client } = mount({
    steps: [
      Response.json([
        {
          id: "s1",
          name: "search",
          role: "assistant",
          state: "output-available",
          output: "Saved step output",
        } satisfies Partial<RunStep>,
      ]),
      Response.json({ detail: "Step refresh failed" }, { status: 409 }),
      Response.json([]),
    ],
  });
  fireEvent.click(
    await screen.findByRole("button", { name: "Show activity details" }),
  );
  expect(await screen.findByText("Search")).toBeVisible();
  await act(() =>
    client.invalidateQueries({ queryKey: ["agent-run-steps", run.id] }),
  );
  expect(await screen.findByText("Step refresh failed")).toBeVisible();
  expect(screen.getByText("Search")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByText("No saved steps for this run.")).toBeVisible();
});

it("shows an initial profile failure and retries only that query", async () => {
  mount({
    url: "/",
    profiles: [
      Response.json({ detail: "Profiles unavailable" }, { status: 409 }),
      Response.json([profile]),
    ],
  });
  expect(await screen.findByText("Profiles unavailable")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByText(/openai · synthetic-model/i)).toBeVisible();
});

it("selects a custom model without submitting the surrounding form", async () => {
  mount({ url: "/" });
  writePrompt("Synthetic research request");
  fireEvent.click(
    await screen.findByRole("button", { name: "Switch AI model" }),
  );
  fireEvent.change(screen.getByRole("textbox", { name: "Custom model ID" }), {
    target: { value: "synthetic-custom-model" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Use" }));
  expect(
    await screen.findByRole("button", { name: "Switch AI model" }),
  ).toHaveTextContent("synthetic-custom-model");
  expect(posts()).toHaveLength(0);
});

it("sends the discovered model and inserts the saved message immediately", async () => {
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Switch AI model" }),
  );
  expect(
    await screen.findByRole("button", { name: /Embedding model/ }),
  ).toBeDisabled();
  fireEvent.change(screen.getByRole("textbox", { name: "Search models" }), {
    target: { value: "discovered" },
  });
  expect(
    screen.queryByRole("button", { name: /Embedding model/ }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Discovered model/ }));
  writePrompt("Synthetic request");
  fireEvent.click(screen.getByRole("button", { name: "Run agent" }));
  expect(await screen.findByText("Synthetic request")).toBeVisible();
  expect(JSON.parse(String(posts()[0][1]?.body))).toMatchObject({
    provider: "openai",
    model: "synthetic-discovered",
    content: "Synthetic request",
  });
});

it("keeps replies in the URL-selected session and starts another only on New chat", async () => {
  mount();
  expect(await screen.findByText("Research safely")).toBeVisible();
  writePrompt("And applications?");
  fireEvent.click(screen.getByRole("button", { name: "Run agent" }));
  expect(await screen.findByText("And applications?")).toBeVisible();
  expect(screen.getByText("Research safely")).toBeVisible();
  expect(location.search).toContain("session=chat-1");
  fireEvent.click(screen.getByRole("button", { name: "New chat" }));
  writePrompt("New topic");
  fireEvent.click(screen.getByRole("button", { name: "Run agent" }));
  await waitFor(() => expect(posts()).toHaveLength(3));
  expect(String(posts()[1][0])).toMatch(/agent-sessions$/);
  expect(String(posts()[2][0])).toContain("chat-new/messages");
});

it("opens a URL-selected session outside the history page and pages through 45 conversations", async () => {
  const sessions = Array.from({ length: 45 }, (_, index) => ({
    ...session,
    id: `chat-${index}`,
    title: `Saved conversation ${index}`,
  }));
  mount({ sessions, url: "/?session=chat-44" });
  expect(await screen.findByText("Research safely")).toBeVisible();
  expect(
    screen.queryByRole("button", { name: /Saved conversation 44/ }),
  ).not.toBeInTheDocument();
  fireEvent.click(
    await screen.findByRole("button", { name: "Load more conversations" }),
  );
  expect(
    await screen.findByRole("button", { name: /Saved conversation 44/ }),
  ).toHaveAttribute("aria-current", "true");
  expect(posts()).toHaveLength(0);
});

it("shows live text before completion and renders the durable answer once", async () => {
  const text = "A streamed synthetic answer";
  const event = `event: agent_event\ndata: ${JSON.stringify({ sequence: 1, run_id: run.id, type: "text-delta", role: "assistant", data: { message_id: "stream-1", delta: text }, created_at: base.created_at })}\n\n`;
  const { client } = mount({
    initialRun: { ...run, state: "running", output: null },
    messages: [savedMessage(1, "Research safely")],
    events: event,
  });
  await waitFor(() =>
    expect(
      screen.getByRole("group", { name: "Live answer" }),
    ).toHaveTextContent(text),
  );
  act(() => {
    client.setQueryData(
      ["agent-session-messages", session.id],
      page([
        savedMessage(1, "Research safely"),
        savedMessage(2, text, "assistant"),
      ]),
    );
    client.setQueryData(
      ["agent-session-runs", session.id, 1],
      page([{ ...run, output: text }]),
    );
  });
  await waitFor(() => expect(screen.getAllByText(text)).toHaveLength(1));
});

it("deduplicates replayed tool calls against saved steps and pins an active model", async () => {
  const events = [
    {
      type: "tool-input-available",
      data: {
        tool_call_id: "tool-1",
        tool_name: "search",
        input: { query: "Synthetic" },
      },
    },
    {
      type: "tool-output-available",
      data: { tool_call_id: "tool-1", output: "Live result" },
    },
  ]
    .map(
      (event, index) =>
        `event: agent_event\ndata: ${JSON.stringify({ ...event, sequence: index + 1, run_id: run.id, role: "assistant", created_at: base.created_at })}\n\n`,
    )
    .join("");
  const { client } = mount({
    initialRun: { ...run, state: "running", output: null },
    messages: [savedMessage(1, "Research safely")],
    events,
    steps: [
      Response.json([
        {
          id: "tool-1",
          name: "search",
          role: "assistant",
          state: "output-available",
          output: "Saved result",
        } satisfies Partial<RunStep>,
      ]),
    ],
  });
  expect(
    await screen.findByRole("button", { name: "Switch AI model" }),
  ).toBeDisabled();
  await waitFor(() => {
    expect(client.getQueryData(["agent-run-steps", run.id])).toHaveLength(1);
    expect(
      screen.getByRole("group", { name: "Live activity" }),
    ).toHaveTextContent("Search");
    expect(screen.getAllByRole("button", { name: /Search/ })).toHaveLength(1);
  });
  fireEvent.click(screen.getByRole("button", { name: /Search/ }));
  expect(await screen.findByText("Live result")).toBeVisible();
  expect(screen.queryByText("Saved result")).not.toBeInTheDocument();
  act(() =>
    client.setQueryData(["agent-session-runs", session.id, 1], page([run])),
  );
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Switch AI model" }),
    ).toBeEnabled(),
  );
  expect(
    screen.getByRole("button", { name: "Show activity details" }),
  ).toHaveAttribute("aria-expanded", "false");
  expect(
    screen.queryByRole("button", { name: /Search/ }),
  ).not.toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "Show activity details" }),
  );
  expect(screen.getAllByRole("button", { name: /Search/ })).toHaveLength(1);
});

it("shows waiting questions, answers and cancellation without falsely claiming cancellation", async () => {
  mount({ initialRun: { ...run, state: "waiting_for_user", output: null } });
  expect(await screen.findByText("Which company?")).toBeVisible();
  expect(
    screen.getByRole("button", { name: "Switch AI model" }),
  ).toBeDisabled();
  expect(screen.queryByText(/This run was cancelled/)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Cancel work" })).toBeEnabled();
  fireEvent.change(
    screen.getByRole("textbox", { name: "Answer Lead question" }),
    { target: { value: "Synthetic Ltd" } },
  );
  fireEvent.click(screen.getByRole("button", { name: "Answer" }));
  await waitFor(() =>
    expect(
      posts().some(([url]) => String(url).endsWith("/questions/q1/answer")),
    ).toBe(true),
  );
  fireEvent.click(screen.getByRole("button", { name: "Cancel work" }));
  expect(
    await screen.findByText(
      "Cancelled. Completed activity remains in this conversation.",
    ),
  ).toBeVisible();
});

it("retains a failed submission and reuses its idempotency key on retry", async () => {
  mount();
  await screen.findByText("Research safely");
  const fallback = vi.mocked(fetch).getMockImplementation()!;
  let attempts = 0;
  vi.mocked(fetch).mockImplementation((input, init) => {
    if (
      init?.method === "POST" &&
      String(input).endsWith("/messages") &&
      ++attempts === 1
    )
      return Promise.resolve(
        Response.json({ detail: "Save failed" }, { status: 409 }),
      );
    return fallback(input, init);
  });
  writePrompt("Keep my draft");
  fireEvent.click(screen.getByRole("button", { name: "Run agent" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Run agent" })).toBeEnabled(),
  );
  expect(
    screen.getByRole("textbox", { name: "Message your agent" }),
  ).toHaveValue("Keep my draft");
  fireEvent.click(screen.getByRole("button", { name: "Run agent" }));
  expect(await screen.findByText("Keep my draft")).toBeVisible();
  expect(new Headers(posts()[0][1]?.headers).get("Idempotency-Key")).toEqual(
    new Headers(posts()[1][1]?.headers).get("Idempotency-Key"),
  );
});

it("adopts an explicitly opened legacy run on continuation", async () => {
  mount({ url: "/?run=run-1", initialRun: { ...run, session_id: null } });
  await screen.findByText("Research safely");
  writePrompt("Continue the old run");
  fireEvent.click(screen.getByRole("button", { name: "Run agent" }));
  await waitFor(() => expect(posts()).toHaveLength(1));
  expect(JSON.parse(String(posts()[0][1]?.body))).toMatchObject({
    continue_run_id: run.id,
  });
  await waitFor(() => expect(location.search).toContain("session=chat-1"));
});

it("marks a reused answer and requests an explicit fresh answer", async () => {
  const reused = {
    ...savedMessage(2, "Reused synthetic response", "assistant"),
    answer_cache: {
      source_run_id: "original-run",
      source_completed_at: "2026-09-21T10:00:00Z",
      expires_at: "2026-09-21T10:05:00Z",
    },
  };
  mount({ messages: [savedMessage(1, "Rewrite: hello"), reused] });
  expect(await screen.findByText(/Reused saved answer from/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Get a fresh answer" }));
  await waitFor(() => expect(posts()).toHaveLength(1));
  expect(JSON.parse(String(posts()[0][1]?.body))).toMatchObject({
    content: "Rewrite: hello",
    fresh_answer: true,
  });
});
