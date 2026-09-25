"use client";

import { ContactImportHistory } from "./contact-import-history";
import { useArtifactHistory } from "@/components/writing/use-artifact-history";
import { ArtifactWriter } from "@/components/writing/artifact-writer";
import { useId, useLayoutEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  ArrowLeft,
  Download,
  FilePlus2,
  Pencil,
  Plus,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { ContactDiscoveryProps } from "./contact-discovery";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Field, FieldLabel } from "@/components/ui/field";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  api,
  ApiError,
  apiDownload,
  dateLabel,
  label,
  recordName,
  type Activity,
  type DocumentImport,
  type Page,
  type Resource,
  type Resources,
  type Schema,
  type WorkspaceRecord,
} from "@/lib/api";
import { RetainedRequestIntent } from "@/lib/retained-intent";
import { ErrorState, LoadingRows, Mark, Status, Spinner } from "./primitives";
import { RecordEditor, resourceNames, stages } from "./record-editor";
import { deferView } from "./deferred-view";
import { useWorkspaceContext } from "./context";
import { ActivityList } from "./activity-list";
import { OpportunityResearch } from "./opportunity-research";
import { DocumentUploadDialog } from "./document-intake";
import { DocumentTasks, TaskDocuments } from "./document-tasks";
import { DocumentOriginal } from "./document-original";
import { DocumentDecisions } from "./document-decisions";
import { PdfExportControl } from "./pdf-export";
import { TaskActionHub } from "./task-action-hub";
import { StructuredContent } from "./structured-content";

const RichAgentResponse = deferView<{ children: string }>(
  () =>
    import("./agent-response").then((module) => ({
      default: module.AgentResponse,
    })),
  "rich content",
);
const DeferredDiscovery = deferView<ContactDiscoveryProps>(
  () =>
    import("./contact-discovery").then((module) => ({
      default: module.ContactDiscovery,
    })),
  "contact discovery",
);
const DeferredRecordWork = deferView<{
  resource: "contacts" | "companies";
  id: string;
}>(
  () =>
    import("./record-agent-work").then((module) => ({
      default: module.RecordAgentWork,
    })),
  "record work",
);
const DeferredFollowUps = deferView<{ contact: Resources["contacts"] }>(
  () =>
    import("./contact-follow-ups").then((module) => ({
      default: module.ContactFollowUps,
    })),
  "follow-ups",
);
const DeferredWorkConversation = deferView<{
  resource: "tasks" | "opportunities";
  recordId: string;
  disabledReason?: string;
}>(
  () =>
    import("./work-conversation").then((module) => ({
      default: module.WorkConversation,
    })),
  "work conversation",
);

type ArtifactReviewDecision = "approved" | "rejected" | "revoked";
type ArtifactReviewDraft = {
  versionId: string;
  version: number;
  contentSha256: string;
  decision: ArtifactReviewDecision;
  reason: string;
};

function reviewSignature(review: ArtifactReviewDraft) {
  return JSON.stringify(review);
}

export function ArtifactContent({
  record,
  pinnedVersionId,
}: {
  record: WorkspaceRecord;
  pinnedVersionId?: string;
}) {
  const queryClient = useQueryClient();
  const versions = useArtifactHistory(record.id);
  const [selected, setSelected] = useState<string | undefined>(pinnedVersionId);
  if (!selected && versions.items[0]) setSelected(versions.items[0].id);
  const versionQuery = useQuery({
    queryKey: ["artifact-version", record.id, selected],
    enabled: !!selected,
    queryFn: () =>
      api<Schema["VersionRead"]>(`artifacts/${record.id}/versions/${selected}`),
  });
  const version = versionQuery.data;
  const pinnedVersionMissing =
    !!selected &&
    versionQuery.error instanceof ApiError &&
    versionQuery.error.status === 404;
  const reviews = useQuery({
    queryKey: ["reviews", version?.id],
    enabled: !!version,
    queryFn: () =>
      api<Schema["ReviewRead"][]>(`versions/${version?.id}/reviews`),
  });
  const imports = useQuery({
    queryKey: ["document-imports", record.id],
    refetchInterval: (query) =>
      query.state.data?.items.some((item) =>
        ["queued", "running"].includes(item.state),
      )
        ? 2000
        : false,
    enabled: (record as unknown as Record<string, unknown>).kind === "document",
    queryFn: () =>
      api<Page<DocumentImport>>(
        `documents/imports?artifact_id=${record.id}&limit=100&offset=0`,
      ),
  });
  const [editing, setEditing] = useState(false);
  const editSession = useRef(0);
  const [editBase, setEditBase] = useState<{
    versionId: string;
    version: number;
    expectedVersion: number;
    session: number;
    text: string;
  }>();
  const [uploading, setUploading] = useState(false);
  const [reviewDraft, setReviewDraft] = useState<ArtifactReviewDraft>();
  const currentReviewDraft = useRef(reviewDraft);
  useLayoutEffect(() => {
    currentReviewDraft.current = reviewDraft;
  }, [reviewDraft]);
  const [pendingVersionId, setPendingVersionId] = useState<string>();
  const [reviewIntent] = useState(() => new RetainedRequestIntent());
  const matchingReviewDraft =
    reviewDraft?.versionId === version?.id ? reviewDraft : undefined;
  const reason = matchingReviewDraft?.reason ?? "";
  const decision = matchingReviewDraft?.decision ?? "approved";
  const newestVersion = versions.items[0];
  const newerVersionAvailable =
    !!version && !!newestVersion && newestVersion.version > version.version;
  const reviewIsDirty =
    !!matchingReviewDraft &&
    (matchingReviewDraft.reason.length > 0 ||
      matchingReviewDraft.decision !== "approved");
  const updateReviewDraft = (
    update: Partial<Pick<ArtifactReviewDraft, "decision" | "reason">>,
  ) => {
    if (!version) return;
    setReviewDraft((current) => ({
      versionId: version.id,
      version: version.version,
      contentSha256: version.content_sha256,
      decision:
        current?.versionId === version.id ? current.decision : "approved",
      reason: current?.versionId === version.id ? current.reason : "",
      ...update,
    }));
  };
  const review = useMutation({
    mutationFn: (submission: ArtifactReviewDraft) => {
      const target = `versions/${submission.versionId}/reviews`;
      const body = { decision: submission.decision, reason: submission.reason };
      const intent = reviewIntent.forRequest("POST", target, body);
      return api(target, {
        method: "POST",
        body,
        key: intent.key,
      });
    },
    onSuccess: (_result, submission) => {
      queryClient.invalidateQueries({
        queryKey: ["reviews", submission.versionId],
      });
      void queryClient.invalidateQueries({ queryKey: ["artifacts"] });
      reviewIntent.confirmRequest(
        "POST",
        `versions/${submission.versionId}/reviews`,
        {
          decision: submission.decision,
          reason: submission.reason,
        },
      );
      if (
        currentReviewDraft.current &&
        reviewSignature(currentReviewDraft.current) ===
          reviewSignature(submission)
      ) {
        setReviewDraft(undefined);
      }
      toast.success("Review recorded for this version");
    },
    onError: (e) => toast.error(e.message),
  });
  const switchVersion = (versionId: string) => {
    setSelected(versionId);
    setReviewDraft(undefined);
    setPendingVersionId(undefined);
    reviewIntent.reset();
    review.reset();
  };
  const requestVersion = (versionId: string) => {
    if (editing) return;
    if (versionId === version?.id) return;
    if (reviewIsDirty) setPendingVersionId(versionId);
    else switchVersion(versionId);
  };
  const download = useMutation({
    mutationFn: async () => {
      if (!version) throw new Error("Choose a version to download.");
      return apiDownload(
        `artifacts/${record.id}/versions/${version.id}/download`,
      );
    },
    onSuccess: ({ blob, filename }) => {
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download =
        filename ??
        `${recordName(record).replace(/[^a-z0-9 -]/gi, "_")}-v${version?.version}`;
      anchor.click();
      URL.revokeObjectURL(url);
    },
    onError: (error) => toast.error(error.message),
  });
  const recordData = record as unknown as Record<string, unknown>;
  const canUploadOriginal =
    recordData.kind === "document" && !!recordData.document_type_id;
  const downloadableImport = imports.data?.items.find(
    (item) => item.source_version_id === version?.id,
  );
  const contentText =
    typeof version?.payload?.text === "string" ? version.payload.text : null;
  const savedFields = Object.fromEntries(
    Object.entries(version?.payload ?? {}).filter(
      ([key]) => contentText === null || key !== "text",
    ),
  );
  return (
    <div className="flex flex-col gap-5">
      {versions.isPending ||
      (!!selected && versionQuery.isPending && !editing) ? (
        <LoadingRows />
      ) : versions.error ? (
        <ErrorState error={versions.error} />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <Select
              value={selected ?? version?.id}
              onValueChange={requestVersion}
              disabled={editing}
            >
              <SelectTrigger className="w-40" aria-label="Artifact version">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {version &&
                    !versions.items.some((item) => item.id === version.id) && (
                      <SelectItem value={version.id}>
                        Version {version.version} ·{" "}
                        {dateLabel(version.created_at)}
                      </SelectItem>
                    )}
                  {versions.items.map((v) => (
                    <SelectItem value={v.id} key={v.id}>
                      Version {v.version} · {dateLabel(v.created_at)}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
            {versions.hasNextPage && (
              <Button
                variant="ghost"
                size="sm"
                disabled={editing || versions.isFetchingNextPage}
                onClick={() => void versions.fetchNextPage()}
              >
                Load older
              </Button>
            )}
            {versionQuery.error && !pinnedVersionMissing && (
              <ErrorState
                error={versionQuery.error}
                retry={() => versionQuery.refetch()}
              />
            )}
            {!pinnedVersionMissing ? (
              <>
                {downloadableImport || version?.payload === null ? (
                  <Button
                    className="ms-auto"
                    variant="ghost"
                    size="icon-sm"
                    onClick={() => download.mutate()}
                    disabled={download.isPending}
                    aria-label={
                      downloadableImport
                        ? `Download original ${downloadableImport.filename}`
                        : `Download ${recordName(record)}`
                    }
                  >
                    <Download />
                  </Button>
                ) : (
                  <span className="ms-auto" />
                )}
                {canUploadOriginal ? (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setUploading(true)}
                  >
                    <FilePlus2 />
                    Upload original
                  </Button>
                ) : null}
                <Button
                  variant="outline"
                  size="sm"
                  disabled={
                    editing || typeof version?.payload?.text !== "string"
                  }
                  onClick={() => {
                    if (!version) return;
                    editSession.current += 1;
                    setEditBase({
                      session: editSession.current,
                      text: String(version.payload?.text ?? ""),
                      versionId: version.id,
                      version: version.version,
                      expectedVersion: record.row_version,
                    });
                    setEditing(true);
                  }}
                >
                  <Plus />
                  New version
                </Button>
                {recordData.kind === "document" && version && !editing ? (
                  <PdfExportControl
                    artifactId={record.id}
                    versionId={version.id}
                    version={version.version}
                    title={recordName(record)}
                    editable={typeof version.payload?.text === "string"}
                  />
                ) : null}
              </>
            ) : null}
          </div>
          {newerVersionAvailable ? (
            <div className="rounded-md border border-border p-3 text-xs">
              <p>
                A newer Version {newestVersion.version} is available. Your
                displayed content and review remain pinned to Version{" "}
                {version.version}.
              </p>
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="mt-2"
                onClick={() => requestVersion(newestVersion.id)}
              >
                Review version {newestVersion.version}
              </Button>
            </div>
          ) : null}
          {pendingVersionId && reviewIsDirty && version ? (
            <div
              role="alert"
              className="rounded-md border border-border p-3 text-xs"
            >
              <p>
                Unsaved review belongs to Version {version.version}. Discard it
                before switching content.
              </p>
              <div className="mt-2 flex gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => setPendingVersionId(undefined)}
                >
                  Keep reviewing version {version.version}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => switchVersion(pendingVersionId)}
                >
                  Discard review and switch
                </Button>
              </div>
            </div>
          ) : null}
          {pinnedVersionMissing && !editing ? (
            <div
              role="alert"
              className="rounded-md border border-destructive/30 p-4 text-sm"
            >
              <p className="font-medium">
                Pinned artifact version is unavailable.
              </p>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                The requested immutable version was not returned. Choose an
                available version to continue.
              </p>
            </div>
          ) : editing ? (
            editBase ? (
              <ArtifactWriter
                key={editBase.session}
                artifactId={record.id}
                initial={{
                  text: editBase.text,
                  baseVersionId: editBase.versionId,
                  baseVersion: editBase.version,
                  expectedVersion: editBase.expectedVersion,
                }}
                onSaved={(saved) => {
                  queryClient.setQueryData(
                    ["artifact-version", record.id, saved.id],
                    saved,
                  );
                  void queryClient.invalidateQueries();
                  if (editBase.session === editSession.current)
                    setSelected(saved.id);
                }}
                onClose={() => {
                  if (editBase.session !== editSession.current) return;
                  editSession.current += 1;
                  setEditing(false);
                  setEditBase(undefined);
                  setReviewDraft(undefined);
                  setPendingVersionId(undefined);
                  reviewIntent.reset();
                }}
              />
            ) : null
          ) : !version ? null : version.payload === null ? (
            <DocumentOriginal key={version.id} imported={downloadableImport} />
          ) : (
            <div className="min-h-56 break-words px-1 py-6 text-base leading-8 sm:px-3">
              {contentText ? (
                <RichAgentResponse>{contentText}</RichAgentResponse>
              ) : null}
              {Object.keys(savedFields).length > 0 ? (
                contentText ? (
                  <details className="mt-8 border-t border-border pt-4">
                    <summary className="cursor-pointer text-sm font-medium">
                      Saved details
                    </summary>
                    <div className="mt-4">
                      <StructuredContent value={savedFields} />
                    </div>
                  </details>
                ) : (
                  <StructuredContent value={savedFields} />
                )
              ) : !contentText ? (
                <p className="text-sm text-muted-foreground">
                  This version is empty.
                </p>
              ) : null}
            </div>
          )}
          {!editing &&
            !pinnedVersionMissing &&
            version &&
            imports.data?.items[0]?.source_version_id === version.id && (
              <DocumentDecisions key={record.id} artifactId={record.id} />
            )}
          {!pinnedVersionMissing ? (
            <>
              <p
                className="truncate font-mono text-[10px] text-muted-foreground"
                title={version?.content_sha256}
              >
                SHA-256 · {version?.content_sha256}
              </p>
              <div className="border-t border-border pt-5">
                <h3 className="text-sm font-medium">Review this version</h3>
                <p className="mt-1 mb-4 text-xs text-muted-foreground">
                  Review decisions stay with the exact content you checked.
                </p>
                {reviews.error ? (
                  <ErrorState
                    error={reviews.error}
                    retry={() => void reviews.refetch()}
                  />
                ) : reviews.isPending && !reviews.data ? (
                  <p
                    className="mb-4 text-xs text-muted-foreground"
                    role="status"
                  >
                    Loading review history…
                  </p>
                ) : reviews.data?.length === 0 ? (
                  <p className="mb-4 text-xs text-muted-foreground">
                    No reviews recorded for this version.
                  </p>
                ) : reviews.isFetching ? (
                  <p
                    className="mb-4 text-xs text-muted-foreground"
                    role="status"
                  >
                    Refreshing review history…
                  </p>
                ) : null}
                {reviews.data?.[0] && (
                  <div className="mb-4 rounded-md bg-muted p-3 text-xs">
                    <strong>{label(reviews.data[0].decision)}</strong>
                    <p className="mt-1 text-muted-foreground">
                      {reviews.data[0].reason}
                    </p>
                  </div>
                )}
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    if (!version) return;
                    review.mutate({
                      versionId: version.id,
                      version: version.version,
                      contentSha256: version.content_sha256,
                      decision,
                      reason,
                    });
                  }}
                  className="flex flex-col gap-3"
                >
                  <Select
                    value={decision}
                    onValueChange={(value) =>
                      updateReviewDraft({
                        decision: value as ArtifactReviewDecision,
                      })
                    }
                  >
                    <SelectTrigger aria-label="Review decision">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectGroup>
                        {["approved", "rejected", "revoked"].map((d) => (
                          <SelectItem key={d} value={d}>
                            {label(d)}
                          </SelectItem>
                        ))}
                      </SelectGroup>
                    </SelectContent>
                  </Select>
                  <Input
                    value={reason}
                    onChange={(e) =>
                      updateReviewDraft({ reason: e.target.value })
                    }
                    required
                    maxLength={2000}
                    aria-label="Review reason"
                    placeholder="What did you check?"
                  />
                  <Button
                    variant="outline"
                    disabled={
                      editing || review.isPending || !version || !reason.trim()
                    }
                    className="self-end"
                  >
                    Record review
                  </Button>
                  {review.error ? (
                    <p role="alert" className="text-xs text-destructive">
                      {review.error.message}
                    </p>
                  ) : null}
                </form>
              </div>
            </>
          ) : null}
        </>
      )}
      {canUploadOriginal ? (
        <DocumentUploadDialog
          open={uploading}
          onOpenChange={setUploading}
          artifact={{
            id: record.id,
            title: recordName(record),
            documentTypeId: String(recordData.document_type_id),
            rowVersion: record.row_version,
          }}
        />
      ) : null}
    </div>
  );
}

function LinkedRecord({
  resource,
  id,
  action,
}: {
  resource: Resource;
  id: string;
  action: string;
}) {
  const context = useWorkspaceContext();
  const query = useQuery({
    queryKey: [resource, id],
    queryFn: ({ signal }) =>
      api<WorkspaceRecord>(`${resource}/${id}`, { signal }),
  });
  return (
    <Button
      variant="link"
      aria-label={action}
      className="h-auto max-w-full justify-start p-0 text-xs"
      onClick={() => context?.open(resource, id)}
    >
      <span className="truncate">
        {query.data ? recordName(query.data) : action}
      </span>
      <span aria-hidden>→</span>
    </Button>
  );
}

export type RecordDetailProps = {
  resource: Resource;
  id: string;
  onClose: () => void;
  compact?: boolean;
  initialTab?: "content" | "conversation" | "follow-ups";
  pinnedVersionId?: string;
};

export function RecordDetail({
  resource,
  id,
  onClose,
  compact = false,
  initialTab,
  pinnedVersionId,
}: RecordDetailProps) {
  const context = useWorkspaceContext();
  const stateFieldId = useId();
  const client = useQueryClient();
  const [discoveringContacts, setDiscoveringContacts] = useState(false);
  const [editing, setEditing] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [activeTab, setActiveTab] = useState(
    initialTab ?? (resource === "artifacts" ? "content" : "overview"),
  );
  const [recordIntent] = useState(() => new RetainedRequestIntent());
  const [archiveIntent] = useState(() => new RetainedRequestIntent());
  const query = useQuery({
    queryKey: [resource, id],
    queryFn: () => api<WorkspaceRecord>(`${resource}/${id}`),
  });
  const activity = useQuery({
    queryKey: ["activity", id],
    queryFn: () => api<Page<Activity>>(`activity?subject_id=${id}&limit=20`),
  });
  const record = query.data;
  const mutation = useMutation({
    mutationFn: (body: unknown) => {
      const target = `${resource}/${id}`;
      const intent = recordIntent.forRequest("PATCH", target, body);
      return api(target, { method: "PATCH", body, key: intent.key });
    },
    onSuccess: (_result, body) => {
      recordIntent.confirmRequest("PATCH", `${resource}/${id}`, body);
      client.invalidateQueries();
      toast.success("Record updated");
    },
    onError: (e) => toast.error(e.message),
  });
  const archive = useMutation({
    mutationFn: (submitted: WorkspaceRecord) => {
      const target = `${resource}/${id}/archive`;
      const body = { expected_version: submitted.row_version };
      const intent = archiveIntent.forRequest("POST", target, body);
      return api(target, {
        method: "POST",
        body,
        key: intent.key,
      });
    },
    onSuccess: (_result, submitted) => {
      archiveIntent.confirmRequest("POST", `${resource}/${id}/archive`, {
        expected_version: submitted.row_version,
      });
      client.invalidateQueries();
      toast.success("Record archived");
      onClose();
    },
    onError: (e) => toast.error(e.message),
  });
  const details = record
    ? Object.entries(record).filter(
        ([key, value]) =>
          ![
            "id",
            "row_version",
            "name",
            "title",
            "created_at",
            "updated_at",
            "archived_at",
            "completed_at",
            "latest_version",
            "latest_research",
            "review_status",
            ...(resource === "opportunities" || resource === "tasks"
              ? ["stage", "state"]
              : []),
            ...(resource === "tasks"
              ? ["priority", "rationale", "due_date", "due_at"]
              : []),
          ].includes(key) &&
          value !== null &&
          value !== "",
      )
    : [];
  const hrefKeys: Record<string, Resource> = {
    company_id: "companies",
    contact_id: "contacts",
    opportunity_id: "opportunities",
    job_id: "jobs",
  };
  const conversationDisabledReason = record
    ? resource === "tasks" &&
      "state" in record &&
      ["done", "cancelled"].includes(String(record.state))
      ? "Reopen this task before adding to its conversation."
      : "archived_at" in record && record.archived_at
        ? "This archived opportunity is read-only. Restore it before adding to its conversation."
        : undefined
    : undefined;
  return (
    <section aria-label="Record details" className="min-w-0 bg-background">
      {discoveringContacts && resource === "companies" && record && (
        <DeferredDiscovery
          open
          onOpenChange={setDiscoveringContacts}
          company={record as Resources["companies"]}
        />
      )}
      <header className="border-b border-border px-6 py-5">
        <div className="mb-5 flex items-center gap-2 text-xs text-muted-foreground">
          {!compact && (
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Back to list"
              onClick={onClose}
            >
              <ArrowLeft />
            </Button>
          )}
          {resourceNames[resource].plural}
        </div>
        <div className="flex items-center gap-3">
          <Mark
            name={record ? recordName(record) : "…"}
            className="size-11 text-base"
          />
          <h2 className="min-w-0 break-words text-xl leading-7 font-medium tracking-tight">
            {record ? recordName(record) : "Loading record…"}
          </h2>
        </div>
        {record && (
          <div className="mt-5 flex flex-wrap items-center gap-2">
            {resource === "companies" && (
              <Button size="sm" onClick={() => setDiscoveringContacts(true)}>
                Find people
              </Button>
            )}
            {resource === "contacts" && (
              <Button size="sm" onClick={() => setActiveTab("follow-ups")}>
                Follow up
              </Button>
            )}
            <Button
              size="sm"
              variant="outline"
              onClick={() => setEditing(true)}
            >
              <Pencil />
              Edit details
            </Button>
            {resource !== "tasks" && (
              <Button
                variant="ghost"
                size="icon-sm"
                className="ms-auto text-muted-foreground"
                aria-label="Archive record"
                onClick={() => setConfirm(true)}
              >
                <Archive />
              </Button>
            )}
          </div>
        )}
        {record && (
          <>
            {resource === "opportunities" && (
              <Field className="mt-4 w-fit">
                <FieldLabel htmlFor={stateFieldId} className="sr-only">
                  Stage
                </FieldLabel>
                <Select
                  value={String(
                    (record as unknown as Record<string, unknown>)["stage"],
                  )}
                  disabled={mutation.isPending}
                  onValueChange={(v) =>
                    mutation.mutate({
                      expected_version: record.row_version,
                      stage: v,
                    })
                  }
                >
                  <SelectTrigger id={stateFieldId} className="min-w-40">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      {stages.map((v) => (
                        <SelectItem key={v} value={v}>
                          {label(v)}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              </Field>
            )}
          </>
        )}
      </header>
      {query.error ? (
        <div className="px-6">
          <ErrorState error={query.error} retry={() => query.refetch()} />
        </div>
      ) : !record ? (
        <LoadingRows />
      ) : (
        <Tabs value={activeTab} onValueChange={setActiveTab} className="gap-0">
          <div className="overflow-x-auto border-b border-border px-6">
            <TabsList className="h-12 min-w-max bg-transparent p-0">
              <TabsTrigger value="overview">Overview</TabsTrigger>
              {resource === "contacts" && (
                <TabsTrigger value="follow-ups">Email & follow-ups</TabsTrigger>
              )}
              {resource === "artifacts" && (
                <TabsTrigger value="content">Content & versions</TabsTrigger>
              )}
              {resource === "opportunities" && (
                <>
                  <TabsTrigger value="research">Research</TabsTrigger>
                  <TabsTrigger value="contacts">Contacts</TabsTrigger>
                </>
              )}
              {(resource === "tasks" || resource === "opportunities") && (
                <TabsTrigger value="conversation">Conversation</TabsTrigger>
              )}
              <TabsTrigger value="activity">Activity</TabsTrigger>
            </TabsList>
          </div>
          <TabsContent value="overview" className="px-6 py-6">
            {resource === "tasks" && (
              <div className="mb-6 flex flex-col gap-6">
                <TaskActionHub
                  record={record}
                  isPending={mutation.isPending}
                  onStatusChange={(state) =>
                    mutation.mutate({
                      expected_version: record.row_version,
                      state,
                    })
                  }
                  onOpenConversation={() => setActiveTab("conversation")}
                />
                <TaskDocuments taskId={id} />
              </div>
            )}
            {resource === "companies" && (
              <div className="mb-6">
                <DeferredRecordWork resource="companies" id={record.id} />
              </div>
            )}
            <dl className="flex flex-col gap-5">
              {details.map(([key, value]) => (
                <div
                  key={key}
                  className={
                    typeof value === "string" && value.length > 200
                      ? ""
                      : "grid grid-cols-[120px_1fr] items-start gap-4"
                  }
                >
                  <dt className="text-xs text-muted-foreground">
                    {label(key.replace(/_id$/, ""))}
                  </dt>
                  <dd className="min-w-0 break-words text-xs leading-6">
                    {hrefKeys[key] ? (
                      <LinkedRecord
                        resource={hrefKeys[key]}
                        id={String(value)}
                        action={`View ${key.replace("_id", "")}`}
                      />
                    ) : ["stage", "state", "relationship"].includes(key) ? (
                      <Status value={String(value)} />
                    ) : ["source_url", "linkedin_url"].includes(key) &&
                      /^https?:\/\//.test(String(value)) ? (
                      <a
                        href={String(value)}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-primary"
                      >
                        Open source ↗
                      </a>
                    ) : key === "priority" ? (
                      ["Low", "Normal", "High", "Urgent"][Number(value)]
                    ) : ["notes", "rationale", "description"].includes(key) ? (
                      <RichAgentResponse>{String(value)}</RichAgentResponse>
                    ) : (
                      <span className="whitespace-pre-wrap">
                        {String(value)}
                      </span>
                    )}
                  </dd>
                </div>
              ))}
            </dl>
            {resource === "contacts" && (
              <ContactImportHistory contactId={record.id} />
            )}
            <div className="mt-8 border-t border-border pt-4 text-[10px] text-muted-foreground">
              <p>
                Created {dateLabel(record.created_at)} · Updated{" "}
                {dateLabel(record.updated_at)}
              </p>
            </div>
          </TabsContent>
          {resource === "contacts" && (
            <TabsContent value="follow-ups" className="p-6">
              <DeferredFollowUps contact={record as Resources["contacts"]} />
            </TabsContent>
          )}
          {resource === "artifacts" && (
            <TabsContent value="content" className="p-6">
              <ArtifactContent
                record={record}
                pinnedVersionId={pinnedVersionId}
              />
              <DocumentTasks
                artifactId={id}
                archived={!!(record as Resources["artifacts"]).archived_at}
              />
            </TabsContent>
          )}
          {resource === "opportunities" && (
            <TabsContent value="research" className="p-6">
              <OpportunityResearch
                key={id}
                opportunityId={id}
                onOpenConversation={() => setActiveTab("conversation")}
              />
            </TabsContent>
          )}
          {resource === "opportunities" && (
            <TabsContent value="contacts" className="p-6">
              <p className="mb-4 text-sm text-muted-foreground">
                People connected to this opportunity.
              </p>
              {"contact_id" in record && record.contact_id ? (
                <LinkedRecord
                  resource="contacts"
                  id={String(record.contact_id)}
                  action="Open linked contact"
                />
              ) : (
                <p className="text-sm text-muted-foreground">
                  No contact linked yet. Edit the opportunity to add one.
                </p>
              )}
              <Button
                variant="ghost"
                className="mt-3 block"
                onClick={() => context?.open("contacts")}
              >
                Browse contacts
              </Button>
            </TabsContent>
          )}
          {(resource === "tasks" || resource === "opportunities") && (
            <TabsContent value="conversation">
              <DeferredWorkConversation
                key={`${resource}:${id}`}
                resource={resource}
                recordId={id}
                disabledReason={conversationDisabledReason}
              />
            </TabsContent>
          )}
          <TabsContent value="activity" className="px-6 py-3">
            {activity.error ? (
              <ErrorState
                error={activity.error}
                retry={() => activity.refetch()}
              />
            ) : activity.isPending ? (
              <LoadingRows />
            ) : (
              <ActivityList events={activity.data.items} />
            )}
          </TabsContent>
        </Tabs>
      )}
      {editing && record && (
        <RecordEditor
          key={id}
          resource={resource}
          record={record}
          open={editing}
          onOpenChange={setEditing}
        />
      )}
      <Dialog open={confirm} onOpenChange={setConfirm}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              Archive this {resourceNames[resource].singular}?
            </DialogTitle>
            <DialogDescription>
              It will leave your active list. Its history and existing
              relationships are preserved.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirm(false)}>
              Keep record
            </Button>
            <Button
              variant="destructive"
              disabled={archive.isPending}
              onClick={() => record && archive.mutate(record)}
            >
              {archive.isPending && <Spinner />}Archive record
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
