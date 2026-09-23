import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import * as apiModule from "@/lib/api";
import { ContactBatchEnrich } from "./contact-batch-enrich";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ userId: "synthetic-owner" }),
}));
vi.mock("./context", () => ({
  useWorkspaceContext: () => ({ open: vi.fn() }),
}));

const contacts = Array.from({ length: 12 }, (_, index) => ({
  id: `person-${index}`,
  name: `Synthetic Person ${index}`,
  outreach: null,
})) as apiModule.Resources["contacts"][];

beforeEach(() => sessionStorage.clear());

function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ContactBatchEnrich
        contacts={contacts}
        instructions="Explore developer tools"
      />
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Batch enrich" }));
}

it("caps selection at ten contacts and queues only two requests at once", async () => {
  const pending: (() => void)[] = [];
  const request = vi
    .spyOn(apiModule, "api")
    .mockImplementation(
      () =>
        new Promise((resolve) =>
          pending.push(() =>
            resolve({ task_id: crypto.randomUUID(), state: "queued" }),
          ),
        ),
    );
  mount();
  for (let index = 0; index < 10; index++)
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: `Enrich Synthetic Person ${index}`,
      }),
    );
  expect(
    screen.getByRole("checkbox", {
      name: "Enrich Synthetic Person 10",
    }),
  ).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Enrich 10" }));
  await waitFor(() => expect(request).toHaveBeenCalledTimes(2));
  expect(pending).toHaveLength(2);
  pending.shift()!();
  await waitFor(() => expect(request).toHaveBeenCalledTimes(3));
  for (let count = 0; count < 9; count++) {
    await waitFor(() => expect(pending.length).toBeGreaterThan(0));
    pending.shift()!();
  }
  await waitFor(() =>
    expect(screen.getAllByRole("button", { name: "Open task" })).toHaveLength(
      10,
    ),
  );
  expect(request).toHaveBeenCalledTimes(10);
});

it("retries only failed people with the same request key after a partial failure", async () => {
  let fail = true;
  const request = vi
    .spyOn(apiModule, "api")
    .mockImplementation(async (route) => {
      if (route.endsWith("person-1") && fail)
        throw new Error("Synthetic interrupted response");
      return { task_id: route, state: "queued" };
    });
  mount();
  fireEvent.click(
    screen.getByRole("checkbox", {
      name: "Enrich Synthetic Person 0",
    }),
  );
  fireEvent.click(
    screen.getByRole("checkbox", {
      name: "Enrich Synthetic Person 1",
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Enrich 2" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Synthetic interrupted response",
  );
  const original = request.mock.calls.find(([route]) =>
    route.endsWith("person-1"),
  )!;
  fail = false;
  fireEvent.click(
    await screen.findByRole("button", { name: "Retry 1 remaining" }),
  );
  await waitFor(() => expect(request).toHaveBeenCalledTimes(3));
  expect(request.mock.calls[2][1]).toEqual(original[1]);
  expect(
    request.mock.calls.filter(([route]) => route.endsWith("person-0")),
  ).toHaveLength(1);
});
