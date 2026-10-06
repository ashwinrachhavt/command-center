"use client";

import { AnimatedIcon } from "@/components/ui/animated-icon";
import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  CircleStop,
  FileText,
  LoaderCircle,
  MessageCircle,
  RefreshCw,
  Sparkles,
  XCircle,
} from "lucide-react";
import {
  ChainOfThought,
  ChainOfThoughtContent,
  ChainOfThoughtHeader,
  ChainOfThoughtStep,
} from "@/components/ai-elements/chain-of-thought";
import { cn } from "@/lib/utils";
import { ActivityTool, activityToolLabel } from "./activity-tool";
import { Button } from "@/components/ui/button";
import { Message, MessageContent } from "@/components/ai-elements/message";
import {
  api,
  runFailureMessage,
  type Page,
  type Run,
  type RunArtifact,
  type RunStep,
} from "@/lib/api";
import { useWorkspaceContext } from "./context";
import { ErrorState } from "./primitives";
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
  deferDetails = false,
}: {
  run: Run;
  showOutput: boolean;
  cancelling?: boolean;
  onCancel?: (run: Run) => void;
  deferDetails?: boolean;
}) {
  const context = useWorkspaceContext();
  const queryClient = useQueryClient();
  const reconciledState = useRef(run.state);
  const [expanded, setExpanded] = useState<{ state: string; open: boolean }>();
  const [visited, setVisited] = useState(!deferDetails);
  const stream = useRunEvents(run.id, streamingStates.has(run.state));
  const displayedState = streamingStates.has(run.state)
    ? (stream.runStatus?.state ?? run.state)
    : run.state;
  const active = activeStates.has(displayedState);
  const detailsOpen =
    expanded?.state === displayedState
      ? expanded.open
      : streamingStates.has(displayedState) || displayedState === "failed";
  const loadDetails = active || visited || detailsOpen;
  const fallbackInterval =
    active && stream.connection !== "live" ? 10_000 : false;
  const failureCode = stream.runStatus?.errorCode ?? run.error_code;
  const steps = useQuery({
    queryKey: ["agent-run-steps", run.id],
    enabled: loadDetails,
    queryFn: ({ signal }) =>
      api<RunStep[]>(`agent-runs/${run.id}/steps`, { signal }),
    refetchInterval: fallbackInterval,
  });

  const artifacts = useQuery({
    queryKey: ["agent-run-artifacts", run.id],
    enabled: loadDetails,
    queryFn: ({ signal }) =>
      api<Page<RunArtifact>>(`agent-runs/${run.id}/artifacts?limit=100`, {
        signal,
      }),
    refetchInterval: fallbackInterval,
  });

  useEffect(() => {
    const state = displayedState;
    if (!state || reconciledState.current === state) return;
    reconciledState.current = state;
    if (streamingStates.has(state)) return;
    void Promise.all([
      queryClient.invalidateQueries({ queryKey: ["agent-session-runs"] }),
      queryClient.invalidateQueries({ queryKey: ["agent-session-messages"] }),
      queryClient.invalidateQueries({ queryKey: ["session-checkpoints"] }),
      queryClient.invalidateQueries({ queryKey: ["agent-session"] }),
      queryClient.invalidateQueries({ queryKey: ["agent-run", run.id] }),
      queryClient.invalidateQueries({
        queryKey: ["agent-run-questions", run.id],
      }),
      queryClient.invalidateQueries({ queryKey: ["agent-run-steps", run.id] }),
      queryClient.invalidateQueries({
        queryKey: ["agent-run-artifacts", run.id],
      }),
    ]);
  }, [queryClient, run.id, displayedState]);

  const showLiveActivity =
    streamingStates.has(displayedState) ||
    (!!stream.runStatus &&
      displayedState !== "waiting_for_user" &&
      showOutput &&
      !run.output);

  const liveToolIds = new Set(
    active ? stream.tools.map((tool) => tool.id) : [],
  );
  const savedToolIds = new Set(steps.data?.map((step) => step.id));
  const savedSteps = steps.data?.filter((step) => !liveToolIds.has(step.id));

  const tools = [
    ...(savedSteps ?? []).map((step) => ({
      id: step.id,
      name: step.name,
      state: step.state,
      output:
        step.state === "output-error" ? undefined : (step.output ?? undefined),
      errorText:
        step.state === "output-error" ? (step.output ?? undefined) : undefined,
      role: step.specialist ?? step.role,
      summary:
        step.name === "catalog_execute"
          ? undefined
          : (step.summary ?? undefined),
      title:
        step.name === "catalog_execute" && step.summary
          ? activityToolLabel(step.name, { tool_name: step.summary })
          : undefined,
    })),
    ...stream.tools
      .filter((tool) => active || !savedToolIds.has(tool.id))
      .map((tool) =>
        !active && tool.state === "input-available"
          ? {
              ...tool,
              state: "output-error" as const,
              errorText: "Operation interrupted; completion is not confirmed.",
            }
          : tool,
      ),
  ];
  const currentTool = [...tools]
    .reverse()
    .find((tool) => tool.state === "input-available");
  const errors = tools.filter((tool) => tool.state === "output-error").length;
  const thinking = displayedState === "running";
  const Icon =
    displayedState === "failed"
      ? XCircle
      : displayedState === "waiting_for_user"
        ? MessageCircle
        : displayedState === "completed"
          ? Check
          : thinking
            ? Sparkles
            : LoaderCircle;
  const heading =
    currentTool && thinking
      ? activityToolLabel(
          currentTool.name,
          "input" in currentTool ? currentTool.input : undefined,
        )
      : thinking
        ? "Thinking…"
        : displayedState === "queued"
          ? "Waiting to start"
          : displayedState === "waiting_for_user"
            ? "Needs your answer"
            : displayedState === "completed"
              ? "Work complete"
              : displayedState === "failed"
                ? "Work needs attention"
                : "Work cancelled";

  return (
    <section aria-label={`${run.title} activity`} className="min-w-0 py-2">
      <ChainOfThought
        open={detailsOpen}
        onOpenChange={(open) => {
          setExpanded({ state: displayedState, open });
          if (open) setVisited(true);
        }}
      >
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <ChainOfThoughtHeader
            aria-label={
              detailsOpen ? "Hide activity details" : "Show activity details"
            }
            className="w-auto max-w-full flex-1 bg-muted/30 text-xs"
            icon={
              <AnimatedIcon state={displayedState} className="size-3.5">
                <Icon
                  aria-hidden
                  className={cn(
                    "size-3.5 shrink-0",
                    thinking && "motion-safe:animate-pulse",
                    displayedState === "failed" && "text-destructive",
                  )}
                />
              </AnimatedIcon>
            }
          >
            <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
              <span
                role="status"
                className="min-w-0 break-words font-medium text-foreground"
              >
                {heading}
              </span>
              {tools.length > 0 ? (
                <span className="shrink-0 border-s border-border ps-2 tabular-nums">
                  {tools.length} {tools.length === 1 ? "step" : "steps"}
                </span>
              ) : null}
              {errors > 0 ? (
                <span className="shrink-0 text-destructive">
                  {errors} {errors === 1 ? "error" : "errors"}
                </span>
              ) : null}
            </span>
          </ChainOfThoughtHeader>
          {active && onCancel ? (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="shrink-0 rounded-full"
              disabled={cancelling}
              onClick={() => onCancel(run)}
            >
              <CircleStop />
              Cancel work
            </Button>
          ) : null}
        </div>
        <ChainOfThoughtContent>
          <div
            role="group"
            aria-label="Live activity"
            className="min-w-0 space-y-3 px-2"
          >
            <p
              className="truncate text-[11px] text-muted-foreground"
              title={run.title}
            >
              {run.title}
            </p>
            {showLiveActivity &&
            stream.connection !== "live" &&
            stream.connection !== "complete" ? (
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <span>
                  {stream.connection === "connecting"
                    ? "Connecting to live activity…"
                    : "Live activity disconnected"}
                </span>
                {stream.connection === "disconnected" ? (
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    onClick={stream.retry}
                  >
                    <RefreshCw />
                    Retry stream
                  </Button>
                ) : null}
                {stream.connectionError ? (
                  <p role="status">
                    Saved work continues in the background. Reconnect to resume
                    live updates from event {stream.lastSequence + 1}.
                  </p>
                ) : null}
              </div>
            ) : null}
            {steps.error ? (
              <ErrorState error={steps.error} retry={() => steps.refetch()} />
            ) : null}
            {steps.isPending && !steps.data ? (
              <p className="text-xs text-muted-foreground" role="status">
                Loading saved steps…
              </p>
            ) : null}
            <div className="min-w-0 space-y-3">
              {tools.map((tool) => (
                <ActivityTool key={tool.id} {...tool} />
              ))}
              {thinking && !currentTool ? (
                <ChainOfThoughtStep
                  icon={Sparkles}
                  label={
                    <span className="flex min-h-8 items-center">
                      Preparing a response…
                    </span>
                  }
                  status="active"
                />
              ) : null}
            </div>
            {steps.data && tools.length === 0 && !thinking ? (
              <p className="text-xs text-muted-foreground">
                No saved steps for this run.
              </p>
            ) : null}
            {stream.usage ? (
              <p className="text-[11px] text-muted-foreground">
                {stream.usage.total.toLocaleString()} tokens ·{" "}
                {stream.usage.input.toLocaleString()} input ·{" "}
                {stream.usage.output.toLocaleString()} output
                {stream.usage.cachedInput > 0
                  ? ` · ${stream.usage.cachedInput.toLocaleString()} of input cached`
                  : ""}
              </p>
            ) : null}
          </div>
        </ChainOfThoughtContent>
      </ChainOfThought>

      {displayedState === "waiting_for_user" ? (
        <p className="mt-3 text-xs text-muted-foreground">
          Work is paused until you answer the saved question below.
        </p>
      ) : displayedState === "failed" ? (
        <p className="mt-3 text-xs text-destructive">
          {runFailureMessage(failureCode)}
        </p>
      ) : displayedState === "cancelled" ? (
        <p className="mt-3 text-xs text-muted-foreground">
          Cancelled. Completed activity remains in this conversation.
        </p>
      ) : null}
      {active ? (
        <RunQuestions
          runId={run.id}
          canAnswer={displayedState === "waiting_for_user"}
        />
      ) : null}
      {artifacts.error ? (
        <div className="mt-3">
          <ErrorState
            error={artifacts.error}
            retry={() => artifacts.refetch()}
          />
        </div>
      ) : null}
      {artifacts.data?.items.length ? (
        <div className="mt-3 flex flex-wrap gap-2" aria-label="Saved outputs">
          {artifacts.data.items.map((artifact) => (
            <Button
              key={artifact.version_id}
              type="button"
              size="sm"
              variant="outline"
              className="max-w-full rounded-full"
              title={`Open immutable version ${artifact.version}`}
              onClick={() =>
                context?.open("artifacts", artifact.id, {
                  tab: "content",
                  versionId: artifact.version_id,
                })
              }
            >
              <FileText />
              <span className="truncate">
                {artifact.title} · v{artifact.version}
              </span>
            </Button>
          ))}
        </div>
      ) : null}
      {showLiveActivity && showOutput && !run.output ? (
        <div role="group" aria-label="Live answer" className="mt-3">
          {stream.messages.map((message) => (
            <Message key={message.id} from="assistant">
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
        </div>
      ) : null}
      {showOutput && run.output ? (
        <div className="mt-3">
          <AgentResponse>{run.output}</AgentResponse>
        </div>
      ) : null}
    </section>
  );
}
