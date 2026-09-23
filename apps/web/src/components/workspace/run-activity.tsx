"use client";

import { useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleStop, FileText, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Message, MessageContent } from "@/components/ai-elements/message";
import {
  Tool,
  ToolContent,
  ToolHeader,
  ToolInput,
  ToolOutput,
} from "@/components/ai-elements/tool";
import {
  api,
  label,
  runFailureMessage,
  type Page,
  type Run,
  type RunArtifact,
  type RunStep,
} from "@/lib/api";
import { useWorkspaceContext } from "./context";
import { ErrorState, Status } from "./primitives";
import { useRunEvents } from "./use-run-events";
import { RunQuestions } from "./run-questions";
import { AgentResponse } from "./agent-response";

const activeStates = new Set(["queued", "running", "waiting_for_user"]);
const streamingStates = new Set(["queued", "running"]);

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
  const queryClient = useQueryClient();
  const reconciledState = useRef("");
  const stream = useRunEvents(run.id, streamingStates.has(run.state));
  const displayedState = streamingStates.has(run.state)
    ? (stream.runStatus?.state ?? run.state)
    : run.state;
  const active = activeStates.has(displayedState);
  const failureCode = stream.runStatus?.errorCode ?? run.error_code;
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

  useEffect(() => {
    const state = stream.runStatus?.state;
    if (!state || activeStates.has(state) || reconciledState.current === state)
      return;
    reconciledState.current = state;
    void Promise.all([
      queryClient.invalidateQueries({ queryKey: ["agent-session-runs"] }),
      queryClient.invalidateQueries({ queryKey: ["agent-session-messages"] }),
      steps.refetch(),
      artifacts.refetch(),
    ]);
  }, [artifacts, queryClient, steps, stream.runStatus?.state]);

  const showLiveActivity =
    streamingStates.has(displayedState) ||
    (!!stream.runStatus &&
      displayedState !== "waiting_for_user" &&
      showOutput &&
      !run.output);

  return (
    <section
      aria-label={`${run.title} activity`}
      className="rounded-lg border border-border bg-card/40 p-4"
    >
      <div className="flex flex-wrap items-center gap-2">
        <p className="min-w-0 flex-1 truncate text-xs font-medium">
          {run.title}
        </p>
        <Status value={displayedState} />
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
          {displayedState === "queued"
            ? "Saved and waiting for a worker."
            : displayedState === "waiting_for_user"
              ? "Work is paused until you answer the saved question below."
              : "Work is active. New instructions join this run at its next safe stopping point."}
        </p>
      ) : displayedState === "failed" ? (
        <p className="mt-3 text-xs leading-5 text-destructive">
          {runFailureMessage(failureCode)}
        </p>
      ) : displayedState === "cancelled" ? (
        <p className="mt-3 text-xs leading-5 text-muted-foreground">
          Cancelled. Completed activity remains in this conversation.
        </p>
      ) : null}

      {active ? (
        <RunQuestions
          runId={run.id}
          canAnswer={displayedState === "waiting_for_user"}
        />
      ) : null}

      {showLiveActivity ? (
        <div
          className="mt-4 border-t border-border pt-4"
          aria-label="Live activity"
          role="group"
        >
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <p className="min-w-0 flex-1 text-[11px] font-medium text-muted-foreground">
              {stream.connection === "live"
                ? "Live activity"
                : stream.connection === "connecting"
                  ? "Connecting to live activity…"
                  : stream.connection === "complete"
                    ? "Live activity complete"
                    : "Live activity disconnected"}
            </p>
            {stream.connection === "disconnected" ? (
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={stream.retry}
              >
                <RefreshCw />
                Retry stream
              </Button>
            ) : null}
          </div>
          {stream.connectionError ? (
            <p className="mb-3 text-xs text-muted-foreground" role="status">
              Saved work continues in the background. Reconnect to resume live
              updates from event {stream.lastSequence + 1}.
            </p>
          ) : null}
          {stream.messages.map((message) => (
            <Message key={message.id} from="assistant" className="mb-3">
              <MessageContent>
                <AgentResponse
                  streaming={
                    stream.connection === "live" &&
                    streamingStates.has(displayedState)
                  }
                >
                  {message.content}
                </AgentResponse>
              </MessageContent>
            </Message>
          ))}
          {stream.tools.map((tool) => (
            <Tool key={tool.id} className="mb-2">
              <ToolHeader
                type="dynamic-tool"
                toolName={tool.name}
                title={label(tool.name)}
                state={tool.state}
              />
              <ToolContent>
                {tool.input !== undefined ? (
                  <ToolInput input={tool.input} />
                ) : null}
                <ToolOutput output={tool.output} errorText={tool.errorText} />
              </ToolContent>
            </Tool>
          ))}
          {stream.usage ? (
            <p className="mt-2 text-[11px] text-muted-foreground">
              {stream.usage.total.toLocaleString()} tokens ·{" "}
              {stream.usage.input.toLocaleString()} input ·{" "}
              {stream.usage.output.toLocaleString()} output
            </p>
          ) : null}
        </div>
      ) : null}

      {steps.error ? (
        <div className="mt-4">
          <ErrorState error={steps.error} retry={() => steps.refetch()} />
        </div>
      ) : null}
      {steps.isPending && !steps.data ? (
        <p className="mt-4 text-xs text-muted-foreground" role="status">
          Loading saved steps…
        </p>
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
      ) : steps.data ? (
        <p className="mt-4 text-xs text-muted-foreground">
          No saved steps for this run.
        </p>
      ) : null}

      {artifacts.error ? (
        <div className="mt-4">
          <ErrorState
            error={artifacts.error}
            retry={() => artifacts.refetch()}
          />
        </div>
      ) : null}
      {artifacts.isPending && !artifacts.data ? (
        <p className="mt-4 text-xs text-muted-foreground" role="status">
          Loading saved outputs…
        </p>
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
      ) : artifacts.data ? (
        <p className="mt-4 text-xs text-muted-foreground">
          No saved outputs for this run.
        </p>
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
