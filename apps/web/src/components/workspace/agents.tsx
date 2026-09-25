"use client";
import { AnimatedIcon } from "@/components/ui/animated-icon";
import { useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  ArrowUp,
  Bot,
  BookOpen,
  FileText,
  Sparkles,
  PanelLeftClose,
  PanelLeftOpen,
  Settings2,
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
  ApiError,
  dateLabel,
  label,
  type AgentProfile,
  type AgentMessage,
  type AgentSession,
  type ModelProvider,
  type Page,
  type Run,
} from "@/lib/api";
import { ModelSwitcher } from "./model-switcher";
import { RetainedRequestIntent } from "@/lib/retained-intent";
import { submitChatOnEnter } from "@/lib/submit-chat-on-enter";
import { cn } from "@/lib/utils";
import { usePanelOpen } from "@/hooks/use-panel-open";
import { useIsMobile } from "@/hooks/use-mobile";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import {
  Conversation,
  ConversationContent,
  ConversationScrollButton,
} from "@/components/ai-elements/conversation";
import { Message, MessageContent } from "@/components/ai-elements/message";
import { deferView } from "./deferred-view";
import { RunActivity } from "./run-activity";
import { AnswerReuseNotice } from "./answer-reuse-notice";
import {
  appendSavedMessage,
  sessionMessageKey,
  useSessionMessages,
} from "./use-session-messages";
import { activeRunStates, useSessionRuns } from "./use-session-runs";
import { ErrorState, LoadingRows, Spinner, Status } from "./primitives";

const RichAgentResponse = deferView<{ children: string }>(
  () =>
    import("./agent-response").then((module) => ({
      default: module.AgentResponse,
    })),
  "rich agent response",
);

export function Agents() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const selectedSessionId =
    params?.get("session") ?? params?.get("conversation") ?? undefined;
  const legacyRunId = params?.get("run") ?? undefined;
  const [showLegacy, setShowLegacy] = useState(false);
  const [historyOpen, setHistoryOpen] = usePanelOpen("chat-history");
  const [historyMobileOpen, setHistoryMobileOpen] = useState(false);
  const historyToggle = useRef<HTMLButtonElement>(null);
  const isMobile = useIsMobile();
  const historyExpanded = isMobile ? historyMobileOpen : historyOpen;
  const selectConversation = (sessionId?: string, runId?: string) => {
    setHistoryMobileOpen(false);
    const next = new URLSearchParams(params?.toString());
    next.delete("session");
    next.delete("conversation");
    next.delete("run");
    if (sessionId) next.set("session", sessionId);
    else if (runId) next.set("run", runId);
    router.push(`${pathname ?? "/"}${next.size ? `?${next}` : ""}`, {
      scroll: false,
    });
  };
  const [profileId, setProfileId] = useState(params?.get("agent") ?? "lead");
  const [prompt, setPrompt] = useState("");
  const [customProvider, setCustomProvider] = useState<ModelProvider>();
  const [customModel, setCustomModel] = useState<string>();
  const profiles = useQuery({
    queryKey: ["profiles"],
    queryFn: () =>
      api<(AgentProfile & { skills: string[] })[]>("agents/profiles"),
  });
  const sessions = useInfiniteQuery({
    queryKey: ["agent-sessions", "history"],
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) =>
      api<Page<AgentSession>>(
        `agent-sessions?standalone=true&limit=30&offset=${pageParam}`,
        { signal },
      ),
    getNextPageParam: (page) =>
      page.offset + page.items.length < page.total
        ? page.offset + page.items.length
        : undefined,
    refetchInterval: 30_000,
  });
  const legacy = useInfiniteQuery({
    queryKey: ["runs", "legacy-history"],
    enabled: showLegacy,
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) =>
      api<Page<Run>>(`agent-runs?limit=30&offset=${pageParam}`, { signal }),
    getNextPageParam: (page) =>
      page.offset + page.items.length < page.total
        ? page.offset + page.items.length
        : undefined,
  });
  const legacyRun = useQuery({
    queryKey: ["agent-run", legacyRunId],
    enabled: !!legacyRunId,
    queryFn: ({ signal }) => api<Run>(`agent-runs/${legacyRunId}`, { signal }),
    refetchInterval: (query) =>
      query.state.data && activeRunStates.has(query.state.data.state)
        ? 10_000
        : false,
  });
  const sessionId =
    selectedSessionId ?? legacyRun.data?.session_id ?? undefined;
  const session = useQuery({
    queryKey: ["agent-session", sessionId],
    enabled: !!sessionId,
    queryFn: ({ signal }) =>
      api<AgentSession>(`agent-sessions/${sessionId}`, { signal }),
  });
  const runs = useSessionRuns(sessionId, 1);
  const run = runs.data?.items[0] ?? (legacyRunId ? legacyRun.data : undefined);
  const [profileScope, setProfileScope] = useState<string>();
  const conversationScope = sessionId ?? legacyRunId ?? "new";
  const profile = profiles.data?.find(
    (p) =>
      p.id ===
      (run &&
      (activeRunStates.has(run.state) || profileScope !== conversationScope)
        ? run.profile
        : profileId),
  );
  const activeProvider = customProvider ?? profile?.provider ?? "openai";
  const activeModel = customModel ?? profile?.model ?? "gpt-5-mini";
  const transcript = useSessionMessages(
    sessionId,
    !!run && activeRunStates.has(run.state),
  );
  const threads = [
    ...new Map(
      sessions.data?.pages
        .flatMap((page) => page.items)
        .map((item) => [item.id, item]) ?? [],
    ).values(),
  ];
  const [runIntent] = useState(() => new RetainedRequestIntent());
  const [cancelIntent] = useState(() => new RetainedRequestIntent());
  const client = useQueryClient();
  const send = useMutation({
    mutationFn: async (submission: {
      profile: string;
      prompt: string;
      provider?: ModelProvider;
      model?: string;
      sessionId?: string;
      legacyRunId?: string;
      fresh_answer?: boolean;
    }) => {
      if (submission.legacyRunId && !submission.sessionId) {
        const body = {
          profile: submission.profile,
          prompt: submission.prompt,
          provider: submission.provider,
          model: submission.model,
          continue_run_id: submission.legacyRunId,
        };
        const intent = runIntent.forRequest("POST", "agent-runs", body);
        const adopted = await api<Run>("agent-runs", {
          method: "POST",
          body,
          key: intent.key,
        });
        runIntent.confirmRequest("POST", "agent-runs", body);
        return { adopted };
      }
      let target = submission.sessionId;
      if (!target) {
        const body = { title: submission.prompt.slice(0, 300) };
        const intent = runIntent.forRequest("POST", "agent-sessions", body);
        const created = await api<AgentSession>("agent-sessions", {
          method: "POST",
          body,
          key: intent.key,
        });
        runIntent.confirmRequest("POST", "agent-sessions", body);
        client.setQueryData(["agent-session", created.id], created);
        target = created.id;
        selectConversation(target);
      }
      const endpoint = `agent-sessions/${target}/messages`;
      const body = {
        content: submission.prompt,
        profile: submission.profile,
        provider: submission.provider,
        model: submission.model,
        ...(submission.fresh_answer ? { fresh_answer: true } : {}),
      };
      const intent = runIntent.forRequest("POST", endpoint, body);
      const message = await api<AgentMessage>(endpoint, {
        method: "POST",
        body,
        key: intent.key,
      });
      runIntent.confirmRequest("POST", endpoint, body);
      return { message };
    },
    onSuccess: (result, submission) => {
      const savedSessionId =
        result.message?.session_id ?? result.adopted?.session_id;
      if (result.message) appendSavedMessage(client, result.message);
      if (savedSessionId) {
        selectConversation(savedSessionId);
        void client.invalidateQueries({
          queryKey: sessionMessageKey(savedSessionId),
        });
        void client.invalidateQueries({
          queryKey: ["agent-session-runs", savedSessionId],
        });
      } else if (result.adopted)
        selectConversation(undefined, result.adopted.id);
      void client.invalidateQueries({ queryKey: ["agent-sessions"] });
      void client.invalidateQueries({ queryKey: ["runs"] });
      setPrompt((current) => (current === submission.prompt ? "" : current));
      toast.success("Message saved to your conversation");
    },
    onError: (e) => toast.error(e.message),
  });
  const cancel = useMutation({
    mutationFn: async (run: Run) => {
      const post = async (fresh: Run) => {
        const target = `agent-runs/${fresh.id}/cancel`;
        const body = { expected_version: fresh.row_version };
        const intent = cancelIntent.forRequest("POST", target, body);
        await api<Run>(target, { method: "POST", body, key: intent.key });
        return { target, body };
      };
      try {
        return await post(await api<Run>(`agent-runs/${run.id}`));
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 409) throw error;
        return post(await api<Run>(`agent-runs/${run.id}`));
      }
    },
    onSuccess: ({ target, body }) => {
      cancelIntent.confirmRequest("POST", target, body);
      client.invalidateQueries();
      toast.success(
        "Cancellation recorded. An in-flight call may finish, but its result cannot update this run.",
      );
    },
    onError: (e) => toast.error(e.message),
  });
  const canSend =
    !!prompt.trim() &&
    !send.isPending &&
    !profiles.isPending &&
    !profiles.error &&
    !!profile?.ready;

  const history = (
    <div className="min-h-0 overflow-y-auto p-3">
      <p className="mb-3 px-2 text-[10px] tracking-wider text-muted-foreground">
        RECENT CONVERSATIONS
      </p>
      <div className="flex flex-col gap-1">
        {sessions.error ? (
          <ErrorState
            error={sessions.error}
            retry={() => void sessions.refetch()}
          />
        ) : null}
        {sessions.isPending ? (
          <LoadingRows />
        ) : !threads.length ? (
          <p className="px-2 py-4 text-xs leading-6 text-muted-foreground">
            Your conversations and their outcomes will live here.
          </p>
        ) : (
          threads.map((thread) => (
            <button
              key={thread.id}
              disabled={send.isPending}
              aria-current={sessionId === thread.id ? "true" : undefined}
              className={cn(
                "flex flex-col gap-2 rounded-lg p-3 text-start hover:bg-muted",
                sessionId === thread.id && "bg-muted",
              )}
              onClick={() => {
                selectConversation(thread.id);
                setCustomProvider(undefined);
                setCustomModel(undefined);
              }}
            >
              <span className="line-clamp-2 text-xs leading-5">
                {thread.title}
              </span>
              <span className="hidden text-[10px] text-muted-foreground xl:inline">
                {dateLabel(thread.updated_at)}
              </span>
            </button>
          ))
        )}
        {sessions.hasNextPage ? (
          <Button
            variant="ghost"
            size="sm"
            disabled={sessions.isFetchingNextPage}
            onClick={() => void sessions.fetchNextPage()}
          >
            Load more conversations
          </Button>
        ) : null}
        <details
          className="mt-4"
          onToggle={(event) => setShowLegacy(event.currentTarget.open)}
        >
          <summary className="cursor-pointer px-2 text-xs text-muted-foreground">
            Earlier runs
          </summary>
          {showLegacy ? (
            <div className="mt-2 flex flex-col gap-1">
              {legacy.error ? (
                <ErrorState
                  error={legacy.error}
                  retry={() => void legacy.refetch()}
                />
              ) : null}
              {legacy.isPending ? <LoadingRows /> : null}
              {legacy.data?.pages
                .flatMap((page) => page.items)
                .filter((item) => !item.session_id)
                .map((item) => (
                  <button
                    key={item.id}
                    disabled={send.isPending}
                    className="rounded-lg p-3 text-start text-xs hover:bg-muted"
                    onClick={() => selectConversation(undefined, item.id)}
                  >
                    {item.title}
                  </button>
                ))}
              {legacy.hasNextPage ? (
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={legacy.isFetchingNextPage}
                  onClick={() => void legacy.fetchNextPage()}
                >
                  Load earlier runs
                </Button>
              ) : null}
            </div>
          ) : null}
        </details>
      </div>
    </div>
  );

  return (
    <section
      aria-label="Chat workspace"
      className="flex min-h-0 flex-1 flex-col overflow-hidden"
    >
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border px-3 py-3 md:px-6">
        <Button
          variant="ghost"
          size="sm"
          aria-label="Toggle conversation history"
          ref={historyToggle}
          aria-expanded={historyExpanded}
          aria-controls={isMobile ? undefined : "chat-history"}
          title={historyExpanded ? "Hide conversations" : "Show conversations"}
          onClick={() =>
            isMobile
              ? setHistoryMobileOpen(!historyMobileOpen)
              : setHistoryOpen(!historyOpen)
          }
        >
          <AnimatedIcon state={historyExpanded}>
            {historyExpanded ? <PanelLeftClose /> : <PanelLeftOpen />}
          </AnimatedIcon>
          Chats
        </Button>
        <h1 className="min-w-0 break-words text-lg font-medium">Assistant</h1>
        <div className="ms-auto flex max-w-full flex-wrap items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={send.isPending}
            onClick={() => selectConversation()}
          >
            <Sparkles />
            New chat
          </Button>
          <Button variant="ghost" size="icon-sm" asChild>
            <Link
              href="/agent-settings"
              aria-label="Configure agents"
              title="Configure agents"
            >
              <Settings2 />
            </Link>
          </Button>
        </div>
      </div>
      <Sheet
        open={isMobile && historyMobileOpen}
        onOpenChange={setHistoryMobileOpen}
      >
        <SheetContent
          side="left"
          className="w-72 gap-0"
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            historyToggle.current?.focus();
          }}
        >
          <SheetHeader>
            <SheetTitle>Conversations</SheetTitle>
            <SheetDescription>Reopen a saved conversation.</SheetDescription>
          </SheetHeader>
          {history}
        </SheetContent>
      </Sheet>
      <div
        className={cn(
          "grid min-h-0 flex-1 grid-cols-1 overflow-hidden",
          !isMobile && historyOpen && "md:grid-cols-[220px_minmax(0,1fr)]",
        )}
      >
        {!isMobile && historyOpen && (
          <aside
            id="chat-history"
            aria-label="Conversation history"
            className="min-h-0 overflow-y-auto border-e border-border bg-card/40"
          >
            {history}
          </aside>
        )}

        <div className="flex min-h-0 min-w-0 flex-col">
          {sessionId || legacyRunId ? (
            <div className="flex min-h-0 flex-1 flex-col">
              <Conversation key={sessionId ?? legacyRunId} className="min-h-0">
                <ConversationContent className="mx-auto w-full max-w-4xl gap-6 px-4 py-5 md:px-8">
                  <div className="flex shrink-0 items-start gap-3">
                    <Bot className="size-5 shrink-0 text-primary" />
                    <p className="min-w-0 break-words text-sm font-medium">
                      {session.data?.title ?? run?.title ?? "Conversation"}
                    </p>
                    {run ? <Status value={run.state} /> : null}
                  </div>
                  {session.error ? (
                    <ErrorState
                      error={session.error}
                      retry={() => void session.refetch()}
                    />
                  ) : null}
                  {legacyRun.error && legacyRunId ? (
                    <ErrorState
                      error={legacyRun.error}
                      retry={() => void legacyRun.refetch()}
                    />
                  ) : null}
                  {runs.error ? (
                    <ErrorState
                      error={runs.error}
                      retry={() => void runs.refetch()}
                    />
                  ) : null}

                  {sessionId ? (
                    <>
                      {transcript.isPending && (
                        <p
                          className="text-sm text-muted-foreground"
                          role="status"
                        >
                          Loading conversation…
                        </p>
                      )}
                      {transcript.error && (
                        <ErrorState
                          error={transcript.error}
                          retry={() => void transcript.refetch()}
                        />
                      )}
                      {transcript.data?.items.map((message) => (
                        <Message key={message.id} from={message.author}>
                          <MessageContent className="whitespace-pre-wrap">
                            {message.author === "assistant" ? (
                              <RichAgentResponse>
                                {message.content}
                              </RichAgentResponse>
                            ) : (
                              message.content
                            )}
                          </MessageContent>
                          <AnswerReuseNotice
                            message={message}
                            disabled={
                              send.isPending ||
                              (!!run && activeRunStates.has(run.state))
                            }
                            onFresh={() => {
                              const original = transcript.data?.items.findLast(
                                (item) =>
                                  item.author === "user" &&
                                  item.sequence < message.sequence,
                              );
                              if (original)
                                send.mutate({
                                  profile: message.profile,
                                  prompt: original.content,
                                  provider: activeProvider,
                                  model: activeModel,
                                  sessionId,
                                  fresh_answer: true,
                                });
                            }}
                          />
                        </Message>
                      ))}
                    </>
                  ) : run ? (
                    <Message from="user">
                      <MessageContent className="whitespace-pre-wrap">
                        {run.prompt}
                      </MessageContent>
                    </Message>
                  ) : null}
                  {run ? (
                    <RunActivity
                      key={run.id}
                      run={run}
                      showOutput={
                        !transcript.data?.items.some(
                          (message) =>
                            message.run_id === run.id &&
                            message.author === "assistant",
                        )
                      }
                      deferDetails={!activeRunStates.has(run.state)}
                      cancelling={cancel.isPending}
                      onCancel={(item) => cancel.mutate(item)}
                    />
                  ) : runs.isPending ? (
                    <p role="status" className="text-sm text-muted-foreground">
                      Loading saved activity…
                    </p>
                  ) : null}
                </ConversationContent>
                <ConversationScrollButton />
              </Conversation>
            </div>
          ) : (
            <div className="flex min-h-0 flex-1 flex-col items-center overflow-y-auto px-6 py-6 text-center sm:justify-center-safe">
              <h2 className="text-2xl font-medium tracking-tight">
                What would you like to work on?
              </h2>
              <p className="mt-3 max-w-md text-sm leading-6 text-muted-foreground">
                Ask a question, develop an idea, or make progress on your work.
                Command Center can bring in the right tools and specialists.
              </p>
              <div className="mt-5 flex max-w-xl flex-wrap justify-center gap-2">
                {[
                  {
                    icon: BookOpen,
                    text: "Research a company",
                    prompt:
                      "Help me research a company. Ask me which company and what I want to learn first.",
                  },
                  {
                    icon: FileText,
                    text: "Save a lead from pasted text",
                    prompt:
                      "Help me save a lead from a message or page. I’ll paste the source text next.",
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
                    className="inline-flex items-center gap-2 rounded-md border border-border px-3 py-2 text-start text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  >
                    <item.icon className="size-3.5" />
                    {item.text}
                  </button>
                ))}
              </div>
            </div>
          )}
          <form
            aria-label="Chat composer"
            className="flex max-h-[75%] shrink-0 flex-col overflow-y-auto border-t border-border bg-background px-3 py-3 md:px-6"
            onSubmit={(e) => {
              e.preventDefault();
              if (canSend)
                send.mutate({
                  profile: profile?.id ?? profileId,
                  prompt,
                  provider: activeProvider,
                  model: activeModel,
                  sessionId,
                  legacyRunId,
                });
            }}
          >
            <div className="mb-3 flex shrink-0 flex-wrap items-center gap-2.5">
              <Select
                value={profile?.id ?? profileId}
                disabled={!!run && activeRunStates.has(run.state)}
                onValueChange={(id) => {
                  setProfileId(id);
                  setProfileScope(conversationScope);
                  setCustomProvider(undefined);
                  setCustomModel(undefined);
                }}
              >
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
                {profile ? `· ${profile.tools.length} scoped tools` : ""}
              </span>
              {profile?.skills.map((skill) => (
                <Badge
                  variant="outline"
                  key={skill}
                  className="hidden font-normal text-muted-foreground xl:inline-flex"
                >
                  {label(skill)} skill
                </Badge>
              ))}
            </div>
            <div className="flex min-h-0 flex-col rounded-2xl border border-input bg-muted/20 transition-shadow focus-within:border-ring focus-within:ring-2 focus-within:ring-ring/20">
              <Textarea
                aria-label="Message your agent"
                placeholder={
                  sessionId || legacyRunId
                    ? "Continue this conversation…"
                    : "Ask Command Center…"
                }
                required
                maxLength={20000}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                onKeyDown={submitChatOnEnter}
                rows={2}
                className="max-h-40 min-h-12 resize-none overflow-y-auto rounded-t-2xl border-0 bg-transparent px-4 pt-3 shadow-none focus-visible:ring-0 dark:bg-transparent"
              />
              <div
                role="group"
                aria-label="Message actions"
                className="sticky bottom-0 z-10 flex min-w-0 shrink-0 items-center justify-end gap-2 rounded-b-2xl bg-background px-3 pt-1 pb-3"
              >
                {profile && (
                  <ModelSwitcher
                    disabled={!!run && activeRunStates.has(run.state)}
                    provider={activeProvider}
                    model={activeModel}
                    onSelect={(p, m) => {
                      setCustomProvider(p);
                      setCustomModel(m);
                    }}
                  />
                )}
                <Button
                  aria-label="Run agent"
                  size="icon"
                  type="submit"
                  className="size-9 shrink-0 rounded-full"
                  disabled={!canSend}
                >
                  <AnimatedIcon state={send.isPending}>
                    {send.isPending ? <Spinner /> : <ArrowUp />}
                  </AnimatedIcon>
                </Button>
              </div>
            </div>
            <div className="mt-2 hidden flex-wrap justify-between gap-2 text-[10px] text-muted-foreground md:flex">
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
    </section>
  );
}
