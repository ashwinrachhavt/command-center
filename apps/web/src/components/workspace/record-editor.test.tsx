import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RecordEditor } from "./record-editor";
import type { Resources, Schema } from "@/lib/api";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ isLoaded: true, userId: "synthetic-record-writer" }),
}));
vi.mock("@/components/writing/rich-writer", () => ({
  RichWriter: ({
    label,
    value,
    disabled,
    onChange,
  }: {
    label: string;
    value: string;
    disabled?: boolean;
    onChange: (value: string) => void;
  }) => (
    <textarea
      aria-label={label}
      value={value}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value)}
    />
  ),
}));
beforeEach(() => sessionStorage.clear());
const record = {
  id: "11111111-1111-4111-8111-111111111111",
  name: "Synthetic company",
  row_version: 1,
  notes: "",
  domain: null,
  industry: null,
  location: null,
  website: null,
  archived_at: null,
  created_at: "2026-09-21",
  updated_at: "2026-09-21",
} as Resources["companies"];
function server(handler: (init?: RequestInit) => Response | Promise<Response>) {
  let draft: Schema["DraftRead"] = {
    scope_key: "record-companies-new",
    data: null,
    row_version: 0,
    updated_at: null,
    last_save_key: null,
  };
  const requests: RequestInit[] = [];
  vi.spyOn(global, "fetch").mockImplementation(async (input, init) => {
    if (String(input).includes("/writing-drafts/")) {
      if (init?.method && init.method !== "GET") {
        const body = JSON.parse(String(init.body));
        draft = {
          ...draft,
          data: body.data ?? null,
          row_version: draft.row_version + 1,
          last_save_key: new Headers(init.headers).get("Idempotency-Key"),
        };
      }
      return Response.json(draft);
    }
    requests.push(init ?? {});
    return handler(init);
  });
  return requests;
}
async function mount(existing = true) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const close = vi.fn();
  const ui = (value = record) => (
    <QueryClientProvider client={client}>
      <RecordEditor
        resource="companies"
        record={existing ? value : undefined}
        open
        onOpenChange={close}
      />
    </QueryClientProvider>
  );
  const rendered = render(ui());
  await waitFor(() =>
    expect(screen.getByTestId("draft-status")).toHaveTextContent("Draft saved"),
  );
  return { ...rendered, client, close, ui };
}
describe("record draft ownership", () => {
  it("retains input and original revision after refresh and a conflict", async () => {
    const requests = server(() =>
      Response.json(
        { detail: "Record changed. Reload before saving." },
        { status: 409 },
      ),
    );
    const { rerender, ui, close } = await mount();
    fireEvent.change(screen.getByLabelText(/company name/i), {
      target: { value: "Unsaved draft" },
    });
    rerender(ui({ ...record, name: "Server update", row_version: 2 }));
    expect(screen.getByLabelText(/company name/i)).toHaveValue("Unsaved draft");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await screen.findByRole("alert");
    expect(JSON.parse(String(requests[0].body))).toMatchObject({
      name: "Unsaved draft",
      expected_version: 1,
    });
    expect(screen.getByLabelText(/company name/i)).toHaveValue("Unsaved draft");
    expect(close).not.toHaveBeenCalled();
  });

  it("keeps edits made during a save and uses the returned revision next time", async () => {
    let finish!: (response: Response) => void;
    const requests = server(() =>
      requests.length === 1
        ? new Promise((resolve) => {
            finish = resolve;
          })
        : Response.json({ ...record, row_version: 3 }),
    );
    const { close } = await mount();
    fireEvent.change(screen.getByLabelText(/company name/i), {
      target: { value: "Submitted draft" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(requests).toHaveLength(1));
    fireEvent.change(screen.getByLabelText(/company name/i), {
      target: { value: "Newer draft" },
    });
    finish(
      Response.json({ ...record, name: "Submitted draft", row_version: 2 }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Save changes" }),
      ).toBeEnabled(),
    );
    expect(close).not.toHaveBeenCalled();
    expect(screen.getByLabelText(/company name/i)).toHaveValue("Newer draft");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(requests).toHaveLength(2));
    expect(JSON.parse(String(requests[1].body))).toMatchObject({
      name: "Newer draft",
      expected_version: 2,
    });
  });

  it("recovers an uncertain creation with the same request across close and reopen", async () => {
    const requests = server(() =>
      requests.length <= 2
        ? Promise.reject(new TypeError("Response lost"))
        : Response.json(record),
    );
    const first = await mount(false);
    fireEvent.change(screen.getByLabelText(/company name/i), {
      target: { value: "Saved once" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create company" }));
    await screen.findByRole("alert");
    expect(screen.getByLabelText(/company name/i)).toBeDisabled();
    first.unmount();
    const second = await mount(false);
    expect(screen.getByLabelText(/company name/i)).toHaveValue("Saved once");
    fireEvent.click(screen.getByRole("button", { name: "Create company" }));
    await waitFor(() => expect(second.close).toHaveBeenCalledWith(false));
    expect(requests).toHaveLength(3);
    expect(requests[2].body).toBe(requests[0].body);
    expect(requests[0].body).toBe(requests[1].body);
    expect(new Headers(requests[0].headers).get("Idempotency-Key")).toBe(
      new Headers(requests[1].headers).get("Idempotency-Key"),
    );
  });
});
