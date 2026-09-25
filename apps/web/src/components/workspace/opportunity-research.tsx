"use client";

import { AnimatedIcon } from "@/components/ui/animated-icon";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Sparkles,
  AlertCircle,
  ExternalLink,
  FileText,
  RefreshCw,
} from "lucide-react";
import { toast } from "sonner";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field, FieldLabel } from "@/components/ui/field";
import { Textarea } from "@/components/ui/textarea";
import {
  api,
  dateLabel,
  type AgentMessage,
  type AgentSession,
  type LeadSource,
  type Page,
} from "@/lib/api";
import { ErrorState, LoadingRows, Spinner } from "./primitives";
import { useWorkspaceContext } from "./context";

const defaultOutreachRequest =
  "Draft a concise outreach message for this opportunity using the saved job-source evidence. Flag any missing context and do not send it.";

export function OpportunityResearch({
  opportunityId,
  onOpenConversation,
}: {
  opportunityId: string;
  onOpenConversation: () => void;
}) {
  const context = useWorkspaceContext();
  const client = useQueryClient();
  const [enrichKey, setEnrichKey] = useState<string>();
  const [draftKey, setDraftKey] = useState<{
    session: string;
    message: string;
  }>();
  const [draftRequest, setDraftRequest] = useState(defaultOutreachRequest);

  const sources = useQuery({
    queryKey: ["opportunity-research", opportunityId],
    queryFn: ({ signal }) =>
      api<Page<LeadSource>>(
        `opportunities/${opportunityId}/research?limit=20&offset=0`,
        { signal },
      ),
  });
  const enrich = useMutation({
    mutationFn: ({ key }: { key: string }) =>
      api<LeadSource>(`opportunities/${opportunityId}/enrich`, {
        method: "POST",
        key,
        body: {},
      }),
    onSuccess: () => {
      setEnrichKey(undefined);
      client.invalidateQueries({
        queryKey: ["opportunity-research", opportunityId],
      });
      client.invalidateQueries({ queryKey: ["activity", opportunityId] });
      toast.success("Public source saved as a new evidence version");
    },
  });
  const draft = useMutation({
    mutationFn: async ({
      sessionKey,
      messageKey,
    }: {
      sessionKey: string;
      messageKey: string;
    }) => {
      const session = await api<AgentSession>("agent-sessions", {
        method: "POST",
        key: sessionKey,
        body: { opportunity_id: opportunityId },
      });
      await api<AgentMessage>(`agent-sessions/${session.id}/messages`, {
        method: "POST",
        key: messageKey,
        body: { content: draftRequest.trim(), profile: "outreach" },
      });
      return session;
    },
    onSuccess: (session) => {
      setDraftKey(undefined);
      client.invalidateQueries({
        queryKey: ["agent-session", "opportunities", opportunityId],
      });
      client.invalidateQueries({
        queryKey: ["agent-session-messages", session.id],
      });
      client.invalidateQueries({
        queryKey: ["agent-session-runs", session.id],
      });
      toast.success("Outreach request added to the conversation");
      onOpenConversation();
    },
  });

  const runEnrich = () => {
    if (enrich.isPending) return;
    const key = enrichKey ?? crypto.randomUUID();
    setEnrichKey(key);
    enrich.mutate({ key });
  };
  const runDraft = () => {
    if (!draftRequest.trim() || draft.isPending) return;
    const keys =
      draftKey ??
      ({ session: crypto.randomUUID(), message: crypto.randomUUID() } as const);
    setDraftKey(keys);
    draft.mutate({ sessionKey: keys.session, messageKey: keys.message });
  };

  return (
    <div className="space-y-7">
      <section aria-labelledby="source-evidence-heading">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 id="source-evidence-heading" className="text-sm font-medium">
              Source evidence
            </h3>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              Fetch the public role page without changing CRM fields or job
              status. Each successful fetch creates an immutable version.
            </p>
          </div>
          <Button onClick={runEnrich} disabled={enrich.isPending} size="sm">
            <AnimatedIcon state={enrich.isPending}>
              {enrich.isPending ? <Spinner /> : <RefreshCw />}
            </AnimatedIcon>
            {enrich.error ? "Retry enrichment" : "Enrich from source"}
          </Button>
        </div>

        {enrich.error ? (
          <RequestError
            title="Source fetch failed"
            error={enrich.error}
            action="Check the public research provider and retry. The opportunity fields and status are unchanged."
            onRetry={runEnrich}
          />
        ) : null}

        {sources.error ? (
          <ErrorState error={sources.error} retry={() => sources.refetch()} />
        ) : sources.isPending ? (
          <LoadingRows />
        ) : sources.data.items.length ? (
          <div className="mt-5 divide-y rounded-lg border">
            {sources.data.items.map((source) => (
              <article key={source.id} className="p-4">
                <div className="flex items-start gap-3">
                  <FileText className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium">{source.title}</p>
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      Version {source.version} · {source.provider} · retrieved{" "}
                      {dateLabel(source.retrieved_at)}
                    </p>
                    <p className="mt-3 line-clamp-4 whitespace-pre-wrap text-xs leading-5 text-muted-foreground">
                      {source.excerpt ||
                        "No excerpt was stored for this source."}
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() =>
                          context?.open("artifacts", source.artifact_id, {
                            tab: "content",
                            versionId: source.version_id,
                          })
                        }
                      >
                        View saved version {source.version}
                      </Button>
                      {/^https?:\/\//i.test(source.url) ? (
                        <Button asChild size="sm" variant="ghost">
                          <a
                            href={source.url}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            Public page
                            <ExternalLink />
                          </a>
                        </Button>
                      ) : (
                        <span className="self-center text-xs text-muted-foreground">
                          Pasted or saved source
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <p className="mt-5 rounded-lg border border-dashed p-5 text-center text-sm text-muted-foreground">
            No saved source evidence yet. Enrich this opportunity to fetch its
            public role page.
          </p>
        )}
      </section>

      <section
        aria-labelledby="draft-outreach-heading"
        className="border-t pt-6"
      >
        <h3 id="draft-outreach-heading" className="text-sm font-medium">
          Draft outreach
        </h3>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">
          Add a request for the Outreach specialist to this opportunity’s
          conversation. This starts draft work only; it does not send a message
          to anyone.
        </p>
        <Field className="mt-4">
          <FieldLabel htmlFor={`outreach-request-${opportunityId}`}>
            Request
          </FieldLabel>
          <Textarea
            id={`outreach-request-${opportunityId}`}
            value={draftRequest}
            rows={4}
            maxLength={20_000}
            onChange={(event) => {
              setDraftRequest(event.target.value);
              setDraftKey(undefined);
              draft.reset();
            }}
          />
        </Field>
        {draft.error ? (
          <RequestError
            title="Outreach draft could not start"
            error={draft.error}
            action="Retry when agent work is available. Your request is still here."
            onRetry={runDraft}
          />
        ) : null}
        <Button
          className="mt-3"
          onClick={runDraft}
          disabled={!draftRequest.trim() || draft.isPending}
        >
          <AnimatedIcon state={draft.isPending}>
            {draft.isPending ? <Spinner /> : <Sparkles />}
          </AnimatedIcon>
          {draft.error ? "Retry draft outreach" : "Draft outreach"}
        </Button>
      </section>
    </div>
  );
}

function RequestError({
  title,
  error,
  action,
  onRetry,
}: {
  title: string;
  error: Error;
  action: string;
  onRetry: () => void;
}) {
  return (
    <Alert variant="destructive" className="mt-4">
      <AlertCircle />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>
        <p>{error.message}</p>
        <p className="mt-1">{action}</p>
        <Button variant="outline" className="mt-3" onClick={onRetry}>
          Retry
        </Button>
      </AlertDescription>
    </Alert>
  );
}
