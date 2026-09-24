"use client";

import Link from "next/link";
import { useAuth } from "@clerk/nextjs";
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
import { RichWriter } from "@/components/writing/rich-writer";
import { EmailPreview } from "@/components/writing/email-preview";
import { DraftStatus } from "@/components/writing/draft-status";
import { useWorkingDraft } from "@/components/writing/use-working-draft";
import { MailPull } from "./mail-pull";
import {
  EmailDeliveryFields,
  emailDelivery,
  emailTiming,
  sendTimeLabel,
  type EmailTiming,
} from "./email-delivery";
import { useArtifactHistory } from "@/components/writing/use-artifact-history";
import {
  api,
  ApiError,
  apiDownload,
  dateLabel,
  label,
  type Page,
  type Schema,
} from "@/lib/api";
import {
  canStartFreshConnectedRequest,
  RetainedRequestIntent,
} from "@/lib/retained-intent";
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
  linkedin_post: { title: "Publish a LinkedIn post", toolkit: "linkedin" },
};
type FormField = {
  key: string;
  title: string;
  required?: boolean;
  format?: "list" | "number" | "text" | "boolean";
  hint?: string;
  options?: { value: string; label: string }[];
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
  linkedin_post: [
    {
      key: "commentary",
      title: "Post text",
      format: "text",
      required: true,
      hint: "Up to 3,000 characters. Publishes as the selected LinkedIn member.",
    },
    {
      key: "visibility",
      title: "Audience",
      options: [
        { value: "PUBLIC", label: "Anyone" },
        { value: "CONNECTIONS", label: "Connections only" },
      ],
    },
  ],
};

function VersionPicker({
  choose,
}: {
  choose: (version: Schema["VersionSummary"], title: string) => void;
}) {
  const [artifactId, setArtifactId] = useState("");
  const [versionId, setVersionId] = useState("");
  const artifacts = useQuery({
    queryKey: ["action-artifacts"],
    queryFn: () => api<Page<Schema["ArtifactRead"]>>("artifacts?limit=100"),
  });
  const versions = useArtifactHistory(artifactId);
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
        {versions.items.map((version) => (
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
          const version = versions.items.find((item) => item.id === versionId);
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
      {versions.hasNextPage && (
        <Button
          type="button"
          size="sm"
          variant="ghost"
          disabled={versions.isFetchingNextPage}
          onClick={() => void versions.fetchNextPage()}
        >
          Load older versions
        </Button>
      )}
      {(artifacts.error || versions.error) && (
        <p role="alert" className="w-full text-xs text-destructive">
          {(artifacts.error ?? versions.error)?.message}
        </p>
      )}
    </div>
  );
}

export function ActionEditor({
  existing,
  seed,
  close,
  onSaved,
}: {
  existing?: Action;
  seed?: {
    sourceVersionId: string;
    sourceTitle: string;
    values: Record<string, string>;
  };
  close: () => void;
  onSaved?: (action: Action) => void;
}) {
  const { isLoaded, userId } = useAuth();
  if (!isLoaded || !userId) return <p role="status">Opening your writer…</p>;
  return (
    <ActionEditorForm
      key={`${userId}-${existing?.id ?? seed?.sourceVersionId ?? "new"}`}
      actor={userId}
      existing={existing}
      seed={seed}
      close={close}
      onSaved={onSaved}
    />
  );
}

type ActionDraft = {
  kind: Kind;
  accountId: string;
  targetId: string;
  baseVersion: number;
  values: Record<string, string>;
  source: string;
  sourceTitle: string;
  attachments: { id: string; title: string }[];
  reason: string;
  timing?: EmailTiming;
};

function ActionEditorForm({
  actor,
  existing,
  seed,
  close,
  onSaved,
}: {
  actor: string;
  existing?: Action;
  seed?: {
    sourceVersionId: string;
    sourceTitle: string;
    values: Record<string, string>;
  };
  close: () => void;
  onSaved?: (action: Action) => void;
}) {
  const client = useQueryClient();
  const writing = useWorkingDraft<ActionDraft>(
    actor,
    existing
      ? `action-${existing.id}`
      : seed
        ? `action-from-${seed.sourceVersionId}`
        : "action-new",
    {
      kind: (existing?.kind as Kind) ?? "gmail_send",
      accountId: existing?.account.id ?? "",
      targetId: existing?.id ?? "",
      baseVersion: existing?.row_version ?? 0,
      values: Object.fromEntries(
        Object.entries(
          existing?.current.payload ??
            seed?.values ?? {
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
      source:
        existing?.current.source_version_id ?? seed?.sourceVersionId ?? "",
      sourceTitle: existing?.current.source_version_id
        ? `Version ${existing.current.source_version_id.slice(0, 8)}`
        : (seed?.sourceTitle ?? ""),
      attachments: (existing?.current.attachments ?? []).map((item) => ({
        id: item.artifact_version_id,
        title: `Version ${item.artifact_version_id.slice(0, 8)}`,
      })),
      reason: existing?.current.reason ?? "Prepared for review",
      timing: emailTiming(existing?.current.delivery),
    },
  );
  const { draft } = writing;
  const {
    kind,
    accountId,
    values,
    source,
    sourceTitle,
    attachments,
    reason,
    targetId,
  } = writing.data;
  function set<K extends keyof ActionDraft>(key: K, value: ActionDraft[K]) {
    draft.edit((current) => ({ ...current, [key]: value }));
  }
  const setKind = (value: Kind) => set("kind", value);
  const setAccountId = (value: string) => set("accountId", value);
  const setValues = (value: Record<string, string>) => set("values", value);
  const setSource = (value: string) => set("source", value);
  const setSourceTitle = (value: string) => set("sourceTitle", value);
  const setAttachments = (value: ActionDraft["attachments"]) =>
    set("attachments", value);
  const setReason = (value: string) => set("reason", value);
  const [picking, setPicking] = useState<"source" | "attachment" | null>(null);
  const [showCopies, setShowCopies] = useState(false);
  const accounts = useQuery({
    queryKey: ["connected-accounts"],
    queryFn: () => api<Account[]>("integrations/composio/accounts"),
  });
  const accountInitialized = useRef(false);
  useEffect(() => {
    if (
      accountInitialized.current ||
      writing.status === "loading" ||
      !accounts.data
    )
      return;
    // Initialize once: clearing a saved working draft must not create a new edit.
    accountInitialized.current = true;
    if (targetId || accountId || kind !== "gmail_send") return;
    const selected = accounts.data?.find(
      (item) =>
        item.toolkit === "gmail" &&
        item.selected_purpose === "outreach" &&
        item.connection_status === "ACTIVE",
    );
    if (selected)
      draft.edit((current) => ({
        ...current,
        accountId: current.accountId || selected.id,
      }));
  }, [accounts.data, accountId, draft, kind, targetId, writing.status]);
  const save = useMutation({
    mutationFn: async () => {
      const snapshot = draft.getSnapshot().data;
      const { kind, values, source, attachments, reason, accountId } = snapshot;
      if (
        kind === "gmail_send" &&
        !(values.body ?? "").replace(/<[^>]*>/g, "").trim()
      )
        throw new Error("Write a message before saving this proposal.");
      await draft.flush();
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
      if (kind === "gmail_send") payload.is_html = values.is_html === "true";
      const body = {
        payload,
        delivery: kind === "gmail_send" ? emailDelivery(snapshot.timing) : null,
        expires_at: existing?.current.expires_at ?? null,
        source_version_id: source || null,
        attachment_version_ids: attachments.map((item) => item.id),
        reason,
        ...(snapshot.targetId
          ? { expected_version: snapshot.baseVersion }
          : { account_id: accountId }),
      };
      const target = snapshot.targetId
        ? `reviewed-actions/${snapshot.targetId}`
        : "reviewed-actions";
      const method = snapshot.targetId ? "PATCH" : "POST";
      const request = draft.request(method, target, body, snapshot);
      return api<Action>(request.target, {
        method: request.method,
        body: request.body,
        key: request.key,
      }).then((result) => ({ result, snapshot: request.snapshot }));
    },
    onError: (error) => {
      if (error instanceof ApiError && [400, 413, 422].includes(error.status))
        draft.resetIntent();
    },
    onSuccess: async ({ result, snapshot }) => {
      void client.invalidateQueries({ queryKey: ["reviewed-actions"] });
      try {
        if (await draft.clearIfUnchanged(snapshot)) {
          draft.resetIntent();
          close();
          onSaved?.(result);
          toast.success("Proposal saved for review");
        } else {
          draft.resetIntent();
          draft.edit((current) => ({
            ...current,
            ...(current.kind === snapshot.kind &&
            current.accountId === snapshot.accountId
              ? { targetId: result.id, baseVersion: result.row_version }
              : {}),
          }));
          toast.success(
            "Proposal saved. Your newer writing remains in the draft.",
          );
        }
      } catch {
        toast.message(
          "Proposal saved for review. Keep this writer open to finish saving its draft state.",
        );
      }
    },
  });
  const retrySave = () => {
    if (canStartFreshConnectedRequest(save.error)) draft.resetIntent();
    save.reset();
    save.mutate();
  };
  return (
    <Dialog open onOpenChange={(open) => !open && close()}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {existing
              ? "Edit proposal"
              : seed
                ? "Review email & timing"
                : "New connected action"}
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
          <DraftStatus
            draft={draft}
            state={writing}
            disabled={save.isPending}
            preview={(copy) =>
              Object.entries(copy.values)
                .filter(([key]) => key !== "is_html")
                .map(([key, value]) => `${label(key)}: ${value}`)
                .join("\n\n")
            }
          />
          <fieldset
            disabled={writing.status === "loading"}
            className="min-w-0 space-y-4"
          >
            <div className="grid gap-3 sm:grid-cols-2">
              <Field>
                <FieldLabel htmlFor="action-kind">Action</FieldLabel>
                <select
                  id="action-kind"
                  className={selectStyle}
                  disabled={!!targetId || save.isPending}
                  value={kind}
                  onChange={(e) => {
                    setKind(e.target.value as Kind);
                    setAccountId("");
                    setValues({ calendar_id: "primary", send_updates: "all" });
                    setSource("");
                    setAttachments([]);
                    set("timing", emailTiming());
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
                  disabled={!!targetId || save.isPending}
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
            </div>
            {accounts.error && <ErrorState error={accounts.error} />}
            {fields[kind]
              .filter(
                (field) =>
                  kind !== "gmail_send" ||
                  !["cc", "bcc"].includes(field.key) ||
                  showCopies ||
                  !!values.cc ||
                  !!values.bcc,
              )
              .map((field) => (
                <Field key={field.key}>
                  <div className="flex items-center justify-between">
                    <FieldLabel htmlFor={`action-${field.key}`}>
                      {field.title}
                    </FieldLabel>
                    {kind === "gmail_send" && field.key === "to" && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-7 px-2 text-xs"
                        aria-expanded={
                          showCopies || !!values.cc || !!values.bcc
                        }
                        onClick={() => setShowCopies(!showCopies)}
                      >
                        Cc / Bcc
                      </Button>
                    )}
                  </div>
                  {kind === "gmail_send" && field.key === "body" ? (
                    <RichWriter
                      id="action-body"
                      label="Message"
                      revision={writing.editorRevision}
                      value={values.body ?? ""}
                      format={values.is_html === "true" ? "html" : "text"}
                      disabled={writing.status === "loading"}
                      placeholder="Write something worth sending…"
                      onChange={(body, format) =>
                        draft.edit((current) => ({
                          ...current,
                          values: {
                            ...current.values,
                            body,
                            is_html: String(format === "html"),
                          },
                        }))
                      }
                    />
                  ) : field.options ? (
                    <select
                      id={`action-${field.key}`}
                      className={selectStyle}
                      value={values[field.key] ?? field.options[0].value}
                      onChange={(e) =>
                        setValues({ ...values, [field.key]: e.target.value })
                      }
                    >
                      {field.options.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  ) : field.format === "text" ? (
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
                    <p className="text-xs text-muted-foreground">
                      {field.hint}
                    </p>
                  )}
                </Field>
              ))}
            {kind === "gmail_send" && (
              <EmailDeliveryFields
                timing={writing.data.timing ?? emailTiming()}
                onChange={(value) => set("timing", value)}
                recipient={(values.to ?? "").trim()}
                accountId={accountId}
              />
            )}
            <details
              className="space-y-3 rounded-lg border border-border p-3"
              open={
                kind.startsWith("notion_") || !!source || attachments.length > 0
              }
            >
              <summary className="cursor-pointer text-sm font-medium">
                Sources, attachments and review note
              </summary>
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
            </details>
            {save.error && (
              <div role="alert" className="space-y-2 text-sm text-destructive">
                <p>{save.error.message}</p>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={save.isPending}
                  onClick={retrySave}
                >
                  {canStartFreshConnectedRequest(save.error)
                    ? "Start a fresh proposal save"
                    : "Retry the same proposal save"}
                </Button>
              </div>
            )}
            <Button
              disabled={
                save.isPending ||
                writing.status === "loading" ||
                writing.status === "conflict"
              }
            >
              {save.isPending ? <Spinner /> : <FileCheck />}Save proposal
            </Button>
          </fieldset>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function SourcePreview({
  versionId,
  onReady,
}: {
  versionId: string;
  onReady?: (id: string | null) => void;
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
    onReady?.(source.data && !source.error ? versionId : null);
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
  const [reviewIntent] = useState(() => new RetainedRequestIntent());
  const [reconcileIntent] = useState(() => new RetainedRequestIntent());
  const review = useMutation({
    mutationFn: (decision: "approved" | "rejected" | "revoked") => {
      const target = `reviewed-actions/${current.id}/reviews`;
      const body = {
        expected_version: current.row_version,
        revision_id: current.current.id,
        decision,
        reason,
      };
      const intent = reviewIntent.forRequest("POST", target, body);
      return api<Action>(target, {
        method: "POST",
        body,
        key: intent.key,
      }).then((result) => ({ result, target, body }));
    },
    onSuccess: ({ target, body }) => {
      reviewIntent.confirmRequest("POST", target, body);
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
    mutationFn: () => {
      const target = `reviewed-actions/${current.id}/reconcile`;
      const body = { expected_version: current.row_version };
      const intent = reconcileIntent.forRequest("POST", target, body);
      return api(target, {
        method: "POST",
        body,
        key: intent.key,
      }).then((result) => ({ result, target, body }));
    },
    onSuccess: ({ target, body }) => {
      reconcileIntent.confirmRequest("POST", target, body);
      void client.invalidateQueries({ queryKey: ["reviewed-actions"] });
      toast.success("Provider receipt checked");
    },
  });
  const retryReconcile = () => {
    if (canStartFreshConnectedRequest(reconcile.error)) {
      reconcileIntent.reset();
      reconcile.reset();
    }
    reconcile.mutate();
  };
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
          {(canReview || current.state === "queued") && (
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
        {current.kind === "gmail_send" && (
          <div className="space-y-1 rounded-lg border p-4 text-sm">
            <p className="font-medium">
              {current.current.scheduled_for
                ? `Scheduled for ${sendTimeLabel(current.current.scheduled_for)}`
                : "Send after your approval"}
            </p>
            {current.current.delivery?.mode === "after_send" && (
              <p className="text-muted-foreground">
                {current.current.delivery.delay_days} days after the selected
                confirmed email. Each email is reviewed separately.
              </p>
            )}
            <p className="text-xs text-muted-foreground">
              {current.current.scheduled_for
                ? "Delivery starts at or after this time while Command Center is running. Edit timing or cancel before delivery starts. Replies are not monitored automatically."
                : "Your selected Gmail account sends this exact reviewed message through Composio."}
            </p>
          </div>
        )}
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
                  {key === "body" &&
                  current.current.payload.is_html === true ? (
                    <EmailPreview html={String(value)} />
                  ) : Array.isArray(value) ? (
                    value.join(", ")
                  ) : typeof value === "boolean" ? (
                    key === "is_html" ? (
                      value ? (
                        "HTML"
                      ) : (
                        "Plain text"
                      )
                    ) : value ? (
                      "Yes"
                    ) : (
                      "No"
                    )
                  ) : (
                    String(value)
                  )}
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
                I reviewed this account, content, delivery timing, source and
                attachments, and authorize this exact action.
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
                    {current.kind === "gmail_send"
                      ? current.current.scheduled_for
                        ? "Approve & schedule"
                        : "Approve & send"
                      : "Approve & queue"}
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
                  {current.kind === "gmail_send" &&
                  current.current.scheduled_for
                    ? "Cancel scheduled email"
                    : "Revoke approval"}
                </Button>
              )}
            </div>
          </div>
        )}
        {(review.error || reconcile.error || action.error) && (
          <div role="alert" className="space-y-2 text-sm text-destructive">
            <p>{(review.error ?? reconcile.error ?? action.error)?.message}</p>
            {reconcile.error && (
              <Button
                size="sm"
                variant="outline"
                disabled={reconcile.isPending}
                onClick={retryReconcile}
              >
                {canStartFreshConnectedRequest(reconcile.error)
                  ? "Start a fresh receipt check"
                  : "Retry the same receipt check"}
              </Button>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

export function ReviewedActionDialog({
  actionId,
  close,
}: {
  actionId: string;
  close: () => void;
}) {
  const action = useQuery({
    queryKey: ["reviewed-actions", actionId],
    queryFn: ({ signal }) =>
      api<Action>(`reviewed-actions/${actionId}`, { signal }),
  });

  if (action.data)
    return <ActionReview key={actionId} initial={action.data} close={close} />;

  return (
    <Dialog open onOpenChange={(open) => !open && close()}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Review action</DialogTitle>
          <DialogDescription>
            Open the saved proposal and its exact review requirements.
          </DialogDescription>
        </DialogHeader>
        {action.error ? (
          <ErrorState error={action.error} retry={() => action.refetch()} />
        ) : (
          <p
            role="status"
            className="flex items-center gap-2 text-sm text-muted-foreground"
          >
            <Spinner /> Loading reviewed action…
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
          <div className="flex flex-wrap gap-2">
            <MailPull />
            <Button onClick={() => setCreating(true)}>
              <Plus />
              New proposal
            </Button>
          </div>
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
                    {action.current.scheduled_for && (
                      <p className="mt-1 text-xs text-muted-foreground">
                        Send time: {sendTimeLabel(action.current.scheduled_for)}
                      </p>
                    )}
                  </div>
                  <Status
                    value={
                      action.state === "queued" && action.current.scheduled_for
                        ? "scheduled"
                        : action.state
                    }
                  />
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
      {creating && (
        <ActionEditor close={() => setCreating(false)} onSaved={setSelected} />
      )}
    </>
  );
}
