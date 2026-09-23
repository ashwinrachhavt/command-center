"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  api,
  label,
  type Activity,
  type Page,
  type Resources,
} from "@/lib/api";
import { RetainedRequestIntent } from "@/lib/retained-intent";
import {
  ErrorState,
  LoadingRows,
  PageHeading,
  Spinner,
  Status,
} from "./primitives";
import { ActivityList } from "./activity-list";
import { useWorkspaceContext } from "./context";
import { RecordEditor, stages } from "./record-editor";
import { DailyTasks, WorkQueues } from "./daily-work";

type Dashboard = {
  counts: Record<string, number>;
  stages: Record<string, number>;
  tasks: Resources["tasks"][];
};
export function Overview() {
  const context = useWorkspaceContext();
  const [creating, setCreating] = useState<"tasks" | "opportunities" | null>(
    null,
  );
  const [intent] = useState(() => new RetainedRequestIntent());
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
    mutationFn: () => {
      const request = intent.forRequest("POST", "demo");
      return api("demo", { method: "POST", key: request.key });
    },
    onSuccess: () => {
      intent.confirmRequest("POST", "demo");
      queryClient.invalidateQueries();
      toast.success(
        "Synthetic examples added. No external actions were taken.",
      );
    },
    onError: (e) => toast.error(e.message),
  });
  return (
    <>
      <PageHeading
        title="Overview"
        description="Your next steps, active work and results to review."
        action={
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              onClick={() => setCreating("opportunities")}
            >
              New opportunity
            </Button>
            <Button onClick={() => setCreating("tasks")}>
              <Plus data-icon="inline-start" />
              New task
            </Button>
          </div>
        }
      />
      <div className="px-5 pb-8 md:px-9">
        <div className="grid min-w-0 gap-10 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
          <div className="flex min-w-0 flex-col gap-9">
            <DailyTasks />
            <section aria-labelledby="recent-activity">
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
          </div>
          <WorkQueues />
        </div>
        <section
          aria-label="Workspace summary"
          className="mt-10 border-t border-border pt-6"
        >
          {query.isPending ? (
            <LoadingRows />
          ) : query.error ? (
            <ErrorState error={query.error} retry={() => query.refetch()} />
          ) : (
            <>
              <div className="mb-6 flex flex-wrap gap-x-6 gap-y-2 text-xs text-muted-foreground">
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
              <section aria-labelledby="pipeline">
                <h2 id="pipeline" className="mb-4 font-medium">
                  Pipeline
                </h2>
                <div className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3 xl:grid-cols-6">
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
              {Object.values(query.data.counts).every(
                (count) => count === 0,
              ) && (
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
        </section>
      </div>
      {creating && (
        <RecordEditor
          resource={creating}
          open
          onOpenChange={(open) => {
            if (!open) setCreating(null);
          }}
          onSaved={(record) => context?.open(creating, record.id)}
        />
      )}
    </>
  );
}
