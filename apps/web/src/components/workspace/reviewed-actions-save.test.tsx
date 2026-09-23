import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import type { Schema } from "@/lib/api";
import { ActionEditor } from "./reviewed-actions";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ isLoaded: true, userId: "synthetic-test" }),
}));

const account: Schema["AccountRead"] = {
  id: "11111111-1111-4111-8111-111111111111",
  row_version: 2,
  toolkit: "gmail",
  display_name: "Work Gmail",
  provider_identity: { email: "synthetic@example.test" },
  connection_status: "ACTIVE",
  identity_verified_at: "2026-09-22T12:00:00Z",
  selected_purpose: "outreach",
};

const existing = {
  id: "22222222-2222-4222-8222-222222222222",
  row_version: 7,
  kind: "gmail_send",
  account,
  current: {
    id: "33333333-3333-4333-8333-333333333333",
    reason: "Follow up on the synthetic conversation",
    source_version_id: null,
    attachments: [],
    payload: {
      kind: "gmail_send",
      to: ["recipient@example.test"],
      subject: "Synthetic follow-up",
      body: "Hello from a synthetic fixture.",
    },
  },
} as unknown as Schema["ActionRead"];

function mount(close = vi.fn()) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ActionEditor existing={existing} close={close} />
    </QueryClientProvider>,
  );
  return close;
}

function key(call: unknown[]) {
  return new Headers((call[1] as RequestInit).headers).get("Idempotency-Key");
}

function body(call: unknown[]) {
  return JSON.parse(String((call[1] as RequestInit).body));
}

it.each([
  {
    code: "connected_request_outcome_unknown",
    button: "Retry the same proposal save",
    fresh: false,
  },
  {
    code: "spending_limit_exceeded",
    button: "Start a fresh proposal save",
    fresh: true,
  },
])(
  "preserves the pinned proposal and $button intent after an error",
  async ({ code, button, fresh }) => {
    sessionStorage.clear();
    let writes = 0;
    let draft = {
      scope_key: `action-${existing.id}`,
      data: null as unknown,
      row_version: 0,
      updated_at: null,
      last_save_key: null as string | null,
    };
    const close = vi.fn();
    const fetch = vi
      .spyOn(global, "fetch")
      .mockImplementation((input, init) => {
        const path = String(input);
        if (path.includes("/writing-drafts/")) {
          if (init?.method !== "GET") {
            const body = JSON.parse(String(init?.body));
            draft = {
              ...draft,
              data: body.data ?? null,
              row_version: draft.row_version + 1,
              last_save_key: new Headers(init?.headers).get("Idempotency-Key"),
            };
          }
          return Promise.resolve(Response.json(draft));
        }
        if (
          init?.method === "GET" &&
          path.endsWith("/integrations/composio/accounts")
        ) {
          return Promise.resolve(Response.json([account]));
        }
        if (
          init?.method === "PATCH" &&
          path.endsWith(`/reviewed-actions/${existing.id}`)
        ) {
          writes += 1;
          return Promise.resolve(
            writes === 1
              ? Response.json(
                  { detail: { code, message: "Synthetic request failure" } },
                  { status: 409 },
                )
              : Response.json(existing),
          );
        }
        throw new Error(`Unexpected request: ${path}`);
      });
    mount(close);

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Save proposal" }),
      ).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Save proposal" }));
    fireEvent.click(await screen.findByRole("button", { name: button }));
    await waitFor(() => expect(writes).toBe(2));

    const requests = fetch.mock.calls.filter(
      ([, init]) => init?.method === "PATCH",
    );
    expect(body(requests[1])).toEqual(body(requests[0]));
    expect(body(requests[1])).toMatchObject({ expected_version: 7 });
    expect(key(requests[1]) === key(requests[0])).toBe(!fresh);
    await waitFor(() => expect(close).toHaveBeenCalledOnce());
  },
);

it("keeps later writing and advances only the acknowledged proposal base", async () => {
  sessionStorage.clear();
  const close = vi.fn();
  let finish!: (response: Response) => void;
  let draft = {
    scope_key: `action-${existing.id}`,
    data: null as unknown,
    row_version: 0,
    updated_at: null,
    last_save_key: null as string | null,
  };
  const writes: Record<string, unknown>[] = [];
  vi.spyOn(global, "fetch").mockImplementation((input, init) => {
    const path = String(input);
    if (path.includes("/writing-drafts/")) {
      if (init?.method !== "GET") {
        const body = JSON.parse(String(init?.body));
        draft = {
          ...draft,
          data: body.data ?? null,
          row_version: draft.row_version + 1,
          last_save_key: new Headers(init?.headers).get("Idempotency-Key"),
        };
      }
      return Promise.resolve(Response.json(draft));
    }
    if (path.endsWith("/integrations/composio/accounts"))
      return Promise.resolve(Response.json([account]));
    if (
      path.endsWith(`/reviewed-actions/${existing.id}`) &&
      init?.method === "PATCH"
    ) {
      writes.push(JSON.parse(String(init.body)));
      if (writes.length === 1)
        return new Promise((resolve) => {
          finish = resolve;
        });
      return Promise.resolve(Response.json({ ...existing, row_version: 9 }));
    }
    throw new Error(`Unexpected request ${path}`);
  });
  mount(close);
  const save = screen.getByRole("button", { name: "Save proposal" });
  await waitFor(() => expect(save).toBeEnabled());
  fireEvent.click(save);
  await waitFor(() => expect(writes).toHaveLength(1));
  fireEvent.change(screen.getByRole("textbox", { name: "Subject" }), {
    target: { value: "Still writing after checkpoint" },
  });
  finish(Response.json({ ...existing, row_version: 8 }));
  await waitFor(() => expect(save).toBeEnabled());
  expect(close).not.toHaveBeenCalled();
  expect(screen.getByRole("textbox", { name: "Subject" })).toHaveValue(
    "Still writing after checkpoint",
  );
  fireEvent.click(save);
  await waitFor(() => expect(close).toHaveBeenCalledOnce());
  expect(writes[0].expected_version).toBe(7);
  expect(writes[1]).toMatchObject({
    expected_version: 8,
    payload: { subject: "Still writing after checkpoint" },
  });
});
