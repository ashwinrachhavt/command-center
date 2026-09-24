type Row = Record<string, unknown>;
const storageKey = "synthetic-document-decisions-v1";
const stamp = "2026-09-24T12:00:00Z";
type State = {
  policy: Row;
  decisions: Record<string, Row>;
  renames: Record<string, Row>;
  receipts: Record<string, unknown>;
};
const initial = (): State => ({
  policy: {
    revision: 0,
    classification_mode: "off",
    catalog_ids: [
      "document-type-resume",
      "document-type-notes",
      "document-type-brief",
    ],
    rename_mode: "off",
    rename_template: "{type} - {uploaded_date} - {short_id}",
    timezone: "America/Los_Angeles",
    provider: "typesafe",
    provider_ready: true,
  },
  decisions: {},
  renames: {},
  receipts: {},
});
export async function documentDecisionsFixture(
  url: URL,
  init: RequestInit | undefined,
  rows: Record<string, Row[]>,
  imports: Row[],
) {
  const path = url.pathname.replace("/api/backend/", "");
  if (!(
    path === "documents/policy" ||
    /^documents\/[^/]+\/classification(?:\/review)?$/.test(path) ||
    path.startsWith("documents/renames/") ||
    path === "test/document-decisions"
  ))
    return null;
  const method = init?.method ?? "GET";
  const state: State =
    JSON.parse(localStorage.getItem(storageKey) ?? "null") ?? initial();
  const body = init?.body ? JSON.parse(String(init.body)) : {};
  const key = new Headers(init?.headers).get("Idempotency-Key") ?? "";
  const save = (value: unknown) => {
    if (method !== "GET") state.receipts[`${path}:${key}`] = value;
    localStorage.setItem(storageKey, JSON.stringify(state));
    return Response.json(value);
  };
  if (method !== "GET" && state.receipts[`${path}:${key}`])
    return Response.json(state.receipts[`${path}:${key}`]);
  if (path === "test/document-decisions")
    return Response.json({
      ...state,
      filenames: imports.map((item) => item.filename),
    });
  if (path === "documents/policy") {
    if (method === "PUT") {
      if (body.expected_version !== state.policy.revision)
        return Response.json({ detail: "Settings changed" }, { status: 409 });
      state.policy = {
        ...state.policy,
        ...body,
        revision: Number(state.policy.revision) + 1,
      };
    }
    return save(state.policy);
  }
  const renameRoute = path.match(
    /^documents\/renames\/([^/]+)\/(apply|cancel)$/,
  );
  if (renameRoute) {
    const proposal = Object.values(state.renames).find(
      (item) => item.id === renameRoute[1],
    );
    if (!proposal)
      return Response.json({ detail: "Not found" }, { status: 404 });
    const artifact = rows.artifacts.find(
      (item) => item.id === proposal.artifact_id,
    )!;
    if (
      artifact.row_version !== proposal.metadata_revision ||
      body.expected_version !== proposal.row_version
    )
      return Response.json(
        { detail: "Title changed; review again" },
        { status: 409 },
      );
    if (renameRoute[2] === "apply") {
      artifact.title = proposal.after_title;
      artifact.row_version = Number(artifact.row_version) + 1;
    }
    proposal.state = renameRoute[2] === "apply" ? "applied" : "cancelled";
    proposal.row_version = Number(proposal.row_version) + 1;
    return save(proposal);
  }
  const artifactId = path.split("/")[1];
  const artifact = rows.artifacts.find((item) => item.id === artifactId);
  if (!artifact) return Response.json({ detail: "Not found" }, { status: 404 });
  const imported = imports.find((item) => item.artifact_id === artifactId);
  const snapshot = () => ({
    artifact_id: artifactId,
    accepted_type_id: artifact.document_type_id,
    metadata_revision: artifact.row_version,
    source_version_id: imported?.source_version_id ?? null,
    extraction_version_id: imported?.extraction_version_id ?? null,
    policy: state.policy,
    latest_decision: state.decisions[artifactId] ?? null,
    pending_rename: ["pending", "needs_correction"].includes(
      String(state.renames[artifactId]?.state),
    )
      ? state.renames[artifactId]
      : null,
  });
  if (method === "GET") return Response.json(snapshot());
  if (body.expected_version !== artifact.row_version)
    return Response.json({ detail: "Document changed" }, { status: 409 });
  if (path.endsWith("/review")) {
    if (body.outcome === "accept") {
      artifact.document_type_id = body.document_type_id;
      artifact.row_version = Number(artifact.row_version) + 1;
      if (state.policy.rename_mode === "task") {
        state.renames[artifactId] = {
          id: `rename-${artifactId}`,
          artifact_id: artifactId,
          review_id: "synthetic-review",
          policy_revision: state.policy.revision,
          metadata_revision: artifact.row_version,
          task_id: "task-document-review",
          before_title: artifact.title,
          after_title: "Resume - 2026-09-21 - a1b2c3d4",
          template: state.policy.rename_template,
          render_inputs: {
            type: "Resume",
            uploaded_date: "2026-09-21",
            short_id: "a1b2c3d4",
          },
          state: "pending",
          error: null,
          row_version: 1,
          created_at: stamp,
        };
      }
    }
    return save(snapshot());
  }
  const type = "document-type-resume";
  state.decisions[artifactId] = {
    id: `decision-${artifactId}`,
    artifact_id: artifactId,
    task_id: imported?.task_id,
    source_version_id: imported?.source_version_id,
    extraction_version_id: imported?.extraction_version_id,
    metadata_revision: artifact.row_version,
    state: "needs_review",
    proposed_type_id: type,
    reason_codes: ["human_review_required"],
    provider: "typesafe",
    requested_model: "jev-latest",
    returned_model: null,
    resolved_model: null,
    question_version: "document-type.v3",
    policy_version: "document-review.v1",
    catalog_snapshot: [
      {
        id: type,
        slug: "resume",
        name: "Resume",
        description: "Career experience and skills",
      },
    ],
    state_hash: "synthetic-state",
    question_hash: "synthetic-questions",
    input_manifest: {
      truncated: false,
      analysis_context: body.analysis_context ?? {},
    },
    questions: {
      document_type: {
        type: "choice",
        instructions: "Which catalog purpose is supported by the text?",
        criteria: { [type]: "Resume", unknown: "Unknown", mixed: "Mixed" },
      },
    },
    answers: {
      document_type: {
        type: "choice",
        choice: type,
        confidence: 0.8,
        probabilities: { [type]: 0.94, unknown: 0.04, mixed: 0.02 },
      },
      sufficient_evidence: { type: "noul", noul: 0.97 },
      incompatible_purposes: { type: "noul", noul: 0.05 },
      processing_instructions: { type: "noul", noul: 0.02 },
      explicit_commitment: { type: "noul", noul: 0.08 },
      follow_up_requested: { type: "noul", noul: 0.05 },
      deadline_present: { type: "noul", noul: 0.04 },
    },
    usage: null,
    cost_status: "not_started",
    provenance: "simulation",
    latency_ms: null,
    error: null,
    created_at: stamp,
    excerpt:
      "Synthetic resume: engineering projects, experience, education and skills.",
  };
  const context = body.analysis_context ?? {};
  const answers = state.decisions[artifactId].answers as Row;
  const score = {
    type: "score",
    score: 1.7,
    confidence: 0.8,
    legend: { "0": "Not supported", "1": "Partial", "2": "Directly supported" },
    probabilities: { "0": 0.1, "1": 0.1, "2": 0.8 },
  };
  if (context.research_query) {
    answers.relevance = score;
    answers.evidence_role = {
      type: "choice",
      choice: "direct_evidence",
      confidence: 0.8,
      probabilities: {
        direct_evidence: 0.8,
        background: 0.1,
        irrelevant: 0.05,
        insufficient: 0.05,
      },
    };
  }
  if (context.claim) answers.claim_supported = { type: "noul", noul: 0.85 };
  if (context.agent_request)
    answers.output_quality = {
      ...score,
      score: 1.4,
      probabilities: { "0": 0.1, "1": 0.4, "2": 0.5 },
    };
  if (context.policy) answers.policy_concern = { type: "noul", noul: 0.2 };
  if (context.agent_request && context.proposed_action)
    answers.action_matches_request = { type: "noul", noul: 0.9 };
  return save(state.decisions[artifactId]);
}
