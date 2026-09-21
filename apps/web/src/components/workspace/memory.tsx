"use client";
import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Pencil, Plus, Archive } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { api, dateLabel, type Page } from "@/lib/api";
import { EmptyState, ErrorState, LoadingRows, PageHeading } from "./primitives";

type Memory = {
  id: string;
  title: string;
  content: string;
  kind: "note" | "preference";
  source: string;
  row_version: number;
  updated_at: string;
};
function MemoryEditor({
  record,
  close,
}: {
  record?: Memory;
  close: () => void;
}) {
  const [title, setTitle] = useState(record?.title ?? "");
  const [content, setContent] = useState(record?.content ?? "");
  const key = useRef({ signature: "", value: "" });
  const client = useQueryClient();
  const save = useMutation({
    mutationFn: () => {
      const signature = title + content;
      if (key.current.signature !== signature)
        key.current = { signature, value: crypto.randomUUID() };
      return api(`memories${record ? `/${record.id}` : ""}`, {
        method: record ? "PATCH" : "POST",
        body: {
          title,
          content,
          kind: record?.kind ?? "note",
          ...(record ? { expected_version: record.row_version } : {}),
        },
        key: key.current.value,
      });
    },
    onSuccess: () => {
      client.invalidateQueries();
      close();
      toast.success("Memory saved");
    },
    onError: (e) => toast.error(e.message),
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
            {record ? "Edit memory" : "Remember something"}
          </DialogTitle>
          <DialogDescription>
            Keep useful preferences and working context close to your agents.
          </DialogDescription>
        </DialogHeader>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="memory-title">Title</FieldLabel>
              <Input
                id="memory-title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                required
                maxLength={200}
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="memory-content">Context</FieldLabel>
              <Textarea
                id="memory-content"
                value={content}
                onChange={(e) => setContent(e.target.value)}
                rows={6}
                required
                maxLength={10000}
              />
            </Field>
          </FieldGroup>
          <Button className="mt-5" disabled={save.isPending}>
            Save memory
          </Button>
          {save.error && (
            <p className="mt-3 text-destructive" role="alert">
              {save.error.message}
            </p>
          )}
        </form>
      </DialogContent>
    </Dialog>
  );
}
export function MemoryPage() {
  const [editing, setEditing] = useState<Memory | "new">();
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["memories"],
    queryFn: () => api<Page<Memory>>("memories?limit=100"),
  });
  const archive = useMutation({
    mutationFn: (m: Memory) =>
      api(`memories/${m.id}/archive`, {
        method: "POST",
        body: { expected_version: m.row_version },
      }),
    onSuccess: () => {
      client.invalidateQueries();
      toast.success("Memory archived");
    },
    onError: (e) => toast.error(e.message),
  });
  return (
    <>
      <PageHeading
        title="Workspace memory"
        description="Useful context that stays with you. Readable, editable and always yours."
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
          Memory helps agents understand preferences and prior work. Notes are
          context—not verified candidate facts or permission to take external
          actions.
        </div>
        {query.error ? (
          <ErrorState error={query.error} />
        ) : query.isPending ? (
          <LoadingRows />
        ) : query.data.items.length === 0 ? (
          <EmptyState
            title="Give your agents a little context"
            description="Remember how you like to work, what you’re exploring and what matters to you."
          >
            <Button variant="outline" onClick={() => setEditing("new")}>
              Add your first memory
            </Button>
          </EmptyState>
        ) : (
          <div className="grid gap-4 lg:grid-cols-2">
            {query.data.items.map((m) => (
              <article
                key={m.id}
                className="rounded-xl border border-border bg-card p-5"
              >
                <div className="flex items-start gap-3">
                  <h2 className="flex-1 text-sm font-medium">{m.title}</h2>
                  <Button
                    size="icon-xs"
                    variant="ghost"
                    aria-label={`Edit ${m.title}`}
                    onClick={() => setEditing(m)}
                  >
                    <Pencil />
                  </Button>
                  <Button
                    size="icon-xs"
                    variant="ghost"
                    aria-label={`Archive ${m.title}`}
                    disabled={archive.isPending}
                    onClick={() => archive.mutate(m)}
                  >
                    <Archive />
                  </Button>
                </div>
                <p className="mt-3 whitespace-pre-wrap text-xs leading-6 text-muted-foreground">
                  {m.content}
                </p>
                <div className="mt-5 flex items-center justify-between">
                  <Badge
                    variant="outline"
                    className="font-normal text-muted-foreground"
                  >
                    {m.source === "agent" ? "Agent note" : "Added by you"}
                  </Badge>
                  <span className="text-[10px] text-muted-foreground">
                    {dateLabel(m.updated_at)}
                  </span>
                </div>
              </article>
            ))}
          </div>
        )}
      </div>
      {editing && (
        <MemoryEditor
          record={editing === "new" ? undefined : editing}
          close={() => setEditing(undefined)}
        />
      )}
    </>
  );
}
