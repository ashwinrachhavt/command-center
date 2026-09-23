import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import * as apiModule from "@/lib/api";
import { ContactOutreach, defaultOutreachBrief } from "./contact-outreach";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ userId: "synthetic-owner", isLoaded: true }),
}));
vi.mock("./context", () => ({
  useWorkspaceContext: () => ({ open: vi.fn() }),
}));

const message =
  "Hi Taylor, I'm exploring opportunities in developer tools. Could we connect and see whether my background could be useful at Example Labs?";
const contact: apiModule.Resources["contacts"] = {
  id: "contact-1",
  row_version: 1,
  name: "Taylor",
  title: "Founder",
  company_id: null,
  email: null,
  linkedin_url: "https://www.linkedin.com/in/synthetic-taylor",
  relationship: "connected",
  notes: null,
  archived_at: null,
  created_at: "2026-09-22T10:00:00Z",
  updated_at: "2026-09-22T10:00:00Z",
  outreach: {
    task_id: "task-1",
    state: "completed",
    error_code: null,
    artifact_id: "draft-1",
    version_id: "version-1",
    message,
    researched_at: "2026-09-22T10:00:00Z",
    sources: [],
    research: {
      identity: "matched",
      company: "Example Labs",
      role: "Founder",
      summary: "Synthetic research.",
      caveats: "Hiring unconfirmed.",
      identity_evidence: [],
      employment_evidence: [],
    },
  },
};

beforeEach(() => {
  sessionStorage.clear();
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
  });
});

function mount(person = contact) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ContactOutreach contact={person} instructions={defaultOutreachBrief} />
    </QueryClientProvider>,
  );
}

it("copies only the visible saved note and links to the selected person's LinkedIn", async () => {
  mount();
  expect(navigator.clipboard.writeText).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Copy note" }));
  await waitFor(() =>
    expect(navigator.clipboard.writeText).toHaveBeenCalledExactlyOnceWith(
      message,
    ),
  );
  expect(screen.getByText(`${message.length}/200`)).toBeVisible();
  expect(screen.getByRole("link", { name: "LinkedIn" })).toHaveAttribute(
    "href",
    contact.linkedin_url,
  );
});

it("keeps the note selectable when clipboard permission fails", async () => {
  vi.mocked(navigator.clipboard.writeText).mockRejectedValue(
    new Error("Permission denied"),
  );
  mount();
  fireEvent.click(screen.getByRole("button", { name: "Copy note" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Select and copy the note above",
  );
  expect(screen.getByText(message)).toBeVisible();
});

it("labels uncertain identities and retains the saved note after a failed refresh", () => {
  mount({
    ...contact,
    outreach: {
      ...contact.outreach!,
      state: "failed",
      research: {
        identity: "uncertain",
        company: "",
        role: "",
        summary: "Namesakes found.",
        caveats: "No reliable match.",
      },
    },
  });
  expect(
    screen.getByRole("button", { name: /Identity needs review/ }),
  ).toBeVisible();
  expect(screen.getByText(/Last attempt failed/)).toBeVisible();
  expect(screen.getByRole("button", { name: "Copy note" })).toBeEnabled();
});

it("starts quick connection work without requesting deep research", async () => {
  const request = vi
    .spyOn(apiModule, "api")
    .mockResolvedValue({ task_id: "task-1", state: "queued" });
  mount({ ...contact, outreach: null });
  fireEvent.click(
    screen.getByRole("button", { name: "Draft connection note" }),
  );
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith(
      "record-work/contacts/contact-1",
      expect.objectContaining({
        method: "POST",
        body: {
          connection_note: true,
          channel: "linkedin",
          instructions: defaultOutreachBrief,
        },
        key: expect.any(String),
      }),
    ),
  );
});

it("keeps deeper research as a separate explicit action", async () => {
  const request = vi
    .spyOn(apiModule, "api")
    .mockResolvedValue({ task_id: "deep-task", state: "queued" });
  mount({ ...contact, outreach: null });
  fireEvent.click(screen.getByRole("button", { name: "Enrich contact" }));
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith(
      "record-work/contacts/contact-1",
      expect.objectContaining({
        body: {
          research_requested: true,
          channel: "linkedin",
          instructions: defaultOutreachBrief,
        },
      }),
    ),
  );
});

it("blocks copying an oversized note and hides unsafe profile URLs", () => {
  mount({
    ...contact,
    linkedin_url: "https://linkedin.com.evil.example/in/person",
    outreach: { ...contact.outreach!, message: "x".repeat(201) },
  });
  expect(screen.getByRole("button", { name: "Copy note" })).toBeDisabled();
  expect(
    screen.queryByRole("link", { name: "LinkedIn" }),
  ).not.toBeInTheDocument();
});
