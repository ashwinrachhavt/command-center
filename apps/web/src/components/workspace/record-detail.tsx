"use client";
import { useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, ArrowLeft, Download, Pencil, Plus, Save } from "lucide-react";
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
  dateLabel,
  label,
  recordName,
  type Activity,
  type Page,
  type Resource,
  type Schema,
  type WorkspaceRecord,
} from "@/lib/api";
import { ErrorState, LoadingRows, Mark, Status, Spinner } from "./primitives";
import { RecordEditor, resourceNames, stages } from "./record-editor";
import { AgentResponse } from "./agent-response";
import { useWorkspaceContext } from "./context";

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

function ArtifactContent({ record }: { record: WorkspaceRecord }) {
  const queryClient = useQueryClient();
  const versions = useQuery({
    queryKey: ["versions", record.id],
    queryFn: () =>
      api<Schema["VersionRead"][]>(`artifacts/${record.id}/versions`),
  });
  const [selected, setSelected] = useState<string>();
  const version =
    versions.data?.find((v) => v.id === selected) ?? versions.data?.[0];
  const reviews = useQuery({
    queryKey: ["reviews", version?.id],
    enabled: !!version,
    queryFn: () =>
      api<Schema["ReviewRead"][]>(`versions/${version?.id}/reviews`),
  });
  const [editing, setEditing] = useState(false);
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
  function download() {
    const url = URL.createObjectURL(
      new Blob([String(version?.payload?.text ?? "")], {
        type: "text/plain;charset=utf-8",
      }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = `${recordName(record).replace(/[^a-z0-9 -]/gi, "_")}-v${version?.version}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  }
  return (
    <div className="flex flex-col gap-5">
      {versions.isPending ? (
        <LoadingRows />
      ) : versions.error ? (
        <ErrorState error={versions.error} />
      ) : (
        <>
          <div className="flex items-center gap-2">
            <Select value={version?.id} onValueChange={setSelected}>
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
            <Button
              className="ml-auto"
              variant="ghost"
              size="icon-sm"
              onClick={download}
              aria-label="Download this version"
            >
              <Download />
            </Button>
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
          </div>
          {editing ? (
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
      )}
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
}: {
  resource: Resource;
  id: string;
  onClose: () => void;
  compact?: boolean;
}) {
  const context = useWorkspaceContext();
  const stateFieldId = useId();
  const client = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [confirm, setConfirm] = useState(false);
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
        <Tabs defaultValue="overview" className="gap-0">
          <div className="border-b border-border px-6">
            <TabsList className="h-12 bg-transparent p-0">
              <TabsTrigger value="overview">Overview</TabsTrigger>
              {resource === "artifacts" && (
                <TabsTrigger value="content">Content & versions</TabsTrigger>
              )}
              {resource === "opportunities" && (
                <TabsTrigger value="contacts">Contacts</TabsTrigger>
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
              <ArtifactContent record={record} />
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
