"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { api, dateLabel, label, type Run, type Schema } from "@/lib/api";
import { ErrorState, Spinner } from "./primitives";
import { ReviewedActionDialog } from "./reviewed-actions";
import { RunActivity } from "./run-activity";

export type WorkQueueItem = Schema["WorkQueueItem"];

type WorkItemDetailsProps = { item: WorkQueueItem; close: () => void };
const activeRunStates = new Set(["queued", "running", "waiting_for_user"]);

function RunDetails({ item, close }: WorkItemDetailsProps) {
  const runId = item.run_id || (item.kind === "run" ? item.id : null);
  const run = useQuery({
    queryKey: ["agent-run", runId],
    enabled: !!runId,
    queryFn: ({ signal }) => api<Run>(`agent-runs/${runId}`, { signal }),
    refetchInterval: (query) =>
      activeRunStates.has(query.state.data?.state ?? "") ? 2500 : false,
  });

  return (
    <Dialog open onOpenChange={(open) => !open && close()}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{item.title}</DialogTitle>
          <DialogDescription>
            Saved agent activity, questions and output for this work.
          </DialogDescription>
        </DialogHeader>
        {!runId ? (
          <p role="status" className="text-sm text-muted-foreground">
            This item has no linked agent run.
          </p>
        ) : (
          <>
            {run.error && (
              <ErrorState error={run.error} retry={() => run.refetch()} />
            )}
            {run.data ? (
              <RunActivity key={run.data.id} run={run.data} showOutput />
            ) : !run.error ? (
              <p
                role="status"
                className="flex items-center gap-2 text-sm text-muted-foreground"
              >
                <Spinner /> Loading agent activity…
              </p>
            ) : null}
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

function BrowserDetails({ item, close }: WorkItemDetailsProps) {
  return (
    <Dialog open onOpenChange={(open) => !open && close()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{item.title}</DialogTitle>
          <DialogDescription>
            Saved browser activity from your workspace.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-4">
          <Badge variant="outline">{label(item.state)}</Badge>
          {item.detail && (
            <p className="whitespace-pre-wrap break-words text-sm leading-6">
              {item.detail}
            </p>
          )}
          <p className="text-xs text-muted-foreground">
            Updated{" "}
            <time dateTime={item.updated_at}>{dateLabel(item.updated_at)}</time>
          </p>
          <Button asChild variant="outline" className="self-start">
            <Link href="/browser" onClick={close}>
              Open Browser
              <ArrowUpRight data-icon="inline-end" aria-hidden="true" />
            </Link>
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function WorkItemDetails({ item, close }: WorkItemDetailsProps) {
  if (item.kind === "action")
    return (
      <ReviewedActionDialog key={item.id} actionId={item.id} close={close} />
    );
  if (item.kind === "run" || item.kind === "question")
    return <RunDetails key={item.id} item={item} close={close} />;
  if (item.kind === "browser")
    return <BrowserDetails item={item} close={close} />;
  return null;
}
