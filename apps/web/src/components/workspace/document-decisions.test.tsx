import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { DocumentDecisions, DocumentSettings } from "./document-decisions";

const types = [
  { id: "type-unknown", slug: "unclassified", name: "Unclassified" },
  { id: "type-paper", slug: "research", name: "Research paper" },
];
const policy = {
  revision: 3,
  classification_mode: "off",
  catalog_ids: ["type-paper"],
  rename_mode: "off",
  rename_template: "{type} - {uploaded_date} - {short_id}",
  timezone: "America/Los_Angeles",
  provider: "TypeSafe",
  provider_ready: false,
};
const initial = {
  artifact_id: "original",
  accepted_type_id: "type-unknown",
  metadata_revision: 8,
  source_version_id: "original-v2",
  extraction_version_id: "text-v2",
  policy,
  latest_decision: null,
  pending_rename: null,
};
type Request = {
  path: string;
  method: string;
  body: Record<string, unknown>;
  key: string | null;
};
function mount(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>{ui}</QueryClientProvider>,
  );
}
function fixture(
  snapshot: unknown = initial,
  mutation?: (request: Request) => Response,
) {
  const requests: Request[] = [];
  vi.spyOn(global, "fetch").mockImplementation(async (input, init) => {
    const path = String(input).replace("/api/backend/", "");
    const method = init?.method ?? "GET";
    const request = {
      path,
      method,
      body: init?.body ? JSON.parse(String(init.body)) : {},
      key: new Headers(init?.headers).get("Idempotency-Key"),
    };
    requests.push(request);
    if (method !== "GET") return mutation?.(request) ?? Response.json(snapshot);
    if (path === "document-types") return Response.json(types);
    if (path === "documents/policy") return Response.json(policy);
    if (path.endsWith("/classification")) return Response.json(snapshot);
    throw new Error(`Unexpected fixture request ${path}`);
  });
  return requests;
}

it("uses saved reads only and permits manual review without a configured provider", async () => {
  const requests = fixture();
  mount(<DocumentDecisions artifactId="original" />);
  await screen.findByRole("button", { name: "Review type" });
  expect(
    screen.getByRole("button", { name: "Classify with Jev" }),
  ).toBeDisabled();
  expect(requests.every((request) => request.method === "GET")).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Review type" }));
  fireEvent.change(screen.getByLabelText("Confirmed type"), {
    target: { value: "type-paper" },
  });
  fireEvent.change(screen.getByLabelText("Reason for this review"), {
    target: { value: "Read the abstract and methods." },
  });
  fireEvent.click(screen.getByRole("button", { name: "Confirm type" }));
  await waitFor(() =>
    expect(
      requests.filter((request) => request.method === "POST"),
    ).toHaveLength(1),
  );
  expect(requests.find((request) => request.method === "POST")).toMatchObject({
    path: "documents/original/classification/review",
    body: {
      expected_version: 8,
      source_version_id: "original-v2",
      extraction_version_id: "text-v2",
      decision_id: null,
      document_type_id: "type-paper",
      outcome: "accept",
      reason: "Read the abstract and methods.",
    },
  });
});

it("requires external-text acknowledgement for each explicit model request", async () => {
  const requests = fixture({
    ...initial,
    policy: { ...policy, provider_ready: true },
  });
  mount(<DocumentDecisions artifactId="original" />);
  const classify = await screen.findByRole("button", {
    name: "Classify with Jev",
  });
  expect(classify).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox", { name: /Send this document/ }));
  fireEvent.click(classify);
  await waitFor(() =>
    expect(
      requests.filter((request) => request.method === "POST"),
    ).toHaveLength(1),
  );
  expect(requests.find((request) => request.method === "POST")?.body).toEqual({
    expected_version: 8,
    source_version_id: "original-v2",
    extraction_version_id: "text-v2",
    external_processing_ack: true,
  });
  await waitFor(() =>
    expect(
      screen.getByRole("checkbox", { name: /Send this document/ }),
    ).not.toBeChecked(),
  );
});

it("keeps a stale human review and exact pinned source instead of silently applying to newer content", async () => {
  const requests = fixture(initial, () =>
    Response.json({ detail: "Document source changed" }, { status: 409 }),
  );
  mount(<DocumentDecisions artifactId="original" />);
  fireEvent.click(await screen.findByRole("button", { name: "Review type" }));
  fireEvent.change(screen.getByLabelText("Reason for this review"), {
    target: { value: "Keep the current type until a clearer file arrives." },
  });
  fireEvent.click(screen.getByRole("button", { name: "Keep current type" }));
  await screen.findByRole("alert");
  expect(screen.getByLabelText("Reason for this review")).toHaveValue(
    "Keep the current type until a clearer file arrives.",
  );
  fireEvent.click(screen.getByRole("button", { name: "Keep current type" }));
  await waitFor(() =>
    expect(
      requests.filter((request) => request.method === "POST"),
    ).toHaveLength(2),
  );
  const writes = requests.filter((request) => request.method === "POST");
  expect(writes[1].key).toBe(writes[0].key);
  expect(writes[1].body).toEqual(writes[0].body);
});

it("reviews a title separately and keeps the preview after a stale apply conflict", async () => {
  const requests = fixture(
    {
      ...initial,
      pending_rename: {
        id: "rename-1",
        artifact_id: "original",
        review_id: "review-1",
        policy_revision: 3,
        metadata_revision: 8,
        task_id: "rename-task",
        before_title: "upload.pdf",
        after_title: "Research paper - a1b2c3d4",
        template: "{type} - {short_id}",
        render_inputs: { type: "Research paper", short_id: "a1b2c3d4" },
        state: "pending",
        error: null,
        row_version: 1,
        created_at: "2026-09-24T10:00:00Z",
      },
    },
    () =>
      Response.json(
        { detail: "Title changed; refresh the preview" },
        { status: 409 },
      ),
  );
  mount(<DocumentDecisions artifactId="original" />);
  fireEvent.click(await screen.findByRole("button", { name: "Apply name" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Title changed");
  expect(screen.getByText("upload.pdf")).toBeVisible();
  expect(requests.find((request) => request.method === "POST")).toMatchObject({
    path: "documents/renames/rename-1/apply",
    body: { expected_version: 1 },
  });
});

it("shows distinct typed model fields and never treats probabilities as approval", async () => {
  fixture({
    ...initial,
    latest_decision: {
      id: "decision-1",
      artifact_id: "original",
      task_id: "review-task",
      source_version_id: "original-v2",
      extraction_version_id: "text-v2",
      metadata_revision: 8,
      state: "needs_review",
      proposed_type_id: "type-paper",
      reason_codes: ["human_review_required", "processing_instructions"],
      provider: "TypeSafe",
      requested_model: "jev-latest",
      returned_model: "jev-1.13",
      resolved_model: "jev-1.13",
      question_version: "document-type.v2",
      policy_version: "documents.v1",
      catalog_snapshot: [],
      state_hash: "state-hash",
      question_hash: "questions-hash",
      input_manifest: {},
      questions: {},
      answers: {
        document_type: {
          type: "choice",
          choice: "type-paper",
          confidence: 0.72,
          probabilities: { "type-paper": 0.91, unknown: 0.06, mixed: 0.03 },
        },
        sufficient_evidence: { type: "noul", noul: 0.94 },
        incompatible_purposes: { type: "noul", noul: 0.08 },
        processing_instructions: { type: "noul", noul: 0.87 },
        explicit_commitment: { type: "noul", noul: 0.73 },
        follow_up_requested: { type: "noul", noul: 0.62 },
        deadline_present: { type: "noul", noul: 0.83 },
      },
      usage: {},
      cost_status: "settled",
      provenance: "mocked",
      latency_ms: 12,
      error: null,
      created_at: "2026-09-24T10:00:00Z",
      excerpt: "Synthetic abstract: distributed systems.",
    },
  });
  mount(<DocumentDecisions artifactId="original" />);
  await screen.findByText("Selected choice probability");
  expect(screen.getByText("91.0%")).toBeVisible();
  expect(screen.getByText("72.0%")).toBeVisible();
  expect(screen.getByText("87.0%")).toBeVisible();
  expect(screen.getByText("83.0%")).toBeVisible();
  expect(screen.getByText(/does not establish urgency/)).toBeVisible();
  expect(screen.getByText("mocked result")).toBeVisible();
  expect(screen.getByText(/cannot change a type or title/)).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "Apply name" }),
  ).not.toBeInTheDocument();
});

it("enabling automatic classification requires acknowledged text processing", async () => {
  const requests = fixture();
  mount(<DocumentSettings />);
  const mode = await screen.findByLabelText("Automatic classification");
  fireEvent.change(mode, { target: { value: "after_extraction" } });
  expect(
    screen.getByRole("button", { name: "Save document settings" }),
  ).toBeDisabled();
  expect(
    screen.getByRole("checkbox", { name: /I allow extracted text/ }),
  ).not.toBeChecked();
  expect(requests.every((request) => request.method === "GET")).toBe(true);
});

it("sends explicit research and agent context together, and renews acknowledgement when context changes", async () => {
  const requests = fixture({
    ...initial,
    policy: { ...policy, provider_ready: true },
  });
  mount(<DocumentDecisions artifactId="original" />);
  await screen.findByRole("button", { name: "Classify with Jev" });
  fireEvent.click(screen.getByText("Add research or agent checks"));
  fireEvent.change(screen.getByLabelText("Research question"), {
    target: { value: "What supports the accessibility claim?" },
  });
  fireEvent.click(screen.getByRole("checkbox", { name: /Send this document/ }));
  fireEvent.change(screen.getByLabelText("Claim to check"), {
    target: { value: "The project improved keyboard access." },
  });
  expect(
    screen.getByRole("checkbox", { name: /Send this document/ }),
  ).not.toBeChecked();
  fireEvent.change(screen.getByLabelText("Original agent request"), {
    target: { value: "Summarize the evidence." },
  });
  fireEvent.change(screen.getByLabelText("Policy to check"), {
    target: { value: "Use only claims present in the source." },
  });
  fireEvent.change(screen.getByLabelText("Proposed action"), {
    target: { value: "Save an internal evidence note." },
  });
  fireEvent.click(screen.getByRole("checkbox", { name: /Send this document/ }));
  fireEvent.click(screen.getByRole("button", { name: "Classify with Jev" }));
  await waitFor(() =>
    expect(
      requests.filter((request) => request.method === "POST"),
    ).toHaveLength(1),
  );
  expect(
    requests.find((request) => request.method === "POST")?.body
      .analysis_context,
  ).toEqual({
    research_query: "What supports the accessibility claim?",
    claim: "The project improved keyboard access.",
    agent_request: "Summarize the evidence.",
    policy: "Use only claims present in the source.",
    proposed_action: "Save an internal evidence note.",
  });
});
