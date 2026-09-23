"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowUpRight,
  Check,
  Copy,
  FileText,
  ListChecks,
  MessageSquare,
  Puzzle,
  Search,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  api,
  dateLabel,
  label,
  type ApplicationPreparation,
  type BrowserSnapshot,
  type Page,
  type Schema,
} from "@/lib/api";
import { RetainedRequestIntent } from "@/lib/retained-intent";
import { cn } from "@/lib/utils";
import { useWorkspaceContext } from "./context";
import { EmptyState, ErrorState, LoadingRows, Status } from "./primitives";
import { RecordEditor } from "./record-editor";
import { ApplicationJobContext } from "./application-job-context";
import { ApplicationMaterials } from "./application-materials";

type Application = Schema["ApplicationRead"];
type Package = Schema["ApplicationPackageRead"];
type Revision = Schema["ApplicationRevision"];
const statuses = [
  "preparing",
  "submitted",
  "interviewing",
  "offer",
  "rejected",
  "withdrawn",
] as const;

export function Applications() {
  const params = useSearchParams();
  const selected = params.get("application");
  const heading = useRef<HTMLHeadingElement>(null);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [offset, setOffset] = useState(0);
  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(search);
      setOffset(0);
    }, 250);
    return () => clearTimeout(timer);
  }, [search]);
  const list = useQuery({
    queryKey: ["applications", query, status, offset],
    queryFn: ({ signal }) => {
      const filter = new URLSearchParams({
        q: query,
        limit: "30",
        offset: String(offset),
      });
      if (status !== "all") filter.set("status", status);
      return api<Page<Application>>(`applications?${filter}`, { signal });
    },
    refetchInterval: 15000,
  });
  function choose(id: string | null) {
    const url = new URL(window.location.href);
    if (id) url.searchParams.set("application", id);
    else url.searchParams.delete("application");
    window.history.pushState(null, "", url);
    if (!id) requestAnimationFrame(() => heading.current?.focus());
  }
  return (
    <div className="mx-auto max-w-[1600px] p-5 md:p-8">
      <header className="mb-7 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="mb-2 text-xs font-medium tracking-wide text-muted-foreground">
            YOUR NEXT CHAPTER
          </p>
          <h1
            ref={heading}
            tabIndex={-1}
            className="text-2xl font-semibold tracking-tight"
          >
            Applications
          </h1>
          <p className="mt-2 max-w-xl text-sm leading-6 text-muted-foreground">
            Keep every application, saved answer and next step together.
          </p>
        </div>
        <Button variant="outline" asChild>
          <Link href="/browser">
            <Puzzle />
            Open browser companion
          </Link>
        </Button>
      </header>
      <div
        className={cn(
          "grid min-w-0 gap-6",
          selected && "lg:grid-cols-[minmax(240px,340px)_minmax(0,1fr)]",
        )}
      >
        <section
          aria-label="Application list"
          className={cn("min-w-0", selected && "hidden lg:block")}
        >
          <div className="mb-4 flex flex-wrap gap-3">
            <div className="relative min-w-40 flex-1">
              <Search
                aria-hidden
                className="absolute left-3 top-2.5 size-4 text-muted-foreground"
              />
              <Input
                aria-label="Search applications"
                placeholder="Search roles or sites…"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                className="pl-9"
              />
            </div>
            <Select
              value={status}
              onValueChange={(value) => {
                setStatus(value);
                setOffset(0);
              }}
            >
              <SelectTrigger
                aria-label="Filter application status"
                className="w-40"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All statuses</SelectItem>
                {statuses.map((value) => (
                  <SelectItem value={value} key={value}>
                    {label(value)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {list.error ? (
            <ErrorState error={list.error} retry={() => list.refetch()} />
          ) : list.isPending ? (
            <LoadingRows />
          ) : list.data?.items.length ? (
            <>
              <p
                className="mb-3 text-xs text-muted-foreground"
                aria-live="polite"
              >
                {list.data.total} application{list.data.total === 1 ? "" : "s"}
              </p>
              <div className="overflow-hidden rounded-xl border bg-card">
                {list.data.items.map((item) => (
                  <button
                    type="button"
                    key={item.task.id}
                    aria-current={
                      selected === item.task.id ? "true" : undefined
                    }
                    onClick={() => choose(item.task.id)}
                    className={cn(
                      "flex w-full flex-col gap-3 border-b p-5 text-left last:border-0 hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
                      selected === item.task.id && "bg-primary/5",
                    )}
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <span className="min-w-0 flex-1 break-words text-sm font-medium">
                        {item.page_title || item.task.title}
                      </span>
                      <Status value={item.status} />
                    </div>
                    <span className="break-all text-xs text-muted-foreground">
                      {new URL(item.origin).hostname}
                    </span>
                    <span className="flex flex-wrap justify-between gap-2 text-xs text-muted-foreground">
                      <span>
                        {item.preparation_count} saved capture
                        {item.preparation_count === 1 ? "" : "s"}
                      </span>
                      <span>
                        {item.task.due_date
                          ? `Task due ${dateLabel(item.task.due_date)}`
                          : dateLabel(item.last_activity_at)}
                      </span>
                    </span>
                  </button>
                ))}
              </div>
              <div className="mt-4 flex items-center justify-between gap-3">
                <Button
                  variant="ghost"
                  disabled={!offset}
                  onClick={() => setOffset(Math.max(0, offset - 30))}
                >
                  Previous
                </Button>
                <span className="text-xs text-muted-foreground">
                  {offset + 1}–{Math.min(offset + 30, list.data.total)} of{" "}
                  {list.data.total}
                </span>
                <Button
                  variant="ghost"
                  disabled={offset + 30 >= list.data.total}
                  onClick={() => setOffset(offset + 30)}
                >
                  Next
                </Button>
              </div>
            </>
          ) : (
            <EmptyState
              title={
                query || status !== "all"
                  ? "No matching applications"
                  : "Your first application starts in the browser"
              }
              description={
                query || status !== "all"
                  ? "Try another search or status."
                  : "Open a job application and choose Autofill in the companion. Its saved answers and résumé will appear here."
              }
            >
              <Button variant="outline" asChild>
                <Link href="/browser">Set up the companion</Link>
              </Button>
            </EmptyState>
          )}
        </section>
        {selected && (
          <ApplicationDetail
            key={selected}
            id={selected}
            back={() => choose(null)}
          />
        )}
      </div>
    </div>
  );
}

function ApplicationDetail({ id, back }: { id: string; back: () => void }) {
  const client = useQueryClient();
  const workspace = useWorkspaceContext();
  const heading = useRef<HTMLHeadingElement>(null);
  const [editingTask, setEditingTask] = useState(false);
  const [offset, setOffset] = useState(0);
  const [selectedPackage, setSelectedPackage] = useState<Package>();
  const [intent] = useState(() => new RetainedRequestIntent());
  const detail = useQuery({
    queryKey: ["application", id],
    queryFn: () => api<Application>(`applications/${id}`),
  });
  const history = useQuery({
    queryKey: ["application-packages", id, offset],
    queryFn: () =>
      api<Page<Package>>(
        `applications/${id}/packages?limit=10&offset=${offset}`,
      ),
  });
  const taskId = detail.data?.task.id;
  useEffect(() => {
    if (taskId) heading.current?.focus();
  }, [taskId]);
  const change = useMutation({
    mutationFn: (body: Revision) => {
      const target = `applications/${id}`;
      return api<Application>(target, {
        method: "PATCH",
        body,
        key: intent.forRequest("PATCH", target, body).key,
      });
    },
    onSuccess: (saved, body) => {
      intent.confirmRequest("PATCH", `applications/${id}`, body);
      client.setQueryData(["application", id], saved);
      void client.invalidateQueries({ queryKey: ["applications"] });
      toast.success(`Application marked ${label(saved.status).toLowerCase()}`);
    },
  });
  const item = detail.data;
  const activePackage = selectedPackage ?? history.data?.items[0];
  return (
    <section
      aria-label="Application detail"
      className="min-w-0 rounded-xl border bg-card p-5 md:p-6"
    >
      <Button variant="ghost" size="sm" className="mb-4 -ml-2" onClick={back}>
        <ArrowLeft />
        All applications
      </Button>
      {detail.error ? (
        <ErrorState error={detail.error} retry={() => detail.refetch()} />
      ) : !item ? (
        <LoadingRows />
      ) : (
        <>
          <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <h2
                ref={heading}
                tabIndex={-1}
                className="break-words text-xl font-semibold tracking-tight"
              >
                {item.page_title || item.task.title}
              </h2>
              <p className="mt-2 break-all text-xs text-muted-foreground">
                {new URL(item.origin).hostname}
              </p>
            </div>
            <Status value={item.status} />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {item.status === "preparing" && (
              <Button
                disabled={change.isPending || !!change.error}
                onClick={() =>
                  change.mutate({
                    expected_version: item.row_version,
                    status: "submitted",
                  })
                }
              >
                <Check />
                Mark as submitted
              </Button>
            )}
            <Select
              value={item.status}
              disabled={change.isPending || !!change.error}
              onValueChange={(value: Application["status"]) =>
                change.mutate({
                  expected_version: item.row_version,
                  status: value,
                })
              }
            >
              <SelectTrigger aria-label="Application status" className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {statuses.map((value) => (
                  <SelectItem key={value} value={value}>
                    {label(value)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button variant="outline" asChild>
              <a href={item.page_url} target="_blank" rel="noreferrer">
                Visit saved page
                <ArrowUpRight />
              </a>
            </Button>
          </div>
          <p className="mt-3 text-xs leading-5 text-muted-foreground">
            Status is your record of progress. Autofill does not mark an
            application submitted.
            {item.submission_recorded_at
              ? ` You recorded submission ${dateLabel(item.submission_recorded_at)}.`
              : ""}
          </p>
          {change.error && (
            <div role="alert" className="mt-3 rounded-lg border p-3 text-sm">
              <p>{change.error.message}</p>
              <div className="mt-2 flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={change.isPending}
                  onClick={() =>
                    change.variables && change.mutate(change.variables)
                  }
                >
                  Retry status update
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={change.isPending}
                  onClick={async () => {
                    const result = await detail.refetch();
                    if (!result.error) {
                      intent.reset();
                      change.reset();
                    }
                  }}
                >
                  Reload current status
                </Button>
              </div>
            </div>
          )}
          <div className="my-6 rounded-lg border bg-background/50 p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-xs font-medium text-muted-foreground">
                  NEXT STEP
                </p>
                <h3 className="mt-2 break-words text-sm font-medium">
                  {item.task.title}
                </h3>
                <p className="mt-2 text-xs text-muted-foreground">
                  Task {label(item.task.state).toLowerCase()} ·{" "}
                  {item.task.due_date || item.task.due_at
                    ? `Due ${dateLabel(item.task.due_date ?? item.task.due_at)}`
                    : "No due date"}
                </p>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setEditingTask(true)}
              >
                Edit next step
              </Button>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => workspace?.open("tasks", item.task.id)}
              >
                <ListChecks />
                Task details
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() =>
                  workspace?.open("tasks", item.task.id, {
                    tab: "conversation",
                  })
                }
              >
                <MessageSquare />
                Work conversation
              </Button>
              {item.task.opportunity_id && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() =>
                    workspace?.open("opportunities", item.task.opportunity_id!)
                  }
                >
                  Opportunity
                  <ArrowUpRight />
                </Button>
              )}
            </div>
          </div>
          <ApplicationJobContext application={item} />
          <ApplicationMaterials
            taskId={item.task.id}
            resumeVersionId={history.data?.items[0]?.resume?.version_id}
          />
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <h3 className="text-sm font-semibold">
              Saved application packages
            </h3>
            <span className="text-xs text-muted-foreground">
              {history.data?.total ?? item.preparation_count} capture
              {(history.data?.total ?? item.preparation_count) === 1 ? "" : "s"}
            </span>
          </div>
          {history.error ? (
            <ErrorState error={history.error} retry={() => history.refetch()} />
          ) : history.isPending ? (
            <LoadingRows />
          ) : (
            <>
              <div className="mb-4 flex flex-wrap gap-2">
                {history.data?.items.map((entry) => (
                  <Button
                    key={entry.id}
                    size="sm"
                    variant={
                      activePackage?.id === entry.id ? "secondary" : "outline"
                    }
                    aria-pressed={activePackage?.id === entry.id}
                    onClick={() => setSelectedPackage(entry)}
                  >
                    <FileText />
                    {dateLabel(entry.created_at)} · v{entry.version}
                  </Button>
                ))}
              </div>
              {(history.data?.total ?? 0) > 10 && (
                <div className="mb-4 flex gap-2">
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={!offset}
                    onClick={() => {
                      setSelectedPackage(undefined);
                      setOffset(Math.max(0, offset - 10));
                    }}
                  >
                    Newer captures
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={offset + 10 >= (history.data?.total ?? 0)}
                    onClick={() => {
                      setSelectedPackage(undefined);
                      setOffset(offset + 10);
                    }}
                  >
                    Older captures
                  </Button>
                </div>
              )}
              {activePackage && (
                <SavedPackage
                  key={`${activePackage.id}:${activePackage.version_id}`}
                  taskId={id}
                  item={activePackage}
                />
              )}
            </>
          )}
          <RecordEditor
            resource="tasks"
            record={item.task}
            open={editingTask}
            onOpenChange={setEditingTask}
            onSaved={() => {
              void detail.refetch();
              void client.invalidateQueries({ queryKey: ["applications"] });
            }}
          />
        </>
      )}
    </section>
  );
}

function SavedPackage({ taskId, item }: { taskId: string; item: Package }) {
  const workspace = useWorkspaceContext();
  const saved = useQuery({
    queryKey: ["application-package-version", taskId, item.id, item.version_id],
    queryFn: () =>
      api<ApplicationPreparation>(
        `applications/${taskId}/packages/${item.id}/versions/${item.version_id}`,
      ),
  });
  const snapshot = useQuery({
    queryKey: ["snapshot", item.snapshot_id],
    queryFn: () =>
      api<BrowserSnapshot>(`browser/snapshots/${item.snapshot_id}`),
  });
  const fields = new Map(
    snapshot.data?.fields.map((field) => [field.id, field]) ?? [],
  );
  const filledCount = Object.values(
    item.latest_fill?.field_results ?? {},
  ).filter((result) => ["filled", "uploaded"].includes(result.status)).length;
  async function copy() {
    const text = saved.data?.fields
      .filter((field) => field.value)
      .map(
        (field) =>
          `${fields.get(field.field_id)?.label || field.field_id}\n${field.value}`,
      )
      .join("\n\n");
    try {
      await navigator.clipboard.writeText(text ?? "");
      toast.success("Saved answers copied");
    } catch {
      toast.error(
        "Clipboard unavailable. Select and copy the answer text below.",
      );
    }
  }
  return (
    <div className="min-w-0 rounded-lg border p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h4 className="text-sm font-medium">
          Saved answers · version {item.version}
        </h4>
        <Button
          size="sm"
          variant="ghost"
          disabled={
            !saved.data?.fields.some((field) => field.value) || !snapshot.data
          }
          onClick={copy}
        >
          <Copy />
          Copy answers
        </Button>
      </div>
      {item.resume ? (
        <button
          type="button"
          disabled={!item.resume_artifact_id}
          className="mt-3 flex min-h-9 items-center gap-2 break-all text-left text-xs text-primary underline underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          onClick={() =>
            workspace?.open("artifacts", item.resume_artifact_id!, {
              tab: "content",
              versionId: item.resume!.version_id,
            })
          }
        >
          <FileText className="size-4 shrink-0" />
          {item.resume.filename} · selected résumé
          <ArrowUpRight className="size-3 shrink-0" />
        </button>
      ) : (
        <p className="mt-3 text-xs text-muted-foreground">
          No résumé selected in this package.
        </p>
      )}
      {item.cover_letter ? (
        <Button
          variant="link"
          className="h-auto justify-start whitespace-normal px-0 text-left"
          disabled={!item.cover_letter_artifact_id}
          onClick={() =>
            workspace?.open("artifacts", item.cover_letter_artifact_id!, {
              tab: "content",
              versionId: item.cover_letter!.version_id,
            })
          }
        >
          <FileText className="size-4 shrink-0" />
          {item.cover_letter.filename} · selected cover letter
        </Button>
      ) : null}
      {item.latest_fill ? (
        <div className="mt-4 rounded-md bg-muted/40 p-3 text-xs leading-5">
          <p className="font-medium">
            Latest fill attempt: {label(item.latest_fill.state)}
          </p>
          <p className="mt-1 text-muted-foreground">
            {filledCount} field{filledCount === 1 ? "" : "s"} filled or attached
            · {dateLabel(item.latest_fill.created_at)}
          </p>
          {item.latest_fill.state === "outcome_unknown" && (
            <p className="mt-1">
              Check the page before trying again. This attempt has no confirmed
              result.
            </p>
          )}
          {item.latest_fill.preparation_version_id !== item.version_id && (
            <p className="mt-1">
              This attempt used an earlier saved version.{" "}
              <button
                type="button"
                className="min-h-8 text-primary underline underline-offset-4 focus-visible:ring-2 focus-visible:ring-ring"
                onClick={() =>
                  workspace?.open("artifacts", item.artifact_id, {
                    tab: "content",
                    versionId: item.latest_fill!.preparation_version_id,
                  })
                }
              >
                View that version
              </button>
            </p>
          )}
        </div>
      ) : (
        <p className="mt-3 text-xs text-muted-foreground">
          Saved preparation · no fill attempt recorded.
        </p>
      )}
      {saved.error || snapshot.error ? (
        <ErrorState
          error={saved.error ?? snapshot.error!}
          retry={() => {
            void saved.refetch();
            void snapshot.refetch();
          }}
        />
      ) : saved.isPending || snapshot.isPending ? (
        <LoadingRows />
      ) : (
        <dl className="mt-4 divide-y">
          {saved.data?.fields.map((field) => (
            <div key={field.field_id} className="py-3">
              <dt className="text-xs font-medium">
                {fields.get(field.field_id)?.label || field.field_id}
              </dt>
              <dd className="mt-1 whitespace-pre-wrap break-words text-sm leading-6">
                {field.value ??
                  (field.status === "preserved"
                    ? "Kept the existing value on the page"
                    : field.status === "unsupported"
                      ? "Complete this control on the page"
                      : "Needs your input")}
              </dd>
              {field.value && (
                <dd className="mt-1 text-xs leading-5 text-muted-foreground">
                  {field.reason}
                </dd>
              )}
            </div>
          ))}
        </dl>
      )}
      <div className="mt-4 flex flex-wrap gap-2 border-t pt-4">
        <Button size="sm" variant="outline" asChild>
          <Link href={`/browser?snapshot=${item.snapshot_id}`}>
            Review saved preparation
            <ArrowUpRight />
          </Link>
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() =>
            workspace?.open("artifacts", item.artifact_id, {
              tab: "content",
              versionId: item.version_id,
            })
          }
        >
          Version history
        </Button>
      </div>
      <p className="mt-3 text-xs leading-5 text-muted-foreground">
        To fill again, reopen the job page and capture the current form in the
        companion. Saved pages omit query parameters.
      </p>
    </div>
  );
}
