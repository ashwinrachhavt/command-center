"use client";

import { AnimatedIcon } from "@/components/ui/animated-icon";
import { useEffect, useRef, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Sparkles, ArrowUpRight } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { api, dateLabel, runFailureMessage, type Schema } from "@/lib/api";
import { ErrorState, LoadingRows, Spinner } from "./primitives";
import { useWorkspaceContext } from "./context";
import { deferView } from "./deferred-view";

type Resource = "contacts" | "companies";
type Work = Schema["WorkRead"];
const active = (work?: Work) =>
  !!work && ["queued", "running", "waiting_for_user"].includes(work.state);
const RichResponse = deferView<{ children: string }>(
  () =>
    import("./agent-response").then((module) => ({
      default: module.AgentResponse,
    })),
  "company brief",
);

export function RecordWorkButton({
  resource,
  id,
  disabled,
  compact,
  onStarted,
  request,
}: {
  resource: Resource;
  id: string;
  disabled?: boolean;
  compact?: boolean;
  onStarted?: (work: Work) => void;
  request?: Partial<Schema["WorkCreate"]>;
}) {
  const { userId } = useAuth();
  return userId ? (
    <StartWork
      key={`${userId}:${resource}:${id}`}
      actor={userId}
      resource={resource}
      id={id}
      disabled={disabled}
      compact={compact}
      onStarted={onStarted}
      request={request}
    />
  ) : null;
}

function StartWork({
  actor,
  resource,
  id,
  disabled,
  compact,
  onStarted,
  request,
}: {
  actor: string;
  resource: Resource;
  id: string;
  disabled?: boolean;
  compact?: boolean;
  onStarted?: (work: Work) => void;
  request?: Partial<Schema["WorkCreate"]>;
}) {
  const client = useQueryClient();
  const mounted = useRef(true);
  const intent = useRef<{ key: string; body: string } | undefined>(undefined);
  const storageKey = `cc:record-work-request:${actor}:${resource}:${id}`;
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const start = useMutation({
    mutationFn: async () => {
      const body = JSON.stringify(request ?? {});
      let retained = intent.current;
      try {
        retained ??=
          JSON.parse(sessionStorage.getItem(storageKey) ?? "null") ?? undefined;
      } catch {
        /* memory-only fallback */
      }
      const key = retained?.body === body ? retained.key : crypto.randomUUID();
      intent.current = { key, body };
      try {
        sessionStorage.setItem(storageKey, JSON.stringify(intent.current));
      } catch {
        /* storage can be unavailable */
      }
      const work = await api<Work>(`record-work/${resource}/${id}`, {
        method: "POST",
        body: request ?? {},
        key,
      });
      if (intent.current?.key === key) intent.current = undefined;
      try {
        if (
          JSON.parse(sessionStorage.getItem(storageKey) ?? "null")?.key === key
        )
          sessionStorage.removeItem(storageKey);
      } catch {
        /* optional journal */
      }
      return work;
    },
    onSuccess: (work) => {
      void client.invalidateQueries({
        queryKey: ["record-work", actor, resource, id],
      });
      void client.invalidateQueries({ queryKey: ["tasks"] });
      void client.invalidateQueries({ queryKey: [resource] });
      if (mounted.current) {
        onStarted?.(work);
        toast.success(
          work.output_version_id
            ? "Saved result recovered"
            : resource === "contacts"
              ? request?.channel === "email"
                ? "Email drafting started"
                : request?.research_requested
                  ? "Contact enrichment started"
                  : request?.connection_note
                    ? "Connection note started"
                    : "Follow-up drafting started"
              : "Company research started",
        );
      }
    },
  });
  return (
    <div className="space-y-2">
      <Button
        size={compact ? "sm" : "default"}
        variant="outline"
        disabled={disabled || start.isPending}
        onClick={() => start.mutate()}
      >
        <AnimatedIcon state={start.isPending}>
          {start.isPending ? <Spinner /> : <Sparkles />}
        </AnimatedIcon>
        {start.isPending
          ? "Starting…"
          : start.error
            ? "Retry agent request"
            : request?.research_requested
              ? request?.channel === "email"
                ? "Research & draft email"
                : "Enrich contact"
              : request?.connection_note
                ? "Draft connection note"
                : resource === "contacts"
                  ? request?.channel === "email"
                    ? "Draft email with agent"
                    : "Draft with agent"
                  : "Enrich company"}
      </Button>
      {start.error && (
        <p role="alert" className="max-w-md text-xs leading-5 text-destructive">
          {start.error.message}
        </p>
      )}
    </div>
  );
}

export function RecordAgentWork({
  resource,
  id,
  onDraftReady,
  email = false,
}: {
  resource: Resource;
  id: string;
  onDraftReady?: (id: string) => void;
  email?: boolean;
}) {
  const { userId } = useAuth();
  const client = useQueryClient();
  const context = useWorkspaceContext();
  const [instructions, setInstructions] = useState(
    "Write a concise, specific email about relevant engineering opportunities. Use the relationship notes, prior sent emails and my reviewed background. Include one useful ask and keep research caveats outside the message.",
  );
  const [research, setResearch] = useState(true);
  const seenOutput = useRef<string | undefined>(undefined);
  const work = useQuery({
    queryKey: ["record-work", userId, resource, id],
    enabled: !!userId,
    queryFn: () => api<Work[]>(`record-work/${resource}/${id}`),
    refetchInterval: (query) => (query.state.data?.some(active) ? 2500 : false),
  });
  const latest = work.data?.find((item) => !email || item.channel === "email");
  const lastSaved = work.data?.find(
    (item) =>
      item.output_version_id &&
      !item.output_archived &&
      (!email || item.channel === "email"),
  );
  const artifact = lastSaved?.output_artifact_id;
  const versionId = lastSaved?.output_version_id;
  const brief = useQuery({
    queryKey: ["company-brief", userId, artifact, versionId],
    enabled: resource === "companies" && !!artifact && !!versionId,
    queryFn: () =>
      api<Schema["VersionRead"]>(`artifacts/${artifact}/versions/${versionId}`),
  });
  useEffect(() => {
    if (versionId && seenOutput.current !== versionId) {
      seenOutput.current = versionId;
      void client.invalidateQueries({
        queryKey: resource === "contacts" ? ["follow-ups", id] : ["companies"],
      });
      void client.invalidateQueries({ queryKey: ["tasks"] });
    }
  }, [client, id, resource, versionId]);
  const viewTask = (item: Work) =>
    context?.open("tasks", item.task_id, { tab: "conversation" });
  return (
    <section
      aria-label={
        resource === "contacts"
          ? "Agent follow-up drafting"
          : "Company research"
      }
      className="space-y-4 rounded-xl shadow-surface bg-card p-4 sm:p-5"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-medium">
            {resource === "contacts"
              ? "Start from a thoughtful draft"
              : "Research for your job search"}
          </h3>
          <p className="mt-1 max-w-lg text-xs leading-5 text-muted-foreground">
            {resource === "contacts"
              ? "Use this person’s notes, saved context and your reviewed profile. Edit the saved message before using it."
              : "Get a cited brief on the business, hiring signals, relevant teams and next steps. Your own company notes stay intact."}
          </p>
        </div>
        <RecordWorkButton
          resource={resource}
          id={id}
          disabled={work.data?.some(active)}
          request={
            email
              ? { channel: "email", research_requested: research, instructions }
              : undefined
          }
        />
      </div>
      {email && (
        <div className="space-y-3">
          <label className="block space-y-2 text-sm">
            <span>Email brief</span>
            <Textarea
              value={instructions}
              maxLength={3000}
              rows={3}
              onChange={(event) => setInstructions(event.target.value)}
            />
          </label>
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-1"
              checked={research}
              onChange={(event) => setResearch(event.target.checked)}
            />
            Research missing person or company context using a few focused
            public sources.
          </label>
          <p className="text-xs text-muted-foreground">
            The agent reuses saved research and confirmed send history. It saves
            an editable draft with evidence for your review.
          </p>
          {work.data?.some(active) && !active(latest) && (
            <p className="text-xs text-muted-foreground">
              Another drafting task for this contact is still active. Finish it
              before starting an email.
            </p>
          )}
        </div>
      )}
      {work.error && (
        <ErrorState error={work.error} retry={() => void work.refetch()} />
      )}
      {work.isPending && <LoadingRows />}
      {latest && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-muted/40 p-3">
          <div role="status" className="flex items-center gap-2 text-xs">
            {active(latest) && latest.state !== "waiting_for_user" && (
              <Spinner />
            )}
            <span>
              {latest.output_archived
                ? "Saved result archived"
                : latest.output_version_id
                  ? "Result saved"
                  : latest.state === "queued"
                    ? "Queued for your agent"
                    : latest.state === "running"
                      ? "Agent is working"
                      : latest.state === "waiting_for_user"
                        ? "Your agent needs an answer"
                        : latest.state === "failed"
                          ? runFailureMessage(latest.error_code)
                          : latest.state === "cancelled"
                            ? "Work cancelled"
                            : "The agent finished without a saved result. Open the work to review."}
            </span>
          </div>
          <Button variant="ghost" size="sm" onClick={() => viewTask(latest)}>
            {latest.state === "waiting_for_user" ? "Answer agent" : "Open work"}
            <ArrowUpRight />
          </Button>
        </div>
      )}
      {lastSaved && resource === "contacts" && (
        <Button
          variant="secondary"
          onClick={() =>
            lastSaved.output_artifact_id &&
            onDraftReady?.(lastSaved.output_artifact_id)
          }
        >
          Review generated draft
        </Button>
      )}
      {resource === "companies" && lastSaved && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
            <span>
              Requested {dateLabel(lastSaved.created_at)} · Review sources
              before acting
            </span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() =>
                artifact &&
                versionId &&
                context?.open("artifacts", artifact, {
                  tab: "content",
                  versionId,
                })
              }
            >
              Sources & versions
              <ArrowUpRight />
            </Button>
          </div>
          {brief.isPending && <LoadingRows />}
          {brief.error && (
            <ErrorState
              error={brief.error}
              retry={() => void brief.refetch()}
            />
          )}
          {brief.data && (
            <RichResponse>
              {String(brief.data.payload?.text ?? "")}
            </RichResponse>
          )}
        </div>
      )}
      {work.data && work.data.length > 1 && (
        <details className="text-xs">
          <summary className="cursor-pointer text-muted-foreground">
            Earlier work
          </summary>
          <div className="mt-2 flex flex-wrap gap-2">
            {work.data.slice(1).map((item) => (
              <Button
                key={item.task_id}
                size="sm"
                variant="ghost"
                onClick={() => viewTask(item)}
              >
                {dateLabel(item.created_at)} ·{" "}
                {item.output_archived
                  ? "Archived result"
                  : item.output_version_id
                    ? "Saved result"
                    : item.state.replaceAll("_", " ")}
              </Button>
            ))}
          </div>
        </details>
      )}
    </section>
  );
}
