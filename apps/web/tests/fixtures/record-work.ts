import type { Schema } from "../../src/lib/api";

type Row = Record<string, unknown>;
type Workspace = {
  rows: Record<string, Row[]>;
  sessions: Row[];
  sessionMessages: Record<string, Row[]>;
  sessionRuns: Record<string, Row[]>;
  artifactVersions: Record<string, Row[]>;
};
type Work = Schema["WorkRead"] & {
  readyAt: number;
  target: string;
  resource: "contacts" | "companies";
  researchRequested?: boolean;
  connectionNote?: boolean;
};
const storage = "synthetic-record-work";
const base = {
  row_version: 1,
  archived_at: null,
  created_at: "2026-09-22T20:00:00Z",
  updated_at: "2026-09-22T20:00:00Z",
};
const brief =
  "# Northstar company brief\n\nNorthstar builds developer tools and lists platform engineering opportunities.\n\n## Next steps\n\nReview [the careers page](https://example.com/careers) and speak with the platform team. Availability and fit still need review.";

function install(work: Work, workspace: Workspace) {
  const contact = workspace.rows.contacts.find((row) => row.id === work.target);
  if (contact && (work.researchRequested || work.connectionNote)) {
    contact.outreach = {
      task_id: work.task_id,
      state: work.state,
      error_code: work.error_code,
      artifact_id: work.output_artifact_id,
      version_id: work.output_version_id,
      message: "",
      research: null,
      researched_at: null,
      sources: [],
    };
  }
  const task = {
    ...base,
    id: work.task_id,
    title:
      work.resource === "companies"
        ? "Research Northstar"
        : "Draft follow-up for Alex",
    state: work.output_version_id ? "done" : "open",
    priority: 1,
    rationale: "Synthetic record work",
    opportunity_id: null,
    due_date: null,
  };
  const oldTask = workspace.rows.tasks.find((row) => row.id === task.id);
  if (oldTask) Object.assign(oldTask, task);
  else workspace.rows.tasks.push(task);
  if (!workspace.sessions.some((row) => row.id === work.session_id))
    workspace.sessions.push({
      ...base,
      id: work.session_id,
      task_id: work.task_id,
      opportunity_id: null,
      title: task.title,
      last_sequence: 1,
    });
  workspace.sessionRuns[work.session_id] = [
    {
      ...base,
      id: work.run_id,
      title: task.title,
      prompt: "Synthetic request",
      profile: work.resource === "companies" ? "research" : "outreach",
      state: work.state,
      output: work.output_version_id ? "The requested result is saved." : null,
      error_code: null,
      completed_at: work.output_version_id ? base.created_at : null,
      session_id: work.session_id,
      input_sequence: 1,
      consumed_sequence: 1,
    },
  ];
  workspace.sessionMessages[work.session_id] = work.output_version_id
    ? [
        {
          ...base,
          id: `${work.task_id}-message`,
          session_id: work.session_id,
          run_id: work.run_id,
          sequence: 1,
          author: "assistant",
          profile: "research",
          content: "The requested result is saved for review.",
        },
      ]
    : [];
  if (!work.output_version_id || !work.output_artifact_id) return;
  const artifact = {
    ...base,
    id: work.output_artifact_id,
    title:
      work.resource === "companies"
        ? "Company brief · Northstar"
        : "Follow-up · Alex Morgan",
    kind: work.resource === "companies" ? "research" : "message",
    sensitivity: "private",
    latest_version: 1,
    document_type_id: null,
  };
  if (!workspace.rows.artifacts.some((row) => row.id === artifact.id))
    workspace.rows.artifacts.push(artifact);
  const payload =
    work.resource === "companies"
      ? { text: brief }
      : {
          text: "Hi Alex, I’m interested in the platform team. Would you be open to a short conversation?",
          format: "text",
          channel: work.channel,
          subject: "Platform team introduction",
          recipient_email: "alex@example.com",
          connection_note:
            work.channel === "linkedin" &&
            !!(work.researchRequested || work.connectionNote),
          ...(work.researchRequested
            ? {
                connection_note: work.channel === "linkedin",
                contact_research: {
                  identity: "matched",
                  company: "Northstar",
                  role: "Engineering lead",
                  summary:
                    "The official team page identifies Alex Morgan as Northstar’s engineering lead. The public biography matches the saved LinkedIn profile.",
                  caveats: "Current hiring needs have not been confirmed.",
                  identity_evidence: [
                    {
                      source_version_id: "00000000-0000-4000-8000-000000000001",
                      quote: "Alex Morgan leads engineering at Northstar.",
                    },
                  ],
                  employment_evidence: [
                    {
                      source_version_id: "00000000-0000-4000-8000-000000000001",
                      quote: "Alex Morgan leads engineering at Northstar.",
                    },
                  ],
                },
              }
            : {}),
        };
  const version = {
    id: work.output_version_id,
    artifact_id: artifact.id,
    version: 1,
    payload,
    created_at: base.created_at,
    content_sha256: "synthetic-record-work-output",
    input_version_ids: [],
  };
  workspace.artifactVersions[artifact.id] = [version];
  if (work.resource === "companies") {
    const company = workspace.rows.companies.find(
      (row) => row.id === work.target,
    );
    if (company)
      company.latest_research = {
        task_id: work.task_id,
        artifact_id: artifact.id,
        version_id: version.id,
        summary:
          "Northstar builds developer tools and lists platform engineering opportunities.",
        created_at: base.created_at,
      };
  } else {
    const drafts = JSON.parse(
      localStorage.getItem("synthetic-follow-ups") ?? "{}",
    );
    // Keep a human edit to an already generated artifact across subsequent polls.
    drafts[artifact.id] ??= {
      artifact,
      version,
      contact_id: work.target,
      plain_text: payload.text,
    };
    localStorage.setItem("synthetic-follow-ups", JSON.stringify(drafts));
    if (contact && (work.researchRequested || work.connectionNote)) {
      const saved = drafts[artifact.id];
      contact.outreach = {
        task_id: work.task_id,
        state: work.state,
        error_code: work.error_code,
        artifact_id: artifact.id,
        version_id: saved.version.id,
        message: saved.plain_text,
        research:
          "contact_research" in payload ? payload.contact_research : null,
        researched_at: base.created_at,
        sources: [
          {
            version_id: "00000000-0000-4000-8000-000000000001",
            url: "https://example.com/team",
            retrieved_at: base.created_at,
          },
        ],
      };
    }
  }
}

export async function recordWorkFixture(
  url: URL,
  init: RequestInit | undefined,
  workspace: Workspace,
) {
  const works: Work[] = JSON.parse(localStorage.getItem(storage) ?? "[]");
  for (const work of works) {
    if (Date.now() >= work.readyAt) {
      work.state = "completed";
      work.output_artifact_id ??= crypto.randomUUID();
      work.output_version_id ??= crypto.randomUUID();
    }
    install(work, workspace);
  }
  localStorage.setItem(storage, JSON.stringify(works));
  const route = url.pathname.replace("/api/backend/", "");
  const match = route.match(/^record-work\/(contacts|companies)\/([^/]+)$/);
  if (!match) return null;
  if ((init?.method ?? "GET") === "GET")
    return Response.json(
      works
        .filter(
          (work) => work.resource === match[1] && work.target === match[2],
        )
        .reverse(),
    );
  const key = new Headers(init?.headers).get("Idempotency-Key");
  const requestKey = "synthetic-record-work-requests";
  const requests = JSON.parse(localStorage.getItem(requestKey) ?? "[]");
  requests.push({ route, key, body: JSON.parse(String(init?.body ?? "{}")) });
  localStorage.setItem(requestKey, JSON.stringify(requests));
  const receipts: Record<string, Work> = JSON.parse(
    localStorage.getItem("synthetic-work-receipts") ?? "{}",
  );
  let work = receipts[String(key)];
  if (!work) {
    work = {
      task_id: crypto.randomUUID(),
      session_id: crypto.randomUUID(),
      run_id: crypto.randomUUID(),
      state: "queued",
      channel: JSON.parse(String(init?.body ?? "{}")).channel ?? "linkedin",
      error_code: null,
      contact_id: match[1] === "contacts" ? match[2] : null,
      company_id: match[1] === "companies" ? match[2] : null,
      output_artifact_id: null,
      output_version_id: null,
      output_archived: false,
      created_at: base.created_at,
      readyAt: Date.now() + 500,
      target: match[2],
      resource: match[1] as Work["resource"],
      researchRequested: !!JSON.parse(String(init?.body ?? "{}"))
        .research_requested,
      connectionNote: !!JSON.parse(String(init?.body ?? "{}")).connection_note,
    };
    works.push(work);
    receipts[String(key)] = work;
    localStorage.setItem(storage, JSON.stringify(works));
    localStorage.setItem("synthetic-work-receipts", JSON.stringify(receipts));
    install(work, workspace);
  }
  if (
    new URLSearchParams(location.search).has("work_fail_start") &&
    requests.length <= 2
  )
    return Response.json(
      {
        detail: "Synthetic response interrupted after the request was accepted",
      },
      { status: 503 },
    );
  return Response.json(work, { status: 201 });
}
