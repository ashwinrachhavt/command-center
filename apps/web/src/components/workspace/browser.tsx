"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  Copy,
  FileCheck2,
  Globe,
  Link2,
  Plus,
  Puzzle,
  RefreshCw,
  Send,
  Sparkles,
  Unplug,
} from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  api,
  dateLabel,
  label,
  type ApplicationPreparation,
  type BrowserField,
  type BrowserFillCommand,
  type BrowserSnapshot,
  type Page,
  type ResumeOptions,
  type Run,
  type WorkspaceRecord,
} from "@/lib/api";
import {
  EmptyState,
  ErrorState,
  PageHeading,
  Spinner,
  Status,
} from "./primitives";

type Device = {
  id: string;
  name: string;
  paired_at: string | null;
  last_seen_at: string | null;
  revoked_at: string | null;
};

type Draft = {
  preparation?: ApplicationPreparation;
  values: Record<string, string>;
  touched: string[];
  replaceFields: string[];
  rememberFields: string[];
  uploadFields: string[];
  uploadsTouched: boolean;
  resumeVersionId: string | null;
  resumeTouched: boolean;
  opportunityId: string | null;
  generationRunId?: string;
  savedSignature?: string;
  savedPreparation?: ApplicationPreparation;
};

const emptyDraft = (defaultResume: string | null): Draft => ({
  values: {},
  touched: [],
  replaceFields: [],
  rememberFields: [],
  uploadFields: [],
  uploadsTouched: false,
  resumeVersionId: defaultResume,
  resumeTouched: false,
  opportunityId: null,
});

function toggle(items: string[], value: string, enabled: boolean) {
  return enabled
    ? Array.from(new Set([...items, value]))
    : items.filter((item) => item !== value);
}

function mergePreparation(
  draft: Draft,
  preparation: ApplicationPreparation,
): Draft {
  const values = { ...draft.values };
  const touched = new Set(draft.touched);
  for (const field of preparation.fields) {
    if (!touched.has(field.field_id) && !values[field.field_id] && field.value)
      values[field.field_id] = field.value;
  }
  return {
    ...draft,
    preparation,
    values,
    resumeVersionId: draft.resumeTouched
      ? draft.resumeVersionId
      : (preparation.resume?.version_id ?? null),
    uploadFields: draft.uploadsTouched
      ? draft.uploadFields
      : preparation.upload_fields,
  };
}

function fieldValueAllowed(field: BrowserField, draft: Draft) {
  return (
    field.value_state === "empty" || draft.replaceFields.includes(field.id)
  );
}

function AnswerInput({
  field,
  draft,
  update,
}: {
  field: BrowserField;
  draft: Draft;
  update: (change: (current: Draft) => Draft) => void;
}) {
  const enabled = fieldValueAllowed(field, draft);
  const value = draft.values[field.id] ?? "";
  const setValue = (next: string) =>
    update((current) => ({
      ...current,
      values: { ...current.values, [field.id]: next },
      touched: toggle(current.touched, field.id, true),
      savedSignature: undefined,
      savedPreparation: undefined,
    }));
  if (field.type === "select" || field.type === "radio")
    return (
      <Select
        value={value || "__skip"}
        onValueChange={(next) => setValue(next === "__skip" ? "" : next)}
        disabled={!enabled}
      >
        <SelectTrigger id={field.id}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectGroup>
            <SelectItem value="__skip">Leave unchanged</SelectItem>
            {field.options.filter(Boolean).map((option) => (
              <SelectItem value={option} key={option}>
                {field.option_labels[option] || option}
              </SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </Select>
    );
  if (field.type === "checkbox")
    return (
      <Select
        value={value || "__skip"}
        onValueChange={(next) => setValue(next === "__skip" ? "" : next)}
        disabled={!enabled}
      >
        <SelectTrigger id={field.id}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="__skip">Leave unchanged</SelectItem>
          <SelectItem value="true">Yes</SelectItem>
          <SelectItem value="false">No</SelectItem>
        </SelectContent>
      </Select>
    );
  if (field.type === "textarea")
    return (
      <Textarea
        id={field.id}
        value={value}
        disabled={!enabled}
        onChange={(event) => setValue(event.target.value)}
        maxLength={5000}
        rows={4}
        placeholder="Add an answer or generate a draft"
      />
    );
  return (
    <Input
      id={field.id}
      value={value}
      disabled={!enabled}
      onChange={(event) => setValue(event.target.value)}
      maxLength={5000}
      placeholder="Leave blank to skip"
    />
  );
}

function PreparationForm({
  snapshot,
  draft,
  resumes,
  opportunities,
  update,
}: {
  snapshot: BrowserSnapshot;
  draft: Draft;
  resumes: ResumeOptions;
  opportunities: WorkspaceRecord[];
  update: (change: (current: Draft) => Draft) => void;
}) {
  const client = useQueryClient();
  const receipts = useRef<Record<string, string>>({});
  const receipt = (kind: string) =>
    (receipts.current[kind] ??= crypto.randomUUID());
  const clearReceipt = (kind: string) => delete receipts.current[kind];
  const selectedResume = resumes.items.find(
    (item) => item.version_id === draft.resumeVersionId,
  );
  const preparation = draft.preparation;
  const preparedByField = new Map(
    preparation?.fields.map((field) => [field.field_id, field]) ?? [],
  );

  useEffect(() => {
    if (
      !draft.resumeTouched &&
      draft.resumeVersionId === null &&
      resumes.default_version_id
    )
      update((current) => ({
        ...current,
        resumeVersionId: resumes.default_version_id,
      }));
  }, [
    draft.resumeTouched,
    draft.resumeVersionId,
    resumes.default_version_id,
    update,
  ]);

  const prepare = useMutation({
    mutationFn: () =>
      api<ApplicationPreparation>(
        `browser/snapshots/${snapshot.id}/preparations`,
        {
          method: "POST",
          key: receipt("prepare"),
          body: {
            opportunity_id: draft.opportunityId,
            resume_version_id: draft.resumeVersionId,
          },
        },
      ),
    onSuccess: (result) => {
      clearReceipt("prepare");
      update((current) => ({
        ...mergePreparation(current, result),
        generationRunId: undefined,
      }));
      toast.success("Application answers prepared for review");
    },
    onError: (error) => toast.error(error.message),
  });

  const generate = useMutation({
    mutationFn: () =>
      api<{ conversation_id: string; run_id: string }>(
        `browser/preparations/${preparation!.id}/generate`,
        { method: "POST", body: {}, key: receipt("generate") },
      ),
    onSuccess: (result) => {
      clearReceipt("generate");
      update((current) => ({
        ...current,
        generationRunId: result.run_id,
      }));
      toast.success("Draft generation queued");
    },
    onError: (error) => toast.error(error.message),
  });
  const generationRun = useQuery({
    queryKey: ["application-generation-run", draft.generationRunId],
    enabled: !!draft.generationRunId,
    queryFn: () => api<Run>(`agent-runs/${draft.generationRunId}`),
    refetchInterval: (query) =>
      ["queued", "running"].includes(query.state.data?.state ?? "queued")
        ? 1000
        : false,
  });
  const generating = ["queued", "running"].includes(
    generationRun.data?.state ?? (draft.generationRunId ? "queued" : ""),
  );
  useQuery({
    queryKey: ["application-preparation", preparation?.id],
    enabled: !!preparation && !!draft.generationRunId,
    queryFn: async () => {
      const latest = await api<ApplicationPreparation>(
        `browser/preparations/${preparation!.id}`,
      );
      update((current) => mergePreparation(current, latest));
      return latest;
    },
    refetchInterval: generating ? 1000 : false,
  });

  const actionFields = Object.fromEntries(
    snapshot.fields
      .filter(
        (field) =>
          !["file", "unsupported"].includes(field.type) &&
          fieldValueAllowed(field, draft) &&
          !!draft.values[field.id],
      )
      .map((field) => [field.id, draft.values[field.id]]),
  );
  const revisionFields = Object.fromEntries(
    snapshot.fields
      .filter((field) => !["file", "unsupported"].includes(field.type))
      .map((field) => [
        field.id,
        field.value_state === "present" &&
        !draft.replaceFields.includes(field.id)
          ? ""
          : (draft.values[field.id] ?? ""),
      ]),
  );
  const uploads = Object.fromEntries(
    draft.resumeVersionId
      ? draft.uploadFields.map((fieldId) => [fieldId, draft.resumeVersionId!])
      : [],
  );
  const requestedFieldIds = new Set([
    ...Object.keys(actionFields),
    ...Object.keys(uploads),
  ]);
  const commandReplaceFields = draft.replaceFields.filter((fieldId) =>
    requestedFieldIds.has(fieldId),
  );
  const commandRememberFields = draft.rememberFields.filter(
    (fieldId) => fieldId in actionFields,
  );
  const revisionSignature = JSON.stringify({
    fields: revisionFields,
    resume_version_id: draft.resumeVersionId,
    replace_fields: commandReplaceFields,
    remember_fields: commandRememberFields,
    upload_fields: draft.uploadFields,
  });
  const send = useMutation({
    mutationFn: async () => {
      if (generating)
        throw new Error("Wait for draft generation to finish before saving a review.");
      if (!preparation)
        throw new Error("Prepare this form before sending a proposal.");
      let saved = draft.savedPreparation;
      if (!saved || draft.savedSignature !== revisionSignature) {
        saved = await api<ApplicationPreparation>(
          `browser/preparations/${preparation.id}/revisions`,
          {
            method: "POST",
            key: receipt("revision"),
            body: {
              expected_version_id: preparation.version_id,
              fields: revisionFields,
              resume_version_id: draft.resumeVersionId,
              replace_fields: commandReplaceFields,
              remember_fields: commandRememberFields,
              upload_fields: draft.uploadFields,
            },
          },
        );
        clearReceipt("revision");
        update((current) => ({
          ...mergePreparation(current, saved!),
          savedSignature: revisionSignature,
          savedPreparation: saved,
        }));
      }
      return api<BrowserFillCommand>("browser/commands", {
        method: "POST",
        key: receipt("command"),
        body: {
          snapshot_id: snapshot.id,
          fields: actionFields,
          uploads,
          replace_fields: commandReplaceFields,
          preparation_version_id: saved.version_id,
        },
      });
    },
    onSuccess: () => {
      clearReceipt("command");
      void client.invalidateQueries({ queryKey: ["browser-commands"] });
      toast.success(
        "Fill proposal sent. Review and apply it in the browser companion.",
      );
    },
    onError: (error) => toast.error(error.message),
  });

  const missing =
    preparation?.fields.filter((field) => field.status === "needs_input") ?? [];
  const hasActions =
    Object.keys(actionFields).length > 0 || Object.keys(uploads).length > 0;

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (hasActions && !generating) send.mutate();
      }}
    >
      <div className="mb-5 flex items-start gap-3">
        <Globe className="mt-1 size-4 text-primary" />
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-medium">
            {snapshot.title || "Shared form"}
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">
            {snapshot.origin} · {dateLabel(snapshot.created_at)}
          </p>
        </div>
        <Badge variant="outline">Protocol v{snapshot.protocol_version}</Badge>
      </div>

      <div className="mb-5 grid gap-4 rounded-lg border border-border bg-muted/20 p-4 sm:grid-cols-2">
        <Field>
          <FieldLabel htmlFor={`opportunity-${snapshot.id}`}>
            Application context
          </FieldLabel>
          <Select
            value={draft.opportunityId ?? "none"}
            onValueChange={(value) =>
              update((current) => ({
                ...current,
                opportunityId: value === "none" ? null : value,
                preparation: undefined,
                generationRunId: undefined,
                savedPreparation: undefined,
                savedSignature: undefined,
              }))
            }
          >
            <SelectTrigger id={`opportunity-${snapshot.id}`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">No opportunity selected</SelectItem>
              {opportunities.map((opportunity) => (
                <SelectItem key={opportunity.id} value={opportunity.id}>
                  {"title" in opportunity
                    ? opportunity.title
                    : opportunity.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field>
          <FieldLabel htmlFor={`resume-${snapshot.id}`}>
            Exact resume version
          </FieldLabel>
          <Select
            value={draft.resumeVersionId ?? "none"}
            onValueChange={(value) =>
              update((current) => ({
                ...current,
                resumeVersionId: value === "none" ? null : value,
                resumeTouched: true,
                preparation: undefined,
                generationRunId: undefined,
                uploadFields: [],
                uploadsTouched: true,
                savedPreparation: undefined,
                savedSignature: undefined,
              }))
            }
          >
            <SelectTrigger
              id={`resume-${snapshot.id}`}
              aria-label="Exact resume version"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">No resume</SelectItem>
              {resumes.items.map((resume) => (
                <SelectItem key={resume.version_id} value={resume.version_id}>
                  {resume.filename} · v{resume.version}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {selectedResume ? (
            <p className="text-[11px] text-muted-foreground">
              Pinned {selectedResume.version_id} ·{" "}
              {Math.ceil(selectedResume.size_bytes / 1024)} KB
            </p>
          ) : null}
        </Field>
        <div className="flex flex-wrap items-center gap-2 sm:col-span-2">
          <Button
            type="button"
            onClick={() => prepare.mutate()}
            disabled={prepare.isPending || generating}
          >
            {prepare.isPending ? <Spinner /> : <FileCheck2 />}
            {preparation ? "Prepare again" : "Prepare answers"}
          </Button>
          {preparation ? (
            <Button
              type="button"
              variant="outline"
              onClick={() => generate.mutate()}
              disabled={generate.isPending || generating}
            >
              {generate.isPending || generating ? <Spinner /> : <Sparkles />}
              {generating ? "Generating…" : "Generate narrative drafts"}
            </Button>
          ) : null}
          {preparation ? (
            <Link
              href={`/tasks?record=${preparation.task_id}&tab=conversation`}
              className="text-xs text-primary underline underline-offset-4"
            >
              Open generation conversation
            </Link>
          ) : null}
        </div>
      </div>

      {missing.length ? (
        <div className="mb-5 rounded-lg border border-[var(--status-amber)]/30 bg-[var(--status-amber)]/5 p-4">
          <p className="text-xs font-medium">Missing answers</p>
          <ul className="mt-2 list-disc space-y-1 pl-4 text-xs text-muted-foreground">
            {missing.map((item) => (
              <li key={item.field_id}>
                {snapshot.fields.find((field) => field.id === item.field_id)
                  ?.label ?? item.field_id}
                : {item.reason}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <FieldGroup className="gap-4">
        {snapshot.fields.map((field) => {
          const prepared = preparedByField.get(field.id);
          const present = field.value_state === "present";
          if (field.type === "file")
            return (
              <Field
                key={field.id}
                className="rounded-lg border border-border p-4"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <FieldLabel>
                      {field.label || field.id}
                      {field.required ? " *" : ""}
                    </FieldLabel>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {field.accept
                        ? `Accepts ${field.accept}`
                        : "Application file upload"}
                    </p>
                  </div>
                  <Badge variant="outline">Resume upload</Badge>
                </div>
                {present ? (
                  <label className="mt-3 flex items-center gap-3 text-xs text-muted-foreground">
                    <Checkbox
                      aria-label={`Replace existing attachment for ${field.label || field.id}`}
                      checked={draft.replaceFields.includes(field.id)}
                      onCheckedChange={(checked) =>
                        update((current) => ({
                          ...current,
                          replaceFields: toggle(
                            current.replaceFields,
                            field.id,
                            checked === true,
                          ),
                          savedPreparation: undefined,
                          savedSignature: undefined,
                        }))
                      }
                    />
                    Replace the attachment already in the application
                  </label>
                ) : null}
                <label className="mt-3 flex items-center gap-3 text-xs">
                  <Checkbox
                    aria-label={`Upload selected resume to ${field.label || field.id}`}
                    checked={draft.uploadFields.includes(field.id)}
                    disabled={
                      !draft.resumeVersionId ||
                      (present && !draft.replaceFields.includes(field.id))
                    }
                    onCheckedChange={(checked) =>
                      update((current) => ({
                        ...current,
                        uploadFields: toggle(
                          current.uploadFields,
                          field.id,
                          checked === true,
                        ),
                        uploadsTouched: true,
                        savedPreparation: undefined,
                        savedSignature: undefined,
                      }))
                    }
                  />
                  Upload {selectedResume?.filename ?? "the selected resume"} to
                  this field
                </label>
                {present && !draft.replaceFields.includes(field.id) ? (
                  <p className="mt-2 text-xs text-muted-foreground">
                    An attachment is already present and will be preserved.
                  </p>
                ) : null}
              </Field>
            );
          if (field.type === "unsupported")
            return (
              <Field
                key={field.id}
                className="rounded-lg border border-border p-4"
              >
                <FieldLabel>{field.label || field.id}</FieldLabel>
                <p className="text-xs text-muted-foreground">
                  {field.unsupported_reason ||
                    prepared?.reason ||
                    "This control needs manual input."}
                </p>
              </Field>
            );
          return (
            <Field
              key={field.id}
              className="rounded-lg border border-border p-4"
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <FieldLabel htmlFor={field.id}>
                  {field.label || field.id}
                  {field.required ? " *" : ""}
                </FieldLabel>
                <div className="flex gap-2">
                  {present ? (
                    <Badge variant="outline">Already filled</Badge>
                  ) : null}
                  {prepared ? (
                    <Badge variant="outline">{label(prepared.status)}</Badge>
                  ) : null}
                </div>
              </div>
              {present ? (
                <label className="flex items-center gap-3 text-xs text-muted-foreground">
                  <Checkbox
                    aria-label={`Replace existing value for ${field.label || field.id}`}
                    checked={draft.replaceFields.includes(field.id)}
                    onCheckedChange={(checked) =>
                      update((current) => ({
                        ...current,
                        replaceFields: toggle(
                          current.replaceFields,
                          field.id,
                          checked === true,
                        ),
                        touched:
                          checked === true
                            ? toggle(current.touched, field.id, true)
                            : current.touched,
                        savedPreparation: undefined,
                        savedSignature: undefined,
                      }))
                    }
                  />
                  Replace the value already in the application
                </label>
              ) : null}
              <AnswerInput field={field} draft={draft} update={update} />
              {prepared?.reason ? (
                <p className="text-xs leading-5 text-muted-foreground">
                  {prepared.reason}
                </p>
              ) : null}
              {prepared?.evidence.map((evidence) => (
                <p
                  key={evidence.revision_id}
                  className="text-[11px] leading-5 text-muted-foreground"
                >
                  Approved fact: {evidence.value}
                  {evidence.context ? ` · ${evidence.context}` : ""} · revision{" "}
                  {evidence.revision_id.slice(0, 8)}
                  {evidence.source_version_id
                    ? ` · source ${evidence.source_version_id.slice(0, 8)}`
                    : ""}
                </p>
              ))}
              {draft.opportunityId && draft.values[field.id] ? (
                <label className="flex items-center gap-3 text-xs text-muted-foreground">
                  <Checkbox
                    aria-label={`Remember ${field.label || field.id}`}
                    checked={draft.rememberFields.includes(field.id)}
                    onCheckedChange={(checked) =>
                      update((current) => ({
                        ...current,
                        rememberFields: toggle(
                          current.rememberFields,
                          field.id,
                          checked === true,
                        ),
                        savedPreparation: undefined,
                        savedSignature: undefined,
                      }))
                    }
                  />
                  Propose this answer for later review and reuse in this
                  opportunity
                </label>
              ) : null}
            </Field>
          );
        })}
      </FieldGroup>
      <Button
        className="mt-5"
        disabled={!preparation || !hasActions || send.isPending || generating}
      >
        {send.isPending ? <Spinner /> : <Send />}
        Save exact revision & send proposal
      </Button>
      <p className="mt-3 text-xs leading-6 text-muted-foreground">
        The companion rechecks this exact shared page and preserves values added
        after sharing. Review every answer and attachment before applying. It
        never clicks Next or Submit.
      </p>
    </form>
  );
}

export function BrowserPage() {
  const client = useQueryClient();
  const [code, setCode] = useState<string>();
  const [selected, setSelected] = useState<string>();
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const devices = useQuery({
    queryKey: ["devices"],
    queryFn: () => api<Device[]>("browser/devices"),
    refetchInterval: 10000,
  });
  const snapshots = useQuery({
    queryKey: ["snapshots"],
    queryFn: () => api<BrowserSnapshot[]>("browser/snapshots"),
    refetchInterval: 10000,
  });
  const commands = useQuery({
    queryKey: ["browser-commands"],
    queryFn: () => api<BrowserFillCommand[]>("browser/commands"),
    refetchInterval: 5000,
  });
  const resumes = useQuery({
    queryKey: ["browser-resumes"],
    queryFn: () => api<ResumeOptions>("browser/resumes"),
  });
  const opportunities = useQuery({
    queryKey: ["browser-opportunities"],
    queryFn: () =>
      api<Page<WorkspaceRecord>>("opportunities?limit=100&offset=0"),
  });
  const pair = useMutation({
    mutationFn: () =>
      api<{ code: string }>("browser/pairings", {
        method: "POST",
        body: { name: "My browser" },
      }),
    onSuccess: (data) => {
      setCode(data.code);
      void client.invalidateQueries({ queryKey: ["devices"] });
    },
    onError: (error) => toast.error(error.message),
  });
  const revoke = useMutation({
    mutationFn: (id: string) =>
      api(`browser/devices/${id}/revoke`, { method: "POST" }),
    onSuccess: () => {
      void client.invalidateQueries();
      toast.success("Browser access revoked");
    },
    onError: (error) => toast.error(error.message),
  });
  const snapshot =
    snapshots.data?.find((item) => item.id === selected) ?? snapshots.data?.[0];
  const draft = snapshot
    ? (drafts[snapshot.id] ??
      emptyDraft(resumes.data?.default_version_id ?? null))
    : undefined;
  const updateDraft = snapshot
    ? (change: (current: Draft) => Draft) =>
        setDrafts((current) => ({
          ...current,
          [snapshot.id]: change(
            current[snapshot.id] ??
              emptyDraft(resumes.data?.default_version_id ?? null),
          ),
        }))
    : undefined;

  return (
    <>
      <PageHeading
        title="Browser companion"
        description="Prepare grounded answers and an exact resume for forms in your signed-in browser."
        action={
          <Button onClick={() => pair.mutate()} disabled={pair.isPending}>
            <Plus /> Pair a browser
          </Button>
        }
      />
      <div className="grid gap-6 px-5 md:px-9 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]">
        <section className="flex flex-col gap-5">
          <div className="rounded-xl border border-border bg-card p-6">
            <Puzzle className="mb-4 size-7 text-primary" />
            <h2 className="text-lg font-medium">Your browser. Your session.</h2>
            <p className="mt-3 text-xs leading-6 text-muted-foreground">
              Load the local extension from <code>apps/extension</code>, pair it
              here, then share the current application page.
            </p>
            <p className="mt-3 text-xs leading-6 text-muted-foreground">
              Logins, cookies and existing field values stay in Chrome. The
              workspace receives field descriptions and whether each field is
              empty or present.
            </p>
            {code ? (
              <div className="mt-5 rounded-lg border border-primary/20 bg-primary/5 p-4">
                <Field>
                  <FieldLabel htmlFor="pair-code">
                    One-time pairing code
                  </FieldLabel>
                  <div className="flex gap-2">
                    <Input
                      id="pair-code"
                      value={code}
                      readOnly
                      className="font-mono text-xs"
                    />
                    <Button
                      size="icon"
                      variant="outline"
                      aria-label="Copy pairing code"
                      onClick={async () => {
                        await navigator.clipboard.writeText(code);
                        toast.success("Pairing code copied");
                      }}
                    >
                      <Copy />
                    </Button>
                  </div>
                </Field>
                <p className="mt-2 text-[11px] text-muted-foreground">
                  Paste this in the companion within 5 minutes.
                </p>
              </div>
            ) : null}
          </div>
          <div className="rounded-xl border border-border bg-card p-5">
            <h2 className="mb-4 text-sm font-medium">Paired browsers</h2>
            {devices.error ? (
              <ErrorState error={devices.error} />
            ) : devices.data?.filter((device) => !device.revoked_at).length ===
              0 ? (
              <p className="text-xs text-muted-foreground">
                No browser paired yet.
              </p>
            ) : (
              devices.data
                ?.filter((device) => !device.revoked_at)
                .map((device) => (
                  <div
                    key={device.id}
                    className="flex items-center gap-3 border-b border-border py-3 last:border-0"
                  >
                    <Link2 className="size-4 text-muted-foreground" />
                    <div className="flex-1">
                      <p className="text-xs font-medium">{device.name}</p>
                      <p className="mt-1 text-[10px] text-muted-foreground">
                        {device.paired_at
                          ? `Connected · Last seen ${dateLabel(device.last_seen_at ?? device.paired_at)}`
                          : "Waiting for pairing"}
                      </p>
                    </div>
                    <Button
                      size="icon-xs"
                      variant="ghost"
                      aria-label={`Revoke ${device.name}`}
                      onClick={() => revoke.mutate(device.id)}
                      disabled={revoke.isPending}
                    >
                      <Unplug />
                    </Button>
                  </div>
                ))
            )}
          </div>
          <div className="rounded-xl border border-border bg-card p-5">
            <h2 className="mb-3 text-sm font-medium">Recent fill proposals</h2>
            {commands.data?.map((command) => (
              <div className="border-b border-border py-3 last:border-0" key={command.id}>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-xs text-muted-foreground">
                    {Object.keys(command.fields).length} answers ·{" "}
                    {Object.keys(command.uploads ?? {}).length} files ·{" "}
                    {dateLabel(command.created_at)}
                  </span>
                  <Status value={command.state} />
                </div>
                {command.field_results &&
                Object.keys(command.field_results).length ? (
                  <ul className="mt-2 space-y-1 text-[11px] text-muted-foreground">
                    {Object.entries(command.field_results).map(
                      ([fieldId, result]) => (
                        <li key={fieldId}>
                          {label(fieldId)}: {label(result.status)}
                          {result.detail ? ` · ${result.detail}` : ""}
                        </li>
                      ),
                    )}
                  </ul>
                ) : null}
              </div>
            ))}
            {commands.data?.length === 0 ? (
              <p className="text-xs text-muted-foreground">No proposals yet.</p>
            ) : null}
          </div>
        </section>
        <section className="rounded-xl border border-border bg-card p-6">
          <div className="mb-5 flex items-center justify-between">
            <h2 className="text-sm font-medium">Shared application forms</h2>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Refresh shared forms"
              onClick={() => snapshots.refetch()}
            >
              <RefreshCw />
            </Button>
          </div>
          {snapshots.error || resumes.error || opportunities.error ? (
            <ErrorState
              error={snapshots.error ?? resumes.error ?? opportunities.error!}
              retry={() => {
                void snapshots.refetch();
                void resumes.refetch();
                void opportunities.refetch();
              }}
            />
          ) : snapshot && draft && updateDraft && resumes.data ? (
            <>
              {snapshots.data && snapshots.data.length > 1 ? (
                <Select value={snapshot.id} onValueChange={setSelected}>
                  <SelectTrigger className="mb-6" aria-label="Shared form">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      {snapshots.data.map((item) => (
                        <SelectItem key={item.id} value={item.id}>
                          {item.title || item.origin}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              ) : null}
              <PreparationForm
                snapshot={snapshot}
                draft={draft}
                resumes={resumes.data}
                opportunities={opportunities.data?.items ?? []}
                update={updateDraft}
              />
            </>
          ) : snapshots.isPending || resumes.isPending ? (
            <div className="flex min-h-40 items-center justify-center">
              <Spinner />
            </div>
          ) : (
            <EmptyState
              title="A little help, right where you need it"
              description="Open a form, click the companion and choose Share form. Its fields will appear here for answer preparation."
            >
              <span className="flex items-center gap-2 text-xs text-muted-foreground">
                <Check className="size-3 text-primary" /> No browser cookies or
                current values leave your device
              </span>
            </EmptyState>
          )}
        </section>
      </div>
    </>
  );
}
