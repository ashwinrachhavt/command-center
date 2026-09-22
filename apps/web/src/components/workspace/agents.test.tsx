import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { Agents } from "./agents";

const profile = {
  id: "research",
  name: "Research",
  description: "Synthetic profile",
  provider: "openai",
  model: "synthetic-model",
  ready: true,
  missing_credentials: [],
  tools: [],
  skills: [],
  revision: "profile-revision",
};
const run = {
  id: "run-1",
  row_version: 1,
  created_at: "2026-09-21T10:00:00Z",
  updated_at: "2026-09-21T10:00:00Z",
  title: "Synthetic run",
  prompt: "Research safely",
  profile: "research",
  state: "completed",
  output: "Complete",
  error_code: null,
  completed_at: "2026-09-21T10:01:00Z",
  session_id: null,
  input_sequence: 0,
  consumed_sequence: 0,
};

function mount(
  stepReads: Response[],
  profileReads = [Response.json([profile])],
) {
  vi.spyOn(global, "fetch").mockImplementation((input, init) => {
    const route = String(input);
    if (init?.method === "GET" && route.endsWith("/agents/profiles"))
      return Promise.resolve(profileReads.shift() ?? Response.json([profile]));
    if (init?.method === "GET" && route.endsWith("/agent-runs"))
      return Promise.resolve(
        Response.json({ items: [run], total: 1, limit: 100, offset: 0 }),
      );
    if (init?.method === "GET" && route.endsWith("/agent-runs/run-1/steps"))
      return Promise.resolve(stepReads.shift() ?? Response.json([]));
    throw new Error(`Unexpected agents request: ${route}`);
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <Agents />
    </QueryClientProvider>,
  );
  return client;
}

it("keeps cached run steps visible through refresh failure and local recovery", async () => {
  const client = mount([
    Response.json([
      {
        id: "step-1",
        name: "search",
        state: "output-available",
        output: "Saved step output",
      },
    ]),
    Response.json({ detail: "Step refresh failed" }, { status: 409 }),
    Response.json([]),
  ]);
  fireEvent.click(await screen.findByRole("button", { name: /Synthetic run/ }));
  expect(await screen.findByText("Search")).toBeVisible();

  await client.invalidateQueries({ queryKey: ["run-steps", "run-1"] });

  expect(await screen.findByText("Step refresh failed")).toBeVisible();
  expect(screen.getByText("Search")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(
    await screen.findByText("No steps were recorded for this run."),
  ).toBeVisible();
});

it("shows an initial profile failure and retries only that query", async () => {
  mount(
    [],
    [
      Response.json({ detail: "Profiles unavailable" }, { status: 409 }),
      Response.json([profile]),
    ],
  );

  expect(await screen.findByText("Profiles unavailable")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByText(/openai · synthetic-model/i)).toBeVisible();
});
