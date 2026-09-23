import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { LocalAIClients } from "./local-ai-clients";

const record = {
  id: "client-1",
  name: "Synthetic Codex",
  created_at: "2026-09-23T00:00:00Z",
  expires_at: "2099-01-01T00:00:00Z",
  revoked_at: null,
};
function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={client}>
      <LocalAIClients />
    </QueryClientProvider>,
  );
  return { client, ...view };
}

it("shows a token once, handles copy failure, and excludes the secret from every query and mutation cache", async () => {
  vi.spyOn(global, "fetch").mockImplementation((_input, init) =>
    Promise.resolve(
      Response.json(
        init?.method === "POST" ? { ...record, token: "synthetic-secret" } : [],
      ),
    ),
  );
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: {
      writeText: vi.fn().mockRejectedValue(new Error("Permission denied")),
    },
  });
  const { client, unmount } = mount();
  fireEvent.change(screen.getByRole("textbox", { name: "Client name" }), {
    target: { value: record.name },
  });
  fireEvent.click(screen.getByRole("button", { name: "Create token" }));
  expect(
    await screen.findByRole("textbox", { name: "New local client token" }),
  ).toHaveValue("synthetic-secret");
  fireEvent.click(screen.getByRole("button", { name: "Copy token" }));
  expect(
    await screen.findByText(
      "Copy failed. Select the token and copy it manually.",
    ),
  ).toBeVisible();
  expect(
    JSON.stringify(
      client
        .getQueryCache()
        .getAll()
        .map((query) => query.state.data),
    ),
  ).not.toContain("synthetic-secret");
  expect(
    JSON.stringify(
      client
        .getMutationCache()
        .getAll()
        .map((mutation) => mutation.state),
    ),
  ).not.toContain("synthetic-secret");
  expect(location.href).not.toContain("synthetic-secret");
  fireEvent.click(screen.getByRole("button", { name: "Hide token" }));
  expect(
    screen.queryByRole("textbox", { name: "New local client token" }),
  ).not.toBeInTheDocument();
  unmount();
  render(
    <QueryClientProvider client={client}>
      <LocalAIClients />
    </QueryClientProvider>,
  );
  expect(
    screen.queryByRole("textbox", { name: "New local client token" }),
  ).not.toBeInTheDocument();
});

it("blocks double creation and does not retry an ambiguous provisioning failure", async () => {
  let fail!: (error: Error) => void;
  vi.spyOn(global, "fetch").mockImplementation((_input, init) =>
    init?.method === "POST"
      ? new Promise((_resolve, reject) => {
          fail = reject;
        })
      : Promise.resolve(Response.json([])),
  );
  mount();
  fireEvent.change(screen.getByRole("textbox", { name: "Client name" }), {
    target: { value: record.name },
  });
  const form = screen
    .getByRole("button", { name: "Create token" })
    .closest("form")!;
  fireEvent.submit(form);
  fireEvent.submit(form);
  await waitFor(() => expect(fail).toBeDefined());
  fail(new Error("Connection lost"));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Refresh the client list before creating another token",
  );
  expect(
    vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method === "POST"),
  ).toHaveLength(1);
  expect(screen.getByRole("textbox", { name: "Client name" })).toHaveValue(
    record.name,
  );
});

it("revokes a client and removes its available action", async () => {
  vi.spyOn(global, "fetch").mockImplementation((_input, init) =>
    Promise.resolve(
      Response.json(
        init?.method === "POST"
          ? { ...record, revoked_at: "2026-09-23T01:00:00Z" }
          : [record],
      ),
    ),
  );
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Revoke Synthetic Codex" }),
  );
  expect(await screen.findByText("Revoked")).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "Revoke Synthetic Codex" }),
  ).not.toBeInTheDocument();
});
