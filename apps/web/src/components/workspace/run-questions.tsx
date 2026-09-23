"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUp } from "lucide-react";
import {
  Message,
  MessageContent,
  MessageResponse,
} from "@/components/ai-elements/message";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { api, label, type AgentRunQuestion } from "@/lib/api";
import { RetainedRequestIntents } from "@/lib/retained-intent";
import { ErrorState, Spinner } from "./primitives";

const answerLimit = 20_000;

export function RunQuestions({
  runId,
  canAnswer,
}: {
  runId: string;
  canAnswer: boolean;
}) {
  const queryClient = useQueryClient();
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [intents] = useState(() => new RetainedRequestIntents());
  const questions = useQuery({
    queryKey: ["agent-run-questions", runId],
    queryFn: ({ signal }) =>
      api<AgentRunQuestion[]>(`agent-runs/${runId}/questions`, { signal }),
    refetchInterval: canAnswer ? 30_000 : false,
    refetchOnWindowFocus: "always",
    refetchOnReconnect: "always",
  });
  const answer = useMutation({
    mutationFn: async ({
      question,
      value,
    }: {
      question: AgentRunQuestion;
      value: string;
    }) => {
      const target = `agent-runs/${runId}/questions/${question.id}/answer`;
      const body = {
        answer: value,
        expected_version: question.row_version,
      };
      const intent = intents.forRequest(question.id, "POST", target, body);
      const result = await api<AgentRunQuestion>(target, {
        method: "POST",
        body,
        key: intent.key,
      });
      return { result, question, target, body, value };
    },
    onSuccess: ({ question, target, body, value }) => {
      intents.confirmRequest(question.id, "POST", target, body);
      setDrafts((current) => {
        if (current[question.id] !== value) return current;
        const next = { ...current };
        delete next[question.id];
        return next;
      });
      setErrors((current) => {
        const next = { ...current };
        delete next[question.id];
        return next;
      });
      void Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["agent-run-questions", runId],
        }),
        queryClient.invalidateQueries({ queryKey: ["agent-session-runs"] }),
        queryClient.invalidateQueries({ queryKey: ["agent-run", runId] }),
      ]);
    },
    onError: (error, { question }) => {
      setErrors((current) => ({
        ...current,
        [question.id]:
          error instanceof Error ? error.message : "Answer failed.",
      }));
      void questions.refetch();
    },
  });

  if (questions.error && !questions.data)
    return canAnswer ? (
      <div className="mt-4">
        <ErrorState error={questions.error} retry={() => questions.refetch()} />
      </div>
    ) : null;

  const refreshError = questions.error ? (
    <div
      className="mt-3 flex flex-wrap items-center gap-2 text-xs text-destructive"
      role="alert"
    >
      <p className="min-w-0 flex-1">
        Couldn’t refresh saved questions. Your prompts and drafts are still
        here.
      </p>
      <Button
        type="button"
        size="sm"
        variant="outline"
        onClick={() => questions.refetch()}
      >
        Retry questions
      </Button>
    </div>
  ) : null;

  const open = questions.data?.filter((question) => question.state === "open");
  if (!open?.length) {
    if (questions.isPending && canAnswer)
      return (
        <p className="mt-4 text-xs text-muted-foreground" role="status">
          Loading saved questions…
        </p>
      );
    return null;
  }

  return (
    <div className="mt-4 space-y-3" aria-label="Questions needing your answer">
      {refreshError}
      {open.map((question) => {
        const draft = drafts[question.id] ?? "";
        const pending =
          answer.isPending && answer.variables?.question.id === question.id;
        const headingId = `question-${question.id}`;
        return (
          <form
            key={question.id}
            className="rounded-lg border border-border bg-background p-3"
            aria-labelledby={headingId}
            onSubmit={(event) => {
              event.preventDefault();
              const value = draft.trim();
              if (
                canAnswer &&
                value &&
                value.length <= answerLimit &&
                !answer.isPending
              )
                answer.mutate({ question, value });
            }}
          >
            <div className="mb-2 flex flex-wrap items-center gap-x-2 gap-y-1">
              <p id={headingId} className="text-xs font-medium">
                {label(question.role)} needs your answer
              </p>
              <span
                className="text-[11px] text-muted-foreground"
                title={`Branch ${question.branch_id}`}
              >
                Branch {question.branch_id.slice(0, 8)}
              </span>
            </div>
            <Message from="assistant">
              <MessageContent>
                <MessageResponse
                  mode="static"
                  skipHtml
                  disallowedElements={["img", "iframe", "script", "style"]}
                  className="text-sm leading-6"
                >
                  {question.prompt}
                </MessageResponse>
              </MessageContent>
            </Message>
            <Textarea
              className="mt-3"
              aria-label={`Answer ${label(question.role)} question`}
              value={draft}
              rows={3}
              maxLength={answerLimit}
              disabled={pending}
              onChange={(event) => {
                const value = event.target.value;
                setDrafts((current) => ({ ...current, [question.id]: value }));
                setErrors((current) => {
                  if (!current[question.id]) return current;
                  const next = { ...current };
                  delete next[question.id];
                  return next;
                });
              }}
              placeholder="Type the answer for this branch…"
            />
            <div className="mt-2 flex min-w-0 items-center gap-2">
              <p
                className={`min-w-0 flex-1 text-[11px] leading-4 ${
                  errors[question.id]
                    ? "text-destructive"
                    : "text-muted-foreground"
                }`}
                role={errors[question.id] ? "alert" : undefined}
              >
                {errors[question.id]
                  ? `${errors[question.id]} Your answer is still here; retry when ready.`
                  : canAnswer
                    ? "Only this saved question and branch will receive the answer."
                    : "This run will accept another branch answer when it is waiting for you again."}
              </p>
              <Button
                type="submit"
                size="sm"
                disabled={
                  !canAnswer ||
                  !draft.trim() ||
                  draft.length > answerLimit ||
                  answer.isPending
                }
              >
                {pending ? <Spinner /> : <ArrowUp />}
                {errors[question.id] ? "Retry answer" : "Answer"}
              </Button>
            </div>
          </form>
        );
      })}
    </div>
  );
}
