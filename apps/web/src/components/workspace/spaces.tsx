"use client";
import { useDebouncedValue } from "@/hooks/use-debounced-value";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  ArrowLeft,
  ArrowRight,
  FolderOpen,
  Link2,
  Pencil,
  Plus,
  RotateCcw,
  Unlink,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  api,
  ApiError,
  label,
  recordName,
  type Page,
  type Resource,
  type Space,
  type SpaceDetail,
  type SpaceLink,
  type WorkspaceRecord,
} from "@/lib/api";
import { RetainedRequestIntent } from "@/lib/retained-intent";
import { cn } from "@/lib/utils";
import { QuickCapture } from "./briefing";
import { useWorkspaceContext } from "./context";
import {
  EmptyState,
  ErrorState,
  LoadingRows,
  PageHeading,
  Spinner,
} from "./primitives";

const recordKinds = {
  task: { resource: "tasks", title: "Tasks" },
  artifact: { resource: "artifacts", title: "Sources & decisions" },
  contact: { resource: "contacts", title: "Contacts" },
  company: { resource: "companies", title: "Companies" },
  opportunity: { resource: "opportunities", title: "Opportunities" },
} satisfies Record<
  SpaceLink["record_type"],
  { resource: Resource; title: string }
>;

function useSpaceWrite() {
  const client = useQueryClient();
  const [intent] = useState(() => new RetainedRequestIntent());
  return useMutation({
    mutationFn: ({
      path,
      body,
      method = "POST",
    }: {
      path: string;
      body: unknown;
      method?: "POST" | "PATCH";
    }) => {
      const request = intent.forRequest(method, path, body);
      return api<SpaceDetail>(path, { method, body, key: request.key });
    },
    onSuccess: (space) => {
      intent.reset();
      client.setQueryData(["spaces", "detail", space.id], space);
      void client.invalidateQueries({ queryKey: ["spaces"] });
      void client.invalidateQueries({ queryKey: ["activity"] });
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409)
        void client.invalidateQueries({ queryKey: ["spaces"] });
    },
  });
}

function SpaceEditor({
  space,
  onClose,
  onSaved,
}: {
  space?: SpaceDetail;
  onClose: () => void;
  onSaved: (space: SpaceDetail) => void;
}) {
  const [title, setTitle] = useState(space?.title ?? "");
  const [purpose, setPurpose] = useState(space?.purpose ?? "");
  const save = useSpaceWrite();
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !save.isPending) onClose();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{space ? "Edit Space" : "Create a Space"}</DialogTitle>
          <DialogDescription>
            Keep a purpose, its next actions, and supporting context together.
          </DialogDescription>
        </DialogHeader>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (!title.trim() || save.isPending) return;
            save.mutate(
              {
                path: space ? `spaces/${space.id}` : "spaces",
                method: space ? "PATCH" : "POST",
                body: {
                  title: title.trim(),
                  purpose: purpose.trim() || null,
                  ...(space ? { expected_version: space.row_version } : {}),
                },
              },
              {
                onSuccess: (saved) => {
                  onSaved(saved);
                  toast.success(space ? "Space updated." : "Space created.");
                },
              },
            );
          }}
          className="space-y-5"
        >
          <div className="space-y-2">
            <label htmlFor="space-title" className="text-sm font-medium">
              Name
            </label>
            <Input
              id="space-title"
              autoFocus
              required
              maxLength={300}
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              disabled={save.isPending}
              placeholder="What are you working toward?"
            />
          </div>
          <div className="space-y-2">
            <label htmlFor="space-purpose" className="text-sm font-medium">
              Purpose
            </label>
            <Textarea
              id="space-purpose"
              maxLength={20000}
              value={purpose}
              onChange={(event) => setPurpose(event.target.value)}
              disabled={save.isPending}
              placeholder="What would progress look like?"
              className="min-h-28"
            />
          </div>
          {save.error && (
            <p role="alert" className="text-sm text-destructive">
              {save.error.message} Your changes are still here.
            </p>
          )}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={onClose}
              disabled={save.isPending}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={!title.trim() || save.isPending}>
              {save.isPending && <Spinner />}
              {space ? "Save changes" : "Create Space"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function LinkRecordDialog({
  space,
  onClose,
}: {
  space: SpaceDetail;
  onClose: () => void;
}) {
  const [kind, setKind] = useState<SpaceLink["record_type"]>("task");
  const [search, setSearch] = useState("");
  const settledSearch = useDebouncedValue(search.trim());
  const [offset, setOffset] = useState(0);
  const save = useSpaceWrite();
  const resource = recordKinds[kind].resource;
  const records = useQuery({
    queryKey: ["spaces", "candidates", resource, settledSearch, offset],
    queryFn: ({ signal }) =>
      api<Page<WorkspaceRecord>>(
        `${resource}?q=${encodeURIComponent(settledSearch)}&limit=20&offset=${offset}`,
        { signal },
      ),
  });
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !save.isPending) onClose();
      }}
    >
      <DialogContent className="max-h-[85dvh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Link an existing record</DialogTitle>
          <DialogDescription>
            Choose saved work or context for {space.title}. Notes, documents,
            and decisions can be linked from Sources & decisions.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <label htmlFor="space-record-kind" className="text-sm font-medium">
              Record type
            </label>
            <Select
              value={kind}
              onValueChange={(value) => {
                setKind(value as SpaceLink["record_type"]);
                setSearch("");
                setOffset(0);
                save.reset();
              }}
              disabled={save.isPending}
            >
              <SelectTrigger id="space-record-kind" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(recordKinds).map(([value, entry]) => (
                  <SelectItem key={value} value={value}>
                    {entry.title}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Input
            aria-label="Search saved records"
            placeholder="Search saved records…"
            value={search}
            disabled={save.isPending}
            onChange={(event) => {
              setSearch(event.target.value);
              setOffset(0);
            }}
          />
          {records.isPending ? (
            <LoadingRows />
          ) : records.error ? (
            <ErrorState
              error={records.error}
              retry={() => void records.refetch()}
            />
          ) : (
            <div className="space-y-1">
              {!records.data?.items.length && (
                <p className="py-6 text-center text-sm text-muted-foreground">
                  No matching records. Try another search or record type.
                </p>
              )}
              {records.data?.items.map((record) => {
                const linked = space.links.some(
                  (link) =>
                    link.record_type === kind && link.record_id === record.id,
                );
                return (
                  <div
                    key={record.id}
                    className="flex items-center gap-3 rounded-lg border border-border p-3"
                  >
                    <p className="min-w-0 flex-1 break-words text-sm">
                      {recordName(record)}
                    </p>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={
                        linked || save.isPending || space.state === "archived"
                      }
                      aria-label={
                        linked
                          ? `${recordName(record)} already linked`
                          : `Link ${recordName(record)}`
                      }
                      onClick={() =>
                        save.mutate(
                          {
                            path: `spaces/${space.id}/links`,
                            body: {
                              expected_version: space.row_version,
                              record_type: kind,
                              record_id: record.id,
                            },
                          },
                          { onSuccess: () => toast.success("Record linked.") },
                        )
                      }
                    >
                      {linked ? "Linked" : "Link"}
                    </Button>
                  </div>
                );
              })}
              {!!records.data?.total && (
                <div className="flex items-center justify-between gap-3 pt-3 text-xs text-muted-foreground">
                  <span>
                    {offset + 1}–{Math.min(offset + 20, records.data.total)} of{" "}
                    {records.data.total}
                  </span>
                  <div className="flex gap-1">
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={!offset || save.isPending}
                      onClick={() => setOffset(offset - 20)}
                    >
                      Previous
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={
                        offset + 20 >= records.data.total || save.isPending
                      }
                      onClick={() => setOffset(offset + 20)}
                    >
                      Next
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}
          {save.error && (
            <p role="alert" className="text-sm text-destructive">
              {save.error.message}
            </p>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={save.isPending}>
            Done
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function LinkedRecords({
  title,
  description,
  links,
  space,
}: {
  title: string;
  description: string;
  links: SpaceLink[];
  space: SpaceDetail;
}) {
  const context = useWorkspaceContext();
  const unlink = useSpaceWrite();
  return (
    <section className="rounded-xl shadow-surface bg-card p-5">
      <h3 className="text-sm font-medium">
        {title}{" "}
        <span className="ms-1 font-normal text-muted-foreground">
          {links.length}
        </span>
      </h3>
      {!links.length && (
        <p className="mt-3 text-sm text-muted-foreground">{description}</p>
      )}
      <ul className="mt-3 divide-y divide-border">
        {links.map((link) => {
          const record = link.record as WorkspaceRecord;
          const name = recordName(record);
          const status =
            "state" in record
              ? record.state
              : "stage" in record
                ? record.stage
                : null;
          return (
            <li key={link.id} className="flex items-center gap-2 py-2">
              <button
                className="group min-w-0 flex-1 rounded-md py-2 text-start outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={() =>
                  context?.open(
                    recordKinds[link.record_type].resource,
                    link.record_id,
                  )
                }
              >
                <span className="block break-words text-sm font-medium group-hover:underline">
                  {name}
                </span>
                <span className="mt-1 block text-xs text-muted-foreground">
                  {label(link.record_type)}
                  {status ? ` · ${label(status)}` : ""}
                </span>
              </button>
              {space.state === "active" && (
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={`Unlink ${name}`}
                  title="Unlink from Space"
                  disabled={unlink.isPending}
                  onClick={() =>
                    unlink.mutate(
                      {
                        path: `spaces/${space.id}/links/${link.id}/unlink`,
                        body: { expected_version: space.row_version },
                      },
                      {
                        onSuccess: () =>
                          toast.success(
                            "Record unlinked. The record is still saved.",
                          ),
                      },
                    )
                  }
                >
                  <Unlink aria-hidden className="size-4" />
                </Button>
              )}
            </li>
          );
        })}
      </ul>
      {unlink.error && (
        <p role="alert" className="mt-2 text-sm text-destructive">
          {unlink.error.message}
        </p>
      )}
    </section>
  );
}

function SpaceContent({
  space,
  onEdit,
  onStateChange,
}: {
  space: SpaceDetail;
  onEdit: () => void;
  onStateChange: (state: "active" | "archived") => void;
}) {
  const [linking, setLinking] = useState(false);
  const changeState = useSpaceWrite();
  const archived = space.state === "archived";
  const isNextAction = (link: SpaceLink) =>
    link.record_type === "task" &&
    "state" in link.record &&
    !["done", "cancelled"].includes(String(link.record.state));
  return (
    <div className="min-w-0 space-y-5">
      <section className="rounded-xl shadow-surface bg-card p-5 md:p-6">
        <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:flex-wrap">
          <div className="min-w-0 w-full sm:w-auto sm:flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-xs text-muted-foreground">Space</p>
              {archived && <Badge variant="secondary">Archived</Badge>}
            </div>
            <h2 className="mt-2 break-words text-xl font-medium tracking-tight">
              {space.title}
            </h2>
          </div>
          <div className="flex flex-wrap gap-2">
            {!archived && (
              <Button variant="outline" size="sm" onClick={onEdit}>
                <Pencil aria-hidden />
                Edit Space
              </Button>
            )}
            <Button
              variant="outline"
              size="sm"
              disabled={changeState.isPending}
              onClick={() =>
                changeState.mutate(
                  {
                    path: `spaces/${space.id}/${archived ? "restore" : "archive"}`,
                    body: { expected_version: space.row_version },
                  },
                  {
                    onSuccess: (result) => {
                      onStateChange(result.state);
                      toast.success(
                        archived
                          ? "Space restored."
                          : "Space archived. You can restore it from Archived.",
                      );
                    },
                  },
                )
              }
            >
              {changeState.isPending ? (
                <Spinner />
              ) : archived ? (
                <RotateCcw aria-hidden />
              ) : (
                <Archive aria-hidden />
              )}
              {archived ? "Restore Space" : "Archive Space"}
            </Button>
          </div>
        </div>
        <h3 className="mt-6 text-xs font-medium text-muted-foreground">
          Purpose
        </h3>
        <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-relaxed">
          {space.purpose || "Add a purpose to keep the next step in view."}
        </p>
        {archived && (
          <p className="mt-5 border-t border-border pt-4 text-sm text-muted-foreground">
            This Space is archived. Its saved context remains available. Restore
            it to add or change linked work.
          </p>
        )}
        {changeState.error && (
          <p role="alert" className="mt-3 text-sm text-destructive">
            {changeState.error.message}
          </p>
        )}
      </section>
      {!archived && <QuickCapture space={space} />}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-base font-medium">Linked context</h2>
        {!archived && (
          <Button size="sm" variant="outline" onClick={() => setLinking(true)}>
            <Link2 aria-hidden />
            Link existing record
          </Button>
        )}
      </div>
      <div className="grid gap-4 2xl:grid-cols-2">
        <LinkedRecords
          title="Next actions"
          description="Capture a next step or link an existing task."
          links={space.links.filter(isNextAction)}
          space={space}
        />
        <LinkedRecords
          title="Related work"
          description="Link opportunities or completed tasks to retain the wider context."
          links={space.links.filter(
            (link) =>
              link.record_type === "opportunity" ||
              (link.record_type === "task" && !isNextAction(link)),
          )}
          space={space}
        />
        <LinkedRecords
          title="People & organizations"
          description="Link the contacts and companies involved."
          links={space.links.filter((link) =>
            ["contact", "company"].includes(link.record_type),
          )}
          space={space}
        />
        <LinkedRecords
          title="Sources & decisions"
          description="Link saved notes, documents, research, or decisions from your Library."
          links={space.links.filter((link) => link.record_type === "artifact")}
          space={space}
        />
      </div>
      {linking && (
        <LinkRecordDialog space={space} onClose={() => setLinking(false)} />
      )}
    </div>
  );
}

export function Spaces() {
  const [state, setState] = useState<"active" | "archived">("active");
  const [search, setSearch] = useState("");
  const settledSearch = useDebouncedValue(search.trim());
  const [offset, setOffset] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editor, setEditor] = useState<"new" | "edit" | null>(null);
  const list = useQuery({
    queryKey: ["spaces", "list", state, settledSearch, offset],
    queryFn: ({ signal }) =>
      api<Page<Space>>(
        `spaces?state=${state}&q=${encodeURIComponent(settledSearch)}&limit=25&offset=${offset}`,
        { signal },
      ),
  });
  const detail = useQuery({
    queryKey: ["spaces", "detail", selectedId],
    queryFn: () => api<SpaceDetail>(`spaces/${selectedId}`),
    enabled: !!selectedId,
  });
  return (
    <div className="min-w-0 pb-8">
      <PageHeading
        title="Spaces"
        description="A place for each purpose, with its work and context together."
        action={
          <Button onClick={() => setEditor("new")}>
            <Plus aria-hidden />
            New Space
          </Button>
        }
      />
      <div className="grid min-w-0 gap-6 px-5 md:px-9 lg:grid-cols-[260px_minmax(0,1fr)]">
        <aside
          aria-label="Browse Spaces"
          className={cn("min-w-0 space-y-4", selectedId && "hidden lg:block")}
        >
          <div
            className="flex gap-1 rounded-lg bg-muted p-1"
            role="group"
            aria-label="Space status"
          >
            {(["active", "archived"] as const).map((value) => (
              <Button
                key={value}
                variant={state === value ? "secondary" : "ghost"}
                size="sm"
                className="flex-1"
                aria-pressed={state === value}
                onClick={() => {
                  setState(value);
                  setOffset(0);
                  setSelectedId(null);
                }}
              >
                {label(value)}
              </Button>
            ))}
          </div>
          <Input
            aria-label="Search Spaces"
            value={search}
            placeholder="Search Spaces…"
            onChange={(event) => {
              setSearch(event.target.value);
              setOffset(0);
            }}
          />
          {list.isPending ? (
            <LoadingRows />
          ) : list.error ? (
            <ErrorState error={list.error} retry={() => void list.refetch()} />
          ) : (
            <>
              {!list.data?.items.length && (
                <p className="px-2 py-5 text-sm text-muted-foreground">
                  {search
                    ? "No matching Spaces."
                    : state === "archived"
                      ? "No archived Spaces."
                      : "No Spaces yet. Create one for something you want to move forward."}
                </p>
              )}
              <div className="space-y-2">
                {list.data?.items.map((space) => (
                  <button
                    key={space.id}
                    onClick={() => setSelectedId(space.id)}
                    aria-pressed={selectedId === space.id}
                    className={cn(
                      "block w-full rounded-xl border p-4 text-start outline-none transition-colors hover:bg-muted/50 focus-visible:ring-2 focus-visible:ring-ring",
                      selectedId === space.id
                        ? "border-primary/50 bg-primary/5"
                        : "border-border bg-card",
                    )}
                  >
                    <span className="flex items-start gap-2">
                      <FolderOpen
                        aria-hidden
                        className="mt-0.5 size-4 shrink-0 text-muted-foreground"
                      />
                      <span className="min-w-0 break-words text-sm font-medium">
                        {space.title}
                      </span>
                    </span>
                    <span className="mt-2 block line-clamp-2 break-words text-xs leading-relaxed text-muted-foreground">
                      {space.purpose || "No purpose added yet"}
                    </span>
                  </button>
                ))}
              </div>
              {!!list.data?.total && (
                <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
                  <span>
                    {offset + 1}–{Math.min(offset + 25, list.data.total)} of{" "}
                    {list.data.total}
                  </span>
                  <div className="flex gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label="Previous Spaces"
                      disabled={!offset}
                      onClick={() => setOffset(offset - 25)}
                    >
                      <ArrowLeft aria-hidden />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label="Next Spaces"
                      disabled={offset + 25 >= list.data.total}
                      onClick={() => setOffset(offset + 25)}
                    >
                      <ArrowRight aria-hidden />
                    </Button>
                  </div>
                </div>
              )}
            </>
          )}
        </aside>
        <div className="min-w-0">
          {selectedId ? (
            <>
              <Button
                variant="ghost"
                size="sm"
                className="mb-4 lg:hidden"
                onClick={() => setSelectedId(null)}
              >
                <ArrowLeft aria-hidden />
                All Spaces
              </Button>
              {detail.isPending ? (
                <LoadingRows />
              ) : detail.error ? (
                <ErrorState
                  error={detail.error}
                  retry={() => void detail.refetch()}
                />
              ) : (
                detail.data && (
                  <SpaceContent
                    key={detail.data.id}
                    space={detail.data}
                    onEdit={() => setEditor("edit")}
                    onStateChange={(next) => {
                      setState(next);
                      setOffset(0);
                    }}
                  />
                )
              )}
            </>
          ) : (
            <div className="rounded-xl border border-dashed border-border">
              <EmptyState
                title="Keep the whole picture together"
                description="Choose a Space to see its purpose, next actions, people, and sources. Each record stays available in the rest of your workspace."
              >
                <Button variant="outline" onClick={() => setEditor("new")}>
                  <Plus aria-hidden />
                  Create a Space
                </Button>
              </EmptyState>
            </div>
          )}
        </div>
      </div>
      {editor && (editor === "new" || detail.data) && (
        <SpaceEditor
          space={editor === "edit" ? detail.data : undefined}
          onClose={() => setEditor(null)}
          onSaved={(space) => {
            setSelectedId(space.id);
            setState(space.state);
            setOffset(0);
            setSearch("");
            setEditor(null);
          }}
        />
      )}
    </div>
  );
}
