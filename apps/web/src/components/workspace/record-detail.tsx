"use client";
import { useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  ArrowLeft,
  Download,
  FilePlus2,
  Pencil,
  Plus,
  Save,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
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
  apiDownload,
  dateLabel,
  label,
  recordName,
  type Activity,
  type DocumentImport,
  type Page,
  type Resource,
  type Schema,
  type WorkspaceRecord,
} from "@/lib/api";
import { ErrorState, LoadingRows, Mark, Status, Spinner } from "./primitives";
import { RecordEditor, resourceNames, stages } from "./record-editor";
import { AgentResponse } from "./agent-response";
import { useWorkspaceContext } from "./context";
import { WorkConversation } from "./work-conversation";
import { OpportunityResearch } from "./opportunity-research";
import { DocumentUploadDialog } from "./document-intake";

export function ActivityList({ events }: { events: Activity[] }) {
  return (
    <div className="flex flex-col">
      {events.map((e) => (
        <div
          key={e.id}
          className="flex gap-3 border-b border-border/60 py-4 last:border-0"
        >
          <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-primary/60" />
          <div className="min-w-0 flex-1">
            <p className="text-xs">{label(e.action.replaceAll(".", " "))}</p>
            <p className="mt-1 text-[11px] text-muted-foreground">
              {e.details.from_stage
                ? `${label(String(e.details.from_stage))} → ${label(String(e.details.to_stage))}`
                : e.details.version
                  ? `Version ${e.details.version}`
                  : e.details.fields
                    ? `Updated ${String(e.details.fields).replaceAll(",", ", ")}`
                    : "Saved to your workspace"}
            </p>
          </div>
          <time
            className="shrink-0 text-[10px] text-muted-foreground"
            dateTime={e.occurred_at}
          >
            {dateLabel(e.occurred_at)}
          </time>
        </div>
      ))}
      {events.length === 0 && (
        <p className="py-8 text-sm text-muted-foreground">
          Activity will appear here as this record changes.
        </p>
      )}
    </div>
  );
}

function ArtifactContent({
  record,
  pinnedVersionId,
}: {
  record: WorkspaceRecord;
  pinnedVersionId?: string;
}) {
  const queryClient = useQueryClient();
  const versions = useQuery({
    queryKey: ["versions", record.id],
    queryFn: () =>
      api<Schema["VersionRead"][]>(`artifacts/${record.id}/versions`),
  });
  const [selected, setSelected] = useState<string | undefined>(pinnedVersionId);
  const version = selected
    ? versions.data?.find((candidate) => candidate.id === selected)
    : versions.data?.[0];
  const pinnedVersionMissing =
    !!selected && !versions.isPending && !versions.error && !version;
  const reviews = useQuery({
    queryKey: ["reviews", version?.id],
    enabled: !!version,
    queryFn: () =>
      api<Schema["ReviewRead"][]>(`versions/${version?.id}/reviews`),
  });
  const imports = useQuery({
    queryKey: ["document-imports", record.id],
    enabled: (record as unknown as Record<string, unknown>).kind === "document",
    queryFn: () =>
      api<Page<DocumentImport>>(
        `documents/imports?artifact_id=${record.id}&limit=100&offset=0`,
      ),
  });
  const [editing, setEditing] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [text, setText] = useState("");
  const [reason, setReason] = useState("");
  const [decision, setDecision] = useState("approved");
  const append = useMutation({
    mutationFn: () =>
      api(`artifacts/${record.id}/versions`, {
        method: "POST",
        body: { expected_version: record.row_version, text },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries();
      setEditing(false);
      setSelected(undefined);
      toast.success("New version saved");
    },
    onError: (e) => toast.error(e.message),
  });
  const review = useMutation({
    mutationFn: () =>
      api(`versions/${version?.id}/reviews`, {
        method: "POST",
        body: { decision, reason },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries();
      setReason("");
      toast.success("Review recorded for this version");
    },
    onError: (e) => toast.error(e.message),
  });
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
  return (
    <div className="flex flex-col gap-5">
      {versions.isPending ? (
        <LoadingRows />
      ) : versions.error ? (
        <ErrorState error={versions.error} />
      ) : (
        <>
          <div className="flex items-center gap-2">
            <Select value={selected ?? version?.id} onValueChange={setSelected}>
              <SelectTrigger className="w-40" aria-label="Artifact version">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {versions.data?.map((v) => (
                    <SelectItem value={v.id} key={v.id}>
                      Version {v.version} · {dateLabel(v.created_at)}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
            {!pinnedVersionMissing ? (
              <>
                {downloadableImport ? (
                  <Button
                    className="ml-auto"
                    variant="ghost"
                    size="icon-sm"
                    onClick={() => download.mutate()}
                    disabled={download.isPending}
                    aria-label={`Download original ${downloadableImport.filename}`}
                  >
                    <Download />
                  </Button>
                ) : (
                  <span className="ml-auto" />
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
                  onClick={() => {
                    setText(String(version?.payload?.text ?? ""));
                    setEditing(true);
                  }}
                >
                  <Plus />
                  New version
                </Button>
              </>
            ) : null}
          </div>
          {pinnedVersionMissing ? (
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
            <form
              onSubmit={(e) => {
                e.preventDefault();
                append.mutate();
              }}
              className="flex flex-col gap-3"
            >
              <Textarea
                rows={12}
                aria-label="New version content"
                value={text}
                onChange={(e) => setText(e.target.value)}
                maxLength={100000}
              />
              <div className="flex justify-end gap-2">
                <Button
                  variant="ghost"
                  type="button"
                  onClick={() => setEditing(false)}
                >
                  Cancel
                </Button>
                <Button disabled={append.isPending}>
                  <Save />
                  Save version
                </Button>
              </div>
            </form>
          ) : (
            <div className="min-h-40 break-words rounded-lg border border-border bg-background p-4">
              <AgentResponse>
                {String(version?.payload?.text || "This version is empty.")}
              </AgentResponse>
            </div>
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
                    review.mutate();
                  }}
                  className="flex flex-col gap-3"
                >
                  <Select value={decision} onValueChange={setDecision}>
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
                    onChange={(e) => setReason(e.target.value)}
                    required
                    maxLength={2000}
                    aria-label="Review reason"
                    placeholder="What did you check?"
                  />
                  <Button
                    variant="outline"
                    disabled={review.isPending || !version || !reason.trim()}
                    className="self-end"
                  >
                    Record review
                  </Button>
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

export function RecordDetail({
  resource,
  id,
  onClose,
  compact = false,
  initialTab,
  pinnedVersionId,
}: {
  resource: Resource;
  id: string;
  onClose: () => void;
  compact?: boolean;
  initialTab?: "content" | "conversation";
  pinnedVersionId?: string;
}) {
  const context = useWorkspaceContext();
  const stateFieldId = useId();
  const client = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [activeTab, setActiveTab] = useState(initialTab ?? "overview");
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
    mutationFn: (body: unknown) =>
      api(`${resource}/${id}`, { method: "PATCH", body }),
    onSuccess: () => {
      client.invalidateQueries();
      toast.success("Record updated");
    },
    onError: (e) => toast.error(e.message),
  });
  const archive = useMutation({
    mutationFn: () =>
      api(`${resource}/${id}/archive`, {
        method: "POST",
        body: { expected_version: record?.row_version },
      }),
    onSuccess: () => {
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
            ...(resource === "opportunities" || resource === "tasks"
              ? ["stage", "state"]
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
          <div className="mt-5 flex items-center gap-2">
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
                className="ml-auto text-muted-foreground"
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
            {(resource === "opportunities" || resource === "tasks") && (
              <Field className="mt-4 w-fit">
                <FieldLabel htmlFor={stateFieldId} className="sr-only">
                  {resource === "tasks" ? "Status" : "Stage"}
                </FieldLabel>
                <Select
                  value={String(
                    (record as unknown as Record<string, unknown>)[
                      resource === "tasks" ? "state" : "stage"
                    ],
                  )}
                  disabled={mutation.isPending}
                  onValueChange={(v) =>
                    mutation.mutate({
                      expected_version: record.row_version,
                      [resource === "tasks" ? "state" : "stage"]: v,
                    })
                  }
                >
                  <SelectTrigger id={stateFieldId} className="min-w-40">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      {(resource === "tasks"
                        ? ["done", "cancelled"].includes(
                            String(
                              (record as unknown as Record<string, unknown>)
                                .state,
                            ),
                          )
                          ? [
                              String(
                                (record as unknown as Record<string, unknown>)
                                  .state,
                              ),
                              "open",
                            ]
                          : [
                              "open",
                              "in_progress",
                              "snoozed",
                              "done",
                              "cancelled",
                            ]
                        : stages
                      ).map((v) => (
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
                    ) : (
                      <span className="whitespace-pre-wrap">
                        {String(value)}
                      </span>
                    )}
                  </dd>
                </div>
              ))}
            </dl>
            <div className="mt-8 border-t border-border pt-4 text-[10px] text-muted-foreground">
              <p>
                Created {dateLabel(record.created_at)} · Updated{" "}
                {dateLabel(record.updated_at)}
              </p>
            </div>
          </TabsContent>
          {resource === "artifacts" && (
            <TabsContent value="content" className="p-6">
              <ArtifactContent
                record={record}
                pinnedVersionId={pinnedVersionId}
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
              <WorkConversation
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
              onClick={() => archive.mutate()}
            >
              {archive.isPending && <Spinner />}Archive record
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
