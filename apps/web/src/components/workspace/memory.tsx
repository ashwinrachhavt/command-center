"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  BookOpen,
  Check,
  ChevronLeft,
  ChevronRight,
  Pencil,
  Plus,
  RotateCcw,
  X,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api, dateLabel, type Page } from "@/lib/api";
import { RetainedRequestIntent } from "@/lib/retained-intent";

import { EmptyState, ErrorState, LoadingRows, PageHeading } from "./primitives";

type ReviewState = "proposed" | "approved" | "rejected" | "revoked";
type MemoryRevision = {
  id: string;
  version: number;
  title: string;
  content: string;
  kind: "note" | "preference";
  scope_type: "global" | "task" | "opportunity";
  scope_id: string | null;
  valid_until: string | null;
  source: "human" | "agent" | "legacy_human" | "legacy_agent";
  source_run_id: string | null;
  source_artifact_id: string | null;
  reason: string | null;
  review_state: ReviewState;
  created_at: string;
};
type Memory = {
  id: string;
  title: string;
  content: string;
  kind: "note" | "preference";
  source: MemoryRevision["source"];
  row_version: number;
  updated_at: string;
  current: MemoryRevision;
  active: MemoryRevision | null;
};

function sourceLabel(source: MemoryRevision["source"]) {
  if (source === "agent") return "Agent proposal";
  if (source === "legacy_agent") return "Legacy agent proposal";
  if (source === "legacy_human") return "Previously added by you";
  return "Added by you";
}

function scopeLabel(revision: MemoryRevision) {
  if (revision.scope_type === "global") return "All work";
  return `${revision.scope_type === "task" ? "Task" : "Opportunity"} scope`;
}

function MemoryEditor({
  record,
  close,
}: {
  record?: Memory;
  close: () => void;
}) {
  const [title, setTitle] = useState(record?.current.title ?? "");
  const [content, setContent] = useState(record?.current.content ?? "");
  const [intent] = useState(() => new RetainedRequestIntent());
  const client = useQueryClient();
  const save = useMutation({
    mutationFn: (submission: { title: string; content: string }) => {
      const target = `memories${record ? `/${record.id}` : ""}`;
      const method = record ? "PATCH" : "POST";
      const body = {
        title: submission.title,
        content: submission.content,
        kind: record?.current.kind ?? "note",
        scope_type: record?.current.scope_type ?? "global",
        scope_id: record?.current.scope_id ?? null,
        valid_until: record?.current.valid_until ?? null,
        source_artifact_id: record?.current.source_artifact_id ?? null,
        reason: null,
        confirm: true,
        ...(record ? { expected_version: record.row_version } : {}),
      };
      const request = intent.forRequest(method, target, body);
      return api(target, {
        method,
        body,
        key: request.key,
      });
    },
    onSuccess: (_result, submission) => {
      const target = `memories${record ? `/${record.id}` : ""}`;
      const method = record ? "PATCH" : "POST";
      intent.confirmRequest(method, target, {
        title: submission.title,
        content: submission.content,
        kind: record?.current.kind ?? "note",
        scope_type: record?.current.scope_type ?? "global",
        scope_id: record?.current.scope_id ?? null,
        valid_until: record?.current.valid_until ?? null,
        source_artifact_id: record?.current.source_artifact_id ?? null,
        reason: null,
        confirm: true,
        ...(record ? { expected_version: record.row_version } : {}),
      });
      void client.invalidateQueries({ queryKey: ["memories"] });
      close();
      toast.success("Reviewed memory saved");
    },
    onError: (error) => toast.error(error.message),
  });
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !save.isPending) close();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {record ? "Edit reviewed memory" : "Add reviewed memory"}
          </DialogTitle>
          <DialogDescription>
            Saving confirms this exact wording for future agent context. It
            never grants permission or changes your reviewed profile facts.
          </DialogDescription>
        </DialogHeader>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            save.mutate({ title, content });
          }}
        >
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="memory-title">Title</FieldLabel>
              <Input
                id="memory-title"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                required
                maxLength={200}
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="memory-content">Reusable context</FieldLabel>
              <Textarea
                id="memory-content"
                value={content}
                onChange={(event) => setContent(event.target.value)}
                rows={6}
                required
                maxLength={10000}
              />
            </Field>
          </FieldGroup>
          <p className="mt-4 text-xs leading-5 text-muted-foreground">
            Scope: {record ? scopeLabel(record.current) : "All work"}. Editing
            creates an immutable revision and makes this reviewed version
            active.
          </p>
          <Button className="mt-5" disabled={save.isPending}>
            Save and confirm memory
          </Button>
          {save.error ? (
            <p className="mt-3 text-destructive" role="alert">
              {save.error.message}
            </p>
          ) : null}
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function MemoryPage() {
  const [editing, setEditing] = useState<Memory | "new">();
  const [offset, setOffset] = useState(0);
  const limit = 30;
  const client = useQueryClient();
  const [reviewIntent] = useState(() => new RetainedRequestIntent());
  const [archiveIntent] = useState(() => new RetainedRequestIntent());
  const query = useQuery({
    queryKey: ["memories", offset],
    queryFn: () =>
      api<Page<Memory>>(`memories?limit=${limit}&offset=${offset}`),
  });
  const review = useMutation({
    mutationFn: ({
      memory,
      decision,
    }: {
      memory: Memory;
      decision: ReviewState;
    }) => {
      const revision = decision === "revoked" ? memory.active : memory.current;
      if (!revision)
        throw new Error("This memory has no active revision to revoke.");
      const target = `memories/${memory.id}/reviews`;
      const body = {
        expected_version: memory.row_version,
        revision_id: revision.id,
        decision,
        reason:
          decision === "approved"
            ? "Approved in the memory review queue."
            : decision === "rejected"
              ? "Rejected in the memory review queue."
              : "Revoked in the memory review queue.",
      };
      const intent = reviewIntent.forRequest("POST", target, body);
      return api(target, {
        method: "POST",
        body,
        key: intent.key,
      });
    },
    onSuccess: (_result, variables) => {
      const revision =
        variables.decision === "revoked"
          ? variables.memory.active!
          : variables.memory.current;
      const target = `memories/${variables.memory.id}/reviews`;
      reviewIntent.confirmRequest("POST", target, {
        expected_version: variables.memory.row_version,
        revision_id: revision.id,
        decision: variables.decision,
        reason:
          variables.decision === "approved"
            ? "Approved in the memory review queue."
            : variables.decision === "rejected"
              ? "Rejected in the memory review queue."
              : "Revoked in the memory review queue.",
      });
      void client.invalidateQueries({ queryKey: ["memories"] });
      toast.success(
        variables.decision === "approved"
          ? "Memory approved"
          : variables.decision === "rejected"
            ? "Memory rejected"
            : "Memory revoked",
      );
    },
    onError: (error) => toast.error(error.message),
  });
  const archive = useMutation({
    mutationFn: (memory: Memory) => {
      const target = `memories/${memory.id}/archive`;
      const body = { expected_version: memory.row_version };
      const intent = archiveIntent.forRequest("POST", target, body);
      return api(target, {
        method: "POST",
        body,
        key: intent.key,
      });
    },
    onSuccess: (_result, memory) => {
      archiveIntent.confirmRequest("POST", `memories/${memory.id}/archive`, {
        expected_version: memory.row_version,
      });
      void client.invalidateQueries({ queryKey: ["memories"] });
      const remaining = (query.data?.items.length ?? 1) - 1;
      if (remaining === 0 && offset > 0) setOffset(Math.max(0, offset - limit));
      toast.success("Memory archived");
    },
    onError: (error) => toast.error(error.message),
  });
  const page = query.data;
  const pending =
    page?.items.filter(
      (memory) => memory.current.review_state === "proposed",
    ) ?? [];

  return (
    <>
      <PageHeading
        title="Workspace memory"
        description="Reviewed notes and preferences available as scoped agent context."
        action={
          <Button onClick={() => setEditing("new")}>
            <Plus />
            Add memory
          </Button>
        }
      />
      <div className="px-5 md:px-9">
        <div className="mb-6 flex gap-3 rounded-lg border border-border bg-card p-4 text-xs leading-6 text-muted-foreground">
          <BookOpen className="mt-1 size-4 shrink-0 text-primary" />
          Memory is untrusted context, separate from verified profile facts and
          permission to take external actions. Agent proposals stay inactive
          until you approve their exact wording.
        </div>
        {pending.length ? (
          <div className="mb-5 rounded-lg border border-[var(--status-amber)]/30 bg-[var(--status-amber)]/5 p-4 text-xs">
            {pending.length} memory{" "}
            {pending.length === 1 ? "proposal needs" : "proposals need"} your
            review.
          </div>
        ) : null}
        {query.error ? (
          <ErrorState error={query.error} />
        ) : query.isPending ? (
          <LoadingRows />
        ) : page?.items.length === 0 ? (
          <EmptyState
            title="No reviewed memories yet"
            description="Add useful working preferences yourself, or review a future agent proposal here."
          >
            <Button variant="outline" onClick={() => setEditing("new")}>
              Add your first memory
            </Button>
          </EmptyState>
        ) : (
          <>
            <div className="grid gap-4 lg:grid-cols-2">
              {page?.items.map((memory) => {
                const proposed = memory.current.review_state === "proposed";
                const activeIsOlder =
                  memory.active && memory.active.id !== memory.current.id;
                return (
                  <article
                    key={memory.id}
                    className="rounded-xl border border-border bg-card p-5"
                  >
                    <div className="flex items-start gap-3">
                      <h2 className="flex-1 text-sm font-medium">
                        {memory.current.title}
                      </h2>
                      <Button
                        size="icon-xs"
                        variant="ghost"
                        aria-label={`Edit ${memory.current.title}`}
                        onClick={() => setEditing(memory)}
                      >
                        <Pencil />
                      </Button>
                      <Button
                        size="icon-xs"
                        variant="ghost"
                        aria-label={`Archive ${memory.current.title}`}
                        disabled={archive.isPending}
                        onClick={() => archive.mutate(memory)}
                      >
                        <Archive />
                      </Button>
                    </div>
                    <p className="mt-3 whitespace-pre-wrap text-xs leading-6 text-muted-foreground">
                      {memory.current.content}
                    </p>
                    {memory.current.reason ? (
                      <p className="mt-3 text-[11px] leading-5 text-muted-foreground">
                        Why remember this: {memory.current.reason}
                      </p>
                    ) : null}
                    {activeIsOlder ? (
                      <div className="mt-4 rounded-md border border-border p-3 text-[11px] leading-5 text-muted-foreground">
                        The prior approved wording remains active while this
                        revision is reviewed:
                        <span className="mt-1 block whitespace-pre-wrap text-foreground">
                          {memory.active?.content}
                        </span>
                      </div>
                    ) : null}
                    <div className="mt-5 flex flex-wrap items-center gap-2">
                      <Badge
                        variant={proposed ? "secondary" : "outline"}
                        className="font-normal"
                      >
                        {proposed
                          ? "Needs review"
                          : memory.current.review_state}
                      </Badge>
                      <Badge
                        variant="outline"
                        className="font-normal text-muted-foreground"
                      >
                        {sourceLabel(memory.current.source)}
                      </Badge>
                      <Badge
                        variant="outline"
                        className="font-normal text-muted-foreground"
                      >
                        {scopeLabel(memory.current)}
                      </Badge>
                      <span className="ml-auto text-[10px] text-muted-foreground">
                        {dateLabel(memory.updated_at)}
                      </span>
                    </div>
                    {proposed ? (
                      <div className="mt-4 flex gap-2">
                        <Button
                          size="sm"
                          disabled={review.isPending}
                          onClick={() =>
                            review.mutate({ memory, decision: "approved" })
                          }
                        >
                          <Check /> Approve exact wording
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={review.isPending}
                          onClick={() =>
                            review.mutate({ memory, decision: "rejected" })
                          }
                        >
                          <X /> Reject
                        </Button>
                      </div>
                    ) : memory.active ? (
                      <Button
                        className="mt-4"
                        size="sm"
                        variant="outline"
                        disabled={review.isPending}
                        onClick={() =>
                          review.mutate({ memory, decision: "revoked" })
                        }
                      >
                        <RotateCcw /> Revoke from future retrieval
                      </Button>
                    ) : null}
                  </article>
                );
              })}
            </div>
            <div className="mt-6 flex items-center justify-between text-xs text-muted-foreground">
              <span>
                {offset + 1}–{Math.min(offset + limit, page?.total ?? 0)} of{" "}
                {page?.total ?? 0}
              </span>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={offset === 0 || query.isFetching}
                  onClick={() => setOffset(Math.max(0, offset - limit))}
                >
                  <ChevronLeft /> Previous
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={
                    offset + limit >= (page?.total ?? 0) || query.isFetching
                  }
                  onClick={() => setOffset(offset + limit)}
                >
                  Next <ChevronRight />
                </Button>
              </div>
            </div>
          </>
        )}
      </div>
      {editing ? (
        <MemoryEditor
          record={editing === "new" ? undefined : editing}
          close={() => setEditing(undefined)}
        />
      ) : null}
    </>
  );
}
