"use client";

import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Pencil, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ArtifactWriter } from "@/components/writing/artifact-writer";
import { api, type Schema } from "@/lib/api";
import { RetainedRequestIntent } from "@/lib/retained-intent";
import { useWorkspaceContext } from "./context";
import { ErrorState, LoadingRows } from "./primitives";

type JobContext = Schema["ApplicationContextRead"];

export function ApplicationJobContext({
  application,
}: {
  application: Schema["ApplicationRead"];
}) {
  const client = useQueryClient();
  const workspace = useWorkspaceContext();
  const region = useRef<HTMLElement>(null);
  const [editing, setEditing] = useState(false);
  const [intent] = useState(() => new RetainedRequestIntent());
  const taskId = application.task.id;
  const source = useQuery({
    queryKey: ["application-job-context", taskId],
    queryFn: () => api<JobContext | null>(`applications/${taskId}/job-context`),
  });
  const create = useMutation({
    mutationFn: (body: Schema["ApplicationContextCreate"]) => {
      const target = `applications/${taskId}/job-context`;
      return api<JobContext>(target, {
        method: "POST",
        body,
        key: intent.forRequest("POST", target, body).key,
      });
    },
    onSuccess: (saved, body) => {
      intent.confirmRequest("POST", `applications/${taskId}/job-context`, body);
      client.setQueryData(["application-job-context", taskId], saved);
      void client.invalidateQueries({ queryKey: ["application", taskId] });
      void client.invalidateQueries({ queryKey: ["applications"] });
      setEditing(true);
      requestAnimationFrame(() => region.current?.focus());
    },
  });
  const context = source.data;
  return (
    <section
      ref={region}
      tabIndex={-1}
      aria-label="Job description"
      className="my-6 rounded-lg border p-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          <FileText className="size-4" />
          Job description
        </h3>
        {context?.text && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setEditing(!editing)}
          >
            <Pencil />
            {editing ? "Close writer" : "Edit description"}
          </Button>
        )}
      </div>
      {source.error ? (
        <ErrorState error={source.error} retry={() => source.refetch()} />
      ) : source.isPending ? (
        <LoadingRows />
      ) : context ? (
        <>
          <p className="mb-3 text-xs leading-5 text-muted-foreground">
            {context.company_name && `${context.company_name} · `}
            {context.extraction_method === "manual"
              ? "Added by you"
              : "Captured from the application page"}{" "}
            · version {context.version}
            {context.truncated && " · capture was shortened"}
          </p>
          {editing || !context.text ? (
            <ArtifactWriter
              artifactId={context.artifact_id}
              label="Job description content"
              initial={{
                text: context.text,
                baseVersionId: context.version_id,
                baseVersion: context.version,
                expectedVersion: context.expected_version,
              }}
              continuous
              onClose={() => setEditing(false)}
              onSaved={() => {
                setEditing(true);
                void source.refetch();
              }}
            />
          ) : (
            <details>
              <summary className="min-h-8 cursor-pointer text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                Read saved requirements
              </summary>
              <p className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-words text-sm leading-6">
                {context.text}
              </p>
            </details>
          )}
          <Button
            size="sm"
            variant="ghost"
            className="mt-3"
            onClick={() =>
              workspace?.open("artifacts", context.artifact_id, {
                tab: "content",
                versionId: context.version_id,
              })
            }
          >
            Source and version history
          </Button>
        </>
      ) : application.job_context_artifact_id ? (
        <>
          <p className="text-sm leading-6 text-muted-foreground">
            This application’s saved description is archived. Restore its source
            to use it again.
          </p>
          <Button
            size="sm"
            variant="outline"
            className="mt-3"
            onClick={() =>
              workspace?.open("artifacts", application.job_context_artifact_id!)
            }
          >
            Open saved source
          </Button>
        </>
      ) : (
        <>
          <p className="mb-3 text-sm leading-6 text-muted-foreground">
            Add the role requirements so your application materials have useful
            context. The companion also captures a clearly identified job
            description when available.
          </p>
          <Button
            variant="outline"
            size="sm"
            disabled={create.isPending}
            onClick={() =>
              create.mutate(
                create.error && create.variables
                  ? create.variables
                  : {
                      expected_version: application.row_version,
                      job_title: application.page_title,
                      company_name: "",
                      text: "",
                    },
              )
            }
          >
            <Plus />
            {create.isPending
              ? "Opening writer…"
              : create.error
                ? "Retry opening writer"
                : "Add job description"}
          </Button>
          {create.error && (
            <div role="alert" className="mt-3 text-sm">
              <p>{create.error.message}</p>
              <Button
                variant="ghost"
                size="sm"
                onClick={async () => {
                  const result = await source.refetch();
                  if (!result.error) {
                    await client.invalidateQueries({
                      queryKey: ["application", taskId],
                    });
                    create.reset();
                    intent.reset();
                  }
                }}
              >
                Reload current description
              </Button>
            </div>
          )}
        </>
      )}
      <p className="mt-3 text-xs leading-5 text-muted-foreground">
        Working edits autosave. Save a checkpoint before using new requirements
        for generation.
      </p>
    </section>
  );
}
