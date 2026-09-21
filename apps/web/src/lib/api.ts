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
export type AgentProfile = {
  id: string;
  name: string;
  description: string;
  model: string;
  tools: string[];
  revision: string;
};
export type Integrations = {
  services: { name: string; state: string }[];
  openai_configured: boolean;
  composio_configured: boolean;
  auth: string;
  composio_toolkits: string[];
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
