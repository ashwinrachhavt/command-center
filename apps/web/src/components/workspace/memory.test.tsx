import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { MemoryPage } from "./memory";

function memory(index: number) {
  const revision = {
    id: `revision-${index}`,
    version: 1,
    title: `Memory ${index}`,
    content: `Synthetic memory content ${index}`,
    kind: "note",
    scope_type: "global",
    scope_id: null,
    valid_until: null,
    source: "human",
    source_run_id: null,
    source_artifact_id: null,
    reason: null,
    review_state: "approved",
    created_at: "2026-09-21T10:00:00Z",
  };
  return {
    id: `memory-${index}`,
    title: revision.title,
    content: revision.content,
    kind: "note",
    source: "human",
    row_version: 1,
    updated_at: "2026-09-21T10:00:00Z",
    current: revision,
    active: revision,
  };
}

function mount(total: number) {
  const records = Array.from({ length: total }, (_, index) =>
    memory(index + 1),
  );
  vi.spyOn(global, "fetch").mockImplementation((input, init) => {
    const url = new URL(String(input), "http://workspace.test");
    if (init?.method === "GET" && url.pathname.endsWith("/memories")) {
      const limit = Number(url.searchParams.get("limit"));
      const offset = Number(url.searchParams.get("offset"));
      return Promise.resolve(
        Response.json({
          items: records.slice(offset, offset + limit),
          total: records.length,
          limit,
          offset,
        }),
      );
    }
    const archive = url.pathname.match(/\/memories\/(memory-\d+)\/archive$/);
    if (init?.method === "POST" && archive) {
      const index = records.findIndex((item) => item.id === archive[1]);
      if (index >= 0) records.splice(index, 1);
      return Promise.resolve(Response.json({ archived: true }));
    }
    throw new Error(`Unexpected memory request: ${url.pathname}${url.search}`);
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryPage />
    </QueryClientProvider>,
  );
}

async function nextPage(times: number) {
  for (let index = 0; index < times; index += 1) {
    fireEvent.click(await screen.findByRole("button", { name: "Next" }));
    await screen.findByText(`Memory ${index * 30 + 31}`);
  }
}

it("reaches and edits memory 101 through bounded pages", async () => {
  mount(101);
  await screen.findByText("Memory 1");
  await nextPage(3);

  expect(await screen.findByText("Memory 101")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Edit Memory 101" }));
  expect(await screen.findByLabelText("Title")).toHaveValue("Memory 101");
  expect(screen.getByLabelText("Reusable context")).toHaveValue(
    "Synthetic memory content 101",
  );
});

it("repairs the offset after archiving the final item on the last page", async () => {
  mount(91);
  await screen.findByText("Memory 1");
  await nextPage(3);
  expect(await screen.findByText("Memory 91")).toBeVisible();

  fireEvent.click(screen.getByRole("button", { name: "Archive Memory 91" }));

  expect(await screen.findByText("Memory 61")).toBeVisible();
  expect(screen.getByText("Memory 90")).toBeVisible();
  expect(screen.getByText("61–90 of 90")).toBeVisible();
});
