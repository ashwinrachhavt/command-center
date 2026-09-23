import type {
  ApplicationPreparation,
  BrowserSnapshot,
  Schema,
} from "../../src/lib/api";
type Application = Schema["ApplicationRead"];
type Package = Schema["ApplicationPackageRead"];
type JobContext = Schema["ApplicationContextRead"];
type Material = Schema["MaterialRead"];
type Row = Record<string, unknown>;
const storage = "synthetic-applications-v1";
const stamp = "2026-09-22T10:00:00Z";
const snapshot: BrowserSnapshot = {
  id: "snapshot-tracker-old",
  protocol_version: 2,
  page_url: "https://jobs.example.test/roles/42",
  origin: "https://jobs.example.test",
  title: "Product Engineer · Northstar",
  created_at: stamp,
  fields: [
    {
      id: "f0",
      label: "Why this role?",
      type: "textarea",
      required: true,
      options: [],
      option_labels: {},
      value_state: "empty",
      autocomplete: "",
      accept: "",
      unsupported_reason: null,
      numeric_constraints: null,
    },
  ],
};
const resume = {
  version_id: "resume-version-1",
  filename: "synthetic-resume.pdf",
  media_type: "application/pdf",
  size_bytes: 24576,
  sha256: "a".repeat(64),
};
const preparation: ApplicationPreparation = {
  id: "preparation-tracker-old",
  snapshot_id: snapshot.id,
  task_id: "task-tracker-1",
  opportunity_id: null,
  artifact_id: "artifact-tracker-1",
  version_id: "version-tracker-1",
  version: 2,
  resume,
  replace_fields: [],
  upload_fields: [],
  created_at: stamp,
  fields: [
    {
      field_id: "f0",
      status: "suggested",
      value: "I build dependable tools that help small teams work well.",
      reason: "Saved by you for this application.",
      evidence: [],
    },
  ],
};
const packageItem: Package = {
  id: preparation.id,
  snapshot_id: snapshot.id,
  artifact_id: preparation.artifact_id,
  version_id: preparation.version_id,
  version: 2,
  created_at: stamp,
  page_title: snapshot.title,
  page_url: snapshot.page_url,
  resume,
  resume_artifact_id: "artifact-resume",
  latest_fill: {
    id: "fill-tracker-1",
    preparation_version_id: preparation.version_id,
    state: "applied",
    field_results: { f0: { status: "filled", detail: "" } },
    created_at: stamp,
    completed_at: stamp,
  },
};
function seed(): Application[] {
  return ["Product Engineer · Northstar", "Frontend Engineer · Harbor"].map(
    (title, index) => ({
      task: {
        id: `task-tracker-${index + 1}`,
        title: index
          ? "Prepare for the interview"
          : "Review application answers",
        state: "open",
        priority: 1,
        opportunity_id: null,
        rationale: "Review the role and prepare a thoughtful application.",
        due_date: "2026-09-25",
        due_at: null,
        completed_at: null,
        row_version: 1,
        created_at: stamp,
        updated_at: stamp,
      },
      status: index ? "interviewing" : "preparing",
      row_version: 1,
      submission_recorded_at: index ? stamp : null,
      preparation_id: preparation.id,
      snapshot_id: snapshot.id,
      page_url: snapshot.page_url,
      page_title: title,
      origin: snapshot.origin,
      preparation_count: 1,
      last_activity_at: stamp,
      job_context_artifact_id: null,
    }),
  );
}
type State = {
  applications: Application[];
  receipts: Record<string, Application>;
  requests: { key: string; body: Row }[];
  loseReply?: number;
  contexts: Record<string, JobContext>;
  contextReceipts: Record<string, JobContext | Schema["VersionRead"]>;
  materials?: Record<string, Material[]>;
  materialReceipts?: Record<string, Material>;
  materialRequests?: { key: string; body: Row }[];
  loseMaterialReply?: number;
  documents?: Record<
    string,
    { artifact: Row; versions: Schema["VersionRead"][] }
  >;
};
export async function applicationsFixture(
  url: URL,
  init: RequestInit | undefined,
  rows: Record<string, Row[]>,
  artifactVersions: Record<string, Row[]>,
) {
  const route = url.pathname.replace("/api/backend/", "");
  const method = init?.method ?? "GET";
  const state: State = JSON.parse(localStorage.getItem(storage) ?? "null") ?? {
    applications: seed(),
    receipts: {},
    requests: [],
    contexts: {},
    contextReceipts: {},
  };
  state.contexts ??= {};
  state.contextReceipts ??= {};
  state.materials ??= {};
  state.materialReceipts ??= {};
  state.materialRequests ??= [];
  state.documents ??= {};
  const save = () => localStorage.setItem(storage, JSON.stringify(state));
  for (const [id, document] of Object.entries(state.documents)) {
    if (!rows.artifacts.some((item) => item.id === id))
      rows.artifacts.push(document.artifact);
    artifactVersions[id] = document.versions;
  }
  const respond = (item: Application) => {
    if (state.loseReply) {
      state.loseReply--;
      save();
      throw new TypeError("Synthetic lost status response");
    }
    save();
    return Response.json(item);
  };
  const key = new Headers(init?.headers).get("Idempotency-Key") ?? "";
  for (const item of state.applications)
    if (!rows.tasks.some((task) => task.id === item.task.id))
      rows.tasks.push(item.task);
  if (route === "test/application-tracker") return Response.json(state);
  if (route === "test/application-material-lost-reply") {
    state.loseMaterialReply = 2;
    save();
    return Response.json({ ok: true });
  }
  if (route === "test/application-material-complete") {
    const material = state.materials["task-tracker-1"]![0];
    const id = `application-document-${material.id}`;
    material.state = "completed";
    material.output = {
      artifact_id: id,
      version_id: `${id}-v1`,
      version: 1,
      title: "Cover letter · Northstar",
      archived: false,
    };
    state.documents[id] = {
      artifact: {
        id,
        title: material.output.title,
        kind: "document",
        document_type_id: "document-type-cover-letter",
        sensitivity: "private",
        row_version: 1,
        latest_version: 1,
        archived_at: null,
        created_at: stamp,
        updated_at: stamp,
      },
      versions: [
        {
          id: `${id}-v1`,
          artifact_id: id,
          version: 1,
          payload: {
            text: "Dear Northstar team,\n\nI build accessible collaboration tools.",
          },
          content_sha256: "c".repeat(64),
          created_at: stamp,
          input_version_ids: [material.job.version_id],
        },
      ],
    };
    save();
    return Response.json(material);
  }
  if (route === "test/application-lost-reply") {
    state.loseReply = 2;
    save();
    return Response.json({ ok: true });
  }
  if (route === `browser/snapshots/${snapshot.id}`)
    return Response.json(snapshot);
  if (route === `browser/snapshots/${snapshot.id}/preparation`)
    return Response.json(preparation);
  const sourceMatch = route.match(
    /^artifacts\/(job-context-task-tracker-[12])\/versions$/,
  );
  const documentMatch = route.match(
    /^artifacts\/(application-document-[^/]+)(.*)$/,
  );
  if (documentMatch) {
    const document = state.documents[documentMatch[1]];
    if (!document)
      return Response.json(
        { detail: "Missing synthetic document" },
        { status: 404 },
      );
    const suffix = documentMatch[2];
    if (!suffix) return Response.json(document.artifact);
    if (suffix === "/version-history")
      return Response.json({
        items: document.versions.map((item) => ({
          id: item.id,
          artifact_id: item.artifact_id,
          version: item.version,
          created_at: item.created_at,
          content_sha256: item.content_sha256,
          is_text: true,
          has_file: false,
        })),
        total: document.versions.length,
        next_before: null,
      });
    if (suffix === "/versions" && method === "POST") {
      if (state.contextReceipts[key])
        return Response.json(state.contextReceipts[key]);
      const body = JSON.parse(String(init?.body));
      if (body.expected_version !== document.artifact.row_version)
        return Response.json({ detail: "Document changed" }, { status: 409 });
      const version = {
        ...document.versions[0],
        id: `${documentMatch[1]}-v${document.versions.length + 1}`,
        version: document.versions.length + 1,
        payload: { text: body.text },
      };
      document.versions.unshift(version);
      document.artifact.row_version = Number(document.artifact.row_version) + 1;
      document.artifact.latest_version = version.version;
      state.contextReceipts[key] = version;
      save();
      return Response.json(version);
    }
    if (/^\/versions\/[^/]+$/.test(suffix))
      return Response.json(
        document.versions.find((item) => item.id === suffix.split("/")[2]),
      );
    if (suffix === "/tasks")
      return Response.json({ items: [], total: 0, limit: 20, offset: 0 });
    return null;
  }
  if (sourceMatch && method === "POST") {
    if (state.contextReceipts[key])
      return Response.json(state.contextReceipts[key]);
    const context = Object.values(state.contexts).find(
      (item) => item.artifact_id === sourceMatch[1],
    )!;
    const body = JSON.parse(String(init?.body));
    if (body.expected_version !== context.expected_version)
      return Response.json({ detail: "Source changed" }, { status: 409 });
    context.text = body.text;
    context.version++;
    context.expected_version++;
    context.version_id = `${context.artifact_id}-v${context.version}`;
    const version = {
      id: context.version_id,
      artifact_id: context.artifact_id,
      version: context.version,
      created_at: stamp,
      payload: { text: context.text },
      content_sha256: "b".repeat(64),
      blob_key: null,
      schema_key: "application.job_context.v1",
      input_version_ids: [],
    };
    state.contextReceipts[key] = version;
    save();
    return Response.json(version);
  }
  const taskMatch = route.match(/^tasks\/(task-tracker-[12])$/);
  if (taskMatch) {
    const item = state.applications.find(
      (item) => item.task.id === taskMatch[1],
    )!;
    if (method === "PATCH") {
      Object.assign(item.task, JSON.parse(String(init?.body)), {
        row_version: item.task.row_version + 1,
      });
      save();
    }
    return Response.json(item.task);
  }
  if (route === "applications") {
    let list = state.applications;
    if (url.searchParams.has("status"))
      list = list.filter(
        (item) => item.status === url.searchParams.get("status"),
      );
    const q = (url.searchParams.get("q") ?? "").toLowerCase();
    list = list.filter((item) =>
      `${item.page_title} ${item.origin} ${item.task.title}`
        .toLowerCase()
        .includes(q),
    );
    return Response.json({
      items: list,
      total: list.length,
      limit: 30,
      offset: 0,
    });
  }
  const match = route.match(/^applications\/(task-tracker-[12])(?:\/(.*))?$/);
  if (!match) return null;
  const item = state.applications.find((item) => item.task.id === match[1])!;
  if (match[2] === "materials") {
    const list = (state.materials[item.task.id] ??= []);
    if (method === "GET")
      return Response.json({
        items: list,
        total: list.length,
        limit: 10,
        offset: 0,
      });
    const body = JSON.parse(String(init?.body));
    state.materialRequests.push({ key, body });
    let result = state.materialReceipts[key];
    if (!result) {
      const context = state.contexts[item.task.id];
      if (!context?.text)
        return Response.json(
          { detail: "Save requirements first" },
          { status: 409 },
        );
      result = {
        id: `material-${list.length + 1}`,
        task_id: item.task.id,
        kind: body.kind,
        run_id: "run-material",
        session_id: "session-material",
        state: "queued",
        error_code: null,
        job: {
          artifact_id: context.artifact_id,
          version_id: body.job_version_id,
          version: context.version,
          title: context.artifact_title,
          archived: false,
        },
        resume: {
          artifact_id: "artifact-resume",
          version_id: body.resume_version_id,
          version: 1,
          title: "Synthetic resume",
          archived: false,
        },
        output: null,
        created_at: stamp,
      };
      list.unshift(result);
      state.materialReceipts[key] = structuredClone(result);
    }
    if (state.loseMaterialReply) {
      state.loseMaterialReply--;
      save();
      throw new TypeError("Synthetic lost generation response");
    }
    save();
    return Response.json(result);
  }
  if (match[2] === "job-context") {
    if (method === "POST") {
      if (state.contextReceipts[key])
        return Response.json(state.contextReceipts[key]);
      const body = JSON.parse(String(init?.body));
      if (
        body.expected_version !== item.row_version ||
        state.contexts[item.task.id]
      )
        return Response.json(
          { detail: "Application changed" },
          { status: 409 },
        );
      const id = `job-context-${item.task.id}`;
      state.contexts[item.task.id] = {
        artifact_id: id,
        artifact_title: `Job description · ${item.page_title}`,
        expected_version: 1,
        version_id: `${id}-v1`,
        version: 1,
        text: body.text,
        job_title: body.job_title,
        company_name: body.company_name,
        page_url: item.page_url,
        extraction_method: "manual",
        truncated: false,
        created_at: stamp,
      };
      item.job_context_artifact_id = id;
      item.row_version++;
      state.contextReceipts[key] = structuredClone(
        state.contexts[item.task.id],
      );
      save();
    }
    return Response.json(state.contexts[item.task.id] ?? null);
  }
  if (match[2] === "packages")
    return Response.json({
      items: [packageItem],
      total: 1,
      limit: 10,
      offset: 0,
    });
  if (match[2]?.startsWith("packages/")) return Response.json(preparation);
  if (method === "PATCH") {
    const body = JSON.parse(String(init?.body));
    state.requests.push({ key, body });
    if (state.receipts[key]) {
      return respond(state.receipts[key]);
    }
    if (body.expected_version !== item.row_version) {
      save();
      return Response.json(
        { detail: "This record changed. Refresh it before saving again." },
        { status: 409 },
      );
    }
    item.status = body.status;
    item.row_version++;
    item.submission_recorded_at =
      item.status === "preparing"
        ? null
        : (item.submission_recorded_at ?? stamp);
    state.receipts[key] = structuredClone(item);
    return respond(item);
  }
  return Response.json(item);
}
