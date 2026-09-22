"use client";

import { useQuery } from "@tanstack/react-query";
import { CircleStop, FileText } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tool,
  ToolContent,
  ToolHeader,
  ToolOutput,
} from "@/components/ai-elements/tool";
import {
  api,
  label,
  type Page,
  type Run,
  type RunArtifact,
  type RunStep,
} from "@/lib/api";
import { AgentResponse } from "./agent-response";
import { useWorkspaceContext } from "./context";
import { ErrorState, Status } from "./primitives";

const activeStates = new Set(["queued", "running"]);

export function RunActivity({
  run,
  showOutput,
  cancelling,
  onCancel,
}: {
  run: Run;
  showOutput: boolean;
  cancelling?: boolean;
  onCancel?: (run: Run) => void;
}) {
  const context = useWorkspaceContext();
  const active = activeStates.has(run.state);
  const steps = useQuery({
    queryKey: ["agent-run-steps", run.id, run.state],
    queryFn: ({ signal }) =>
      api<RunStep[]>(`agent-runs/${run.id}/steps`, { signal }),
    refetchInterval: active ? 2500 : false,
  });
  const artifacts = useQuery({
    queryKey: ["agent-run-artifacts", run.id, run.state],
    queryFn: ({ signal }) =>
      api<Page<RunArtifact>>(`agent-runs/${run.id}/artifacts?limit=100`, {
        signal,
      }),
    refetchInterval: active ? 2500 : false,
  });

  return (
    <section
      aria-label={`${run.title} activity`}
      className="rounded-lg border border-border bg-card/40 p-4"
    >
      <div className="flex flex-wrap items-center gap-2">
        <p className="min-w-0 flex-1 truncate text-xs font-medium">
          {run.title}
        </p>
        <Status value={run.state} />
        {active && onCancel ? (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={cancelling}
            onClick={() => onCancel(run)}
          >
            <CircleStop />
            Cancel work
          </Button>
        ) : null}
      </div>

      {active ? (
        <p className="mt-3 text-xs leading-5 text-muted-foreground">
          {run.state === "queued"
            ? "Saved and waiting for a worker."
            : "Work is active. New instructions join this run at its next safe stopping point."}
        </p>
      ) : run.state === "failed" ? (
        <p className="mt-3 text-xs leading-5 text-destructive">
          This work could not finish
          {run.error_code ? ` (${label(run.error_code)})` : ""}. Review the
          issue before trying again.
        </p>
      ) : run.state === "cancelled" ? (
        <p className="mt-3 text-xs leading-5 text-muted-foreground">
          Cancelled. Completed activity remains in this conversation.
        </p>
      ) : null}

      {steps.error ? (
        <div className="mt-4">
          <ErrorState error={steps.error} retry={() => steps.refetch()} />
        </div>
      ) : steps.data?.length ? (
        <div className="mt-4 space-y-2">
          {steps.data.map((step) => {
            const specialist = step.specialist
              ? `${label(step.specialist)} specialist`
              : step.role === "assistant"
                ? "Assistant"
                : label(step.role);
            return (
              <div key={step.id}>
                <p className="mb-1 text-[11px] text-muted-foreground">
                  {specialist}
                  {step.summary ? ` · ${step.summary}` : ""}
                </p>
                <Tool className="mb-0">
                  <ToolHeader
                    type="dynamic-tool"
                    toolName={step.name}
                    title={label(step.name)}
                    state={step.state}
                  />
                  <ToolContent>
                    {step.output ? (
                      <ToolOutput
                        output={
                          step.state === "output-error"
                            ? undefined
                            : step.output
                        }
                        errorText={
                          step.state === "output-error"
                            ? step.output
                            : undefined
                        }
                      />
                    ) : (
                      <p className="text-xs text-muted-foreground">
                        {active
                          ? "Waiting for the result…"
                          : "No result was recorded for this step."}
                      </p>
                    )}
                  </ToolContent>
                </Tool>
              </div>
            );
          })}
        </div>
      ) : null}

      {artifacts.error ? (
        <div className="mt-4">
          <ErrorState
            error={artifacts.error}
            retry={() => artifacts.refetch()}
          />
        </div>
      ) : artifacts.data?.items.length ? (
        <div className="mt-4 flex flex-wrap gap-2" aria-label="Saved outputs">
          {artifacts.data.items.map((artifact) => (
            <Button
              key={artifact.version_id}
              type="button"
              size="sm"
              variant="outline"
              title={`Open immutable version ${artifact.version}`}
              onClick={() =>
                context?.open("artifacts", artifact.id, {
                  tab: "content",
                  versionId: artifact.version_id,
                })
              }
            >
              <FileText />
              {artifact.title} · v{artifact.version}
            </Button>
          ))}
        </div>
      ) : null}

      {showOutput && run.output ? (
        <div className="mt-4 border-t border-border pt-4">
          <p className="mb-2 text-[11px] font-medium text-muted-foreground">
            Run outcome
          </p>
          <AgentResponse>{run.output}</AgentResponse>
        </div>
      ) : null}
    </section>
  );
}
