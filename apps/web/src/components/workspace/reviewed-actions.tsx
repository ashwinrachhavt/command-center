"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  FileCheck,
  Pencil,
  Plus,
  RefreshCw,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  api,
  apiDownload,
  dateLabel,
  label,
  type Page,
  type Schema,
} from "@/lib/api";
import {
  EmptyState,
  ErrorState,
  LoadingRows,
  PageHeading,
  Spinner,
  Status,
} from "./primitives";

type Action = Schema["ActionRead"];
type Account = Schema["AccountRead"];
type Kind = Schema["ActionCreate"]["payload"]["kind"];
const selectStyle =
  "h-9 w-full rounded-md border border-input bg-background px-3 text-sm";
const kinds: Record<Kind, { title: string; toolkit: string }> = {
  gmail_send: { title: "Send an email", toolkit: "gmail" },
  calendar_create: {
    title: "Create a calendar event",
    toolkit: "googlecalendar",
  },
  calendar_update: {
    title: "Update a calendar event",
    toolkit: "googlecalendar",
  },
  linear_create: { title: "Create a Linear issue", toolkit: "linear" },
  linear_update: { title: "Update a Linear issue", toolkit: "linear" },
  notion_publish: { title: "Publish a Notion page", toolkit: "notion" },
  notion_update: { title: "Update a Notion page", toolkit: "notion" },
};
type FormField = {
  key: string;
  title: string;
  required?: boolean;
  format?: "list" | "number" | "text" | "boolean";
  hint?: string;
};
const fields: Record<Kind, FormField[]> = {
  gmail_send: [
    { key: "to", title: "To", required: true, format: "list" },
    { key: "cc", title: "Cc", format: "list" },
    { key: "bcc", title: "Bcc", format: "list" },
    { key: "subject", title: "Subject", required: true },
    { key: "body", title: "Message", format: "text", required: true },
  ],
  calendar_create: [
    { key: "calendar_id", title: "Calendar ID", required: true },
    { key: "summary", title: "Event title", required: true },
    { key: "description", title: "Description", format: "text" },
    {
      key: "start_at",
      title: "Start",
      required: true,
      hint: "Include a timezone offset, e.g. 2026-09-24T10:00:00-07:00",
    },
    { key: "end_at", title: "End", required: true },
    {
      key: "timezone",
      title: "Timezone",
      required: true,
      hint: "For example, America/Los_Angeles",
    },
    { key: "attendees", title: "Attendee emails", format: "list" },
    {
      key: "send_updates",
      title: "Notify attendees",
      required: true,
      hint: "all, externalOnly, or none",
    },
    {
      key: "create_meeting_room",
      title: "Create meeting room",
      format: "boolean",
    },
  ],
  calendar_update: [
    { key: "calendar_id", title: "Calendar ID", required: true },
    { key: "event_id", title: "Event ID", required: true },
    { key: "summary", title: "Event title" },
    { key: "description", title: "Description", format: "text" },
    {
      key: "start_at",
      title: "Start",
      hint: "Change start and end together; include a timezone offset.",
    },
    { key: "end_at", title: "End" },
    { key: "timezone", title: "Timezone" },
    { key: "attendees", title: "Attendee emails", format: "list" },
    {
      key: "send_updates",
      title: "Notify attendees",
      hint: "all, externalOnly, or none",
    },
  ],
  linear_create: [
    { key: "team_id", title: "Team ID", required: true },
    { key: "title", title: "Issue title", required: true },
    { key: "description", title: "Description", format: "text" },
    { key: "priority", title: "Priority (0–4)", format: "number" },
    { key: "due_date", title: "Due date", hint: "YYYY-MM-DD" },
    { key: "assignee_id", title: "Assignee ID" },
    { key: "state_id", title: "Status ID" },
    { key: "label_ids", title: "Label IDs", format: "list" },
  ],
  linear_update: [
    { key: "issue_id", title: "Issue ID", required: true },
    { key: "title", title: "Issue title" },
    { key: "description", title: "Description", format: "text" },
    { key: "priority", title: "Priority (0–4)", format: "number" },
    { key: "due_date", title: "Due date", hint: "YYYY-MM-DD" },
    { key: "assignee_id", title: "Assignee ID" },
    { key: "state_id", title: "Status ID" },
    { key: "label_ids", title: "Label IDs", format: "list" },
  ],
  notion_publish: [
    { key: "parent_id", title: "Parent page ID", required: true },
    { key: "title", title: "Page title", required: true },
  ],
  notion_update: [{ key: "page_id", title: "Page ID", required: true }],
};

function VersionPicker({
  choose,
}: {
  choose: (version: Schema["VersionRead"], title: string) => void;
}) {
  const [artifactId, setArtifactId] = useState("");
  const [versionId, setVersionId] = useState("");
  const artifacts = useQuery({
    queryKey: ["action-artifacts"],
    queryFn: () => api<Page<Schema["ArtifactRead"]>>("artifacts?limit=100"),
  });
  const versions = useQuery({
    queryKey: ["versions", artifactId],
    queryFn: () =>
      api<Schema["VersionRead"][]>(`artifacts/${artifactId}/versions`),
    enabled: !!artifactId,
  });
  return (
    <div className="flex flex-wrap gap-2">
      <select
        aria-label="Source artifact"
        className={`${selectStyle} flex-1`}
        value={artifactId}
        onChange={(e) => {
          setArtifactId(e.target.value);
          setVersionId("");
        }}
      >
        <option value="">Choose artifact</option>
        {artifacts.data?.items.map((artifact) => (
          <option key={artifact.id} value={artifact.id}>
            {artifact.title}
          </option>
        ))}
      </select>
      <select
        aria-label="Exact artifact version"
        className={`${selectStyle} flex-1`}
        value={versionId}
        disabled={!artifactId}
        onChange={(e) => setVersionId(e.target.value)}
      >
        <option value="">Choose version</option>
        {versions.data?.map((version) => (
          <option key={version.id} value={version.id}>
            Version {version.version} · {dateLabel(version.created_at)}
          </option>
        ))}
      </select>
      <Button
        type="button"
        variant="outline"
        disabled={!versionId}
        onClick={() => {
          const version = versions.data?.find((item) => item.id === versionId);
          if (version)
            choose(
              version,
              artifacts.data?.items.find((item) => item.id === artifactId)
                ?.title ?? "Artifact",
            );
        }}
      >
        Use version
      </Button>
      {(artifacts.error || versions.error) && (
        <p role="alert" className="w-full text-xs text-destructive">
          {(artifacts.error ?? versions.error)?.message}
        </p>
      )}
    </div>
  );
}

function ActionEditor({
  existing,
  close,
}: {
  existing?: Action;
  close: () => void;
}) {
  const client = useQueryClient();
  const [kind, setKind] = useState<Kind>(
    (existing?.kind as Kind) ?? "gmail_send",
  );
  const [accountId, setAccountId] = useState(existing?.account.id ?? "");
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      Object.entries(
        existing?.current.payload ?? {
          calendar_id: "primary",
          send_updates: "all",
        },
      ).map(([key, value]) => [
        key,
        Array.isArray(value)
          ? value.join(", ")
          : value === null
            ? ""
            : String(value),
      ]),
    ),
  );
  const [source, setSource] = useState(
    existing?.current.source_version_id ?? "",
  );
  const [sourceTitle, setSourceTitle] = useState(
    source ? `Version ${source.slice(0, 8)}` : "",
  );
  const [attachments, setAttachments] = useState(
    (existing?.current.attachments ?? []).map((item) => ({
      id: item.artifact_version_id,
      title: `Version ${item.artifact_version_id.slice(0, 8)}`,
    })),
  );
  const [reason, setReason] = useState(existing?.current.reason ?? "");
  const [picking, setPicking] = useState<"source" | "attachment" | null>(null);
  const key = useRef({ signature: "", value: "" });
  const accounts = useQuery({
    queryKey: ["connected-accounts"],
    queryFn: () => api<Account[]>("integrations/composio/accounts"),
  });
  const save = useMutation({
    mutationFn: () => {
      const payload: Record<string, unknown> = {
        ...(existing?.current.payload ?? {}),
        kind,
      };
      for (const field of fields[kind]) {
        const value = values[field.key] ?? "";
        if (!value && !field.required) {
          delete payload[field.key];
          continue;
        }
        payload[field.key] =
          field.format === "list"
            ? value
                .split(",")
                .map((item) => item.trim())
                .filter(Boolean)
            : field.format === "number"
              ? Number(value)
              : field.format === "boolean"
                ? value === "true"
                : value;
      }
      const body = {
        payload,
        source_version_id: source || null,
        attachment_version_ids: attachments.map((item) => item.id),
        reason,
        ...(existing
          ? { expected_version: existing.row_version }
          : { account_id: accountId }),
      };
      const signature = JSON.stringify(body);
      if (signature !== key.current.signature)
        key.current = { signature, value: crypto.randomUUID() };
      return api<Action>(
        existing ? `reviewed-actions/${existing.id}` : "reviewed-actions",
        { method: existing ? "PATCH" : "POST", body, key: key.current.value },
      );
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["reviewed-actions"] });
      close();
      toast.success("Proposal saved for review");
    },
  });
  return (
    <Dialog open onOpenChange={(open) => !open && close()}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {existing ? "Edit proposal" : "New connected action"}
          </DialogTitle>
          <DialogDescription>
            Save an exact proposal, then review it before execution. Edits
            require a fresh approval.
          </DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <Field>
            <FieldLabel htmlFor="action-kind">Action</FieldLabel>
            <select
              id="action-kind"
              className={selectStyle}
              disabled={!!existing}
              value={kind}
              onChange={(e) => {
                setKind(e.target.value as Kind);
                setAccountId("");
                setValues({ calendar_id: "primary", send_updates: "all" });
                setSource("");
                setAttachments([]);
              }}
            >
              {Object.entries(kinds).map(([key, value]) => (
                <option key={key} value={key}>
                  {value.title}
                </option>
              ))}
            </select>
          </Field>
          <Field>
            <FieldLabel htmlFor="action-account">Account</FieldLabel>
            <select
              id="action-account"
              className={selectStyle}
              disabled={!!existing}
              value={accountId}
              required
              onChange={(e) => setAccountId(e.target.value)}
            >
              <option value="">Choose a verified account</option>
              {accounts.data
                ?.filter(
                  (account) =>
                    account.toolkit === kinds[kind].toolkit &&
                    account.connection_status === "ACTIVE",
                )
                .map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.display_name}
                    {account.selected_purpose ? " · outreach" : ""}
                  </option>
                ))}
            </select>
          </Field>
          {accounts.error && <ErrorState error={accounts.error} />}
          {fields[kind].map((field) => (
            <Field key={field.key}>
              <FieldLabel htmlFor={`action-${field.key}`}>
                {field.title}
              </FieldLabel>
              {field.format === "text" ? (
                <Textarea
                  id={`action-${field.key}`}
                  rows={6}
                  required={field.required}
                  value={values[field.key] ?? ""}
                  onChange={(e) =>
                    setValues({ ...values, [field.key]: e.target.value })
                  }
                />
              ) : field.format === "boolean" ? (
                <input
                  id={`action-${field.key}`}
                  type="checkbox"
                  checked={values[field.key] === "true"}
                  onChange={(e) =>
                    setValues({
                      ...values,
                      [field.key]: String(e.target.checked),
                    })
                  }
                />
              ) : (
                <Input
                  id={`action-${field.key}`}
                  required={field.required}
                  value={values[field.key] ?? ""}
                  placeholder={
                    field.format === "list"
                      ? "Separate values with commas"
                      : undefined
                  }
                  onChange={(e) =>
                    setValues({ ...values, [field.key]: e.target.value })
                  }
                />
              )}
              {field.hint && (
                <p className="text-xs text-muted-foreground">{field.hint}</p>
              )}
            </Field>
          ))}
          <div className="space-y-3 rounded-lg border border-border p-4">
            <p className="text-sm font-medium">Exact source & attachments</p>
            <p className="text-xs text-muted-foreground">
              Notion publishes the selected source text. Attachments use the
              exact file version selected here.
            </p>
            {source && (
              <p className="flex items-center justify-between text-sm">
                Source: {sourceTitle}
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label="Remove source"
                  onClick={() => setSource("")}
                >
                  <X />
                </Button>
              </p>
            )}
            {attachments.map((item) => (
              <p
                key={item.id}
                className="flex items-center justify-between text-sm"
              >
                {item.title}
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label={`Remove ${item.title}`}
                  onClick={() =>
                    setAttachments(
                      attachments.filter(
                        (attachment) => attachment.id !== item.id,
                      ),
                    )
                  }
                >
                  <X />
                </Button>
              </p>
            ))}
            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setPicking("source")}
              >
                Choose source
              </Button>
              {kind === "gmail_send" && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setPicking("attachment")}
                >
                  Attach file version
                </Button>
              )}
            </div>
            {picking && (
              <VersionPicker
                choose={(version, title) => {
                  if (picking === "source") {
                    setSource(version.id);
                    setSourceTitle(`${title} · v${version.version}`);
                  } else if (
                    !attachments.some((item) => item.id === version.id)
                  )
                    setAttachments([
                      ...attachments,
                      {
                        id: version.id,
                        title: `${title} · v${version.version}`,
                      },
                    ]);
                  setPicking(null);
                }}
              />
            )}
          </div>
          <Field>
            <FieldLabel htmlFor="proposal-reason">Reason</FieldLabel>
            <Textarea
              id="proposal-reason"
              required
              maxLength={2000}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </Field>
          {save.error && (
            <p role="alert" className="text-sm text-destructive">
              {save.error.message}
            </p>
          )}
          <Button disabled={save.isPending}>
            {save.isPending ? <Spinner /> : <FileCheck />}Save proposal
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function SourcePreview({
  versionId,
  onReady,
}: {
  versionId: string;
  onReady: (id: string | null) => void;
}) {
  const source = useQuery({
    queryKey: ["action-source", versionId],
    queryFn: async () => {
      let offset = 0,
        text = "",
        first: Schema["DocumentTextRead"] | undefined;
      while (true) {
        const page = await api<Schema["DocumentTextRead"]>(
          `documents/versions/${versionId}/text?offset=${offset}&limit=12000`,
        );
        first ??= page;
        text += page.text;
        if (page.next_offset === null) return { ...first, text };
        offset = page.next_offset;
      }
    },
  });
  useEffect(() => {
    onReady(source.data && !source.error ? versionId : null);
  }, [source.data, source.error, versionId, onReady]);
  return (
    <div className="rounded-lg border border-border p-4">
      {source.error ? (
        <ErrorState error={source.error} />
      ) : !source.data ? (
        <LoadingRows />
      ) : (
        <>
          <Link
            href={`/artifacts?inspect=artifacts:${source.data.artifact_id}:content:${versionId}`}
            className="text-sm font-medium underline underline-offset-4"
          >
            {source.data.title}
          </Link>
          <p className="mt-1 text-xs text-muted-foreground">
            Exact source version {versionId.slice(0, 8)}
          </p>
          <pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-words font-sans text-sm leading-6">
            {source.data.text}
          </pre>
        </>
      )}
    </div>
  );
}

function ActionReview({
  initial,
  close,
}: {
  initial: Action;
  close: () => void;
}) {
  const client = useQueryClient();
  const action = useQuery({
    queryKey: ["reviewed-actions", initial.id],
    queryFn: () => api<Action>(`reviewed-actions/${initial.id}`),
    initialData: initial,
    staleTime: 0,
    refetchInterval: (query) =>
      ["queued", "running"].includes(query.state.data?.state ?? "")
        ? 2000
        : false,
  });
  const current = action.data;
  const [editing, setEditing] = useState(false);
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState<string | null>(null);
  const [readySource, setReadySource] = useState<string | null>(null);
  const sourceReady = useCallback(
    (id: string | null) => setReadySource(id),
    [],
  );
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const review = useMutation({
    mutationFn: (decision: "approved" | "rejected" | "revoked") =>
      api<Action>(`reviewed-actions/${current.id}/reviews`, {
        method: "POST",
        body: {
          expected_version: current.row_version,
          revision_id: current.current.id,
          decision,
          reason,
        },
      }),
    onSuccess: () => {
      setConfirmed(null);
      void client.invalidateQueries({ queryKey: ["reviewed-actions"] });
      toast.success("Review recorded");
    },
    onError: () => {
      setConfirmed(null);
      void action.refetch();
    },
  });
  const reconcile = useMutation({
    mutationFn: () =>
      api(`reviewed-actions/${current.id}/reconcile`, {
        method: "POST",
        body: { expected_version: current.row_version },
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["reviewed-actions"] });
      toast.success("Provider receipt checked");
    },
  });
  if (editing)
    return <ActionEditor existing={current} close={() => setEditing(false)} />;
  const canReview = current.state === "proposed";
  const title = kinds[current.kind as Kind]?.title ?? label(current.kind);
  return (
    <Dialog open onOpenChange={(open) => !open && close()}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            Review version {current.current.version} for{" "}
            {current.account.display_name}. Approval queues exactly this
            revision.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-wrap items-center gap-2">
          <Status value={current.state} />
          <Badge variant="outline">{label(current.account.toolkit)}</Badge>
          {canReview && (
            <Button
              size="sm"
              variant="outline"
              className="ml-auto"
              onClick={() => setEditing(true)}
            >
              <Pencil />
              Edit proposal
            </Button>
          )}
        </div>
        <div className="rounded-lg border border-border p-4">
          <p className="text-xs text-muted-foreground">Verified account</p>
          <p className="mt-1 text-sm font-medium">
            {current.account.display_name}
          </p>
          {Object.entries(current.account.provider_identity).map(
            ([key, value]) => (
              <p
                key={key}
                className="mt-1 break-all text-xs text-muted-foreground"
              >
                {label(key)}:{" "}
                {typeof value === "object"
                  ? JSON.stringify(value)
                  : String(value)}
              </p>
            ),
          )}
        </div>
        <dl className="space-y-4">
          {Object.entries(current.current.payload)
            .filter(
              ([key, value]) =>
                key !== "kind" &&
                value !== null &&
                value !== "" &&
                (!Array.isArray(value) || value.length),
            )
            .map(([key, value]) => (
              <div key={key}>
                <dt className="mb-1 text-xs font-medium text-muted-foreground">
                  {fields[current.kind as Kind]?.find(
                    (field) => field.key === key,
                  )?.title ??
                    (key === "is_html" ? "Message format" : label(key))}
                </dt>
                <dd className="max-h-96 overflow-auto whitespace-pre-wrap break-words text-sm leading-6">
                  {Array.isArray(value)
                    ? value.join(", ")
                    : typeof value === "boolean"
                      ? key === "is_html"
                        ? value
                          ? "HTML"
                          : "Plain text"
                        : value
                          ? "Yes"
                          : "No"
                      : String(value)}
                </dd>
              </div>
            ))}
        </dl>
        {current.current.source_version_id && (
          <SourcePreview
            versionId={current.current.source_version_id}
            onReady={sourceReady}
          />
        )}
        {!!current.current.attachments.length && (
          <div className="space-y-2">
            <h3 className="text-sm font-medium">Attachments</h3>
            {current.current.attachments.map((attachment) => (
              <div
                key={attachment.artifact_version_id}
                className="rounded-lg border border-border p-3"
              >
                <p className="text-sm">
                  {attachment.filename} · {attachment.media_type} · version{" "}
                  {attachment.artifact_version_id.slice(0, 8)}
                </p>
                <p className="mt-1 break-all font-mono text-[10px] text-muted-foreground">
                  SHA-256 {attachment.content_sha256}
                </p>
                {"artifact_id" in attachment &&
                  typeof attachment.artifact_id === "string" && (
                    <Button
                      size="sm"
                      variant="outline"
                      className="mt-2"
                      onClick={() => {
                        setDownloadError(null);
                        void apiDownload(
                          `artifacts/${attachment.artifact_id}/versions/${attachment.artifact_version_id}/download`,
                        ).catch((error) => setDownloadError(error.message));
                      }}
                    >
                      Open exact attachment
                    </Button>
                  )}
              </div>
            ))}
          </div>
        )}
        {downloadError && (
          <p role="alert" className="text-sm text-destructive">
            {downloadError}
          </p>
        )}
        {current.conditional_update_notice && (
          <p className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-sm">
            {current.conditional_update_notice}
          </p>
        )}
        {current.current.expires_at && (
          <p className="text-xs text-muted-foreground">
            Approval expires {dateLabel(current.current.expires_at)}
          </p>
        )}
        <p className="text-sm text-muted-foreground">
          Reason: {current.current.reason}
        </p>
        {current.attempt && (
          <div className="space-y-2 rounded-lg border border-border p-4">
            <h3 className="text-sm font-medium">Execution receipt</h3>
            <Status value={current.attempt.state} />
            {current.attempt.error_code && (
              <p className="text-sm">{label(current.attempt.error_code)}</p>
            )}
            {current.attempt.provider_external_id && (
              <p className="break-all text-xs">
                Provider record: {current.attempt.provider_external_id}
              </p>
            )}
            {current.attempt.provider_log_id && (
              <p className="break-all text-xs">
                Receipt: {current.attempt.provider_log_id}
              </p>
            )}
            {current.attempt.receipt && (
              <pre className="max-h-60 overflow-auto whitespace-pre-wrap text-xs">
                {JSON.stringify(current.attempt.receipt, null, 2)}
              </pre>
            )}
          </div>
        )}
        {["outcome_unknown", "partial"].includes(current.state) && (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              The provider outcome is uncertain. Check its receipt before taking
              further action; this action will not be resent.
            </p>
            <Button
              variant="outline"
              disabled={reconcile.isPending}
              onClick={() => reconcile.mutate()}
            >
              {reconcile.isPending ? <Spinner /> : <RefreshCw />}Check provider
              receipt
            </Button>
          </div>
        )}
        {(canReview || current.state === "queued") && (
          <div className="space-y-3 border-t border-border pt-4">
            <Field>
              <FieldLabel htmlFor="review-reason">Review reason</FieldLabel>
              <Input
                id="review-reason"
                value={reason}
                maxLength={2000}
                onChange={(e) => setReason(e.target.value)}
              />
            </Field>
            {canReview && (
              <label className="flex items-start gap-2 text-sm leading-5">
                <input
                  className="mt-1"
                  type="checkbox"
                  checked={confirmed === current.current.id}
                  onChange={(e) =>
                    setConfirmed(e.target.checked ? current.current.id : null)
                  }
                />
                I reviewed this account, content, source and attachments, and
                authorize this exact action.
              </label>
            )}
            <div className="flex flex-wrap gap-2">
              {canReview ? (
                <>
                  <Button
                    disabled={
                      review.isPending ||
                      confirmed !== current.current.id ||
                      action.isFetching ||
                      !!action.error ||
                      (!!current.current.source_version_id &&
                        readySource !== current.current.source_version_id) ||
                      !reason.trim()
                    }
                    onClick={() => review.mutate("approved")}
                  >
                    <Check />
                    Approve & queue
                  </Button>
                  <Button
                    variant="outline"
                    disabled={review.isPending || !reason.trim()}
                    onClick={() => review.mutate("rejected")}
                  >
                    <X />
                    Reject
                  </Button>
                </>
              ) : (
                <Button
                  variant="outline"
                  disabled={review.isPending || !reason.trim()}
                  onClick={() => review.mutate("revoked")}
                >
                  Revoke approval
                </Button>
              )}
            </div>
          </div>
        )}
        {(review.error || reconcile.error || action.error) && (
          <p role="alert" className="text-sm text-destructive">
            {(review.error ?? reconcile.error ?? action.error)?.message}
          </p>
        )}
      </DialogContent>
    </Dialog>
  );
}

export function ReviewedActions() {
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<Action | null>(null);
  const [creating, setCreating] = useState(false);
  const actions = useQuery({
    queryKey: ["reviewed-actions", "list", offset],
    queryFn: () =>
      api<Page<Action>>(`reviewed-actions?offset=${offset}&limit=20`),
    refetchInterval: 10000,
  });
  return (
    <>
      <PageHeading
        title="Reviewed actions"
        description="Decide exactly what your connected apps will do."
        action={
          <Button onClick={() => setCreating(true)}>
            <Plus />
            New proposal
          </Button>
        }
      />
      <div className="mx-5 space-y-4 md:mx-9">
        {actions.error ? (
          <ErrorState error={actions.error} />
        ) : actions.isPending ? (
          <LoadingRows />
        ) : !actions.data.items.length ? (
          <EmptyState
            title="Nothing awaiting review"
            description="Ask your assistant to draft an email, calendar event, Linear issue or Notion page, or create a proposal here."
          />
        ) : (
          <>
            <div className="overflow-hidden rounded-xl border border-border">
              {actions.data.items.map((action) => (
                <button
                  type="button"
                  key={action.id}
                  className="flex w-full items-center justify-between gap-4 border-b border-border bg-card p-5 text-left last:border-0 hover:bg-muted/50"
                  onClick={() => setSelected(action)}
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">
                      {String(
                        action.current.payload.subject ||
                          action.current.payload.title ||
                          action.current.payload.summary ||
                          kinds[action.kind as Kind]?.title ||
                          label(action.kind),
                      )}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {action.account.display_name} · v{action.current.version}{" "}
                      · {dateLabel(action.updated_at)}
                    </p>
                  </div>
                  <Status value={action.state} />
                </button>
              ))}
            </div>
            <div className="flex items-center justify-between">
              <p className="text-xs text-muted-foreground">
                {actions.data.total} actions
              </p>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="icon"
                  aria-label="Previous actions"
                  disabled={!offset}
                  onClick={() => setOffset(Math.max(0, offset - 20))}
                >
                  <ChevronLeft />
                </Button>
                <Button
                  variant="outline"
                  size="icon"
                  aria-label="Next actions"
                  disabled={offset + 20 >= actions.data.total}
                  onClick={() => setOffset(offset + 20)}
                >
                  <ChevronRight />
                </Button>
              </div>
            </div>
          </>
        )}
      </div>
      {selected && (
        <ActionReview initial={selected} close={() => setSelected(null)} />
      )}
      {creating && <ActionEditor close={() => setCreating(false)} />}
    </>
  );
}
