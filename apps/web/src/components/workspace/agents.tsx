"use client";
import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowUp,
  Bot,
  BookOpen,
  CircleStop,
  Clock3,
  FileText,
  Sparkles,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  api,
  dateLabel,
  label,
  runFailureMessage,
  type AgentProfile,
  type Page,
  type Run,
} from "@/lib/api";
import { RetainedRequestIntent } from "@/lib/retained-intent";
import { cn } from "@/lib/utils";
import {
  Conversation,
  ConversationContent,
  ConversationScrollButton,
} from "@/components/ai-elements/conversation";
import { Message, MessageContent } from "@/components/ai-elements/message";
import {
  Tool,
  ToolHeader,
  ToolContent,
  ToolOutput,
} from "@/components/ai-elements/tool";
import { deferView } from "./deferred-view";
import {
  ErrorState,
  LoadingRows,
  PageHeading,
  Spinner,
  Status,
} from "./primitives";

const RichAgentResponse = deferView<{ children: string }>(
  () =>
    import("./agent-response").then((module) => ({
      default: module.AgentResponse,
    })),
  "rich agent response",
);

export function Agents() {
  const [profileId, setProfileId] = useState("research");
  const [prompt, setPrompt] = useState("");
  const [selected, setSelected] = useState<string>();
  const profiles = useQuery({
    queryKey: ["profiles"],
    queryFn: () =>
      api<(AgentProfile & { skills: string[] })[]>("agents/profiles"),
  });
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: () => api<Page<Run>>("agent-runs"),
    refetchInterval: 4000,
  });
  const profile = profiles.data?.find((p) => p.id === profileId);
  const run = runs.data?.items.find((r) => r.id === selected);
  const steps = useQuery({
    queryKey: ["run-steps", selected],
    enabled: !!selected,
    queryFn: () =>
      api<
        {
          id: string;
          name: string;
          state: "input-available" | "output-available" | "output-error";
          output: string | null;
        }[]
      >(`agent-runs/${selected}/steps`),
    refetchInterval:
      run && ["queued", "running"].includes(run.state) ? 3000 : false,
  });
  const [runIntent] = useState(() => new RetainedRequestIntent());
  const [cancelIntent] = useState(() => new RetainedRequestIntent());
  const client = useQueryClient();
  const send = useMutation({
    mutationFn: (submission: { profile: string; prompt: string }) => {
      const target = "agent-runs";
      const body = submission;
      const intent = runIntent.forRequest("POST", target, body);
      return api<Run>("agent-runs", {
        method: "POST",
        body,
        key: intent.key,
      });
    },
    onSuccess: (r, submission) => {
      runIntent.confirmRequest("POST", "agent-runs", submission);
      client.invalidateQueries({ queryKey: ["runs"] });
      setSelected(r.id);
      setPrompt((current) => (current === submission.prompt ? "" : current));
      toast.success("Your agent run is queued");
    },
    onError: (e) => toast.error(e.message),
  });
  const cancel = useMutation({
    mutationFn: (r: Run) => {
      const target = `agent-runs/${r.id}/cancel`;
      const body = { expected_version: r.row_version };
      const intent = cancelIntent.forRequest("POST", target, body);
      return api(target, {
        method: "POST",
        body,
        key: intent.key,
      });
    },
    onSuccess: (_result, r) => {
      cancelIntent.confirmRequest("POST", `agent-runs/${r.id}/cancel`, {
        expected_version: r.row_version,
      });
      client.invalidateQueries();
      toast.success(
        "Cancellation recorded. An in-flight call may finish, but its result cannot update this run.",
      );
    },
    onError: (e) => toast.error(e.message),
  });
  return (
    <>
      <PageHeading
        title="Agents"
        description="Research, drafts, and a record of each run."
      />
      <div className="grid min-h-[620px] grid-cols-1 border-y border-border lg:grid-cols-[240px_minmax(0,1fr)]">
        <aside className="border-b border-border bg-card/40 p-4 lg:border-r lg:border-b-0">
          <Button
            variant="outline"
            className="mb-5 w-full"
            onClick={() => setSelected(undefined)}
          >
            <Sparkles />
            New run
          </Button>
          <p className="mb-3 px-2 text-[10px] tracking-wider text-muted-foreground">
            RECENT RUNS
          </p>
          <div className="flex flex-col gap-1">
            {runs.error ? (
              <ErrorState
                error={runs.error}
                retry={() => void runs.refetch()}
              />
            ) : null}
            {runs.isPending && !runs.data ? (
              <LoadingRows />
            ) : runs.data?.items.length === 0 ? (
              <p className="px-2 py-4 text-xs leading-6 text-muted-foreground">
                Your conversations and their outcomes will live here.
              </p>
            ) : runs.data ? (
              runs.data.items.map((r) => (
                <button
                  key={r.id}
                  className={cn(
                    "flex flex-col gap-2 rounded-lg p-3 text-left hover:bg-muted",
                    selected === r.id && "bg-muted",
                  )}
                  onClick={() => setSelected(r.id)}
                >
                  <span className="line-clamp-2 text-xs leading-5">
                    {r.title}
                  </span>
                  <span className="flex w-full items-center justify-between">
                    <span className="text-[10px] text-muted-foreground">
                      {dateLabel(r.created_at)}
                    </span>
                    <Status value={r.state} />
                  </span>
                </button>
              ))
            ) : null}
          </div>
        </aside>
        <div className="flex min-w-0 flex-col">
          {run ? (
            <div className="flex-1 p-6 md:p-9">
              <div className="mb-7 flex items-center gap-3">
                <Bot className="size-5 text-primary" />
                <p className="text-sm font-medium">
                  {profiles.data?.find((p) => p.id === run.profile)?.name ??
                    run.profile}
                </p>
                <Status value={run.state} />
                {["queued", "running"].includes(run.state) && (
                  <Button
                    className="ml-auto"
                    size="sm"
                    variant="ghost"
                    disabled={cancel.isPending}
                    onClick={() => cancel.mutate(run)}
                  >
                    <CircleStop />
                    Cancel
                  </Button>
                )}
              </div>
              <Conversation className="max-h-[65vh] min-h-60">
                <ConversationContent className="gap-6 p-0 pb-12">
                  <Message from="user">
                    <MessageContent className="whitespace-pre-wrap">
                      {run.prompt}
                    </MessageContent>
                  </Message>
                  {steps.error ? (
                    <ErrorState
                      error={steps.error}
                      retry={() => void steps.refetch()}
                    />
                  ) : null}
                  {steps.isPending && !steps.data ? (
                    <p className="text-sm text-muted-foreground" role="status">
                      Loading run steps…
                    </p>
                  ) : steps.data?.length === 0 ? (
                    <p className="text-sm text-muted-foreground">
                      No steps were recorded for this run.
                    </p>
                  ) : null}
                  {steps.data?.map((step) => (
                    <Tool key={step.id} className="mb-0">
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
                          <p className="text-sm text-muted-foreground">
                            {run.state === "running"
                              ? "Waiting for the tool result…"
                              : "No result was recorded for this step."}
                          </p>
                        )}
                      </ToolContent>
                    </Tool>
                  ))}
                  {run.output ? (
                    <Message from="assistant">
                      <MessageContent>
                        <RichAgentResponse>{run.output}</RichAgentResponse>
                      </MessageContent>
                    </Message>
                  ) : ["queued", "running"].includes(run.state) ? (
                    <div className="mt-8 flex items-center gap-3 text-sm text-muted-foreground">
                      <Clock3 className="size-4 animate-pulse" />
                      {run.state === "queued"
                        ? "Waiting for a worker. Your request is saved."
                        : "Your agent is working. This page updates automatically."}
                    </div>
                  ) : (
                    <p className="mt-8 text-sm text-muted-foreground">
                      {run.state === "failed"
                        ? runFailureMessage(run.error_code)
                        : "This run was cancelled."}
                    </p>
                  )}
                </ConversationContent>
                <ConversationScrollButton />
              </Conversation>
            </div>
          ) : (
            <div className="flex flex-1 flex-col items-center justify-center px-6 py-12 text-center">
              <span className="mb-5 flex size-14 items-center justify-center rounded-2xl border border-primary/20 bg-primary/10 text-primary">
                <Sparkles className="size-6" />
              </span>
              <h2 className="text-2xl font-medium tracking-tight">
                Start a request
              </h2>
              <p className="mt-3 max-w-md text-sm leading-6 text-muted-foreground">
                Choose a profile, then describe the research or draft you need.
              </p>
              <div className="mt-8 grid max-w-xl gap-3 sm:grid-cols-2">
                {[
                  {
                    icon: BookOpen,
                    text: "Research a company",
                    prompt:
                      "Help me research a company. Ask me which company and what I want to learn first.",
                  },
                  {
                    icon: FileText,
                    text: "Draft an introduction",
                    prompt:
                      "Help me write a concise introduction. Ask for my background and the audience before drafting.",
                  },
                ].map((item) => (
                  <button
                    key={item.text}
                    onClick={() => setPrompt(item.prompt)}
                    className="rounded-xl border border-border bg-card p-4 text-left text-xs leading-6 text-muted-foreground transition-colors hover:border-primary/30 hover:text-foreground"
                  >
                    <item.icon className="mb-3 size-4 text-primary" />
                    {item.text}
                  </button>
                ))}
              </div>
            </div>
          )}
          <form
            className="border-t border-border bg-card/40 p-5 md:px-8"
            onSubmit={(e) => {
              e.preventDefault();
              if (profile?.ready && prompt.trim())
                send.mutate({ profile: profileId, prompt });
            }}
          >
            <div className="mb-3 flex flex-wrap items-center gap-3">
              <Select value={profileId} onValueChange={setProfileId}>
                <SelectTrigger className="min-w-44" aria-label="Choose agent">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {profiles.data?.map((p) => (
                      <SelectItem key={p.id} value={p.id}>
                        {p.name}
                        {p.ready ? "" : " · setup required"}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
              <span className="text-[10px] text-muted-foreground">
                {profile ? `${label(profile.provider)} · ${profile.model}` : ""}
                {profile ? ` · ${profile.tools.length} scoped tools` : ""}
              </span>
              {profile?.skills.map((skill) => (
                <Badge
                  variant="outline"
                  key={skill}
                  className="font-normal text-muted-foreground"
                >
                  {label(skill)} skill
                </Badge>
              ))}
            </div>
            <div className="relative">
              <Textarea
                aria-label="Message your agent"
                placeholder="Give your agent a focused task…"
                required
                maxLength={20000}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                rows={3}
                className="resize-none bg-background pr-14"
              />
              <Button
                aria-label="Run agent"
                size="icon"
                type="submit"
                className="absolute right-3 bottom-3"
                disabled={
                  !prompt.trim() ||
                  send.isPending ||
                  profiles.isPending ||
                  !!profiles.error ||
                  !profile?.ready
                }
              >
                {send.isPending ? <Spinner /> : <ArrowUp />}
              </Button>
            </div>
            <div className="mt-3 flex flex-wrap justify-between gap-2 text-[10px] text-muted-foreground">
              <span>
                Skills and tool grants are pinned to each run.{" "}
                <Link href="/memory" className="underline underline-offset-2">
                  Manage memory
                </Link>
              </span>
              <span>
                {profile && !profile.ready ? (
                  <Link href="/settings" className="text-[var(--status-amber)]">
                    Configure {profile.missing_credentials.join(", ")} to start
                  </Link>
                ) : (
                  "Runs use your configured provider account."
                )}
              </span>
            </div>
            {profiles.isPending && !profiles.data ? (
              <p className="mt-3 text-xs text-muted-foreground" role="status">
                Loading agent profiles…
              </p>
            ) : null}
            {profiles.error ? (
              <ErrorState
                error={profiles.error}
                retry={() => void profiles.refetch()}
              />
            ) : null}
          </form>
        </div>
      </div>
    </>
  );
}
