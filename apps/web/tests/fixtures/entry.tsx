import { createRoot } from "react-dom/client";
import { Providers } from "../../src/components/providers";
import { WorkspaceShell } from "../../src/components/workspace/shell";
import { isResource } from "../../src/components/workspace/context";
import { Records } from "../../src/components/workspace/records";
import { Overview } from "../../src/components/workspace/overview";
import { Agents } from "../../src/components/workspace/agents";
import { Settings } from "../../src/components/workspace/settings";
import { installNavigation, usePathname } from "./navigation";
import "../../src/app/globals.css";

installNavigation();
const base = {
  row_version: 1,
  created_at: "2026-09-21T10:00:00Z",
  updated_at: "2026-09-21T10:00:00Z",
  archived_at: null,
};
const company = {
  ...base,
  id: "company-1",
  name: "Northstar",
  industry: "Developer tools",
  location: "San Francisco",
  website: "https://example.com",
  notes: "Synthetic company for interface review.",
};
const contact = {
  ...base,
  id: "contact-1",
  name: "Alex Morgan",
  title: "Engineering lead",
  company_id: company.id,
  email: "alex@example.com",
  relationship: "warm",
  notes: "Discuss the platform team and interview process.",
};
const opportunities: Record<string, unknown>[] = [
  {
    ...base,
    id: "opportunity-1",
    title: "Staff Product Engineer",
    company_id: company.id,
    contact_id: contact.id,
    stage: "interviewing",
    priority: 2,
    notes:
      "Build thoughtful tools for small teams. Follow up after the technical conversation.",
  },
  {
    ...base,
    id: "opportunity-2",
    title: "Senior Frontend Engineer",
    company_id: company.id,
    stage: "researching",
    priority: 1,
    notes: "Review the product and speak to the team.",
  },
];
const tasks = [
  {
    ...base,
    id: "task-1",
    title: "Prepare for the technical conversation",
    opportunity_id: opportunities[0].id,
    state: "open",
    priority: 2,
    due_date: "2026-09-24",
  },
];
const artifact = {
  ...base,
  id: "artifact-1",
  title: "Northstar interview brief",
  kind: "document",
  sensitivity: "private",
  latest_version: 3,
  document_type_id: "document-type-brief",
};
const resumeArtifact = {
  ...base,
  id: "artifact-resume",
  title: "Synthetic resume",
  kind: "document",
  sensitivity: "private",
  latest_version: 1,
  document_type_id: "document-type-resume",
};
const resumeExtractionArtifact = {
  ...base,
  id: "artifact-resume-extracted",
  title: "Synthetic resume extracted text",
  kind: "document",
  sensitivity: "private",
  latest_version: 1,
  document_type_id: "document-type-resume",
};
const sourceArtifact = {
  ...base,
  id: "artifact-source-1",
  title: "Northstar role source",
  kind: "source",
  sensitivity: "public",
  latest_version: 1,
  document_type_id: null,
};
const empty = { items: [], total: 0 };
const rows: Record<string, Record<string, unknown>[]> = {
  companies: [company],
  contacts: [contact],
  opportunities,
  tasks,
  artifacts: [
    artifact,
    resumeArtifact,
    resumeExtractionArtifact,
    sourceArtifact,
  ],
  jobs: [],
};
const conversationBase = {
  row_version: 1,
  created_at: "2026-09-21T10:00:00Z",
  updated_at: "2026-09-21T10:00:00Z",
};
const sessions: Record<string, unknown>[] = [
  {
    ...conversationBase,
    id: "session-opportunity-1",
    title: "Staff Product Engineer conversation",
    task_id: null,
    opportunity_id: "opportunity-1",
    last_sequence: 3,
  },
];
const sessionMessages: Record<string, Record<string, unknown>[]> = {
  "session-opportunity-1": [
    {
      ...conversationBase,
      id: "message-opportunity-1-user",
      session_id: "session-opportunity-1",
      run_id: "run-opportunity-1",
      sequence: 1,
      author: "user",
      profile: "research",
      content: "Summarize the interview context.",
    },
    {
      ...conversationBase,
      id: "message-opportunity-1-assistant",
      session_id: "session-opportunity-1",
      run_id: "run-opportunity-1",
      sequence: 2,
      author: "assistant",
      profile: "research",
      content:
        "## Interview brief\n\n**Northstar** is hiring for a platform-focused role.\n\n- Ask about the roadmap.\n- Connect prior developer-tools work.",
    },
    {
      ...conversationBase,
      id: "message-opportunity-1-steering",
      session_id: "session-opportunity-1",
      run_id: "run-opportunity-1",
      sequence: 3,
      author: "user",
      profile: "research",
      content: "Add compensation questions.",
    },
  ],
};
const sessionRuns: Record<string, Record<string, unknown>[]> = {
  "session-opportunity-1": [
    {
      ...conversationBase,
      id: "run-opportunity-1-continuation",
      title: "Continue interview brief",
      prompt: "Add compensation questions.",
      profile: "research",
      state: "completed",
      output: null,
      error_code: null,
      completed_at: "2026-09-21T10:04:00Z",
      session_id: "session-opportunity-1",
      input_sequence: 3,
      consumed_sequence: 3,
    },
    {
      ...conversationBase,
      id: "run-opportunity-1",
      title: "Prepare interview brief",
      prompt: "Summarize the interview context.",
      profile: "research",
      state: "completed",
      output:
        "## Interview brief\n\n**Northstar** is hiring for a platform-focused role.",
      error_code: null,
      completed_at: "2026-09-21T10:03:00Z",
      session_id: "session-opportunity-1",
      input_sequence: 1,
      consumed_sequence: 1,
    },
  ],
};
const runSteps: Record<string, Record<string, unknown>[]> = {
  "run-opportunity-1": [
    {
      id: "step-opportunity-1",
      name: "search_sources",
      role: "specialist",
      specialist: "research",
      summary: "Reviewed the synthetic company notes",
      state: "output-available",
      output: '{"sources":2,"status":"saved"}',
    },
  ],
};
const runArtifacts: Record<string, Record<string, unknown>[]> = {
  "run-opportunity-1": [
    {
      id: "artifact-1",
      title: "Northstar interview brief",
      kind: "document",
      version_id: "artifact-version-2",
      version: 2,
    },
  ],
};
const artifactVersions: Record<string, Record<string, unknown>[]> = {
  "artifact-1": [
    {
      id: "artifact-version-3",
      artifact_id: "artifact-1",
      version: 3,
      payload: { text: "Latest version three content." },
      content_sha256: "version-three-sha",
      created_at: "2026-09-21T10:05:00Z",
    },
    {
      id: "artifact-version-2",
      artifact_id: "artifact-1",
      version: 2,
      payload: { text: "Pinned version two content." },
      content_sha256: "version-two-sha",
      created_at: "2026-09-21T10:03:00Z",
    },
  ],
  "artifact-source-1": [
    {
      id: "source-version-1",
      artifact_id: "artifact-source-1",
      version: 1,
      payload: {
        text: "Synthetic fetched role evidence for the Northstar staff product role.",
      },
      content_sha256: "source-version-one-sha",
      created_at: "2026-09-21T10:07:00Z",
    },
  ],
  "artifact-resume": [
    {
      id: "resume-version-1",
      artifact_id: "artifact-resume",
      version: 1,
      payload: { text: "Original synthetic resume bytes are downloadable." },
      content_sha256: "resume-version-one-sha",
      created_at: "2026-09-21T10:08:00Z",
    },
  ],
  "artifact-resume-extracted": [
    {
      id: "resume-extraction-version-1",
      artifact_id: "artifact-resume-extracted",
      version: 1,
      payload: { text: "Product engineer with accessible systems experience." },
      content_sha256: "resume-extraction-one-sha",
      created_at: "2026-09-21T10:09:00Z",
    },
  ],
};
const documentImports: Record<string, unknown>[] = [
  {
    id: "document-import-completed",
    artifact_id: "artifact-resume",
    source_version_id: "resume-version-1",
    task_id: "task-document-review",
    filename: "synthetic-resume.pdf",
    media_type: "application/pdf",
    byte_size: 24576,
    state: "completed",
    extraction_artifact_id: "artifact-resume-extracted",
    extraction_version_id: "resume-extraction-version-1",
    error: null,
    created_at: "2026-09-21T10:08:00Z",
    row_version: 2,
  },
  {
    id: "document-import-failed",
    artifact_id: "artifact-1",
    source_version_id: "artifact-version-3",
    task_id: "task-document-failed",
    filename: "interview-brief.docx",
    media_type:
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    byte_size: 8192,
    state: "failed",
    extraction_artifact_id: null,
    extraction_version_id: null,
    error: "Converter was temporarily unavailable.",
    created_at: "2026-09-21T10:07:00Z",
    row_version: 2,
  },
];
tasks.push({
  ...base,
  id: "task-document-review",
  title: "Review synthetic resume extraction",
  opportunity_id: null,
  state: "open",
  priority: 1,
  due_date: "2026-09-25",
});
const defaultResume: Record<string, unknown> = {
  row_version: 1,
  version_id: "resume-version-1",
  artifact_id: "artifact-resume",
  title: "Synthetic resume",
  filename: "synthetic-resume.pdf",
  media_type: "application/pdf",
  byte_size: 24576,
};
const profileFacts: Record<string, unknown>[] = [
  {
    id: "fact-headline",
    row_version: 2,
    field: "headline",
    active: {
      id: "fact-headline-v1",
      version: 1,
      value: "Product engineer",
      context: null,
      source_version_id: "resume-extraction-version-1",
      source_artifact_id: "artifact-resume-extracted",
      source_excerpt: "Product engineer",
      valid_until: null,
      review_state: "approved",
      created_at: "2026-09-21T10:10:00Z",
    },
    current: {
      id: "fact-headline-v2",
      version: 2,
      value: "Staff product engineer",
      context: "Use for product engineering roles",
      source_version_id: "resume-extraction-version-1",
      source_artifact_id: "artifact-resume-extracted",
      source_excerpt: "Product engineer with accessible systems experience.",
      valid_until: null,
      review_state: "proposed",
      created_at: "2026-09-21T10:11:00Z",
    },
  },
];
const opportunityResearch: Record<string, Record<string, unknown>[]> = {};
const leadRequestKeys: Record<string, string[]> = {};
const documentRequestKeys: Record<string, string[]> = {};
const failedLeadRequests: Record<string, number> = {};
const terminalDetailsAvailable = new Set<string>();
let pendingTerminalRunId: string | undefined;
let retryImportFailures = 0;
let staleReview = true;

function page(items: Record<string, unknown>[], limit = 100) {
  return { items, total: items.length, limit, offset: 0 };
}

const fixtureFetch: typeof fetch = async (input, init) => {
  const url = new URL(String(input), location.origin);
  if (!url.pathname.startsWith("/api/backend/"))
    throw new Error("Only fixture API requests are supported");
  const route = url.pathname.replace("/api/backend/", "");
  const method = init?.method ?? "GET";
  const idempotencyKey =
    new Headers(init?.headers).get("Idempotency-Key") ?? "";
  const trackLeadRequest = (name: string) => {
    (leadRequestKeys[name] ??= []).push(idempotencyKey);
  };
  const shouldFailTwice = (name: string) => {
    failedLeadRequests[name] = (failedLeadRequests[name] ?? 0) + 1;
    return failedLeadRequests[name] <= 2;
  };
  if (route === "test/lead-request-keys") return Response.json(leadRequestKeys);
  if (route === "test/document-request-keys")
    return Response.json(documentRequestKeys);
  if (route === "test/complete-active-run" && method === "POST") {
    const run = Object.values(sessionRuns)
      .flat()
      .find((item) => ["queued", "running"].includes(String(item.state)));
    if (!run)
      return Response.json({ detail: "Active run not found" }, { status: 404 });
    run.state = "completed";
    run.output = "# Final run outcome\n\nThe final synthetic result is saved.";
    run.consumed_sequence = run.input_sequence;
    run.completed_at = "2026-09-21T10:06:00Z";
    run.row_version = Number(run.row_version) + 1;
    runSteps[String(run.id)] = [
      {
        id: `step-${String(run.id)}`,
        name: "finalize_plan",
        role: "specialist",
        specialist: "research",
        summary: "Final specialist result",
        state: "output-available",
        output: '{"status":"final"}',
      },
    ];
    pendingTerminalRunId = String(run.id);
    return Response.json(run);
  }
  if (route === "document-types")
    return Response.json([
      { id: "document-type-resume", name: "Resume", slug: "resume" },
      {
        id: "document-type-brief",
        name: "Interview brief",
        slug: "interview_brief",
      },
    ]);
  if (route === "documents/imports" && method === "GET")
    return Response.json(page(documentImports, 20));
  if (route === "documents/imports" && method === "POST") {
    (documentRequestKeys.upload ??= []).push(idempotencyKey);
    const form = init?.body as FormData;
    const file = form.get("file") as File;
    const artifactId = String(
      form.get("artifact_id") ??
        `artifact-upload-${documentImports.length + 1}`,
    );
    const existing = rows.artifacts.find((item) => item.id === artifactId);
    const version = Number(existing?.latest_version ?? 0) + 1;
    const versionId = `${artifactId}-version-${version}`;
    if (!existing) {
      rows.artifacts.push({
        ...base,
        id: artifactId,
        title: String(form.get("title")),
        kind: "document",
        sensitivity: "private",
        latest_version: version,
        document_type_id: String(form.get("document_type_id")),
      });
    } else {
      existing.latest_version = version;
      existing.row_version = Number(existing.row_version) + 1;
    }
    (artifactVersions[artifactId] ??= []).unshift({
      id: versionId,
      artifact_id: artifactId,
      version,
      payload: { text: "Conversion pending." },
      content_sha256: `${artifactId}-${version}-sha`,
      created_at: "2026-09-21T10:12:00Z",
    });
    const created = {
      id: `document-import-${documentImports.length + 1}`,
      artifact_id: artifactId,
      source_version_id: versionId,
      task_id: `task-document-${documentImports.length + 1}`,
      filename: file.name,
      media_type: file.type || "text/plain",
      byte_size: file.size,
      state: "queued",
      extraction_artifact_id: null,
      extraction_version_id: null,
      error: null,
      created_at: "2026-09-21T10:12:00Z",
      row_version: 1,
    };
    documentImports.unshift(created);
    return Response.json(created, { status: 202 });
  }
  const importAction = route.match(
    /^documents\/imports\/([^/]+)\/(retry|cancel)$/,
  );
  if (importAction && method === "POST") {
    const item = documentImports.find(
      (candidate) => candidate.id === importAction[1],
    );
    if (!item)
      return Response.json({ detail: "Import not found" }, { status: 404 });
    const action = importAction[2];
    (documentRequestKeys[action] ??= []).push(idempotencyKey);
    if (action === "retry" && retryImportFailures++ === 0)
      return Response.json(
        { detail: "Queue temporarily unavailable." },
        { status: 503 },
      );
    item.state = action === "retry" ? "queued" : "cancelled";
    item.error = null;
    item.row_version = Number(item.row_version) + 1;
    return Response.json(item);
  }
  const downloadMatch = route.match(
    /^artifacts\/([^/]+)\/versions\/([^/]+)\/download$/,
  );
  if (downloadMatch)
    return new Response(`Synthetic bytes for ${downloadMatch[2]}`, {
      headers: {
        "Content-Type": "application/octet-stream",
        "Content-Disposition": "attachment; filename=synthetic-document.txt",
        "X-Content-Type-Options": "nosniff",
      },
    });
  if (route === "profile/default-resume" && method === "GET")
    return Response.json(defaultResume);
  if (route === "profile/default-resume" && method === "POST") {
    const body = JSON.parse(String(init?.body)) as {
      version_id: string | null;
    };
    defaultResume.version_id = body.version_id;
    defaultResume.row_version = Number(defaultResume.row_version) + 1;
    const selectedImport = documentImports.find(
      (item) => item.source_version_id === body.version_id,
    );
    defaultResume.artifact_id = selectedImport?.artifact_id ?? null;
    defaultResume.filename = selectedImport?.filename ?? null;
    defaultResume.byte_size = selectedImport?.byte_size ?? null;
    return Response.json(defaultResume);
  }
  if (route === "profile/facts" && method === "GET")
    return Response.json(page(profileFacts, 100));
  if (route === "profile/facts" && method === "POST") {
    const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
    const created = {
      id: `fact-${profileFacts.length + 1}`,
      row_version: 1,
      field: body.field,
      active: null,
      current: {
        id: `fact-${profileFacts.length + 1}-v1`,
        version: 1,
        value: body.value,
        context: body.context ?? null,
        source_version_id: null,
        source_artifact_id: null,
        source_excerpt: null,
        valid_until: body.valid_until ?? null,
        review_state: "proposed",
        created_at: "2026-09-21T10:13:00Z",
      },
    };
    profileFacts.push(created);
    return Response.json(created);
  }
  const factVersionMatch = route.match(/^profile\/facts\/([^/]+)\/versions$/);
  if (factVersionMatch && method === "POST") {
    const fact = profileFacts.find((item) => item.id === factVersionMatch[1]);
    if (!fact)
      return Response.json({ detail: "Fact not found" }, { status: 404 });
    const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
    const previous = fact.current as Record<string, unknown>;
    fact.row_version = Number(fact.row_version) + 1;
    fact.current = {
      ...previous,
      id: `${fact.id}-v${Number(previous.version) + 1}`,
      version: Number(previous.version) + 1,
      value: body.value,
      context: body.context ?? null,
      valid_until: body.valid_until ?? null,
      review_state: "proposed",
    };
    return Response.json(fact);
  }
  const factReviewMatch = route.match(/^profile\/facts\/([^/]+)\/reviews$/);
  if (factReviewMatch && method === "POST") {
    if (staleReview) {
      staleReview = false;
      return Response.json(
        { detail: "Fact changed after this review was opened." },
        { status: 409 },
      );
    }
    const fact = profileFacts.find((item) => item.id === factReviewMatch[1]);
    if (!fact)
      return Response.json({ detail: "Fact not found" }, { status: 404 });
    const body = JSON.parse(String(init?.body)) as {
      revision_id: string;
      decision: string;
    };
    const current = fact.current as Record<string, unknown>;
    const active = fact.active as Record<string, unknown> | null;
    const revision = current.id === body.revision_id ? current : active;
    if (!revision)
      return Response.json({ detail: "Revision not found" }, { status: 404 });
    revision.review_state = body.decision;
    fact.active =
      body.decision === "approved"
        ? revision
        : body.decision === "revoked"
          ? null
          : fact.active;
    fact.row_version = Number(fact.row_version) + 1;
    return Response.json(fact);
  }
  const artifactVersionsMatch = route.match(/^artifacts\/([^/]+)\/versions$/);
  if (artifactVersionsMatch && method === "GET")
    return Response.json(artifactVersions[artifactVersionsMatch[1]] ?? []);
  if (/^versions\/[^/]+\/reviews$/.test(route)) return Response.json([]);
  if (route === "research/search" && method === "POST") {
    trackLeadRequest("search");
    const body = JSON.parse(String(init?.body)) as { query: string };
    const failureId = `search:${idempotencyKey}`;
    if (
      body.query.toLowerCase().includes("retry provider") &&
      shouldFailTwice(failureId)
    ) {
      return Response.json(
        { detail: "The public search provider is temporarily unavailable." },
        { status: 503 },
      );
    }
    return Response.json([
      {
        title: "Platform Engineer",
        url: "https://jobs.example.com/meridian/platform-engineer",
        content:
          "Synthetic public result for a platform engineering role at Meridian Labs.",
      },
      {
        title: "Product Engineer",
        url: "https://careers.example.org/solstice/product-engineer",
        content:
          "Synthetic public result for a product engineering role at Solstice Systems.",
      },
    ]);
  }
  if (route === "leads/capture" && method === "POST") {
    trackLeadRequest("capture");
    const body = JSON.parse(String(init?.body)) as {
      url: string;
      title: string;
      company_name: string;
      snippet?: string;
    };
    const failureId = `capture:${idempotencyKey}`;
    if (body.company_name === "Retry Labs" && shouldFailTwice(failureId)) {
      return Response.json(
        { detail: "Lead capture is temporarily unavailable." },
        { status: 503 },
      );
    }
    const existingJob = rows.jobs.find((item) => item.source_url === body.url);
    const existingOpportunity = existingJob
      ? opportunities.find((item) => item.job_id === existingJob.id)
      : undefined;
    if (existingJob && existingOpportunity) {
      const existingSource =
        opportunityResearch[String(existingOpportunity.id)]?.[0];
      return Response.json({
        opportunity_id: existingOpportunity.id,
        job_id: existingJob.id,
        company_id: existingOpportunity.company_id,
        created: false,
        source: existingSource,
      });
    }
    const suffix = String(rows.jobs.length + 1);
    const companyRecord = {
      ...base,
      id: `company-lead-${suffix}`,
      name: body.company_name,
      industry: null,
      location: null,
      website: null,
      notes: null,
    };
    const job = {
      ...base,
      id: `job-lead-${suffix}`,
      title: body.title,
      company_id: companyRecord.id,
      source_url: body.url,
      status: "unknown",
      location: null,
      work_mode: null,
    };
    const opportunity = {
      ...base,
      id: `opportunity-lead-${suffix}`,
      title: body.title,
      company_id: companyRecord.id,
      job_id: job.id,
      stage: "researching",
      priority: 1,
      notes: null,
    };
    const source = {
      id: `lead-source-${suffix}-1`,
      artifact_id: `artifact-source-lead-${suffix}`,
      version_id: `source-version-lead-${suffix}-1`,
      version: 1,
      url: body.url,
      title: body.title,
      provider: "search",
      retrieved_at: "2026-09-21T10:08:00Z",
      excerpt: body.snippet ?? "",
    };
    rows.companies.push(companyRecord);
    rows.jobs.push(job);
    opportunities.push(opportunity);
    rows.artifacts.push({
      ...base,
      id: source.artifact_id,
      title: `${body.title} source`,
      kind: "source",
      sensitivity: "public",
      latest_version: 1,
      document_type_id: null,
    });
    artifactVersions[source.artifact_id] = [
      {
        id: source.version_id,
        artifact_id: source.artifact_id,
        version: 1,
        payload: { text: body.snippet ?? "" },
        content_sha256: `source-lead-${suffix}-one-sha`,
        created_at: source.retrieved_at,
      },
    ];
    opportunityResearch[opportunity.id] = [source];
    return Response.json({
      opportunity_id: opportunity.id,
      job_id: job.id,
      company_id: companyRecord.id,
      created: true,
      source,
    });
  }
  const enrichMatch = route.match(/^opportunities\/([^/]+)\/enrich$/);
  if (enrichMatch && method === "POST") {
    trackLeadRequest("enrich");
    const opportunityId = enrichMatch[1];
    const failureId = `enrich:${idempotencyKey}`;
    if (opportunityId === "opportunity-2" && shouldFailTwice(failureId)) {
      return Response.json(
        { detail: "The page fetch provider timed out." },
        { status: 503 },
      );
    }
    const opportunity = opportunities.find((item) => item.id === opportunityId);
    if (!opportunity)
      return Response.json(
        { detail: "Opportunity not found" },
        { status: 404 },
      );
    const existing = opportunityResearch[opportunityId]?.[0];
    const artifactId = String(
      existing?.artifact_id ?? `artifact-source-${opportunityId}`,
    );
    const nextVersion = Number(existing?.version ?? 0) + 1;
    const versionId = `${artifactId}-version-${nextVersion}`;
    if (!rows.artifacts.some((item) => item.id === artifactId))
      rows.artifacts.push({
        ...base,
        id: artifactId,
        title: `${String(opportunity.title)} source`,
        kind: "source",
        sensitivity: "public",
        latest_version: nextVersion,
        document_type_id: null,
      });
    const artifactRecord = rows.artifacts.find(
      (item) => item.id === artifactId,
    );
    if (artifactRecord) artifactRecord.latest_version = nextVersion;
    const source = {
      id: `lead-source-${opportunityId}-${nextVersion}`,
      artifact_id: artifactId,
      version_id: versionId,
      version: nextVersion,
      url: String(
        rows.jobs.find((item) => item.id === opportunity.job_id)?.source_url ??
          "https://jobs.example.com/northstar/staff-product-engineer",
      ),
      title: `${String(opportunity.title)} public role page`,
      provider: "firecrawl",
      retrieved_at: "2026-09-21T10:09:00Z",
      excerpt: "Synthetic fetched evidence saved from the public role page.",
    };
    (artifactVersions[artifactId] ??= []).unshift({
      id: versionId,
      artifact_id: artifactId,
      version: nextVersion,
      payload: {
        text: `Exact immutable evidence for ${String(opportunity.title)}, version ${nextVersion}.`,
      },
      content_sha256: `${artifactId}-${nextVersion}-sha`,
      created_at: source.retrieved_at,
    });
    (opportunityResearch[opportunityId] ??= []).unshift(source);
    return Response.json(source);
  }
  const researchMatch = route.match(/^opportunities\/([^/]+)\/research$/);
  if (researchMatch && method === "GET")
    return Response.json(page(opportunityResearch[researchMatch[1]] ?? [], 20));
  if (route === "agent-sessions") {
    if (method === "POST") {
      const body = JSON.parse(String(init?.body)) as Record<string, string>;
      const existing = sessions.find(
        (item) =>
          (body.task_id && item.task_id === body.task_id) ||
          (body.opportunity_id && item.opportunity_id === body.opportunity_id),
      );
      if (existing) return Response.json(existing);
      const created = {
        ...conversationBase,
        id: `session-${body.task_id ?? body.opportunity_id}`,
        title: "Work conversation",
        task_id: body.task_id ?? null,
        opportunity_id: body.opportunity_id ?? null,
        last_sequence: 0,
      };
      sessions.push(created);
      sessionMessages[String(created.id)] = [];
      sessionRuns[String(created.id)] = [];
      return Response.json(created);
    }
    const taskId = url.searchParams.get("task_id");
    const opportunityId = url.searchParams.get("opportunity_id");
    return Response.json(
      page(
        sessions.filter(
          (item) =>
            (taskId && item.task_id === taskId) ||
            (opportunityId && item.opportunity_id === opportunityId),
        ),
        1,
      ),
    );
  }
  const messageMatch = route.match(/^agent-sessions\/([^/]+)\/messages$/);
  if (messageMatch) {
    const sessionId = messageMatch[1];
    const items = sessionMessages[sessionId] ?? [];
    if (method === "POST") {
      const body = JSON.parse(String(init?.body)) as {
        content: string;
        profile: string;
      };
      if (body.content === "First delayed message.")
        await new Promise((resolve) => setTimeout(resolve, 300));
      const existingRun = (sessionRuns[sessionId] ?? []).find((run) =>
        ["queued", "running"].includes(String(run.state)),
      );
      if (existingRun && existingRun.profile !== body.profile)
        return Response.json(
          { detail: "Keep the same profile while work is active." },
          { status: 409 },
        );
      const sequence = items.length + 1;
      const run = existingRun ?? {
        ...conversationBase,
        id: `run-${sessionId}-${crypto.randomUUID()}`,
        title: "Conversation work",
        prompt: body.content,
        profile: body.profile,
        state: "running",
        output: null,
        error_code: null,
        completed_at: null,
        session_id: sessionId,
        input_sequence: sequence,
        consumed_sequence: 0,
      };
      if (!existingRun) (sessionRuns[sessionId] ??= []).unshift(run);
      else {
        existingRun.input_sequence = sequence;
        existingRun.row_version = Number(existingRun.row_version) + 1;
      }
      const message = {
        ...conversationBase,
        id: `message-${sessionId}-${sequence}`,
        session_id: sessionId,
        run_id: run.id,
        sequence,
        author: "user",
        profile: body.profile,
        content: body.content,
      };
      items.push(message);
      const target = sessions.find((item) => item.id === sessionId);
      if (target) target.last_sequence = sequence;
      return Response.json(message);
    }
    const after = Number(url.searchParams.get("after_sequence") ?? 0);
    return Response.json(
      page(items.filter((item) => Number(item.sequence) > after)),
    );
  }
  const sessionRunsMatch = route.match(/^agent-sessions\/([^/]+)\/runs$/);
  if (sessionRunsMatch) {
    const items = sessionRuns[sessionRunsMatch[1]] ?? [];
    if (
      pendingTerminalRunId &&
      items.some((item) => item.id === pendingTerminalRunId)
    ) {
      terminalDetailsAvailable.add(pendingTerminalRunId);
      pendingTerminalRunId = undefined;
    }
    return Response.json(page(items, 30));
  }
  const runRoute = route.match(
    /^agent-runs\/([^/]+)(?:\/(steps|artifacts|cancel))?$/,
  );
  if (runRoute) {
    const runId = runRoute[1];
    const action = runRoute[2];
    const run = Object.values(sessionRuns)
      .flat()
      .find((item) => item.id === runId);
    if (!run)
      return Response.json({ detail: "Run not found" }, { status: 404 });
    if (action === "steps")
      return Response.json(
        run.state === "completed" &&
          runId.startsWith("run-session-") &&
          !terminalDetailsAvailable.has(runId)
          ? []
          : (runSteps[runId] ?? []),
      );
    if (action === "artifacts")
      return Response.json(page(runArtifacts[runId] ?? []));
    if (action === "cancel" && method === "POST") {
      run.state = "cancelled";
      run.row_version = Number(run.row_version) + 1;
      run.updated_at = "2026-09-21T10:04:00Z";
      return Response.json(run);
    }
    return Response.json(run);
  }
  let payload: unknown = empty;
  const [resource, id] = route.split("/");
  if (rows[resource]) {
    if (!id && init?.method === "POST") {
      const created = {
        ...base,
        ...JSON.parse(String(init.body)),
        id: crypto.randomUUID(),
      };
      rows[resource].push(created);
      return Response.json(created);
    }
    if (id) {
      const record = rows[resource].find((row) => row.id === id);
      if (!record)
        return Response.json({ detail: "Record not found" }, { status: 404 });
      if (init?.method === "PATCH")
        Object.assign(record, JSON.parse(String(init.body)), {
          row_version: Number(record.row_version) + 1,
        });
      payload = record;
    } else {
      const q = url.searchParams.get("q")?.toLowerCase() ?? "";
      const stage = url.searchParams.get("stage");
      const matches = rows[resource].filter(
        (row) =>
          String(row.name ?? row.title)
            .toLowerCase()
            .includes(q) &&
          (!stage || row.stage === stage),
      );
      payload = { items: matches, total: matches.length };
    }
  }
  if (route === "company-labels") payload = [company];
  if (route === "me")
    payload = {
      ...base,
      display_name: "Alex’s workspace",
      headline: "Product engineer",
      location: "San Francisco",
      timezone: "America/Los_Angeles",
    };
  if (route === "dashboard")
    payload = {
      counts: { opportunities: 2, contacts: 1, companies: 1, tasks: 1 },
      stages: { researching: 1, interviewing: 1 },
      tasks,
    };
  if (route === "agents/profiles")
    payload = [
      {
        id: "lead",
        name: "Lead",
        description: "Coordinates the work",
        provider: "gemini",
        model: "Synthetic preview",
        ready: true,
        missing_credentials: [],
        tools: [],
        skills: [],
        revision: "lead-v1",
      },
      {
        id: "research",
        name: "Research",
        description: "Research companies and roles",
        provider: "gemini",
        model: "Synthetic preview",
        ready: true,
        missing_credentials: [],
        tools: [],
        skills: [],
        revision: "research-v1",
      },
      {
        id: "application",
        name: "Application",
        description: "Prepares application materials",
        provider: "gemini",
        model: "Synthetic preview",
        ready: true,
        missing_credentials: [],
        tools: [],
        skills: [],
        revision: "application-v1",
      },
      {
        id: "outreach",
        name: "Outreach",
        description: "Drafts reviewed outreach",
        provider: "gemini",
        model: "Synthetic preview",
        ready: true,
        missing_credentials: [],
        tools: [],
        skills: [],
        revision: "outreach-v1",
      },
      {
        id: "mixed",
        name: "Mixed provider profile",
        description: "Uses a Mistral specialist",
        provider: "gemini",
        model: "Synthetic preview",
        ready: false,
        missing_credentials: ["MISTRAL_API_KEY"],
        tools: [],
        skills: [],
        revision: "mixed-v1",
      },
    ];
  if (route === "agent-runs" && method === "POST") {
    const body = JSON.parse(String(init?.body));
    return Response.json({
      ...base,
      id: crypto.randomUUID(),
      profile: body.profile,
      title: body.prompt,
      prompt: body.prompt,
      state: "queued",
      output: null,
      error: null,
    });
  }
  if (route === "agent-runs")
    payload = {
      items: [
        {
          ...base,
          id: "run-1",
          profile: "research",
          title: "Northstar research",
          prompt: "Summarize this synthetic company.",
          state: "completed",
          output:
            "## Company brief\n\n**Northstar** builds developer tools.\n\n- Ask about the platform roadmap.\n- Review team responsibilities.",
          error: null,
        },
      ],
      total: 1,
    };
  if (route === "agent-runs/run-1/steps") payload = [];
  if (route === "integrations")
    payload = {
      services: [
        { name: "Firecrawl", state: "online" },
        { name: "SearXNG", state: "online" },
      ],
      model_providers: {
        openai: false,
        gemini: true,
        mistral: false,
        cohere: false,
      },
      openai_configured: false,
      composio_configured: false,
      auth: "clerk",
      composio_toolkits: [],
    };
  return Response.json(payload);
};
window.fetch = fixtureFetch;
function Preview() {
  const path = usePathname();
  const resource = path.slice(1);
  return (
    <Providers>
      <WorkspaceShell>
        {path === "/" ? (
          <Overview />
        ) : path === "/agents" ? (
          <Agents />
        ) : path === "/settings" ? (
          <Settings />
        ) : (
          <Records
            key={path}
            resource={isResource(resource) ? resource : "opportunities"}
          />
        )}
      </WorkspaceShell>
    </Providers>
  );
}
createRoot(document.getElementById("root")!).render(<Preview />);
