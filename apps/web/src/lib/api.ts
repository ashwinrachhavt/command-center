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
    method?: "GET" | "POST" | "PATCH";
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
export function recordName(record: WorkspaceRecord) {
  return "name" in record ? record.name : record.title;
}
export function dateLabel(value: string | null | undefined) {
  if (!value) return "No date";
  const date = new Date(value.length === 10 ? `${value}T12:00:00` : value);
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
