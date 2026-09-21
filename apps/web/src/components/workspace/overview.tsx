"use client";
import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  ArrowUpRight,
  Bot,
  BriefcaseBusiness,
  Building2,
  CheckCheck,
  CircleCheck,
  Plus,
  Sparkles,
  Users,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  api,
  dateLabel,
  label,
  type Activity,
  type Page,
  type Resources,
} from "@/lib/api";
import {
  ErrorState,
  LoadingRows,
  PageHeading,
  Priority,
  Spinner,
} from "./primitives";
import { ActivityList } from "./record-detail";
import { RecordEditor, stages } from "./record-editor";

type Dashboard = {
  counts: Record<string, number>;
  stages: Record<string, number>;
  tasks: Resources["tasks"][];
};
export function Overview() {
  const [creating, setCreating] = useState(false);
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => api<Dashboard>("dashboard"),
  });
  const activity = useQuery({
    queryKey: ["activity", "overview"],
    queryFn: () => api<Page<Activity>>("activity?limit=5"),
  });
  const demo = useMutation({
    mutationFn: () => api("demo", { method: "POST" }),
    onSuccess: () => {
      queryClient.invalidateQueries();
      toast.success(
        "Synthetic examples added. No external actions were taken.",
      );
    },
    onError: (e) => toast.error(e.message),
  });
  const complete = useMutation({
    mutationFn: (task: Resources["tasks"]) =>
      api(`tasks/${task.id}`, {
        method: "PATCH",
        body: { state: "done", expected_version: task.row_version },
      }),
    onSuccess: () => queryClient.invalidateQueries(),
    onError: (e) => toast.error(e.message),
  });
  const metrics = [
    {
      key: "opportunities",
      title: "Active opportunities",
      icon: BriefcaseBusiness,
      path: "/opportunities",
    },
    {
      key: "contacts",
      title: "People in your corner",
      icon: Users,
      path: "/contacts",
    },
    {
      key: "companies",
      title: "Companies on your radar",
      icon: Building2,
      path: "/companies",
    },
    { key: "tasks", title: "Open tasks", icon: CheckCheck, path: "/tasks" },
  ];
  const total = Object.values(query.data?.stages ?? {}).reduce(
    (a, b) => a + b,
    0,
  );
  return (
    <>
      <PageHeading
        eyebrow="YOUR WORKSPACE, AT A GLANCE"
        title="Make your next move."
        description="A little clarity. A focused plan. Everything you need to move forward."
        action={
          <Button onClick={() => setCreating(true)}>
            <Plus />
            New opportunity
          </Button>
        }
      />
      <div className="px-5 pb-8 md:px-9">
        {query.error ? (
          <ErrorState error={query.error} retry={() => query.refetch()} />
        ) : query.isPending ? (
          <LoadingRows />
        ) : (
          <>
            <div className="grid grid-cols-2 divide-x divide-y divide-border overflow-hidden rounded-xl border border-border bg-card lg:grid-cols-4 lg:divide-y-0">
              {metrics.map((m) => (
                <Link
                  href={m.path}
                  key={m.key}
                  className="group px-5 py-5 hover:bg-muted/40"
                >
                  <div className="mb-5 flex items-center justify-between">
                    <m.icon className="size-4 text-muted-foreground" />
                    <ArrowUpRight className="size-3.5 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
                  </div>
                  <span className="text-3xl font-medium tabular-nums tracking-tight">
                    {query.data.counts[m.key]}
                  </span>
                  <p className="mt-1.5 text-[11px] text-muted-foreground">
                    {m.title}
                  </p>
                </Link>
              ))}
            </div>
            {Object.values(query.data.counts).every((v) => v === 0) && (
              <div className="mt-6 flex flex-wrap items-center gap-4 rounded-lg border border-primary/20 bg-primary/5 px-5 py-4">
                <span className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <Sparkles className="size-4" />
                </span>
                <div className="flex-1">
                  <p className="text-sm font-medium">
                    A fresh start, with room to grow.
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Add your first opportunity, or explore the workspace with
                    clearly fictional examples.
                  </p>
                </div>
                <Button
                  variant="outline"
                  onClick={() => demo.mutate()}
                  disabled={demo.isPending}
                >
                  {demo.isPending && <Spinner />}Add examples
                </Button>
              </div>
            )}
            <div className="mt-8 flex items-center justify-between">
              <div>
                <h2 className="text-sm font-medium">
                  Your opportunity pipeline
                </h2>
                <p className="mt-1 text-xs text-muted-foreground">
                  Every next chapter starts somewhere.
                </p>
              </div>
              <Link
                href="/opportunities"
                className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              >
                View all <ArrowUpRight className="size-3" />
              </Link>
            </div>
            <div className="mt-5 grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
              {stages.map((stage, i) => (
                <Link
                  href="/opportunities"
                  key={stage}
                  className="rounded-lg border border-border bg-card p-4 transition-colors hover:border-input"
                >
                  <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                    <span
                      className={`size-1.5 rounded-full ${["bg-slate-400", "bg-purple-300", "bg-blue-300", "bg-amber-300", "bg-emerald-300", "bg-rose-300"][i]}`}
                    />
                    {label(stage)}
                  </div>
                  <div className="mt-4 flex items-end justify-between">
                    <span className="text-2xl font-medium tabular-nums">
                      {query.data.stages[stage] ?? 0}
                    </span>
                    <span className="text-[10px] text-muted-foreground">
                      {total
                        ? Math.round(
                            ((query.data.stages[stage] ?? 0) / total) * 100,
                          )
                        : 0}
                      %
                    </span>
                  </div>
                  <div className="mt-3 h-0.5 overflow-hidden rounded-full bg-border">
                    <div
                      className="h-full bg-primary/60"
                      style={{
                        width: `${total ? ((query.data.stages[stage] ?? 0) / total) * 100 : 0}%`,
                      }}
                    />
                  </div>
                </Link>
              ))}
            </div>
            <div className="mt-8 grid gap-6 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
              <div className="overflow-hidden rounded-xl border border-border bg-card">
                <div className="flex items-center justify-between border-b border-border px-5 py-4">
                  <h2 className="text-sm font-medium">Next on your list</h2>
                  <Link
                    href="/tasks"
                    className="text-xs text-muted-foreground hover:text-foreground"
                  >
                    All tasks ↗
                  </Link>
                </div>
                {query.data.tasks.length ? (
                  query.data.tasks.map((task) => (
                    <div
                      key={task.id}
                      className="flex items-center gap-3 border-b border-border/60 px-4 py-4 last:border-0"
                    >
                      <Button
                        variant="ghost"
                        size="icon-xs"
                        disabled={complete.isPending}
                        onClick={() => complete.mutate(task)}
                        aria-label={`Complete ${task.title}`}
                      >
                        <CircleCheck className="text-muted-foreground" />
                      </Button>
                      <Link
                        href={`/tasks?record=${task.id}`}
                        className="min-w-0 flex-1"
                      >
                        <p className="truncate text-xs font-medium">
                          {task.title}
                        </p>
                        <p className="mt-1 text-[10px] text-muted-foreground">
                          {dateLabel(task.due_date ?? task.due_at)}
                        </p>
                      </Link>
                      <Priority value={task.priority ?? 1} />
                      <ArrowUpRight className="size-3 text-muted-foreground" />
                    </div>
                  ))
                ) : (
                  <div className="flex min-h-52 flex-col items-center justify-center gap-3 p-6">
                    <CheckCheck className="size-7 text-primary/60" />
                    <p className="text-sm">A clear list. A clear mind.</p>
                    <p className="text-xs text-muted-foreground">
                      Add a task when you’re ready for the next step.
                    </p>
                    <Button variant="outline" size="sm" asChild>
                      <Link href="/tasks">Go to tasks</Link>
                    </Button>
                  </div>
                )}
              </div>
              <div className="workspace-grid relative flex flex-col overflow-hidden rounded-xl border border-primary/20 bg-card p-6">
                <div className="mb-6 flex size-10 items-center justify-center rounded-xl border border-primary/20 bg-primary/10 text-primary">
                  <Bot className="size-5" />
                </div>
                <p className="text-[10px] font-medium tracking-widest text-primary">
                  YOUR THINKING PARTNERS
                </p>
                <h2 className="mt-3 text-xl leading-7 font-medium tracking-tight">
                  Less busywork.
                  <br />
                  More forward motion.
                </h2>
                <p className="mt-3 max-w-xs text-xs leading-6 text-muted-foreground">
                  Turn an open question into research, or a rough idea into a
                  thoughtful draft. Your agents work with the context you
                  choose.
                </p>
                <Button variant="outline" className="mt-6 w-fit" asChild>
                  <Link href="/agents">
                    Start a conversation <ArrowRight />
                  </Link>
                </Button>
              </div>
            </div>
            <div className="mt-8">
              <h2 className="text-sm font-medium">Recent activity</h2>
              <p className="mt-1 text-xs text-muted-foreground">
                A clear record of what’s changed.
              </p>
              {activity.error ? (
                <ErrorState error={activity.error} />
              ) : (
                <ActivityList events={activity.data?.items ?? []} />
              )}
            </div>
          </>
        )}
      </div>
      {creating && (
        <RecordEditor
          resource="opportunities"
          open
          onOpenChange={setCreating}
        />
      )}
    </>
  );
}
