"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, CircleCheck, Play } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@/components/ui/empty";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  api,
  dateLabel,
  label,
  type Page,
  type Profile,
  type Schema,
} from "@/lib/api";
import { RetainedRequestIntent } from "@/lib/retained-intent";
import { useWorkspaceContext } from "./context";
import { ErrorState, LoadingRows, Priority } from "./primitives";
import type { WorkQueueItem } from "./work-item-details";
import { deferView } from "./deferred-view";

const WorkItemDetails = deferView<{ item: WorkQueueItem; close: () => void }>(
  () =>
    import("./work-item-details").then((module) => ({
      default: module.WorkItemDetails,
    })),
  "work details",
);

const pageSize = 6;
const views = {
  today: "Today",
  upcoming: "Upcoming",
  unscheduled: "Unscheduled",
  waiting: "Waiting",
  snoozed: "Snoozed",
} as const;
type TaskView = keyof typeof views;
type DailyTask = Schema["DailyTaskRead"];
type DailyTasks = Schema["DailyTasksRead"];

function QueueEmpty({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <Empty className="py-8">
      <EmptyHeader>
        <EmptyTitle>{title}</EmptyTitle>
        <EmptyDescription>{description}</EmptyDescription>
      </EmptyHeader>
    </Empty>
  );
}

function QueuePages({
  name,
  total,
  offset,
  busy,
  onPage,
}: {
  name: string;
  total: number;
  offset: number;
  busy: boolean;
  onPage: (offset: number) => void;
}) {
  if (total <= pageSize && offset === 0) return null;
  return (
    <nav
      aria-label={`${name} pages`}
      className="flex flex-wrap items-center justify-between gap-3 pt-3 text-xs text-muted-foreground"
    >
      <span>
        {total === 0 || offset >= total
          ? "No items on this page"
          : `${offset + 1}–${Math.min(offset + pageSize, total)} of ${total}`}
      </span>
      <div className="flex max-w-full flex-wrap gap-1">
        <Button
          variant="ghost"
          size="sm"
          disabled={offset === 0 || busy}
          onClick={() => onPage(Math.max(0, offset - pageSize))}
        >
          Previous
        </Button>
        <Button
          variant="ghost"
          size="sm"
          disabled={offset + pageSize >= total || busy}
          onClick={() => onPage(offset + pageSize)}
        >
          Next
        </Button>
      </div>
    </nav>
  );
}

function TaskDue({ task, timezone }: { task: DailyTask; timezone: string }) {
  const value = task.due_date || task.due_at;
  const text = task.due_date
    ? dateLabel(task.due_date)
    : task.due_at
      ? new Intl.DateTimeFormat(undefined, {
          timeZone: timezone,
          month: "short",
          day: "numeric",
          hour: "numeric",
          minute: "2-digit",
        }).format(new Date(task.due_at))
      : "No due date";
  return (
    <span
      className={
        task.due_status === "overdue"
          ? "text-xs text-destructive"
          : "text-xs text-muted-foreground"
      }
    >
      {task.due_status === "overdue"
        ? "Overdue · "
        : task.due_status === "today"
          ? "Due today · "
          : ""}
      {value ? <time dateTime={value}>{text}</time> : text}
    </span>
  );
}

function DailyTaskList({ timezone }: { timezone: string }) {
  const context = useWorkspaceContext();
  const client = useQueryClient();
  const [page, setPage] = useState<{ view: TaskView; offset: number }>({
    view: "today",
    offset: 0,
  });
  const [intent] = useState(() => new RetainedRequestIntent());
  const query = useQuery({
    queryKey: ["dashboard", "tasks", timezone, page],
    queryFn: () =>
      api<DailyTasks>(
        `dashboard/tasks?${new URLSearchParams({ view: page.view, timezone, limit: String(pageSize), offset: String(page.offset) })}`,
      ),
    refetchInterval: 60_000,
  });
  const update = useMutation({
    mutationFn: (task: DailyTask) => {
      const path = `tasks/${task.id}`;
      const body = {
        state:
          task.state === "snoozed" || task.state === "waiting"
            ? "in_progress"
            : "done",
        expected_version: task.row_version,
      };
      const request = intent.forRequest("PATCH", path, body);
      return api(path, { method: "PATCH", body, key: request.key });
    },
    onSuccess: (_result, task) => {
      intent.confirmRequest("PATCH", `tasks/${task.id}`, {
        state:
          task.state === "snoozed" || task.state === "waiting"
            ? "in_progress"
            : "done",
        expected_version: task.row_version,
      });
      void client.invalidateQueries();
    },
    onError: (error) => toast.error(error.message),
  });
  return (
    <Tabs
      value={page.view}
      onValueChange={(view) => setPage({ view: view as TaskView, offset: 0 })}
    >
      <div className="pb-1">
        <TabsList variant="line" aria-label="Task views">
          {Object.entries(views).map(([value, title]) => (
            <TabsTrigger key={value} value={value}>
              {title}{" "}
              {query.data && (
                <span className="text-xs tabular-nums text-muted-foreground">
                  {query.data.counts[value as TaskView]}
                </span>
              )}
            </TabsTrigger>
          ))}
        </TabsList>
      </div>
      <TabsContent value={page.view}>
        <p className="mb-3 text-xs text-muted-foreground">
          {page.view === "today"
            ? "Due today and overdue"
            : page.view === "waiting"
              ? "Marked by you as waiting on a person or external event"
              : page.view === "snoozed"
                ? "Paused until you resume them"
                : page.view === "unscheduled"
                  ? "Open tasks without a due date"
                  : "Scheduled after today"}{" "}
          · {query.data?.timezone || timezone}
        </p>
        {query.isPending ? (
          <LoadingRows />
        ) : query.error ? (
          <ErrorState error={query.error} retry={() => query.refetch()} />
        ) : (
          <>
            {query.data.items.length ? (
              <ul
                aria-label={`${views[page.view]} tasks`}
                className="divide-y divide-border border-y border-border"
              >
                {query.data.items.map((task) => (
                  <li key={task.id} className="flex items-start gap-3 py-4">
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      disabled={update.isPending}
                      aria-label={`${task.state === "snoozed" || task.state === "waiting" ? "Resume" : "Complete"} ${task.title}`}
                      onClick={() => update.mutate(task)}
                    >
                      {task.state === "snoozed" || task.state === "waiting" ? (
                        <Play aria-hidden className="translate-x-0.5" />
                      ) : (
                        <CircleCheck aria-hidden />
                      )}
                    </Button>
                    <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                      <Button
                        variant="link"
                        className="h-auto w-fit max-w-full justify-start p-0 text-start whitespace-normal text-foreground"
                        onClick={() => context?.open("tasks", task.id)}
                      >
                        {task.title}
                      </Button>
                      {task.rationale && (
                        <p className="line-clamp-2 text-xs text-muted-foreground">
                          {task.rationale}
                        </p>
                      )}
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="outline">{label(task.state)}</Badge>
                        <TaskDue task={task} timezone={query.data.timezone} />
                      </div>
                    </div>
                    <Priority value={task.priority} />
                  </li>
                ))}
              </ul>
            ) : (
              <QueueEmpty
                title={
                  page.offset
                    ? "No tasks on this page"
                    : `No ${page.view === "today" ? "tasks due today" : `${page.view} tasks`}`
                }
                description={
                  page.offset
                    ? "Return to the previous page to see your tasks."
                    : page.view === "today"
                      ? "Your upcoming and unscheduled work is one tab away."
                      : page.view === "waiting"
                        ? "Mark a task as waiting when someone else or an external event is the next step."
                        : page.view === "snoozed"
                          ? "Tasks you snooze will stay here until you resume them."
                          : "Create a task or choose another view."
                }
              />
            )}
            <QueuePages
              name={`${views[page.view]} tasks`}
              total={query.data.total}
              offset={page.offset}
              busy={query.isFetching}
              onPage={(offset) => setPage({ ...page, offset })}
            />
          </>
        )}
      </TabsContent>
    </Tabs>
  );
}

export function DailyTasks({ title = "Your tasks" }: { title?: string } = {}) {
  const context = useWorkspaceContext();
  const profile = useQuery({
    queryKey: ["me"],
    queryFn: () => api<Profile>("me"),
  });
  return (
    <section aria-labelledby="daily-tasks-heading" className="min-w-0">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 id="daily-tasks-heading" className="font-medium">
          {title}
        </h2>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => context?.open("tasks")}
        >
          View all tasks
        </Button>
      </div>
      {profile.isPending ? (
        <LoadingRows />
      ) : profile.error ? (
        <ErrorState error={profile.error} retry={() => profile.refetch()} />
      ) : (
        <DailyTaskList
          key={profile.data.timezone}
          timezone={profile.data.timezone}
        />
      )}
    </section>
  );
}

const lanes = {
  attention: {
    title: "Needs attention",
    description: "Questions, reviews and interrupted work.",
    empty: "Nothing needs your attention",
    help: "Open questions and work awaiting your review will appear here.",
  },
  running: {
    title: "Running",
    description: "Queued and active work, with its saved status.",
    empty: "No active work",
    help: "Queued agents and actions will appear here when you start them.",
  },
  outputs: {
    title: "Recent outputs",
    description: "Saved versions and confirmed results.",
    empty: "No outputs yet",
    help: "Saved documents and completed work will appear here.",
  },
} as const;

function WorkLane({
  lane,
  onOpen,
  briefing = false,
}: {
  lane: keyof typeof lanes;
  onOpen: (item: WorkQueueItem) => void;
  briefing?: boolean;
}) {
  const [offset, setOffset] = useState(0);
  const copy =
    briefing && lane === "attention"
      ? { ...lanes[lane], title: "Needs a decision" }
      : lanes[lane];
  const query = useQuery({
    queryKey: ["dashboard", "work", lane, offset],
    queryFn: () =>
      api<Page<WorkQueueItem>>(
        `dashboard/work?lane=${lane}&limit=${pageSize}&offset=${offset}`,
      ),
    refetchInterval: 30_000,
  });
  return (
    <section aria-labelledby={`${lane}-heading`} className="min-w-0">
      <div className="mb-3">
        <h2
          id={`${lane}-heading`}
          className="flex items-center gap-2 font-medium"
        >
          {copy.title}
          {query.data && !query.isError && (
            <Badge variant="secondary">{query.data.total}</Badge>
          )}
        </h2>
        <p className="mt-1 text-xs text-muted-foreground">{copy.description}</p>
      </div>
      {query.isPending ? (
        <LoadingRows />
      ) : query.error ? (
        <ErrorState error={query.error} retry={() => query.refetch()} />
      ) : (
        <>
          {query.data.items.length ? (
            <ul
              aria-label={copy.title}
              className="divide-y divide-border border-y border-border"
            >
              {query.data.items.map((item) => (
                <li key={`${item.kind}:${item.id}`}>
                  <Button
                    variant="ghost"
                    className="h-auto w-full items-start justify-start gap-3 rounded-none px-1 py-4 text-start whitespace-normal"
                    onClick={() => onOpen(item)}
                    aria-label={`Open ${item.title}`}
                  >
                    <span className="flex min-w-0 flex-1 flex-col gap-1.5">
                      <span className="font-medium">{item.title}</span>
                      <span className="line-clamp-2 text-xs font-normal text-muted-foreground">
                        {item.detail}
                      </span>
                      <span className="flex flex-wrap items-center gap-2">
                        <Badge variant="outline">{label(item.state)}</Badge>
                        <span className="text-xs font-normal text-muted-foreground">
                          {item.kind === "action"
                            ? label(item.action_kind || "action")
                            : item.kind === "browser"
                              ? "Browser companion"
                              : label(item.kind)}{" "}
                          ·{" "}
                          <time dateTime={item.updated_at}>
                            {dateLabel(item.updated_at)}
                          </time>
                        </span>
                      </span>
                    </span>
                    <ArrowUpRight
                      aria-hidden
                      data-icon="inline-end"
                      className="mt-0.5 shrink-0 text-muted-foreground"
                    />
                  </Button>
                </li>
              ))}
            </ul>
          ) : (
            <QueueEmpty
              title={offset ? "No items on this page" : copy.empty}
              description={
                offset
                  ? "Return to the previous page to see your work."
                  : copy.help
              }
            />
          )}
          <QueuePages
            name={copy.title}
            total={query.data.total}
            offset={offset}
            busy={query.isFetching}
            onPage={setOffset}
          />
        </>
      )}
    </section>
  );
}

export function WorkQueues({ briefing = false }: { briefing?: boolean } = {}) {
  const context = useWorkspaceContext();
  const [selected, setSelected] = useState<WorkQueueItem | null>(null);
  const open = (item: WorkQueueItem) => {
    if (item.kind === "artifact" && item.artifact_id && item.version_id)
      context?.open("artifacts", item.artifact_id, {
        tab: "content",
        versionId: item.version_id,
      });
    else if (item.kind === "action" || item.kind === "browser")
      setSelected(item);
    else if (item.task_id)
      context?.open("tasks", item.task_id, { tab: "conversation" });
    else if (item.opportunity_id)
      context?.open("opportunities", item.opportunity_id, {
        tab: "conversation",
      });
    else setSelected(item);
  };
  return (
    <>
      <div className="flex min-w-0 flex-col gap-8">
        {(Object.keys(lanes) as (keyof typeof lanes)[]).map((lane) => (
          <WorkLane key={lane} lane={lane} onOpen={open} briefing={briefing} />
        ))}
      </div>
      {selected && (
        <WorkItemDetails
          key={`${selected.kind}:${selected.id}`}
          item={selected}
          close={() => setSelected(null)}
        />
      )}
    </>
  );
}
