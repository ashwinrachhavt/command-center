"use client";

import { AnimatedIcon } from "@/components/ui/animated-icon";
import { useState } from "react";
import Link from "next/link";
import { useAuth } from "@clerk/nextjs";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { DraftStatus } from "@/components/writing/draft-status";
import { RichWriter } from "@/components/writing/rich-writer";
import { useWorkingDraft } from "@/components/writing/use-working-draft";
import { api, ApiError, type ResumeOptions, type Schema } from "@/lib/api";
import { useWorkspaceContext } from "./context";
import { ErrorState, LoadingRows, Spinner } from "./primitives";
import { runFailureMessage } from "@/lib/api";
import { ApplicationKeywordMatch } from "./application-keyword-match";

type Material = Schema["MaterialRead"];
type Kind = Schema["MaterialCreate"]["kind"];
const active = (item: Material) =>
  ["queued", "running", "waiting_for_user"].includes(item.state);
const title = (kind: Kind) =>
  kind === "resume" ? "Tailored résumé" : "Cover letter";

export function ApplicationMaterials({
  taskId,
  resumeVersionId,
}: {
  taskId: string;
  resumeVersionId?: string;
}) {
  const { userId } = useAuth();
  return userId ? (
    <Materials
      key={`${userId}:${taskId}`}
      actor={userId}
      taskId={taskId}
      resumeVersionId={resumeVersionId}
    />
  ) : null;
}

function Materials({
  actor,
  taskId,
  resumeVersionId,
}: {
  actor: string;
  taskId: string;
  resumeVersionId?: string;
}) {
  const client = useQueryClient();
  const workspace = useWorkspaceContext();
  const [offset, setOffset] = useState(0);
  const [checkingKeywords, setCheckingKeywords] = useState(false);
  const writing = useWorkingDraft(actor, `application-material-${taskId}`, {
    instructions: "",
    resumeVersionId: "",
    kind: "cover-letter" as Kind,
    sourceVersion: 0,
  });
  const { draft } = writing;
  const job = useQuery({
    queryKey: ["application-job-context", taskId],
    queryFn: () =>
      api<Schema["ApplicationContextRead"] | null>(
        `applications/${taskId}/job-context`,
      ),
  });
  const resumes = useQuery({
    queryKey: ["material-resumes", actor],
    queryFn: () => api<ResumeOptions>("browser/resumes"),
  });
  const history = useQuery({
    queryKey: ["application-materials", taskId, offset],
    queryFn: () =>
      api<Schema["Page_MaterialRead_"]>(
        `applications/${taskId}/materials?limit=10&offset=${offset}`,
      ),
    refetchInterval: (query) =>
      query.state.data?.items.some(active) ? 2000 : false,
  });
  const files = resumes.data?.items ?? [];
  const selected =
    writing.data.resumeVersionId ||
    [resumeVersionId, resumes.data?.default_version_id].find((id) =>
      files.some((file) => file.version_id === id),
    ) ||
    "";
  const pendingReceipt = draft.hasCheckpoint;
  const working = history.data?.items.some(active);
  const start = useMutation({
    mutationFn: async (kind: Kind) => {
      if (!pendingReceipt && (!job.data?.text.trim() || !selected))
        throw new Error("Save a job description and choose a résumé first.");
      if (writing.data.instructions.length > 3000)
        throw new Error("Keep writing preferences under 3,000 characters.");
      if (!draft.hasCheckpoint)
        draft.edit((copy) => ({
          ...copy,
          kind,
          resumeVersionId: selected,
          sourceVersion: job.data?.version ?? 0,
        }));
      await draft.flush();
      const request = draft.request(
        "POST",
        `applications/${taskId}/materials`,
        {
          kind,
          job_version_id: job.data?.version_id,
          resume_version_id: selected,
          instructions: draft.getSnapshot().data.instructions,
        },
        draft.getSnapshot().data,
      );
      return api<Material>(request.target, {
        method: "POST",
        body: request.body,
        key: request.key,
      });
    },
    onSuccess: () => {
      draft.resetIntent();
      setOffset(0);
      void client.invalidateQueries({
        queryKey: ["application-materials", taskId],
      });
      void client.invalidateQueries({ queryKey: ["tasks"] });
      toast.success("Document requested. Follow its progress below.");
    },
    onError: (error) => {
      if (
        error instanceof ApiError &&
        [400, 403, 404, 409, 413, 422].includes(error.status)
      )
        draft.resetIntent();
      void client.invalidateQueries({
        queryKey: ["application-materials", taskId],
      });
      if (error instanceof ApiError && error.status === 409)
        void client.invalidateQueries({
          queryKey: ["application-job-context", taskId],
        });
    },
  });
  const busy = start.isPending || pendingReceipt || checkingKeywords;
  const unavailable =
    writing.status === "loading" ||
    writing.status === "conflict" ||
    history.isPending ||
    !!history.error ||
    !!resumes.error ||
    !job.data?.text.trim() ||
    !files.some((file) => file.version_id === selected);
  return (
    <section
      aria-label="Application documents"
      className="my-6 space-y-4 rounded-lg border p-4"
    >
      <div>
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          <FileText className="size-4" />
          Application documents
        </h3>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          Start from a draft shaped for this role. Edit and export it when
          you’re ready.
        </p>
      </div>
      {resumes.error ? (
        <ErrorState error={resumes.error} retry={() => resumes.refetch()} />
      ) : resumes.isPending ? (
        <LoadingRows />
      ) : (
        <div className="space-y-2">
          <Label htmlFor={`material-resume-${taskId}`}>
            Résumé to work from
          </Label>
          <Select
            value={selected}
            onValueChange={(value) =>
              draft.edit((copy) => ({ ...copy, resumeVersionId: value }))
            }
            disabled={busy || writing.status === "loading"}
          >
            <SelectTrigger
              id={`material-resume-${taskId}`}
              className="w-full min-w-0"
            >
              <SelectValue placeholder="Choose a saved résumé" />
            </SelectTrigger>
            <SelectContent>
              {files.map((file) => (
                <SelectItem key={file.version_id} value={file.version_id}>
                  {file.title} · v{file.version} · {file.filename}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {!files.length && (
            <p className="text-xs text-muted-foreground">
              Upload and extract a résumé in Library to begin.
            </p>
          )}
        </div>
      )}
      <details>
        <summary className="min-h-8 cursor-pointer text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          Writing preferences
        </summary>
        <div className="mt-3 space-y-3">
          <RichWriter
            id={`material-instructions-${taskId}`}
            label="Application writing preferences"
            value={writing.data.instructions}
            format="markdown"
            revision={writing.editorRevision}
            disabled={busy || writing.status === "loading"}
            placeholder="Emphasize product work. Keep the cover letter concise…"
            onChange={(text) =>
              draft.edit((copy) => ({ ...copy, instructions: text }))
            }
          />
          <DraftStatus
            draft={draft}
            state={writing}
            disabled={busy}
            preview={(copy) => copy.instructions}
          />
        </div>
      </details>
      {job.error && (
        <ErrorState error={job.error} retry={() => job.refetch()} />
      )}
      {!job.isPending && !job.error && !job.data?.text.trim() && (
        <p className="text-xs text-muted-foreground">
          Save a job-description checkpoint above before generating.
        </p>
      )}
      <p className="text-xs leading-5 text-muted-foreground">
        Uses your approved profile and the selected résumé with saved job
        requirements
        {job.data
          ? ` (version ${pendingReceipt ? writing.data.sourceVersion : job.data.version})`
          : ""}
        . Unfinished description edits stay in your writer.
      </p>
      <div className="flex flex-wrap gap-2">
        {pendingReceipt ? (
          <Button
            size="sm"
            disabled={
              start.isPending ||
              writing.status === "loading" ||
              writing.status === "conflict"
            }
            onClick={() => start.mutate("cover-letter")}
          >
            <AnimatedIcon state={start.isPending}>
              {start.isPending ? <Spinner /> : <Sparkles />}
            </AnimatedIcon>
            Recover {title(writing.data.kind).toLowerCase()} request
          </Button>
        ) : (
          <>
            <Button
              size="sm"
              disabled={unavailable || working || busy}
              onClick={() => start.mutate("cover-letter")}
            >
              <Sparkles />
              Draft cover letter
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={unavailable || working || busy}
              onClick={() => start.mutate("resume")}
            >
              <Sparkles />
              Tailor résumé
            </Button>
          </>
        )}
        <Button size="sm" variant="ghost" asChild>
          <Link href="/settings">Profile and résumé setup</Link>
        </Button>
      </div>
      {start.error && (
        <p role="alert" className="text-sm text-destructive">
          {start.error.message}
        </p>
      )}
      <ApplicationKeywordMatch
        actor={actor}
        taskId={taskId}
        resumeVersionId={
          files.some((file) => file.version_id === selected)
            ? selected
            : undefined
        }
        jobVersionId={job.data?.text.trim() ? job.data.version_id : undefined}
        loading={
          job.isPending || resumes.isPending || writing.status === "loading"
        }
        disabled={
          start.isPending || pendingReceipt || !!job.error || !!resumes.error
        }
        onPendingChange={setCheckingKeywords}
      />
      {history.error ? (
        <ErrorState error={history.error} retry={() => history.refetch()} />
      ) : history.isPending ? (
        <LoadingRows />
      ) : (
        <>
          <div className="space-y-3">
            {history.data.items.map((item) => (
              <article
                key={item.id}
                className="space-y-3 rounded-md bg-muted/40 p-3"
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <h4 className="text-sm font-medium">{title(item.kind)}</h4>
                  <time
                    className="text-xs text-muted-foreground"
                    dateTime={item.created_at}
                  >
                    {new Date(item.created_at).toLocaleString(undefined, {
                      dateStyle: "medium",
                      timeStyle: "short",
                    })}
                  </time>
                </div>
                <p role="status" className="text-xs leading-5">
                  {item.output
                    ? item.output.archived
                      ? "Saved draft archived"
                      : "Draft saved · ready to edit"
                    : item.state === "waiting_for_user"
                      ? "Your agent needs an answer"
                      : item.state === "failed"
                        ? runFailureMessage(item.error_code)
                        : item.state === "cancelled"
                          ? "Generation cancelled"
                          : item.state === "completed"
                            ? "The agent finished without a saved document. Open the conversation to review."
                            : item.state === "running"
                              ? "Writing your draft…"
                              : "Queued for your agent"}
                </p>
                <p className="text-xs leading-5 text-muted-foreground">
                  Job description v{item.job.version} · {item.resume.title} v
                  {item.resume.version}
                </p>
                <div className="flex flex-wrap gap-2">
                  {item.output && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() =>
                        workspace?.open("artifacts", item.output!.artifact_id, {
                          tab: "content",
                        })
                      }
                    >
                      {item.output.archived
                        ? "Open archived draft"
                        : "Open draft & export"}
                    </Button>
                  )}
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() =>
                      workspace?.open("tasks", taskId, { tab: "conversation" })
                    }
                  >
                    {item.state === "waiting_for_user"
                      ? "Answer agent"
                      : "Work conversation"}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() =>
                      workspace?.open("artifacts", item.job.artifact_id, {
                        tab: "content",
                        versionId: item.job.version_id,
                      })
                    }
                  >
                    Source requirements
                  </Button>
                </div>
              </article>
            ))}
          </div>
          {history.data.total > 10 && (
            <div className="flex items-center justify-between gap-2 text-xs">
              <Button
                size="sm"
                variant="ghost"
                disabled={!offset}
                onClick={() => setOffset(Math.max(0, offset - 10))}
              >
                Previous documents
              </Button>
              <span>
                {offset + 1}–{Math.min(offset + 10, history.data.total)} of{" "}
                {history.data.total}
              </span>
              <Button
                size="sm"
                variant="ghost"
                disabled={offset + 10 >= history.data.total}
                onClick={() => setOffset(offset + 10)}
              >
                Next documents
              </Button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
