"use client";

import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUp, MessagesSquare } from "lucide-react";
import { Button } from "@/components/ui/button";
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
  Conversation,
  ConversationContent,
  ConversationScrollButton,
} from "@/components/ai-elements/conversation";
import {
  Message,
  MessageContent,
  MessageResponse,
} from "@/components/ai-elements/message";
import {
  api,
  ApiError,
  label,
  type AgentMessage,
  type AgentProfile,
  type AgentSession,
  type Page,
  type Run,
} from "@/lib/api";
import { ErrorState, LoadingRows, Spinner, Status } from "./primitives";
import { RunActivity } from "./run-activity";

const activeStates = new Set(["queued", "running"]);
const messagePageSize = 100;

export function WorkConversation({
  resource,
  recordId,
  disabledReason,
}: {
  resource: "tasks" | "opportunities";
  recordId: string;
  disabledReason?: string;
}) {
  const queryClient = useQueryClient();
  const scopeField = resource === "tasks" ? "task_id" : "opportunity_id";
  const sessionKey = ["agent-session", resource, recordId] as const;
  const [draft, setDraft] = useState("");
  const [profileId, setProfileId] = useState("lead");
  const [sendError, setSendError] = useState<Error>();
  const [cancelError, setCancelError] = useState<Error>();
  const [savedNotice, setSavedNotice] = useState("");
  const sessionReceipt = useRef("");
  const messageReceipt = useRef({ signature: "", value: "" });

  const profiles = useQuery({
    queryKey: ["agent-profiles"],
    queryFn: () => api<AgentProfile[]>("agents/profiles"),
  });
  const sessionQuery = useQuery({
    queryKey: sessionKey,
    queryFn: () =>
      api<Page<AgentSession>>(
        `agent-sessions?${scopeField}=${recordId}&limit=1`,
      ),
  });
  const session = sessionQuery.data?.items[0];
  const messageKey = ["agent-session-messages", session?.id] as const;
  const messages = useQuery({
    queryKey: messageKey,
    enabled: !!session,
    queryFn: async () => {
      const cached =
        queryClient.getQueryData<Page<AgentMessage>>(messageKey)?.items ?? [];
      const merged = [...cached];
      let cursor = merged.at(-1)?.sequence ?? 0;
      let page: Page<AgentMessage>;
      do {
        page = await api<Page<AgentMessage>>(
          `agent-sessions/${session!.id}/messages?after_sequence=${cursor}&limit=${messagePageSize}`,
        );
        for (const item of page.items) {
          if (!merged.some((message) => message.id === item.id))
            merged.push(item);
        }
        cursor = page.items.at(-1)?.sequence ?? cursor;
      } while (page.items.length === messagePageSize);
      merged.sort((a, b) => a.sequence - b.sequence);
      return {
        items: merged,
        total: Math.max(page.total, merged.length),
        limit: messagePageSize,
        offset: 0,
      };
    },
    refetchInterval: 2500,
  });
  const runs = useQuery({
    queryKey: ["agent-session-runs", session?.id],
    enabled: !!session,
    queryFn: () =>
      api<Page<Run>>(`agent-sessions/${session!.id}/runs?limit=30`),
    refetchInterval: 2500,
  });
  const activeRuns =
    runs.data?.items.filter((run) => activeStates.has(run.state)) ?? [];
  const activeRun = activeRuns[0];

  const addressedProfileId = activeRun?.profile ?? profileId;
  const selectedProfile =
    profiles.data?.find((profile) => profile.id === addressedProfileId) ??
    profiles.data?.[0];

  const send = useMutation({
    mutationFn: async () => {
      const content = draft;
      const profile = selectedProfile?.id ?? profileId;
      let target = session;
      if (!target) {
        if (!sessionReceipt.current)
          sessionReceipt.current = crypto.randomUUID();
        target = await api<AgentSession>("agent-sessions", {
          method: "POST",
          body: { [scopeField]: recordId },
          key: sessionReceipt.current,
        });
        queryClient.setQueryData<Page<AgentSession>>(sessionKey, {
          items: [target],
          total: 1,
          limit: 1,
          offset: 0,
        });
      }
      const signature = `${target.id}\u0000${profile}\u0000${content}`;
      if (messageReceipt.current.signature !== signature) {
        messageReceipt.current = {
          signature,
          value: crypto.randomUUID(),
        };
      }
      const wasActive = !!activeRun;
      const message = await api<AgentMessage>(
        `agent-sessions/${target.id}/messages`,
        {
          method: "POST",
          body: { content, profile },
          key: messageReceipt.current.value,
        },
      );
      return { message, target, wasActive, submittedContent: content };
    },
    onSuccess: ({ target, wasActive, submittedContent }) => {
      setDraft((current) => (current === submittedContent ? "" : current));
      setSendError(undefined);
      setSavedNotice(
        wasActive
          ? "Instruction saved. It will be applied at the next safe stopping point."
          : "Message saved. Work is now queued.",
      );
      sessionReceipt.current = "";
      messageReceipt.current = { signature: "", value: "" };
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: messageKey }),
        queryClient.invalidateQueries({
          queryKey: ["agent-session-runs", target.id],
        }),
        queryClient.invalidateQueries({ queryKey: sessionKey }),
      ]);
    },
    onError: (error) => setSendError(error),
  });

  const cancel = useMutation({
    mutationFn: async (run: Run) => {
      const postCancel = (fresh: Run) =>
        api<Run>(`agent-runs/${fresh.id}/cancel`, {
          method: "POST",
          body: { expected_version: fresh.row_version },
          key: crypto.randomUUID(),
        });
      let fresh = await api<Run>(`agent-runs/${run.id}`);
      try {
        return await postCancel(fresh);
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 409) throw error;
        fresh = await api<Run>(`agent-runs/${run.id}`);
        return postCancel(fresh);
      }
    },
    onSuccess: () => {
      setCancelError(undefined);
      setSavedNotice(
        "Cancellation recorded. Completed activity remains available.",
      );
      void queryClient.invalidateQueries({
        queryKey: ["agent-session-runs", session?.id],
      });
    },
    onError: (error) => setCancelError(error),
  });

  const profileReady = selectedProfile?.ready === true;
  const contentReady = !!draft.trim() && draft.length <= 20_000;
  const canSend =
    !disabledReason && profileReady && contentReady && !send.isPending;
  const assistantRunIds = new Set(
    messages.data?.items
      .filter((message) => message.author === "assistant" && message.run_id)
      .map((message) => message.run_id) ?? [],
  );
  const consumedSequence = Math.max(
    0,
    ...(runs.data?.items.map((run) => run.consumed_sequence) ?? []),
  );

  return (
    <div className="flex min-w-0 flex-col gap-5 py-5">
      <div className="flex flex-wrap items-center gap-2 px-6">
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-medium">Work conversation</h3>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            Messages and outcomes stay with this{" "}
            {resource === "tasks" ? "task" : "opportunity"}.
          </p>
        </div>
        {activeRuns.length ? (
          <span className="text-xs text-muted-foreground">
            {activeRuns.length} active run{activeRuns.length === 1 ? "" : "s"}
          </span>
        ) : null}
      </div>

      {disabledReason ? (
        <p className="mx-6 rounded-md border border-border bg-muted/50 p-3 text-xs leading-5 text-muted-foreground">
          {disabledReason}
        </p>
      ) : selectedProfile && !profileReady ? (
        <p className="mx-6 rounded-md border border-border bg-muted/50 p-3 text-xs leading-5 text-muted-foreground">
          {selectedProfile.name} is unavailable. Configure{" "}
          {selectedProfile.missing_credentials.join(", ")} in Settings before
          starting work.
        </p>
      ) : null}

      {sessionQuery.error ? (
        <div className="px-6">
          <ErrorState
            error={sessionQuery.error}
            retry={() => sessionQuery.refetch()}
          />
        </div>
      ) : sessionQuery.isPending ? (
        <div className="px-6">
          <LoadingRows />
        </div>
      ) : (
        <>
          <Conversation className="max-h-[52vh] min-h-52 border-y border-border">
            <ConversationContent className="gap-5 px-6 py-5">
              {messages.error ? (
                <ErrorState
                  error={messages.error}
                  retry={() => messages.refetch()}
                />
              ) : messages.isPending && session ? (
                <LoadingRows />
              ) : !messages.data?.items.length ? (
                <div className="flex min-h-36 flex-col items-center justify-center text-center">
                  <MessagesSquare className="mb-3 size-5 text-muted-foreground" />
                  <p className="text-sm font-medium">No conversation yet</p>
                  <p className="mt-1 max-w-sm text-xs leading-5 text-muted-foreground">
                    Address the lead or a specialist when you are ready to
                    begin.
                  </p>
                </div>
              ) : (
                messages.data.items.map((message) => {
                  const instructionState =
                    message.author === "user" && message.run_id
                      ? message.sequence <= consumedSequence
                        ? "Applied"
                        : "Received"
                      : undefined;
                  const profileName =
                    profiles.data?.find(
                      (profile) => profile.id === message.profile,
                    )?.name ?? label(message.profile);
                  return (
                    <Message key={message.id} from={message.author}>
                      <p className="text-[10px] font-medium tracking-wide text-muted-foreground uppercase">
                        {message.author === "user"
                          ? `You → ${profileName}`
                          : profileName}
                        {instructionState ? ` · ${instructionState}` : ""}
                      </p>
                      <MessageContent
                        className={
                          message.author === "user"
                            ? "whitespace-pre-wrap"
                            : undefined
                        }
                      >
                        {message.author === "assistant" ? (
                          <MessageResponse
                            mode="static"
                            skipHtml
                            disallowedElements={[
                              "img",
                              "iframe",
                              "script",
                              "style",
                            ]}
                            className="text-base leading-7 [&_a:visited]:text-primary/70"
                          >
                            {message.content}
                          </MessageResponse>
                        ) : (
                          message.content
                        )}
                      </MessageContent>
                    </Message>
                  );
                })
              )}
            </ConversationContent>
            <ConversationScrollButton />
          </Conversation>

          {runs.error ? (
            <div className="px-6">
              <ErrorState error={runs.error} retry={() => runs.refetch()} />
            </div>
          ) : runs.data?.items.length ? (
            <div className="space-y-3 px-6" aria-label="Recent run activity">
              {runs.data.items.slice(0, 10).map((run) => (
                <RunActivity
                  key={run.id}
                  run={run}
                  showOutput={!assistantRunIds.has(run.id)}
                  cancelling={
                    cancel.isPending && cancel.variables?.id === run.id
                  }
                  onCancel={
                    activeStates.has(run.state)
                      ? (item) => cancel.mutate(item)
                      : undefined
                  }
                />
              ))}
            </div>
          ) : null}

          {cancelError ? (
            <p className="mx-6 text-xs text-destructive" role="alert">
              {cancelError.message} Refresh the activity and try cancelling
              again.
            </p>
          ) : null}

          <form
            className="mx-6 rounded-lg border border-border bg-card/50 p-3"
            onSubmit={(event) => {
              event.preventDefault();
              if (canSend) send.mutate();
            }}
          >
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <Select
                value={selectedProfile?.id ?? addressedProfileId}
                onValueChange={setProfileId}
                disabled={
                  !!activeRun ||
                  profiles.isPending ||
                  !!profiles.error ||
                  !profiles.data?.length ||
                  !!disabledReason
                }
              >
                <SelectTrigger
                  aria-label="Address"
                  className="min-w-40 flex-1 sm:flex-none"
                >
                  <SelectValue placeholder="Choose a profile" />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {profiles.data?.map((profile) => (
                      <SelectItem key={profile.id} value={profile.id}>
                        {profile.name}
                        {profile.ready ? "" : " · setup required"}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
              {activeRun ? <Status value={activeRun.state} /> : null}
            </div>
            {profiles.error ? (
              <ErrorState
                error={profiles.error}
                retry={() => profiles.refetch()}
              />
            ) : profiles.data?.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                No agent profiles are available for this workspace.
              </p>
            ) : null}
            <Textarea
              aria-label="Message"
              value={draft}
              onChange={(event) => {
                setDraft(event.target.value);
                setSendError(undefined);
                setSavedNotice("");
              }}
              disabled={!!disabledReason}
              maxLength={20_000}
              rows={3}
              placeholder={
                activeRun
                  ? "Add an instruction for the current work…"
                  : "Describe the outcome you need…"
              }
            />
            <div className="mt-2 flex min-w-0 items-center gap-2">
              <p
                className="min-w-0 flex-1 text-[11px] leading-4 text-muted-foreground"
                aria-live="polite"
              >
                {sendError
                  ? `${sendError.message} Your message is still here; retry when ready.`
                  : savedNotice ||
                    (activeRun
                      ? "Instructions are saved now and applied at the next safe stopping point."
                      : "Your message is saved before work begins.")}
              </p>
              <Button
                type="submit"
                size="sm"
                disabled={!canSend}
                aria-label={activeRun ? "Send instruction" : "Send message"}
              >
                {send.isPending ? <Spinner /> : <ArrowUp />}
                <span className="hidden sm:inline">
                  {sendError ? "Retry" : activeRun ? "Instruct" : "Send"}
                </span>
              </Button>
            </div>
          </form>
        </>
      )}
    </div>
  );
}
