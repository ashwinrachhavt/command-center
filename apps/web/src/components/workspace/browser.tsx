"use client";

import { AnimatedIcon } from "@/components/ui/animated-icon";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  Copy,
  FileCheck2,
  Globe,
  Link2,
  Plus,
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
import { RetainedRequestIntent } from "@/lib/retained-intent";
import {
  EmptyState,
  ErrorState,
  LoadingRows,
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
  coverLetterVersionId: string | null;
  coverLetterUploadFields: string[];
  coverLetterTouched: boolean;
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
  coverLetterVersionId: null,
  coverLetterUploadFields: [],
  coverLetterTouched: false,
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
    coverLetterVersionId: draft.coverLetterTouched
      ? draft.coverLetterVersionId
      : (preparation.cover_letter?.version_id ?? null),
    coverLetterUploadFields: draft.uploadsTouched
      ? draft.coverLetterUploadFields
      : (preparation.cover_letter_upload_fields ?? []),
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
            {field.options?.filter(Boolean).map((option) => (
              <SelectItem value={option} key={option}>
                {field.option_labels?.[option] || option}
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
      type={field.type === "unsupported" ? "text" : field.type}
      min={
        field.temporal_constraints?.minimum ??
        field.numeric_constraints?.minimum ??
        undefined
      }
      max={
        field.temporal_constraints?.maximum ??
        field.numeric_constraints?.maximum ??
        undefined
      }
      step={field.temporal_constraints?.step ?? field.numeric_constraints?.step}
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
  const [requestIntent] = useState(() => new RetainedRequestIntent());
  const coverLetters = useQuery({
    queryKey: ["browser-cover-letters"],
    queryFn: () => api<ResumeOptions>("browser/cover-letters"),
  });
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
    mutationFn: () => {
      const target = `browser/snapshots/${snapshot.id}/preparations`;
      const body = {
        opportunity_id: draft.opportunityId,
        resume_version_id: draft.resumeVersionId,
        cover_letter_version_id: draft.coverLetterVersionId,
      };
      const intent = requestIntent.forRequest("POST", target, body);
      return api<ApplicationPreparation>(target, {
        method: "POST",
        key: intent.key,
        body,
      }).then((result) => ({ result, target, body }));
    },
    onSuccess: ({ result, target, body }) => {
      requestIntent.confirmRequest("POST", target, body);
      update((current) => ({
        ...mergePreparation(current, result),
        generationRunId: undefined,
      }));
      toast.success("Application answers prepared for review");
    },
    onError: (error) => toast.error(error.message),
  });

  const generate = useMutation({
    mutationFn: () => {
      const target = `browser/preparations/${preparation!.id}/generate`;
      const body = {};
      const intent = requestIntent.forRequest("POST", target, body);
      return api<{ conversation_id: string; run_id: string }>(target, {
        method: "POST",
        body,
        key: intent.key,
      }).then((result) => ({ result, target, body }));
    },
    onSuccess: ({ result, target, body }) => {
      requestIntent.confirmRequest("POST", target, body);
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
  const uploads = Object.fromEntries([
    ...(draft.resumeVersionId
      ? draft.uploadFields.map((fieldId) => [fieldId, draft.resumeVersionId!])
      : []),
    ...(draft.coverLetterVersionId
      ? draft.coverLetterUploadFields.map((fieldId) => [
          fieldId,
          draft.coverLetterVersionId!,
        ])
      : []),
  ]);
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
    cover_letter_version_id: draft.coverLetterVersionId,
    replace_fields: commandReplaceFields,
    remember_fields: commandRememberFields,
    upload_fields: draft.uploadFields,
    cover_letter_upload_fields: draft.coverLetterUploadFields,
  });
  const send = useMutation({
    mutationFn: async () => {
      if (generating)
        throw new Error(
          "Wait for draft generation to finish before saving a review.",
        );
      if (!preparation)
        throw new Error("Prepare this form before sending a proposal.");
      let saved = draft.savedPreparation;
      if (!saved || draft.savedSignature !== revisionSignature) {
        const revisionTarget = `browser/preparations/${preparation.id}/revisions`;
        const revisionBody = {
          expected_version_id: preparation.version_id,
          fields: revisionFields,
          resume_version_id: draft.resumeVersionId,
          cover_letter_version_id: draft.coverLetterVersionId,
          replace_fields: commandReplaceFields,
          remember_fields: commandRememberFields,
          upload_fields: draft.uploadFields,
          cover_letter_upload_fields: draft.coverLetterUploadFields,
        };
        const revisionIntent = requestIntent.forRequest(
          "POST",
          revisionTarget,
          revisionBody,
        );
        saved = await api<ApplicationPreparation>(revisionTarget, {
          method: "POST",
          key: revisionIntent.key,
          body: revisionBody,
        });
        requestIntent.confirmRequest("POST", revisionTarget, revisionBody);
        update((current) => ({
          ...mergePreparation(current, saved!),
          savedSignature: revisionSignature,
          savedPreparation: saved,
        }));
      }
      const commandTarget = "browser/commands";
      const commandBody = {
        snapshot_id: snapshot.id,
        fields: actionFields,
        uploads,
        replace_fields: commandReplaceFields,
        preparation_version_id: saved.version_id,
      };
      const commandIntent = requestIntent.forRequest(
        "POST",
        commandTarget,
        commandBody,
      );
      const command = await api<BrowserFillCommand>(commandTarget, {
        method: "POST",
        key: commandIntent.key,
        body: commandBody,
      });
      return { command, target: commandTarget, body: commandBody };
    },
    onSuccess: ({ target, body }) => {
      requestIntent.confirmRequest("POST", target, body);
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

      <div className="mb-5 grid grid-cols-1 gap-4 rounded-lg border border-border bg-muted/20 p-4 sm:grid-cols-2">
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
        <Field className="sm:col-span-2">
          <FieldLabel htmlFor={`cover-letter-${snapshot.id}`}>
            Exact cover letter · optional
          </FieldLabel>
          <Select
            value={draft.coverLetterVersionId ?? "none"}
            disabled={coverLetters.isPending || Boolean(coverLetters.error)}
            onValueChange={(value) =>
              update((current) => ({
                ...current,
                coverLetterVersionId: value === "none" ? null : value,
                coverLetterTouched: true,
                coverLetterUploadFields: [],
                uploadsTouched: true,
                savedPreparation: undefined,
                savedSignature: undefined,
              }))
            }
          >
            <SelectTrigger
              id={`cover-letter-${snapshot.id}`}
              className="w-full min-w-0 max-w-full [&_[data-slot=select-value]]:min-w-0"
              aria-label="Exact cover-letter version"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">No cover letter</SelectItem>
              {(coverLetters.data?.items ?? []).map((letter) => (
                <SelectItem key={letter.version_id} value={letter.version_id}>
                  {letter.title} · {letter.filename}
                </SelectItem>
              ))}
              {draft.coverLetterVersionId &&
              !coverLetters.data?.items.some(
                (item) => item.version_id === draft.coverLetterVersionId,
              ) ? (
                <SelectItem value={draft.coverLetterVersionId} disabled>
                  {preparation?.cover_letter?.filename ??
                    "Selected cover letter unavailable"}
                </SelectItem>
              ) : null}
            </SelectContent>
          </Select>
          {coverLetters.error ? (
            <div role="alert" className="text-xs text-destructive">
              {coverLetters.error.message}{" "}
              <Button
                variant="ghost"
                size="sm"
                onClick={() => void coverLetters.refetch()}
              >
                Retry cover letters
              </Button>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">
              Choose an uploaded letter or an exported PDF. Create and export
              drafts from Applications.
            </p>
          )}
        </Field>
        <div className="flex flex-wrap items-center gap-2 sm:col-span-2">
          <Button
            type="button"
            onClick={() => prepare.mutate()}
            disabled={prepare.isPending || generating}
          >
            <AnimatedIcon state={prepare.isPending}>
              {prepare.isPending ? <Spinner /> : <FileCheck2 />}
            </AnimatedIcon>
            {preparation ? "Prepare again" : "Prepare answers"}
          </Button>
          {preparation ? (
            <Button
              type="button"
              variant="outline"
              onClick={() => generate.mutate()}
              disabled={generate.isPending || generating}
            >
              <AnimatedIcon state={generate.isPending || generating}>
                {generate.isPending || generating ? <Spinner /> : <Sparkles />}
              </AnimatedIcon>
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
          <ul className="mt-2 list-disc space-y-1 ps-4 text-xs text-muted-foreground">
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
                  <Badge variant="outline">Document upload</Badge>
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
                          uploadFields:
                            checked === true
                              ? current.uploadFields
                              : current.uploadFields.filter(
                                  (id) => id !== field.id,
                                ),
                          coverLetterUploadFields:
                            checked === true
                              ? current.coverLetterUploadFields
                              : current.coverLetterUploadFields.filter(
                                  (id) => id !== field.id,
                                ),
                          uploadsTouched: true,
                          savedPreparation: undefined,
                          savedSignature: undefined,
                        }))
                      }
                    />
                    Replace the attachment already in the application
                  </label>
                ) : null}
                <Select
                  value={
                    draft.uploadFields.includes(field.id)
                      ? "resume"
                      : draft.coverLetterUploadFields.includes(field.id)
                        ? "cover-letter"
                        : "none"
                  }
                  disabled={present && !draft.replaceFields.includes(field.id)}
                  onValueChange={(value) =>
                    update((current) => ({
                      ...current,
                      uploadFields: toggle(
                        current.uploadFields,
                        field.id,
                        value === "resume",
                      ),
                      coverLetterUploadFields: toggle(
                        current.coverLetterUploadFields,
                        field.id,
                        value === "cover-letter",
                      ),
                      uploadsTouched: true,
                      savedPreparation: undefined,
                      savedSignature: undefined,
                    }))
                  }
                >
                  <SelectTrigger
                    className="mt-3 w-full min-w-0 max-w-full [&_[data-slot=select-value]]:min-w-0"
                    aria-label={`Document to upload to ${field.label || field.id}`}
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">
                      Leave this file field unchanged
                    </SelectItem>
                    <SelectItem
                      value="resume"
                      disabled={!draft.resumeVersionId}
                    >
                      Attach selected résumé
                    </SelectItem>
                    <SelectItem
                      value="cover-letter"
                      disabled={!draft.coverLetterVersionId}
                    >
                      Attach selected cover letter
                    </SelectItem>
                  </SelectContent>
                </Select>
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
                  {field.history ? `${field.history.label} · ` : ""}
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
        <AnimatedIcon state={send.isPending}>
          {send.isPending ? <Spinner /> : <Send />}
        </AnimatedIcon>
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
  const params = useSearchParams();
  const [requestIntent] = useState(() => new RetainedRequestIntent());
  const [code, setCode] = useState<string>();
  const [selected, setSelected] = useState<string>();
  const selectedId = selected ?? params.get("snapshot");
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
  const selectedSnapshot = useQuery({
    queryKey: ["snapshot", selectedId],
    enabled: !!selectedId,
    queryFn: () => api<BrowserSnapshot>(`browser/snapshots/${selectedId}`),
  });
  const snapshot = selectedId ? selectedSnapshot.data : snapshots.data?.[0];
  const savedPreparation = useQuery({
    queryKey: ["snapshot-preparation", snapshot?.id],
    enabled: !!snapshot,
    queryFn: () =>
      api<ApplicationPreparation | null>(
        `browser/snapshots/${snapshot!.id}/preparation`,
      ),
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
    mutationFn: () => {
      const target = "browser/pairings";
      const body = { name: "My browser" };
      const intent = requestIntent.forRequest("POST", target, body);
      return api<{ code: string }>(target, {
        method: "POST",
        body,
        key: intent.key,
      });
    },
    onSuccess: (data) => {
      requestIntent.confirmRequest("POST", "browser/pairings", {
        name: "My browser",
      });
      setCode(data.code);
      void client.invalidateQueries({ queryKey: ["devices"] });
    },
    onError: (error) => toast.error(error.message),
  });
  const revoke = useMutation({
    mutationFn: (id: string) => {
      const target = `browser/devices/${id}/revoke`;
      const intent = requestIntent.forRequest("POST", target);
      return api(target, { method: "POST", key: intent.key });
    },
    onSuccess: (_result, id) => {
      requestIntent.confirmRequest("POST", `browser/devices/${id}/revoke`);
      void client.invalidateQueries();
      toast.success("Browser access revoked");
    },
    onError: (error) => toast.error(error.message),
  });
  const initialDraft = savedPreparation.data
    ? {
        ...mergePreparation(emptyDraft(null), savedPreparation.data),
        opportunityId: savedPreparation.data.opportunity_id,
        replaceFields: savedPreparation.data.replace_fields,
      }
    : emptyDraft(resumes.data?.default_version_id ?? null);
  const draft = snapshot ? (drafts[snapshot.id] ?? initialDraft) : undefined;
  const activeDevices =
    devices.data?.filter((device) => !device.revoked_at) ?? [];
  const updateDraft = snapshot
    ? (change: (current: Draft) => Draft) =>
        setDrafts((current) => ({
          ...current,
          [snapshot.id]: change(current[snapshot.id] ?? initialDraft),
        }))
    : undefined;

  return (
    <>
      <PageHeading
        title="Browser companion"
        description="Autofill job applications from your approved profile, keep drafts, and track the work here."
        action={
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" asChild>
              <Link href="/applications">Applications</Link>
            </Button>
            <Button onClick={() => pair.mutate()} disabled={pair.isPending}>
              <Plus /> Pair a browser
            </Button>
          </div>
        }
      />
      <div className="grid grid-cols-1 gap-6 px-5 md:px-9 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]">
        <section className="flex flex-col gap-5">
          <div className="rounded-xl shadow-surface bg-card p-6">
            <h2 className="text-lg font-medium">Get ready in three steps</h2>
            <ol className="mt-5 space-y-5 text-sm">
              <li className="flex gap-3">
                <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-muted text-xs">
                  1
                </span>
                <div>
                  <h3 className="font-medium">Add the extension to Chrome</h3>
                  <p className="mt-1 leading-6 text-muted-foreground">
                    Open <code>chrome://extensions</code>, turn on Developer
                    mode, choose Load unpacked, and select{" "}
                    <code>apps/extension</code>. Pin Command Center to your
                    toolbar.
                  </p>
                </div>
              </li>
              <li className="flex gap-3">
                <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-muted text-xs">
                  2
                </span>
                <div>
                  <h3 className="font-medium">Connect this browser</h3>
                  <p className="mt-1 leading-6 text-muted-foreground">
                    Choose Pair a browser above. Open the extension and paste
                    the one-time code.
                  </p>
                </div>
              </li>
              <li className="flex gap-3">
                <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-muted text-xs">
                  3
                </span>
                <div>
                  <h3 className="font-medium">
                    Open an application and autofill
                  </h3>
                  <p className="mt-1 leading-6 text-muted-foreground">
                    Click the extension icon on the application tab, choose your
                    résumé, then Autofill this page. Review the filled answers
                    before continuing.
                  </p>
                </div>
              </li>
            </ol>
            <div className="mt-5 flex flex-wrap gap-3 border-t border-border pt-4 text-sm">
              <Link href="/settings" className="underline underline-offset-4">
                Review profile facts
              </Link>
              <Link href="/documents" className="underline underline-offset-4">
                Upload a résumé
              </Link>
            </div>
            <details className="mt-5 text-sm">
              <summary className="cursor-pointer text-muted-foreground">
                Capture not working?
              </summary>
              <p className="mt-2 leading-6 text-muted-foreground">
                In the extension’s Capture settings, choose This browser for
                your regular Chrome window. Click the extension icon again after
                changing tabs to grant access. Open the actual application form
                before filling.
              </p>
              <p className="mt-2 leading-6 text-muted-foreground">
                AgentBrowser is an advanced option for the dedicated browser
                opened with <code>make companion-browser</code>. It requires the
                local helper. Next and Submit remain yours.
              </p>
            </details>
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
          <div className="rounded-xl shadow-surface bg-card p-5">
            <h2 className="mb-4 text-sm font-medium">Paired browsers</h2>
            {devices.error ? (
              <ErrorState
                error={devices.error}
                retry={() => void devices.refetch()}
              />
            ) : null}
            {devices.isPending && !devices.data ? (
              <LoadingRows />
            ) : activeDevices.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                No browser paired yet.
              </p>
            ) : (
              activeDevices.map((device) => (
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
          <div className="rounded-xl shadow-surface bg-card p-5">
            <h2 className="mb-3 text-sm font-medium">Recent fill proposals</h2>
            {commands.error ? (
              <ErrorState
                error={commands.error}
                retry={() => void commands.refetch()}
              />
            ) : null}
            {commands.isPending && !commands.data ? (
              <p className="text-xs text-muted-foreground" role="status">
                Loading fill proposals…
              </p>
            ) : null}
            {commands.data?.map((command) => (
              <div
                className="border-b border-border py-3 last:border-0"
                key={command.id}
              >
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
        <section className="rounded-xl shadow-surface bg-card p-6">
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
          {snapshots.error ||
          selectedSnapshot.error ||
          savedPreparation.error ||
          resumes.error ||
          opportunities.error ? (
            <ErrorState
              error={
                snapshots.error ??
                selectedSnapshot.error ??
                savedPreparation.error ??
                resumes.error ??
                opportunities.error!
              }
              retry={() => {
                void snapshots.refetch();
                void resumes.refetch();
                void opportunities.refetch();
                if (selectedId) void selectedSnapshot.refetch();
                if (snapshot) void savedPreparation.refetch();
              }}
            />
          ) : snapshot &&
            draft &&
            updateDraft &&
            resumes.data &&
            !savedPreparation.isPending ? (
            <>
              {snapshots.data && snapshots.data.length > 1 ? (
                <Select value={snapshot.id} onValueChange={setSelected}>
                  <SelectTrigger className="mb-6" aria-label="Shared form">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      {[
                        ...(snapshots.data.some(
                          (item) => item.id === snapshot.id,
                        )
                          ? []
                          : [snapshot]),
                        ...snapshots.data,
                      ].map((item) => (
                        <SelectItem key={item.id} value={item.id}>
                          {item.title || item.origin}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              ) : null}
              <PreparationForm
                key={snapshot.id}
                snapshot={snapshot}
                draft={draft}
                resumes={resumes.data}
                opportunities={opportunities.data?.items ?? []}
                update={updateDraft}
              />
            </>
          ) : snapshots.isPending ||
            resumes.isPending ||
            (selectedId && selectedSnapshot.isPending) ||
            (snapshot && savedPreparation.isPending) ? (
            <div className="flex min-h-40 items-center justify-center">
              <Spinner />
            </div>
          ) : (
            <EmptyState
              title="A little help, right where you need it"
              description="Open a job application, click the companion and choose Autofill this page. Its saved preparation and task will appear here."
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
