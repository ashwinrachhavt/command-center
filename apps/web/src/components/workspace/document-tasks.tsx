"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { FileText, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api, type Page, type Schema } from "@/lib/api";
import { useWorkspaceContext } from "./context";
import { ErrorState, Status } from "./primitives";
import { RecordEditor } from "./record-editor";
type Artifact = Schema["ArtifactRead"];

export function DocumentTasks({
  artifactId,
  archived = false,
}: {
  artifactId: string;
  archived?: boolean;
}) {
  const workspace = useWorkspaceContext();
  const [creating, setCreating] = useState(false);
  const [offset, setOffset] = useState(0);
  const tasks = useQuery({
    queryKey: ["document-tasks", artifactId, offset],
    queryFn: () =>
      api<Page<Schema["TaskRead"]>>(
        `artifacts/${artifactId}/tasks?limit=10&offset=${offset}`,
      ),
  });
  return (
    <section
      aria-label="Linked tasks"
      className="mt-8 border-t border-border pt-5"
    >
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-medium">Turn a thought into a next step</h3>
        <Button
          disabled={archived}
          variant="outline"
          size="sm"
          onClick={() => setCreating(true)}
        >
          <Plus />
          Create task
        </Button>
      </div>
      {tasks.error ? (
        <ErrorState error={tasks.error} retry={() => tasks.refetch()} />
      ) : tasks.isPending ? (
        <p role="status" className="mt-3 text-xs text-muted-foreground">
          Loading linked tasks…
        </p>
      ) : tasks.data.items.length ? (
        <ul className="mt-3 divide-y divide-border">
          {tasks.data.items.map((task) => (
            <li key={task.id}>
              <button
                className="flex w-full items-center justify-between gap-3 rounded-md py-3 text-left text-sm hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={() => workspace?.open("tasks", task.id)}
              >
                <span className="min-w-0 break-words">{task.title}</span>
                <Status value={task.state} />
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-3 text-xs leading-5 text-muted-foreground">
          Create a task from this document. It stays linked here and appears in
          Tasks.
        </p>
      )}
      {tasks.data && tasks.data.total > 10 && (
        <div className="mt-2 flex gap-2">
          <Button
            size="sm"
            variant="ghost"
            disabled={!offset}
            onClick={() => setOffset(offset - 10)}
          >
            Previous tasks
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={offset + 10 >= tasks.data.total}
            onClick={() => setOffset(offset + 10)}
          >
            More tasks
          </Button>
        </div>
      )}
      <RecordEditor
        resource="tasks"
        open={creating}
        onOpenChange={setCreating}
        sourceArtifactId={artifactId}
        draftKey={`document-task-${artifactId}`}
      />
    </section>
  );
}

export function TaskDocuments({ taskId }: { taskId: string }) {
  const workspace = useWorkspaceContext();
  const documents = useQuery({
    queryKey: ["task-documents", taskId],
    queryFn: () => api<Page<Artifact>>(`artifacts?task_id=${taskId}&limit=30`),
  });
  if (documents.error)
    return (
      <ErrorState error={documents.error} retry={() => documents.refetch()} />
    );
  if (!documents.data?.items.length) return null;
  return (
    <section aria-label="Linked documents" className="space-y-3">
      <h3 className="text-sm font-medium">Linked documents</h3>
      {documents.data.items.map((item) => (
        <Button
          key={item.id}
          variant="outline"
          className="h-auto w-full justify-start whitespace-normal py-3 text-left"
          onClick={() =>
            workspace?.open("artifacts", item.id, { tab: "content" })
          }
        >
          <FileText className="shrink-0" />
          {item.title}
        </Button>
      ))}
    </section>
  );
}
