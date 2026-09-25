import { createRoot } from "react-dom/client";
import WorkspaceError from "../../src/app/(workspace)/error";
import { Providers } from "../../src/components/providers";
import { WorkspaceShell } from "../../src/components/workspace/shell";
import { isResource } from "../../src/components/workspace/context";
import { Records } from "../../src/components/workspace/records";
import { Overview } from "../../src/components/workspace/overview";
import { ActivityPage } from "../../src/components/workspace/activity";
import { Briefing } from "../../src/components/workspace/briefing";
import { Spaces } from "../../src/components/workspace/spaces";
import { spacesFixture } from "./spaces";
import { documentDecisionsFixture } from "./document-decisions";
import { Agents } from "../../src/components/workspace/agents";
import { AgentSettings } from "../../src/components/workspace/agent-settings";
import { OpportunityNavigation } from "../../src/components/workspace/opportunity-navigation";
import { BrowserPage } from "../../src/components/workspace/browser";
import { Applications } from "../../src/components/workspace/applications";
import { applicationsFixture } from "./applications";
import { MemoryPage } from "../../src/components/workspace/memory";
import { Settings } from "../../src/components/workspace/settings";
import { ConnectedAccounts } from "../../src/components/workspace/connected-accounts";
import { ReviewedActions } from "../../src/components/workspace/reviewed-actions";
import { workflowFixture } from "./workflows";
import { connectionsFixture } from "./connections";
import { writingFixture } from "./writing";
import { careerFixture } from "./career";
import { followUpFixture } from "./follow-ups";
import { contactDiscoveryFixture } from "./contact-discovery";
import { recordWorkFixture } from "./record-work";
import { Library } from "../../src/components/workspace/library";
import { libraryFixture } from "./library";
import { installNavigation, usePathname } from "./navigation";
import "../../src/app/globals.css";

installNavigation();
const base = {
  row_version: 1,
  created_at: "2026-09-21T10:00:00Z",
  updated_at: "2026-09-21T10:00:00Z",
  archived_at: null,
};
const briefingRequests: {
  route: string;
  method: string;
  key: string;
  body?: Record<string, unknown>;
}[] = [];
const capturedTasks = new Map<string, Record<string, unknown>>();
let failedTaskCaptures = 0;
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
  linkedin_url: "https://www.linkedin.com/in/synthetic-cc-contact/",
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
  {
    ...base,
    id: "task-stream",
    title: "Review streamed application guidance",
    opportunity_id: opportunities[0].id,
    state: "open",
    priority: 1,
    due_date: null,
  },
  {
    ...base,
    id: "task-question",
    title: "Answer saved agent questions",
    opportunity_id: opportunities[0].id,
    state: "open",
    priority: 2,
    due_date: null,
  },
  {
    ...base,
    id: "task-waiting",
    title: "Wait for interview availability",
    opportunity_id: opportunities[0].id,
    state: "waiting",
    priority: 1,
    due_date: null,
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
const generatedArtifact = {
  ...artifact,
  id: "artifact-generated-brief",
  title: "Platform research memo",
  latest_version: 1,
  review_status: "unreviewed",
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
    generatedArtifact,
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
const answeredQuestionIds = new Set<string>(
  JSON.parse(sessionStorage.getItem("answered-question-ids") ?? "[]"),
);
const sessions: Record<string, unknown>[] = [
  {
    ...conversationBase,
    id: "session-opportunity-1",
    title: "Staff Product Engineer conversation",
    task_id: null,
    opportunity_id: "opportunity-1",
    last_sequence: 3,
  },
  {
    ...conversationBase,
    id: "session-stream",
    title: "Streamed work conversation",
    task_id: "task-stream",
    opportunity_id: null,
    last_sequence: 1,
  },
  {
    ...conversationBase,
    id: "session-question",
    title: "Saved agent questions",
    task_id: "task-question",
    opportunity_id: null,
    last_sequence: 1,
  },
];
const standaloneRuns: Record<string, unknown>[] = [
  {
    ...conversationBase,
    id: "run-1",
    profile: "research",
    title: "Northstar research",
    prompt: "Summarize this synthetic company.",
    state: "completed",
    session_id: null,
    output:
      "## Company brief\n\n**Northstar** builds developer tools.\n\n- Ask about the platform roadmap.\n- Review team responsibilities.",
    error_code: null,
  },
];
const sessionMessages: Record<string, Record<string, unknown>[]> = {
  "session-question": [
    {
      ...conversationBase,
      id: "message-question-user",
      session_id: "session-question",
      run_id: "run-question",
      sequence: 1,
      author: "user",
      profile: "lead",
      content: "Prepare the interview plan and ask when evidence is missing.",
    },
  ],
  "session-stream": [
    {
      ...conversationBase,
      id: "message-stream-user",
      session_id: "session-stream",
      run_id: "run-stream-a",
      sequence: 1,
      author: "user",
      profile: "application",
      content: "Prepare grounded application guidance.",
    },
  ],
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
  "session-question": [
    {
      ...conversationBase,
      id: "run-question",
      title: "Interview plan with saved questions",
      prompt: "Prepare the interview plan and ask when evidence is missing.",
      profile: "lead",
      state: answeredQuestionIds.has("question-research")
        ? "queued"
        : "waiting_for_user",
      output: null,
      error_code: null,
      completed_at: null,
      session_id: "session-question",
      input_sequence: 1,
      consumed_sequence: 1,
    },
  ],
  "session-stream": [
    {
      ...conversationBase,
      id: "run-stream-a",
      title: "Grounded application guidance",
      prompt: "Prepare grounded application guidance.",
      profile: "application",
      state: "running",
      output: null,
      error_code: null,
      completed_at: null,
      session_id: "session-stream",
      input_sequence: 1,
      consumed_sequence: 1,
    },
    {
      ...conversationBase,
      id: "run-stream-b",
      title: "Independent background check",
      prompt: "Check the saved evidence.",
      profile: "research",
      state: "running",
      output: null,
      error_code: null,
      completed_at: null,
      session_id: "session-stream",
      input_sequence: 1,
      consumed_sequence: 1,
    },
  ],
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
const runQuestions: Record<string, Record<string, unknown>[]> = {
  "run-question": [
    {
      ...conversationBase,
      id: "question-research",
      run_id: "run-question",
      session_id: "session-question",
      interrupt_id: "interrupt-research",
      branch_id: "research-branch",
      role: "research",
      tool_call_id: "tool-question-research",
      prompt: "Which product area should the research branch prioritize?",
      state: answeredQuestionIds.has("question-research") ? "answered" : "open",
      answer: answeredQuestionIds.has("question-research")
        ? "Prioritize the developer platform roadmap."
        : null,
      answered_at: answeredQuestionIds.has("question-research")
        ? "2026-09-21T10:10:00Z"
        : null,
    },
    {
      ...conversationBase,
      id: "question-application",
      run_id: "run-question",
      session_id: "session-question",
      interrupt_id: "interrupt-application",
      branch_id: "application-branch",
      role: "application",
      tool_call_id: "tool-question-application",
      prompt: "Which accomplishment should the application branch emphasize?",
      state: "open",
      answer: null,
      answered_at: null,
    },
  ],
};
const localClients: {
  id: string;
  name: string;
  created_at: string;
  expires_at: string;
  revoked_at: string | null;
}[] = [];
const questionAnswerKeys: Record<string, string[]> = {};
const failedQuestionAnswers = new Set<string>();
let failedQuestionRefreshes = 0;
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
  "artifact-generated-brief": [
    {
      id: "generated-brief-v1",
      artifact_id: "artifact-generated-brief",
      version: 1,
      payload: {
        text: "# Platform research\n\nA synthetic research memo to review.\n\n## Next steps\n\nDiscuss ownership and accessibility with the team.",
      },
      content_sha256: "synthetic-generated-sha",
      input_version_ids: [],
      created_at: base.created_at,
    },
  ],
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
      payload: null,
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
const versionReads: string[] = [];
const artifactReviews: Record<string, Record<string, unknown>[]> = {};
if (new URLSearchParams(location.search).get("binary-generated") === "1") {
  artifactVersions["artifact-generated-brief"][0].payload = null;
}
if (new URLSearchParams(location.search).get("structured-generated") === "1") {
  artifactVersions["artifact-generated-brief"][0].payload = {
    fields: [{ label: "Preferred start", answer: "After the interview" }],
    prior_applications: 0,
    submitted: false,
    source: "https://example.test/" + "source".repeat(60),
  };
}
if (new URLSearchParams(location.search).get("long-history") === "1") {
  artifactVersions["artifact-1"] = Array.from({ length: 30 }, (_, index) => ({
    id: `long-version-${30 - index}`,
    artifact_id: "artifact-1",
    version: 30 - index,
    payload: { text: `History checkpoint ${30 - index}` },
    content_sha256: `synthetic-history-${30 - index}`,
    created_at: "2026-09-22T12:00:00Z",
    input_version_ids: [],
  }));
}
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
const pdfExports: Record<string, Record<string, unknown>> = {};
const pdfExportPolls: Record<string, number> = {};
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
if (new URLSearchParams(location.search).has("many-facts")) {
  const sample = profileFacts[0];
  for (let index = 2; index <= 105; index += 1) {
    profileFacts.push({
      ...sample,
      id: `fact-skill-${index}`,
      field: "skill",
      active: null,
      current: {
        ...(sample.current as Record<string, unknown>),
        id: `fact-skill-${index}-v1`,
        version: 1,
        value: `Synthetic imported skill ${index}`,
      },
    });
  }
}
const priorMemoryRevision = {
  id: "memory-revision-approved",
  version: 1,
  title: "Synthetic communication preference",
  content: "Use short synthetic status updates.",
  kind: "preference",
  scope_type: "global",
  scope_id: null,
  valid_until: null,
  source: "legacy_human",
  source_run_id: null,
  source_artifact_id: null,
  reason: "Preserved explicit legacy human-authored memory.",
  review_state: "approved",
  created_at: "2026-09-21T10:00:00Z",
};
const proposedMemoryRevision = {
  ...priorMemoryRevision,
  id: "memory-revision-proposed",
  version: 2,
  content: "Use concise synthetic summaries with one clear next step.",
  source: "agent",
  source_run_id: "run-memory-synthetic",
  reason: "This preference recurred during the synthetic task.",
  review_state: "proposed",
  created_at: "2026-09-21T11:00:00Z",
};
const memoryItems: Record<string, unknown>[] = [
  {
    id: "memory-synthetic",
    row_version: 2,
    title: proposedMemoryRevision.title,
    content: proposedMemoryRevision.content,
    kind: proposedMemoryRevision.kind,
    source: proposedMemoryRevision.source,
    updated_at: "2026-09-21T11:00:00Z",
    current: proposedMemoryRevision,
    active: priorMemoryRevision,
  },
];
let latestMemoryReview: Record<string, unknown> | undefined;
const opportunityResearch: Record<string, Record<string, unknown>[]> = {};
const leadRequestKeys: Record<string, string[]> = {};
const documentRequestKeys: Record<string, string[]> = {};
const failedLeadRequests: Record<string, number> = {};
const terminalDetailsAvailable = new Set<string>();
let pendingTerminalRunId: string | undefined;
let retryImportFailures = 0;
let staleReview = true;
const browserSnapshots: Record<string, unknown>[] = [
  {
    id: "snapshot-application-1",
    protocol_version: 2,
    title: "Northstar application",
    origin: "https://jobs.example.test",
    page_url: "https://jobs.example.test/apply",
    created_at: "2026-09-21T10:20:00Z",
    fields: [
      {
        id: "f0",
        label: "Full name",
        type: "text",
        required: true,
        options: [],
        option_labels: {},
        value_state: "empty",
        autocomplete: "name",
        accept: "",
        unsupported_reason: null,
      },
      {
        id: "f1",
        label: "Email",
        type: "email",
        required: true,
        options: [],
        option_labels: {},
        value_state: "present",
        autocomplete: "email",
        accept: "",
        unsupported_reason: null,
      },
      {
        id: "f2",
        label: "Why are you interested in this role?",
        type: "textarea",
        required: true,
        options: [],
        option_labels: {},
        value_state: "empty",
        autocomplete: "",
        accept: "",
        unsupported_reason: null,
      },
      {
        id: "f3",
        label: "Resume",
        type: "file",
        required: true,
        options: [],
        option_labels: {},
        value_state: "empty",
        autocomplete: "",
        accept: ".pdf,application/pdf",
        unsupported_reason: null,
      },
      {
        id: "f5",
        label: "Cover letter",
        type: "file",
        value_state: "empty",
        accept: "application/pdf",
        required: false,
      },
      {
        id: "f4",
        label: "Custom eligibility widget",
        type: "unsupported",
        required: true,
        options: [],
        option_labels: {},
        value_state: "empty",
        autocomplete: "",
        accept: "",
        unsupported_reason: "Complete this custom control in the browser.",
      },
    ],
  },
  {
    id: "snapshot-application-2",
    protocol_version: 2,
    title: "Second application page",
    origin: "https://jobs.example.test",
    page_url: "https://jobs.example.test/apply/second",
    created_at: "2026-09-21T10:21:00Z",
    fields: [
      {
        id: "f0",
        label: "Additional note",
        type: "textarea",
        required: false,
        options: [],
        option_labels: {},
        value_state: "empty",
        autocomplete: "",
        accept: "",
        unsupported_reason: null,
      },
    ],
  },
];
const browserResumeOptions = {
  default_version_id: "resume-version-1",
  items: [
    {
      version_id: "resume-version-1",
      artifact_id: "artifact-resume",
      title: "Synthetic resume",
      filename: "synthetic-resume.pdf",
      media_type: "application/pdf",
      size_bytes: 24576,
      sha256: "a".repeat(64),
      version: 1,
    },
    {
      version_id: "resume-version-specialized",
      artifact_id: "artifact-resume-specialized",
      title: "Synthetic product resume",
      filename: "synthetic-product-resume.pdf",
      media_type: "application/pdf",
      size_bytes: 32768,
      sha256: "b".repeat(64),
      version: 2,
    },
  ],
};
const browserCoverLetterOptions = {
  default_version_id: null,
  items: [
    {
      version_id: "letter-version-1",
      artifact_id: "artifact-letter-1",
      title: "Northstar cover letter",
      filename: "northstar-letter.pdf",
      media_type: "application/pdf",
      size_bytes: 8192,
      sha256: "c".repeat(64),
      version: 1,
    },
  ],
};
let browserPreparation: Record<string, unknown> | undefined;
let browserPreparationVersion = 0;
let generationPolls = 0;
const browserCommands: Record<string, unknown>[] = [];
const applicationGenerationRun: Record<string, unknown> = {
  ...conversationBase,
  id: "run-application-generation",
  profile: "application",
  title: "Draft application answers",
  prompt: "Draft grounded answers for the shared form.",
  state: "completed",
  output: null,
  error: null,
};
sessionRuns["session-application"] = [applicationGenerationRun];

function makeBrowserPreparation(body: Record<string, unknown>) {
  browserPreparationVersion += 1;
  const resume = browserResumeOptions.items.find(
    (item) => item.version_id === body.resume_version_id,
  );
  return {
    id: "preparation-application-1",
    snapshot_id: "snapshot-application-1",
    task_id: "task-application-1",
    opportunity_id: body.opportunity_id ?? null,
    artifact_id: "artifact-application-package",
    version_id: `preparation-version-${browserPreparationVersion}`,
    version: browserPreparationVersion,
    resume: resume ?? null,
    cover_letter:
      browserCoverLetterOptions.items.find(
        (item) => item.version_id === body.cover_letter_version_id,
      ) ?? null,
    cover_letter_upload_fields: [],
    replace_fields: [],
    upload_fields: [],
    fields: [
      {
        field_id: "f0",
        status: "suggested",
        value: "Synthetic Candidate",
        reason: "Matched an approved full-name fact.",
        evidence: [
          {
            fact_id: "fact-name",
            revision_id: "revision-name-approved",
            value: "Synthetic Candidate",
            context: null,
            source_version_id: "resume-extraction-version-1",
          },
        ],
      },
      {
        field_id: "f1",
        status: "preserved",
        value: null,
        reason: "The browser reported an existing value.",
        evidence: [],
      },
      {
        field_id: "f2",
        status: "needs_input",
        value: null,
        reason: "No approved answer matches this question and opportunity.",
        evidence: [],
      },
      {
        field_id: "f4",
        status: "unsupported",
        value: null,
        reason: "Complete this custom control in the browser.",
        evidence: [],
      },
    ],
    created_at: "2026-09-21T10:22:00Z",
  };
}

function page(items: Record<string, unknown>[], limit = 100) {
  return { items, total: items.length, limit, offset: 0 };
}

const streamAttempts: Record<string, number> = {};
const streamAfterSequences: Record<string, number[]> = {};
const encoder = new TextEncoder();

function streamEvent(
  runId: string,
  sequence: number,
  type: string,
  data: Record<string, unknown>,
) {
  return `event: agent_event\nid: ${sequence}\ndata: ${JSON.stringify({
    sequence,
    run_id: runId,
    type,
    role: type.startsWith("tool-") ? "tool" : "assistant",
    data,
    created_at: "2026-09-21T10:30:00Z",
  })}\n\n`;
}

function eventResponse(runId: string, afterSequence: number) {
  streamAttempts[runId] = (streamAttempts[runId] ?? 0) + 1;
  (streamAfterSequences[runId] ??= []).push(afterSequence);
  const attempt = streamAttempts[runId];
  let cancelled = false;
  const body = new ReadableStream<Uint8Array>({
    async start(controller) {
      const send = (value: string) => {
        if (!cancelled) controller.enqueue(encoder.encode(value));
      };
      if (runId !== "run-stream-a" && runId !== "run-stream-b") {
        // Other scenarios control lifecycle through their explicit fixture mutations.
        // Keep their stream idle; never fabricate a completion for an active run.
        send(": connected\n\n");
        return;
      }
      if (
        runId === "run-stream-a" &&
        new URLSearchParams(location.search).has("smooth_stream")
      ) {
        send(streamEvent(runId, 1, "run-status", { state: "queued" }));
        await new Promise((resolve) => setTimeout(resolve, 20));
        send(streamEvent(runId, 2, "run-status", { state: "running" }));
        for (let index = 0; index < 70; index++) {
          if (cancelled) return;
          send(
            streamEvent(runId, index + 3, "text-delta", {
              message_id: "smooth-reply",
              delta:
                index === 0
                  ? "## Steady reply\n\n"
                  : `Paragraph ${index}: useful **grounded** context remains readable while the response continues.\n\n`,
            }),
          );
          await new Promise((resolve) => setTimeout(resolve, 50));
        }
        send(streamEvent(runId, 73, "run-status", { state: "completed" }));
        const run = sessionRuns["session-stream"].find(
          (item) => item.id === runId,
        );
        if (run) run.state = "completed";
        if (!cancelled) controller.close();
        return;
      }
      if (runId === "run-stream-a" && attempt === 1) {
        const first = streamEvent(runId, 1, "text-delta", {
          message_id: "stream-message-a",
          delta: "## Streaming answer\n\n**Grounded",
        });
        send(first.slice(0, 37));
        await new Promise((resolve) => setTimeout(resolve, 20));
        send(first.slice(37));
        send(
          streamEvent(runId, 2, "tool-input-available", {
            tool_call_id: "tool-a",
            tool_name: "document_read",
            input: { version_id: "resume-version-1" },
          }),
        );
        await new Promise((resolve) => setTimeout(resolve, 80));
        if (!cancelled) controller.close();
        return;
      }
      const events =
        runId === "run-stream-a"
          ? [
              streamEvent(runId, 2, "tool-input-available", {
                tool_call_id: "tool-a",
                tool_name: "duplicate_should_not_render",
                input: { duplicate: true },
              }),
              streamEvent(runId, 3, "text-delta", {
                message_id: "stream-message-a",
                delta: " evidence** is ready.",
              }),
              streamEvent(runId, 4, "tool-output-available", {
                tool_call_id: "tool-a",
                output: { cited_versions: 1 },
              }),
              streamEvent(runId, 5, "usage", {
                input_tokens: 120,
                output_tokens: 30,
                total_tokens: 150,
              }),
              streamEvent(runId, 6, "run-status", { state: "completed" }),
            ]
          : [
              streamEvent(runId, 1, "text-delta", {
                message_id: "stream-message-b",
                delta: "Independent **second** stream.",
              }),
              streamEvent(runId, 2, "run-status", { state: "completed" }),
            ];
      for (const event of events) {
        send(event);
        await new Promise((resolve) => setTimeout(resolve, 15));
      }
      const run = (sessionRuns["session-stream"] ?? []).find(
        (item) => item.id === runId,
      );
      if (run) {
        run.state = "completed";
        run.completed_at = "2026-09-21T10:31:00Z";
      }
      if (!cancelled) controller.close();
    },
    cancel() {
      cancelled = true;
    },
  });
  return new Response(body, {
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}

const fixtureFetch: typeof fetch = async (input, init) => {
  const url = new URL(String(input), location.origin);
  if (!url.pathname.startsWith("/api/backend/"))
    throw new Error("Only fixture API requests are supported");
  const route = url.pathname.replace("/api/backend/", "");
  const method = init?.method ?? "GET";
  const idempotencyKey =
    new Headers(init?.headers).get("Idempotency-Key") ?? "";
  if (route === "activity") return Response.json(page([]));
  if (route === "test/briefing-requests")
    return Response.json(briefingRequests);
  briefingRequests.push({
    route,
    method,
    key: idempotencyKey,
    ...(route === "tasks" && method === "POST"
      ? { body: JSON.parse(String(init?.body)) }
      : {}),
  });
  const spaceResponse = await spacesFixture(url, init, rows);
  if (spaceResponse) return spaceResponse;
  const documentDecisionResponse = await documentDecisionsFixture(
    url,
    init,
    rows,
    documentImports,
  );
  if (documentDecisionResponse) return documentDecisionResponse;
  const application = await applicationsFixture(
    url,
    init,
    rows,
    artifactVersions,
  );
  if (application) return application;
  const library = await libraryFixture(url, init, rows, documentImports);
  if (library) return library;
  const work = await recordWorkFixture(url, init, {
    rows,
    sessions,
    sessionMessages,
    sessionRuns,
    artifactVersions,
  });
  if (work) return work;
  const writing = await writingFixture(url, init);
  const career = await careerFixture(url, init);
  if (career) return career;
  const discovery = await contactDiscoveryFixture(url, init);
  if (discovery) return discovery;
  const followUp = await followUpFixture(url, init);
  if (followUp) return followUp;
  if (writing) return writing;
  const connection = await connectionsFixture(url, init);
  if (connection) return connection;
  const workflow = await workflowFixture(url, init);
  if (workflow) return workflow;
  const trackLeadRequest = (name: string) => {
    (leadRequestKeys[name] ??= []).push(idempotencyKey);
  };
  const shouldFailTwice = (name: string) => {
    failedLeadRequests[name] = (failedLeadRequests[name] ?? 0) + 1;
    return failedLeadRequests[name] <= 2;
  };
  if (route === "test/stream-state")
    return Response.json({
      attempts: streamAttempts,
      after: streamAfterSequences,
    });
  if (route === "test/question-answer-state")
    return Response.json({ keys: questionAnswerKeys, questions: runQuestions });
  if (route === "test/fail-question-refresh" && method === "POST") {
    failedQuestionRefreshes = 2;
    return Response.json({ ok: true });
  }
  if (route === "test/wait-for-next-question" && method === "POST") {
    const run = Object.values(sessionRuns)
      .flat()
      .find((item) => item.id === "run-question");
    if (run) {
      run.state = "waiting_for_user";
      run.row_version = Number(run.row_version) + 1;
    }
    return Response.json(run ?? null);
  }
  const eventMatch = route.match(/^agent-runs\/([^/]+)\/events$/);
  if (eventMatch)
    return eventResponse(
      eventMatch[1],
      Number(url.searchParams.get("after_sequence") ?? 0),
    );
  if (route === "test/lead-request-keys") return Response.json(leadRequestKeys);
  if (route === "test/document-request-keys")
    return Response.json(documentRequestKeys);
  if (route === "test/latest-browser-command")
    return Response.json(browserCommands.at(-1) ?? null);
  if (route === "test/latest-browser-preparation")
    return Response.json(browserPreparation ?? null);
  if (route === "test/latest-memory-review")
    return Response.json(latestMemoryReview ?? null);
  if (route === "browser/devices" && method === "GET")
    return Response.json([
      {
        id: "browser-device-1",
        name: "Synthetic Chrome",
        paired_at: "2026-09-21T10:00:00Z",
        last_seen_at: "2026-09-21T10:20:00Z",
        revoked_at: null,
      },
    ]);
  if (route === "browser/snapshots" && method === "GET")
    return Response.json(browserSnapshots);
  const savedSnapshot = route.match(
    /^browser\/snapshots\/([^/]+)(\/preparation)?$/,
  );
  if (savedSnapshot && method === "GET") {
    const snapshot = browserSnapshots.find(
      (item) => item.id === savedSnapshot[1],
    );
    if (!snapshot)
      return Response.json(
        { detail: "Form snapshot not found" },
        { status: 404 },
      );
    return Response.json(
      savedSnapshot[2] ? (browserPreparation ?? null) : snapshot,
    );
  }
  if (route === "browser/cover-letters" && method === "GET")
    return Response.json(browserCoverLetterOptions);
  if (route === "browser/resumes" && method === "GET")
    return Response.json(browserResumeOptions);
  if (route === "browser/commands" && method === "GET")
    return Response.json(browserCommands);
  if (route === "browser/commands" && method === "POST") {
    const body = JSON.parse(String(init?.body));
    const command = {
      ...body,
      id: `browser-command-${browserCommands.length + 1}`,
      state: "pending",
      created_at: "2026-09-21T10:25:00Z",
      idempotency_key: idempotencyKey,
    };
    browserCommands.push(command);
    return Response.json(command, { status: 201 });
  }
  const createPreparation = route.match(
    /^browser\/snapshots\/([^/]+)\/preparations$/,
  );
  if (createPreparation && method === "POST") {
    const body = JSON.parse(String(init?.body));
    browserPreparation = makeBrowserPreparation(body);
    return Response.json(browserPreparation, { status: 201 });
  }
  const preparationRoute = route.match(
    /^browser\/preparations\/([^/]+)(?:\/(revisions|generate))?$/,
  );
  if (preparationRoute && browserPreparation) {
    const action = preparationRoute[2];
    if (!action && method === "GET") {
      generationPolls += 1;
      if (
        applicationGenerationRun.state !== "completed" &&
        generationPolls >= 2
      ) {
        browserPreparationVersion += 1;
        browserPreparation.version = browserPreparationVersion;
        browserPreparation.version_id = `preparation-version-${browserPreparationVersion}`;
        const fields = browserPreparation.fields as Record<string, unknown>[];
        const narrative = fields.find((item) => item.field_id === "f2");
        if (narrative) {
          narrative.status = "suggested";
          narrative.value = "Generated grounded narrative from approved facts.";
          narrative.reason = "Drafted by the application profile for review.";
        }
        applicationGenerationRun.state = "completed";
      }
      return Response.json(browserPreparation);
    }
    if (action === "generate" && method === "POST") {
      generationPolls = 0;
      applicationGenerationRun.state = "queued";
      return Response.json({
        conversation_id: "session-application",
        run_id: applicationGenerationRun.id,
      });
    }
    if (action === "revisions" && method === "POST") {
      const body = JSON.parse(String(init?.body));
      browserPreparationVersion += 1;
      browserPreparation.version = browserPreparationVersion;
      browserPreparation.version_id = `preparation-version-${browserPreparationVersion}`;
      browserPreparation.resume =
        browserResumeOptions.items.find(
          (item) => item.version_id === body.resume_version_id,
        ) ?? null;
      browserPreparation.replace_fields = body.replace_fields;
      browserPreparation.upload_fields = body.upload_fields;
      browserPreparation.cover_letter_upload_fields =
        body.cover_letter_upload_fields ?? [];
      browserPreparation.cover_letter =
        browserCoverLetterOptions.items.find(
          (item) => item.version_id === body.cover_letter_version_id,
        ) ?? null;
      const currentFields = browserPreparation.fields as Record<
        string,
        unknown
      >[];
      for (const [fieldId, value] of Object.entries(body.fields)) {
        let field = currentFields.find((item) => item.field_id === fieldId);
        if (!field) {
          field = { field_id: fieldId, evidence: [] };
          currentFields.push(field);
        }
        field.status = value ? "suggested" : "needs_input";
        field.value = value || null;
        field.reason = value
          ? "Saved in the reviewed user revision."
          : "Cleared in the reviewed user revision.";
      }
      return Response.json(browserPreparation);
    }
  }
  if (route === "test/complete-active-run" && method === "POST") {
    const run = Object.values(sessionRuns)
      .flat()
      .find(
        (item) =>
          ["queued", "running"].includes(String(item.state)) &&
          !String(item.id).startsWith("run-stream-"),
      );
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
      {
        id: "document-type-unclassified",
        name: "Unclassified",
        slug: "unclassified",
      },
      { id: "document-type-notes", name: "Notes", slug: "notes" },
      { id: "document-type-resume", name: "Resume", slug: "resume" },
      {
        id: "document-type-brief",
        name: "Interview brief",
        slug: "interview_brief",
      },
    ]);
  const createPdfMatch = route.match(
    /^artifacts\/([^/]+)\/versions\/([^/]+)\/exports$/,
  );
  if (createPdfMatch && method === "POST") {
    const [artifactId, versionId] = createPdfMatch.slice(1);
    const source = artifactVersions[artifactId]?.find(
      (candidate) => candidate.id === versionId,
    );
    if (!source)
      return Response.json({ detail: "Version not found" }, { status: 404 });
    const id = `pdf-export-${versionId}`;
    const existing = pdfExports[id];
    if (existing) return Response.json(existing, { status: 202 });
    const item: Record<string, unknown> = {
      id,
      state: "queued",
      source: {
        artifact_id: artifactId,
        artifact_title: String(
          rows.artifacts.find((candidate) => candidate.id === artifactId)
            ?.title,
        ),
        version_id: versionId,
        version: Number(source.version),
      },
      output: null,
      renderer_revision: `sha256:${"a".repeat(64)}`,
      attempt_count: 0,
      max_attempts: 2,
      error_code: null,
      cleanup_pending: false,
      row_version: 1,
      created_at: "2026-09-21T10:20:00Z",
      updated_at: "2026-09-21T10:20:00Z",
      completed_at: null,
    };
    pdfExports[id] = item;
    pdfExportPolls[id] = 0;
    return Response.json(item, { status: 202 });
  }
  const pdfExportMatch = route.match(
    /^pdf-exports\/([^/]+)(?:\/(cancel|retry))?$/,
  );
  if (pdfExportMatch) {
    const item = pdfExports[pdfExportMatch[1]];
    if (!item)
      return Response.json({ detail: "PDF export not found" }, { status: 404 });
    if (method === "POST") {
      item.state = pdfExportMatch[2] === "retry" ? "queued" : "cancelled";
      item.row_version = Number(item.row_version) + 1;
      item.error_code = null;
      pdfExportPolls[pdfExportMatch[1]] = 0;
      return Response.json(item);
    }
    pdfExportPolls[pdfExportMatch[1]] += 1;
    if (pdfExportPolls[pdfExportMatch[1]] >= 2 && item.state === "queued") {
      const source = item.source as Record<string, unknown>;
      item.state = "completed";
      item.output = {
        artifact_id: `pdf-output-${source.version_id}`,
        artifact_title: `${source.artifact_title} — PDF`,
        version_id: `pdf-output-version-${source.version_id}`,
        version: 1,
      };
      item.row_version = Number(item.row_version) + 1;
      item.completed_at = "2026-09-21T10:20:05Z";
    }
    return Response.json(item);
  }
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
  if (downloadMatch) {
    const pdf = downloadMatch[1].startsWith("pdf-output-");
    return new Response(`Synthetic bytes for ${downloadMatch[2]}`, {
      headers: {
        "Content-Type": pdf ? "application/pdf" : "application/octet-stream",
        "Content-Disposition": `attachment; filename="synthetic-document.${pdf ? "pdf" : "txt"}"`,
        "X-Content-Type-Options": "nosniff",
      },
    });
  }
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
  if (route === "memories" && method === "GET")
    return Response.json(page(memoryItems, 30));
  const memoryReviewMatch = route.match(/^memories\/([^/]+)\/reviews$/);
  if (memoryReviewMatch && method === "POST") {
    const memory = memoryItems.find((item) => item.id === memoryReviewMatch[1]);
    if (!memory)
      return Response.json({ detail: "Memory not found" }, { status: 404 });
    const body = JSON.parse(String(init?.body)) as {
      revision_id: string;
      decision: "approved" | "rejected" | "revoked";
    };
    latestMemoryReview = body;
    const current = memory.current as Record<string, unknown>;
    const active = memory.active as Record<string, unknown> | null;
    const revision = current.id === body.revision_id ? current : active;
    if (!revision)
      return Response.json({ detail: "Revision not found" }, { status: 404 });
    revision.review_state = body.decision;
    memory.active =
      body.decision === "approved"
        ? revision
        : body.decision === "revoked"
          ? null
          : memory.active;
    memory.row_version = Number(memory.row_version) + 1;
    memory.source = current.source;
    return Response.json(memory);
  }
  if (route === "profile/facts" && method === "GET") {
    const limit = Number(url.searchParams.get("limit") ?? 20);
    const offset = Number(url.searchParams.get("offset") ?? 0);
    return Response.json({
      items: profileFacts.slice(offset, offset + limit),
      total: profileFacts.length,
      limit,
      offset,
    });
  }
  if (route === "contacts/contact-1/observations")
    return Response.json({
      items: [
        {
          id: "observation-1",
          contact_id: "contact-1",
          source_artifact_id: "artifact-1",
          source_version_id: "version-1",
          source_row: 1,
          mapping_version: "linkedin-contacts-profile-v2",
          first_name: "Alex",
          last_name: "Morgan",
          email: "alex@example.com",
          linkedin_url: "https://www.linkedin.com/in/synthetic-alex",
          company: "Northstar",
          position: "Engineering lead",
          connected_on: "01 Jan 2025",
          imported_at: "2026-09-22T10:00:00Z",
        },
      ],
      total: 1,
      limit: 10,
      offset: 0,
    });
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
  const historyMatch = route.match(/^artifacts\/([^/]+)\/version-history$/);
  if (route === "test/version-reads") return Response.json(versionReads);
  if (historyMatch) {
    versionReads.push(`${route}${url.search}`);
    const versions = artifactVersions[historyMatch[1]] ?? [];
    const before = Number(url.searchParams.get("before") ?? Infinity);
    const limit = Number(url.searchParams.get("limit") ?? 20);
    const matching = versions.filter(
      (version) => Number(version.version) < before,
    );
    const items = matching.slice(0, limit).map((version) => ({
      id: version.id,
      artifact_id: version.artifact_id,
      version: version.version,
      content_sha256: version.content_sha256,
      created_at: version.created_at,
      is_text:
        typeof (version.payload as Record<string, unknown> | null)?.text ===
        "string",
      has_file: version.payload === null,
    }));
    return Response.json({
      items,
      total: versions.length,
      next_before: matching.length > limit ? items.at(-1)?.version : null,
    });
  }
  const versionBodyMatch = route.match(
    /^artifacts\/([^/]+)\/versions\/([^/]+)$/,
  );
  if (versionBodyMatch && method === "GET") {
    versionReads.push(route);
    const version = artifactVersions[versionBodyMatch[1]]?.find(
      (version) => version.id === versionBodyMatch[2],
    );
    return version
      ? Response.json(version)
      : Response.json({ detail: "Version not found" }, { status: 404 });
  }
  const artifactVersionsMatch = route.match(/^artifacts\/([^/]+)\/versions$/);
  if (artifactVersionsMatch && method === "GET")
    return Response.json(artifactVersions[artifactVersionsMatch[1]] ?? []);
  if (artifactVersionsMatch && method === "POST") {
    const body = JSON.parse(String(init?.body)) as {
      based_on_version_id: string;
      text: string;
    };
    const versions = artifactVersions[artifactVersionsMatch[1]] ?? [];
    const baseVersion = versions.find(
      (candidate) => candidate.id === body.based_on_version_id,
    );
    if (!baseVersion)
      return Response.json(
        { detail: "Base version not found" },
        { status: 422 },
      );
    const payload = {
      ...((baseVersion.payload as Record<string, unknown>) ?? {}),
      text: body.text,
    };
    const created = {
      ...baseVersion,
      id: `${artifactVersionsMatch[1]}-version-${Math.max(...versions.map((version) => Number(version.version))) + 1}`,
      version:
        Math.max(...versions.map((version) => Number(version.version))) + 1,
      payload,
      content_sha256: `${artifactVersionsMatch[1]}-edited-sha`,
      created_at: "2026-09-21T10:25:00Z",
    };
    versions.unshift(created);
    artifactVersions[artifactVersionsMatch[1]] = versions;
    return Response.json(created, { status: 201 });
  }
  const artifactReviewMatch = route.match(/^versions\/([^/]+)\/reviews$/);
  if (artifactReviewMatch) {
    const versionId = artifactReviewMatch[1];
    if (method === "POST") {
      const body = JSON.parse(String(init?.body));
      const review = {
        ...body,
        id: crypto.randomUUID(),
        created_at: base.created_at,
      };
      (artifactReviews[versionId] ??= []).unshift(review);
      const artifact = rows.artifacts.find(
        (item) => artifactVersions[String(item.id)]?.[0]?.id === versionId,
      );
      if (artifact) artifact.review_status = body.decision;
      return Response.json(review, { status: 201 });
    }
    return Response.json(artifactReviews[versionId] ?? []);
  }
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
        id: `session-${body.task_id ?? body.opportunity_id ?? crypto.randomUUID()}`,
        title: body.title ?? "Work conversation",
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
    const standalone = url.searchParams.get("standalone") === "true";
    const filtered = sessions.filter(
      (item) =>
        (!taskId || item.task_id === taskId) &&
        (!opportunityId || item.opportunity_id === opportunityId) &&
        (!standalone || (!item.task_id && !item.opportunity_id)),
    );
    const limit = Number(url.searchParams.get("limit") ?? 30);
    const offset = Number(url.searchParams.get("offset") ?? 0);
    return Response.json({
      items: filtered.slice(offset, offset + limit),
      total: filtered.length,
      limit,
      offset,
    });
  }
  const sessionDetail = route.match(/^agent-sessions\/([^/]+)$/);
  if (sessionDetail && method === "GET") {
    const item = sessions.find((session) => session.id === sessionDetail[1]);
    return item
      ? Response.json(item)
      : Response.json({ detail: "Session not found" }, { status: 404 });
  }
  if (route === "mcp-clients") {
    if (method === "POST") {
      const body = JSON.parse(String(init?.body));
      const created = {
        id: crypto.randomUUID(),
        name: body.name,
        created_at: base.created_at,
        expires_at: "2099-01-01T00:00:00Z",
        revoked_at: null,
      };
      localClients.unshift(created);
      return Response.json({ ...created, token: "synthetic-preview-token" });
    }
    return Response.json(localClients);
  }
  const revokeClient = route.match(/^mcp-clients\/([^/]+)\/revoke$/);
  if (revokeClient && method === "POST") {
    const record = localClients.find((item) => item.id === revokeClient[1])!;
    record.revoked_at = base.updated_at;
    return Response.json(record);
  }
  const messageMatch = route.match(/^agent-sessions\/([^/]+)\/messages$/);
  if (messageMatch) {
    const sessionId = messageMatch[1];
    const items = sessionMessages[sessionId] ?? [];
    if (
      method === "GET" &&
      new URLSearchParams(location.search).has("long_chat") &&
      items.length >= 2
    ) {
      items[0].content =
        "Start of pasted source.\n\n" +
        "Synthetic conversation context and a long source URL https://example.test/".repeat(
          100,
        );
      items[1].content =
        "## Saved response\n\n" +
        Array.from(
          { length: 45 },
          (_, index) =>
            `Paragraph ${index + 1}: Synthetic follow-up details remain readable.\n\n`,
        ).join("") +
        "Final line of the saved response.";
    }
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
  const questionAnswerMatch = route.match(
    /^agent-runs\/([^/]+)\/questions\/([^/]+)\/answer$/,
  );
  if (questionAnswerMatch && method === "POST") {
    const [, runId, questionId] = questionAnswerMatch;
    const question = (runQuestions[runId] ?? []).find(
      (item) => item.id === questionId,
    );
    if (!question)
      return Response.json({ detail: "Question not found" }, { status: 404 });
    (questionAnswerKeys[questionId] ??= []).push(idempotencyKey);
    const body = JSON.parse(String(init?.body)) as {
      answer: string;
      expected_version: number;
    };
    if (body.expected_version !== question.row_version)
      return Response.json(
        { detail: "Question changed. Refresh and try again." },
        { status: 409 },
      );
    if (
      questionId === "question-research" &&
      !failedQuestionAnswers.has(questionId)
    ) {
      failedQuestionAnswers.add(questionId);
      return Response.json(
        { detail: "The saved answer could not be accepted." },
        { status: 422 },
      );
    }
    question.state = "answered";
    question.answer = body.answer;
    question.answered_at = "2026-09-21T10:10:00Z";
    question.row_version = Number(question.row_version) + 1;
    const run = Object.values(sessionRuns)
      .flat()
      .find((item) => item.id === runId);
    if (run) {
      run.state = "queued";
      run.row_version = Number(run.row_version) + 1;
    }
    answeredQuestionIds.add(questionId);
    sessionStorage.setItem(
      "answered-question-ids",
      JSON.stringify([...answeredQuestionIds]),
    );
    return Response.json(question);
  }
  const runQuestionsMatch = route.match(/^agent-runs\/([^/]+)\/questions$/);
  if (runQuestionsMatch && method === "GET") {
    if (failedQuestionRefreshes > 0) {
      failedQuestionRefreshes -= 1;
      return Response.json(
        { detail: "Saved questions are temporarily unavailable." },
        { status: 503 },
      );
    }
    return Response.json(runQuestions[runQuestionsMatch[1]] ?? []);
  }
  if (route === "agent-runs") {
    if (method === "GET") return Response.json(page(standaloneRuns));
    const body = JSON.parse(String(init?.body));
    const previous = standaloneRuns.find(
      (run) => run.id === body.continue_run_id,
    );
    const sessionId = String(previous?.session_id ?? crypto.randomUUID());
    const messages = (sessionMessages[sessionId] ??= []);
    if (previous && !previous.session_id) {
      previous.session_id = sessionId;
      for (const [author, content] of [
        ["user", previous.prompt],
        ["assistant", previous.output],
      ]) {
        if (content)
          messages.push({
            ...conversationBase,
            id: crypto.randomUUID(),
            session_id: sessionId,
            run_id: previous.id,
            sequence: messages.length + 1,
            author,
            profile: previous.profile,
            content,
          });
      }
    }
    const run = {
      ...conversationBase,
      id: crypto.randomUUID(),
      session_id: sessionId,
      profile: body.profile,
      title: previous?.title ?? body.prompt,
      prompt: body.prompt,
      state: "completed",
      output: "Synthetic reply saved in this conversation.",
      error_code: null,
    };
    standaloneRuns.unshift(run);
    (sessionRuns[sessionId] ??= []).unshift(run);
    if (!sessions.some((item) => item.id === sessionId))
      sessions.push({
        ...conversationBase,
        id: sessionId,
        title: run.title,
        task_id: null,
        opportunity_id: null,
        last_sequence: messages.length + 2,
      });
    for (const [author, content] of [
      ["user", body.prompt],
      ["assistant", run.output],
    ]) {
      messages.push({
        ...conversationBase,
        id: crypto.randomUUID(),
        session_id: sessionId,
        run_id: run.id,
        sequence: messages.length + 1,
        author,
        profile: body.profile,
        content,
      });
    }
    return Response.json(run);
  }
  const standaloneRoute = route.match(/^agent-runs\/([^/]+)(?:\/(steps))?$/);
  const standaloneRun = standaloneRuns.find(
    (run) => run.id === standaloneRoute?.[1],
  );
  if (standaloneRun)
    return Response.json(standaloneRoute?.[2] ? [] : standaloneRun);
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
      const previous =
        resource === "tasks" ? capturedTasks.get(idempotencyKey) : undefined;
      const created = previous ?? {
        ...base,
        ...(resource === "tasks"
          ? { state: "open", priority: 0, due_date: null }
          : {}),
        ...JSON.parse(String(init.body)),
        id: crypto.randomUUID(),
      };
      if (!previous) rows[resource].push(created);
      if (resource === "tasks") {
        capturedTasks.set(idempotencyKey, created);
        if (
          new URLSearchParams(location.search).has("capture_retry") &&
          failedTaskCaptures++ < 2
        )
          return Response.json(
            { detail: "Connection lost after saving task." },
            { status: 503 },
          );
      }
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
  if (route === "dashboard/tasks") {
    const today = "2026-09-24";
    const view = url.searchParams.get("view") || "today";
    const offset = Number(url.searchParams.get("offset") || 0);
    const limit = Number(url.searchParams.get("limit") || 6);
    const active = tasks.filter((task) =>
      ["open", "in_progress"].includes(task.state),
    );
    const groups = {
      today: active.filter((task) => task.due_date && task.due_date <= today),
      upcoming: active.filter((task) => task.due_date && task.due_date > today),
      unscheduled: active.filter((task) => !task.due_date),
      waiting: tasks.filter((task) => task.state === "waiting"),
      snoozed: tasks.filter((task) => task.state === "snoozed"),
    };
    const matches = groups[view as keyof typeof groups] || [];
    payload = {
      items: matches.slice(offset, offset + limit).map((task) => ({
        ...task,
        due_status: !task.due_date
          ? "unscheduled"
          : task.due_date < today
            ? "overdue"
            : task.due_date === today
              ? "today"
              : "upcoming",
      })),
      total: matches.length,
      limit,
      offset,
      today,
      timezone: url.searchParams.get("timezone") || "UTC",
      counts: Object.fromEntries(
        Object.entries(groups).map(([key, rows]) => [key, rows.length]),
      ),
    };
  }
  if (route === "dashboard/work")
    payload = {
      items: [],
      total: 0,
      limit: 6,
      offset: Number(url.searchParams.get("offset") || 0),
    };
  if (route === "agents/models")
    payload = [
      {
        id: "gemini-synthetic-flash",
        name: "Synthetic Flash",
        selectable: true,
        description: "Available for agent chat",
      },
      {
        id: "gemini-synthetic-pro",
        name: "Synthetic Pro",
        selectable: true,
        description: "Available for agent chat",
      },
      {
        id: "synthetic-embedding",
        name: "Synthetic Embedding",
        selectable: false,
        description: "Not supported by this agent chat flow",
      },
    ];
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
        {["/opportunities", "/applications", "/jobs"].includes(path) && (
          <OpportunityNavigation />
        )}
        {new URLSearchParams(location.search).has("routeError") ? (
          <WorkspaceError />
        ) : path === "/" || path === "/briefing" ? (
          <Briefing />
        ) : path === "/spaces" ? (
          <Spaces />
        ) : path === "/overview" ? (
          <Overview />
        ) : path === "/activity" ? (
          <ActivityPage />
        ) : path === "/notes" ? (
          <Library key="notes" notes />
        ) : path === "/library" ? (
          <Library />
        ) : path === "/documents" ? (
          <Library key="vault" vault />
        ) : path === "/agent-settings" ? (
          <AgentSettings />
        ) : path === "/agents" ? (
          <Agents />
        ) : path === "/settings" ? (
          <Settings />
        ) : path === "/connections" ? (
          <ConnectedAccounts />
        ) : path === "/actions" ? (
          <ReviewedActions />
        ) : path === "/browser" ? (
          <BrowserPage />
        ) : path === "/applications" ? (
          <Applications />
        ) : path === "/memory" ? (
          <MemoryPage />
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
