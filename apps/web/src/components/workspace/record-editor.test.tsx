import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RecordEditor } from "./record-editor";
import type { Resources } from "@/lib/api";

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
function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const close = vi.fn();
  const ui = (value = record) => (
    <QueryClientProvider client={client}>
      <RecordEditor
        resource="companies"
        record={value}
        open
        onOpenChange={close}
      />
    </QueryClientProvider>
  );
  return { ...render(ui()), client, close, ui };
}
describe("record draft ownership", () => {
  it("retains input and original revision after refresh and a conflict", async () => {
    const fetch = vi
      .spyOn(global, "fetch")
      .mockResolvedValue(
        Response.json(
          { detail: "Record changed. Reload before saving." },
          { status: 409 },
        ),
      );
    const { rerender, ui, close } = mount();
    fireEvent.change(screen.getByLabelText(/company name/i), {
      target: { value: "Unsaved draft" },
    });
    rerender(ui({ ...record, name: "Server update", row_version: 2 }));
    expect(screen.getByLabelText(/company name/i)).toHaveValue("Unsaved draft");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await screen.findByRole("alert");
    expect(JSON.parse(String(fetch.mock.calls[0][1]?.body))).toMatchObject({
      name: "Unsaved draft",
      expected_version: 1,
    });
    expect(screen.getByLabelText(/company name/i)).toHaveValue("Unsaved draft");
    expect(close).not.toHaveBeenCalled();
  });

  it("keeps edits made during a save and uses the returned revision next time", async () => {
    let finish!: (response: Response) => void;
    const fetch = vi
      .spyOn(global, "fetch")
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      )
      .mockResolvedValue(Response.json({ ...record, row_version: 3 }));
    const { close } = mount();
    fireEvent.change(screen.getByLabelText(/company name/i), {
      target: { value: "Submitted draft" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
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
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(JSON.parse(String(fetch.mock.calls[1][1]?.body))).toMatchObject({
      name: "Newer draft",
      expected_version: 2,
    });
  });
});
