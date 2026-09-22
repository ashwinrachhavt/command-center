import type { components } from "./api-types";

export type Schema = components["schemas"];
export type Resources = {
  companies: Schema["CompanyRead"];
  contacts: Schema["ContactRead"];
  jobs: Schema["JobRead"];
  opportunities: Schema["OpportunityRead"];
  tasks: Schema["TaskRead"];
  artifacts: Schema["ArtifactRead"];
};
export type Resource = keyof Resources;
export type WorkspaceRecord = Resources[Resource];
export type Page<T> = {
  items: T[];
  total: number;
  limit: number;
  offset: number;
};
export type Profile = Schema["ProfileRead"];
export type Activity = Schema["ActivityRead"];
export type Run = Schema["RunRead"];
export type AgentSession = Schema["SessionRead"];
export type AgentMessage = Schema["MessageRead"];
export type RunStep = Schema["RunStepRead"];
export type RunArtifact = Schema["RunArtifactRead"];
export type PublicSearchResult = {
  title: string;
  url: string;
  content: string;
};
export type LeadSource = Schema["LeadSourceRead"];
export type CapturedLead = Schema["LeadCaptureRead"];
export type ModelProvider = "openai" | "gemini" | "mistral" | "cohere";
export type AgentProfile = {
  id: string;
  name: string;
  description: string;
  provider: ModelProvider;
  model: string;
  ready: boolean;
  missing_credentials: string[];
  tools: string[];
  revision: string;
};
export type Integrations = {
  services: { name: string; state: string }[];
  model_providers: Record<ModelProvider, boolean>;
  openai_configured: boolean;
  composio_configured: boolean;
  auth: string;
  composio_toolkits: string[];
};

export type DocumentImport = Schema["DocumentImportRead"];
export type ResumeSelection = Schema["ResumeSelectionRead"];
export type FactRevision = Schema["FactRevisionRead"];
export type ProfileFact = Schema["FactRead"];

export type PdfExport = Schema["PdfExportRead"];

export type BrowserField = {
  id: string;
  label: string;
  type:
    | "text"
    | "email"
    | "tel"
    | "url"
    | "textarea"
    | "select"
    | "file"
    | "radio"
    | "checkbox"
    | "number"
    | "unsupported";
  required: boolean;
  options: string[];
  option_labels: Record<string, string>;
  value_state: "empty" | "present";
  autocomplete: string;
  accept: string;
  unsupported_reason: string | null;
  numeric_constraints: {
    minimum: string | null;
    maximum: string | null;
    step: string;
    step_base: string;
  } | null;
};
export type BrowserSnapshot = {
  id: string;
  protocol_version: 2;
  title: string;
  origin: string;
  page_url: string;
  created_at: string;
  fields: BrowserField[];
};
export type ResumeFile = Schema["ResumeFile"];
export type ResumeOption = Schema["ResumeOption"];
export type ResumeOptions = Schema["ResumeOptions"];
export type PreparedEvidence = Schema["ApplicationEvidenceRead"];
export type PreparedField = Schema["PreparedFieldRead"];
export type ApplicationPreparation = Schema["ApplicationPreparationRead"];
export type BrowserFillCommand = {
  id: string;
  state: string;
  created_at: string;
  fields: Record<string, string>;
  uploads: Record<string, string>;
  field_results?: Record<string, Schema["FieldResult"]>;
};

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function api<T>(
  path: string,
  options: {
    method?: "GET" | "POST" | "PUT" | "PATCH";
    body?: unknown;
    key?: string;
    signal?: AbortSignal;
  } = {},
): Promise<T> {
  const method = options.method ?? "GET";
  const key =
    method === "GET" ? undefined : (options.key ?? crypto.randomUUID());
  for (let attempt = 0; ; attempt++) {
    try {
      const response = await fetch(`/api/backend/${path}`, {
        method,
        cache: "no-store",
        signal: options.signal,
        headers: {
          ...(options.body !== undefined
            ? { "Content-Type": "application/json" }
            : {}),
          ...(key ? { "Idempotency-Key": key } : {}),
        },
        body:
          options.body === undefined ? undefined : JSON.stringify(options.body),
      });
      const data = await response.json();
      if (!response.ok) {
        const detail =
          typeof data.detail === "string"
            ? data.detail
            : Array.isArray(data.detail)
              ? data.detail
                  .map(
                    (item: { msg: string; loc?: string[] }) =>
                      `${item.loc?.at(-1) ?? "Field"}: ${item.msg}`,
                  )
                  .join(". ")
              : typeof data.detail?.message === "string"
                ? data.detail.message
                : "The request could not be completed.";
        throw new ApiError(
          response.status,
          response.status === 401
            ? "Your session expired. Sign in again to continue."
            : detail,
        );
      }
      return data as T;
    } catch (error) {
      if (
        options.signal?.aborted ||
        attempt > 0 ||
        (error instanceof ApiError && error.status < 500)
      )
        throw error;
      await new Promise((resolve) => setTimeout(resolve, 350));
    }
  }
}

async function responseError(response: Response) {
  let detail: unknown;
  try {
    detail = (await response.json()).detail;
  } catch {
    detail = undefined;
  }
  const message =
    typeof detail === "string"
      ? detail
      : Array.isArray(detail)
        ? detail
            .map(
              (item: { msg: string; loc?: string[] }) =>
                `${item.loc?.at(-1) ?? "Field"}: ${item.msg}`,
            )
            .join(". ")
        : detail &&
            typeof detail === "object" &&
            "message" in detail &&
            typeof detail.message === "string"
          ? detail.message
          : "The request could not be completed.";
  return new ApiError(
    response.status,
    response.status === 401
      ? "Your session expired. Sign in again to continue."
      : message,
  );
}

export async function apiForm<T>(
  path: string,
  form: FormData,
  options: { key: string; signal?: AbortSignal },
): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    try {
      const response = await fetch(`/api/backend/${path}`, {
        method: "POST",
        cache: "no-store",
        signal: options.signal,
        headers: { "Idempotency-Key": options.key },
        body: form,
      });
      if (!response.ok) throw await responseError(response);
      return (await response.json()) as T;
    } catch (error) {
      if (
        options.signal?.aborted ||
        attempt > 0 ||
        (error instanceof ApiError && error.status < 500)
      )
        throw error;
      await new Promise((resolve) => setTimeout(resolve, 350));
    }
  }
}

export async function apiDownload(path: string) {
  const response = await fetch(`/api/backend/${path}`, {
    cache: "no-store",
  });
  if (!response.ok) throw await responseError(response);
  const disposition = response.headers.get("content-disposition") ?? "";
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  const quoted = disposition.match(/filename="([^"]+)"/i)?.[1];
  return {
    blob: await response.blob(),
    filename: encoded ? decodeURIComponent(encoded) : quoted,
  };
}

export function label(value: string | null | undefined) {
  return value
    ? value
        .replaceAll("_", " ")
        .replaceAll("-", " ")
        .replace(/^./, (c) => c.toUpperCase())
    : "—";
}

const runFailureMessages: Record<string, string> = {
  spending_policy_unconfigured:
    "Configure spending limits and provider rates in Settings before starting work.",
  cost_bound_unavailable:
    "Add a rate for the selected model or connected tool in Settings.",
  spending_monthly_limit: "The monthly spending limit has been reached.",
  spending_work_limit:
    "The spending limit for this task or opportunity has been reached.",
  spending_period_expired:
    "This run’s monthly budget snapshot expired. Start a new run.",
  spending_lease_lost: "This run stopped because its worker lease ended.",
  spending_reservation_conflict:
    "The spending record changed. Refresh before trying again.",
  spending_reservation_missing:
    "The spending record is unavailable. Refresh before trying again.",
  execution_timeout: "This run reached its time limit and stopped.",
  context_limit: "This run reached its context limit and stopped.",
  model_limit: "This run reached its model-call limit and stopped.",
  tool_limit: "This run reached its tool-call limit and stopped.",
  worker_interrupted:
    "The worker stopped before this run finished. No automatic replay was attempted.",
  agent_execution_failed:
    "The provider or worker stopped unexpectedly. No automatic replay was attempted.",
};

export function runFailureMessage(code: string | null | undefined) {
  return code && runFailureMessages[code]
    ? runFailureMessages[code]
    : "This work could not finish. Review the activity before trying again.";
}
export function recordName(record: WorkspaceRecord) {
  return "name" in record ? record.name : record.title;
}
export function dateLabel(value: string | null | undefined) {
  if (!value) return "No date";
  const date = new Date(value.length === 10 ? `${value}T12:00:00` : value);
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
