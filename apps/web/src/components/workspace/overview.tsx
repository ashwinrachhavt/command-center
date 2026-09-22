"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, Plus } from "lucide-react";
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
  Status,
} from "./primitives";
import { ActivityList } from "./record-detail";
import { useWorkspaceContext } from "./context";
import { RecordEditor, stages } from "./record-editor";

type Dashboard = {
  counts: Record<string, number>;
  stages: Record<string, number>;
  tasks: Resources["tasks"][];
};
export function Overview() {
  const context = useWorkspaceContext();
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
  return (
    <>
      <PageHeading
        title="Overview"
        action={
          <Button onClick={() => setCreating(true)}>
            <Plus />
            New opportunity
          </Button>
        }
      />
      <div className="px-5 pb-8 md:px-9">
        {query.isPending ? (
          <LoadingRows />
        ) : query.error ? (
          <ErrorState error={query.error} retry={() => query.refetch()} />
        ) : (
          <>
            <div className="mb-8 flex flex-wrap gap-x-6 gap-y-2 border-b border-border pb-5 text-xs text-muted-foreground">
              {(
                ["opportunities", "contacts", "companies", "tasks"] as const
              ).map((resource) => (
                <Button
                  key={resource}
                  variant="link"
                  className="h-auto gap-2 p-0 text-xs text-muted-foreground"
                  onClick={() => context?.open(resource)}
                >
                  <span className="font-medium tabular-nums text-foreground">
                    {query.data.counts[resource] ?? 0}
                  </span>
                  {label(resource)}
                </Button>
              ))}
            </div>
            <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_260px]">
              <section aria-labelledby="upcoming-tasks">
                <div className="mb-3 flex items-center justify-between">
                  <h2 id="upcoming-tasks" className="font-medium">
                    Upcoming tasks
                  </h2>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => context?.open("tasks")}
                  >
                    View all
                  </Button>
                </div>
                <div className="divide-y divide-border border-y border-border">
                  {query.data.tasks.map((task) => (
                    <div key={task.id} className="flex items-center gap-3 py-4">
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label={`Complete ${task.title}`}
                        disabled={complete.isPending}
                        onClick={() => complete.mutate(task)}
                      >
                        <CircleCheck className="text-muted-foreground" />
                      </Button>
                      <Button
                        variant="link"
                        className="h-auto min-w-0 flex-1 justify-start p-0 text-left font-normal text-foreground"
                        onClick={() => context?.open("tasks", task.id)}
                      >
                        <span className="truncate">{task.title}</span>
                      </Button>
                      <Priority value={task.priority} />
                      <span className="shrink-0 text-xs text-muted-foreground">
                        {dateLabel(task.due_date || task.due_at)}
                      </span>
                    </div>
                  ))}
                  {!query.data.tasks.length && (
                    <p className="py-10 text-sm text-muted-foreground">
                      No upcoming tasks.
                    </p>
                  )}
                </div>
                <section className="mt-9" aria-labelledby="recent-activity">
                  <h2 id="recent-activity" className="mb-2 font-medium">
                    Recent activity
                  </h2>
                  {activity.isPending ? (
                    <LoadingRows />
                  ) : activity.error ? (
                    <ErrorState
                      error={activity.error}
                      retry={() => activity.refetch()}
                    />
                  ) : (
                    <ActivityList events={activity.data.items} />
                  )}
                </section>
              </section>
              <section aria-labelledby="pipeline">
                <h2 id="pipeline" className="mb-4 font-medium">
                  Pipeline
                </h2>
                <div className="divide-y divide-border">
                  {stages.map((stage) => (
                    <div
                      key={stage}
                      className="flex items-center justify-between py-3"
                    >
                      <Status value={stage} />
                      <span className="text-xs tabular-nums text-muted-foreground">
                        {query.data.stages[stage] ?? 0}
                      </span>
                    </div>
                  ))}
                </div>
              </section>
            </div>
            {Object.values(query.data.counts).every((count) => count === 0) && (
              <div className="mt-8 flex flex-wrap items-center gap-4 border-t border-border pt-5 text-xs text-muted-foreground">
                <span>Exploring the workspace?</span>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={demo.isPending}
                  onClick={() => demo.mutate()}
                >
                  {demo.isPending && <Spinner />}Add synthetic examples
                </Button>
              </div>
            )}
          </>
        )}
      </div>
      {creating && (
        <RecordEditor
          resource="opportunities"
          open
          onOpenChange={setCreating}
          onSaved={(record) => context?.open("opportunities", record.id)}
        />
      )}
    </>
  );
}
