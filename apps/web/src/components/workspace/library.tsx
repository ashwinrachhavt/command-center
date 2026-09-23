"use client";

import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowUpRight,
  FileText,
  History,
  NotebookPen,
  Plus,
  Search,
  Upload,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ArtifactWriter } from "@/components/writing/artifact-writer";
import { useArtifactHistory } from "@/components/writing/use-artifact-history";
import { api, dateLabel, label, type Page, type Schema } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useWorkspaceContext } from "./context";
import { DocumentIntake, DocumentUploadDialog } from "./document-intake";
import { ErrorState, LoadingRows } from "./primitives";
import { RecordEditor } from "./record-editor";
import { DocumentTasks } from "./document-tasks";

type Artifact = Schema["ArtifactRead"];
type DocumentType = { id: string; slug: string; name: string };

export function Library({
  notes: legacyNotes = false,
  vault = false,
}: {
  notes?: boolean;
  vault?: boolean;
}) {
  const workspace = useWorkspaceContext();
  const params = useSearchParams();
  const notes = !vault && (legacyNotes || params.get("view") === "notes");
  const generated = !vault && params.get("view") === "generated";
  const selected = notes ? params.get("note") : null;
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [type, setType] = useState("all");
  const [sort, setSort] = useState("recent");
  const [offset, setOffset] = useState(0);
  const [creating, setCreating] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [showUploads, setShowUploads] = useState(false);
  const [review, setReview] = useState("all");
  const [newNote, setNewNote] = useState(false);
  const listHeading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(search);
      setOffset(0);
    }, 250);
    return () => clearTimeout(timer);
  }, [search]);
  const types = useQuery({
    queryKey: ["document-types"],
    queryFn: () => api<DocumentType[]>("document-types"),
  });
  const noteType = types.data?.find((item) => item.slug === "notes");
  const collection = vault
    ? "vault"
    : notes
      ? "notes"
      : generated
        ? "generated"
        : "library";
  const records = useQuery({
    queryKey: ["artifacts", collection, query, type, review, sort, offset],
    queryFn: ({ signal }) => {
      const filter = new URLSearchParams({
        collection,
        q: query,
        sort,
        limit: "30",
        offset: String(offset),
      });
      if (type !== "all" && !notes) filter.set("document_type_id", type);
      if (review !== "all" && !vault && !notes) filter.set("review", review);
      return api<Page<Artifact>>(`artifacts?${filter}`, { signal });
    },
  });
  function selectNote(id: string | null) {
    const url = new URL(window.location.href);
    if (id) url.searchParams.set("note", id);
    else url.searchParams.delete("note");
    window.history.pushState(null, "", url);
    if (!id) requestAnimationFrame(() => listHeading.current?.focus());
  }
  return (
    <div className="mx-auto max-w-[1500px] p-5 md:p-8">
      <header className="mb-7 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="mb-2 text-xs font-medium tracking-wide text-muted-foreground">
            YOUR WORKSPACE
          </p>
          <h1 className="text-2xl font-semibold tracking-tight">
            {vault ? "Document Vault" : "Library"}
          </h1>
          <p className="mt-2 max-w-xl text-sm leading-6 text-muted-foreground">
            {vault
              ? "Original files, extracted text, and source metadata. Keep the documents you rely on together."
              : "Your notes and agent-created work. Read, refine, and review every saved version."}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {vault && (
            <Button variant="outline" onClick={() => setUploading(true)}>
              <Upload />
              Upload document
            </Button>
          )}
          {!vault && !notes && (
            <Button
              variant="outline"
              disabled={!noteType}
              onClick={() => {
                setNewNote(true);
                setCreating(true);
              }}
            >
              <NotebookPen />
              New note
            </Button>
          )}
          {!vault && (
            <Button
              disabled={notes && !noteType}
              onClick={() => {
                setNewNote(notes);
                setCreating(true);
              }}
            >
              <Plus />
              {notes ? "New note" : "Write document"}
            </Button>
          )}
        </div>
      </header>
      {!vault && (
        <nav
          aria-label="Library collections"
          className="mb-6 flex flex-wrap gap-1 border-b border-border pb-3"
        >
          {[
            {
              name: "All work",
              href: "/library",
              active: !notes && !generated,
            },
            { name: "Notes", href: "/library?view=notes", active: notes },
            {
              name: "Agent outputs",
              href: "/library?view=generated",
              active: generated,
            },
          ].map((item) => (
            <Button
              key={item.name}
              variant={item.active ? "secondary" : "ghost"}
              size="sm"
              asChild
            >
              <Link
                href={item.href}
                aria-current={item.active ? "page" : undefined}
                onClick={() => setOffset(0)}
              >
                {item.name}
              </Link>
            </Button>
          ))}
        </nav>
      )}
      {types.error && (
        <ErrorState error={types.error} retry={() => types.refetch()} />
      )}
      {notes && types.data && !noteType && (
        <p role="alert">
          The Notes document type is unavailable. Check the workspace setup.
        </p>
      )}
      <div
        className={cn(
          "grid min-w-0 gap-6",
          notes &&
            selected &&
            "md:grid-cols-[minmax(220px,280px)_minmax(0,1fr)]",
        )}
      >
        <section
          aria-label={notes ? "Note list" : "Document library"}
          className={cn("min-w-0", notes && selected && "hidden md:block")}
        >
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <div className="relative min-w-[160px] flex-1">
              <Search
                aria-hidden
                className="absolute top-3 left-3 size-4 text-muted-foreground"
              />
              <Input
                className="pl-9"
                aria-label={
                  vault
                    ? "Search vault"
                    : notes
                      ? "Search notes"
                      : "Search library"
                }
                placeholder="Search titles and saved content…"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </div>
            {!notes && (
              <Select
                value={type}
                onValueChange={(value) => {
                  setType(value);
                  setOffset(0);
                }}
              >
                <SelectTrigger
                  className="w-44"
                  aria-label="Document type filter"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All document types</SelectItem>
                  {types.data?.map((item) => (
                    <SelectItem key={item.id} value={item.id}>
                      {item.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
            {!vault && !notes && (
              <Select
                value={review}
                onValueChange={(value) => {
                  setReview(value);
                  setOffset(0);
                }}
              >
                <SelectTrigger
                  className="w-40"
                  aria-label="Review status filter"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All review states</SelectItem>
                  <SelectItem value="unreviewed">Needs review</SelectItem>
                  <SelectItem value="approved">Approved</SelectItem>
                  <SelectItem value="rejected">Rejected</SelectItem>
                  <SelectItem value="revoked">Revoked</SelectItem>
                </SelectContent>
              </Select>
            )}
            <Select
              value={sort}
              onValueChange={(value) => {
                setSort(value);
                setOffset(0);
              }}
            >
              <SelectTrigger
                className={cn("w-36", notes && selected && "w-full")}
                aria-label="Sort documents"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="recent">Recently updated</SelectItem>
                <SelectItem value="title">Title A–Z</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="mb-3 flex items-center justify-between gap-2">
            <h2
              ref={listHeading}
              tabIndex={-1}
              className="text-xs font-medium text-muted-foreground outline-none"
            >
              {query
                ? "SEARCH RESULTS"
                : notes
                  ? "ALL NOTES"
                  : vault
                    ? "YOUR SOURCE DOCUMENTS"
                    : "SAVED IN YOUR LIBRARY"}
            </h2>
            <span role="status" className="text-xs text-muted-foreground">
              {records.data
                ? `${records.data.total} ${notes ? "notes" : "items"}`
                : "Loading…"}
            </span>
          </div>
          {records.isPending ? (
            <LoadingRows />
          ) : records.error ? (
            <ErrorState error={records.error} retry={() => records.refetch()} />
          ) : records.data.items.length ? (
            <ul className="overflow-hidden rounded-xl border border-border divide-y divide-border">
              {records.data.items.map((record) => (
                <li key={record.id}>
                  <button
                    className={cn(
                      "group flex w-full min-w-0 items-start gap-3 p-4 text-left transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
                      selected === record.id && "bg-primary/5",
                    )}
                    aria-current={selected === record.id ? "page" : undefined}
                    onClick={() =>
                      notes
                        ? selectNote(record.id)
                        : workspace?.open("artifacts", record.id, {
                            tab: "content",
                          })
                    }
                  >
                    {notes ? (
                      <NotebookPen
                        aria-hidden
                        className="mt-0.5 size-4 shrink-0 text-muted-foreground"
                      />
                    ) : (
                      <FileText
                        aria-hidden
                        className="mt-0.5 size-4 shrink-0 text-muted-foreground"
                      />
                    )}
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">
                        {record.title}
                      </span>
                      <span className="mt-1.5 block text-xs leading-5 text-muted-foreground">
                        {types.data?.find(
                          (item) => item.id === record.document_type_id,
                        )?.name ?? label(record.kind)}{" "}
                        · {dateLabel(record.updated_at)}
                        {!vault && !notes && (
                          <span className="ml-2 inline-block rounded bg-muted px-2 py-0.5">
                            {!record.review_status ||
                            record.review_status === "unreviewed"
                              ? "Needs review"
                              : label(record.review_status)}
                          </span>
                        )}
                      </span>
                    </span>
                    {(!notes || !selected) && (
                      <span className="hidden text-xs text-muted-foreground sm:block">
                        Version {record.latest_version}
                      </span>
                    )}
                    {!notes && (
                      <ArrowUpRight
                        aria-hidden
                        className="size-4 shrink-0 text-muted-foreground"
                      />
                    )}
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <div className="rounded-xl border border-dashed border-border px-6 py-14 text-center">
              <h3 className="font-medium">
                {query || type !== "all"
                  ? "No matching documents"
                  : notes
                    ? "A little space to think"
                    : "Make room for your work"}
              </h3>
              <p className="mx-auto mt-2 max-w-sm text-sm leading-6 text-muted-foreground">
                {query || type !== "all"
                  ? "Try a different phrase or document type. Search covers saved versions; working drafts stay in the writer."
                  : notes
                    ? "Capture an interview, a question, or a half-formed idea. Your writing autosaves as you go."
                    : vault
                      ? "Upload a résumé, paper, brief, or other source document. Read the original alongside its extracted text."
                      : "Write a note or ask an agent to research or draft something. Saved outputs and their reviews appear here."}
              </p>
              {!query && type === "all" && (
                <Button
                  className="mt-5"
                  variant="outline"
                  disabled={notes && !noteType}
                  onClick={() =>
                    vault ? setUploading(true) : setCreating(true)
                  }
                >
                  <Plus />
                  {vault
                    ? "Upload your first document"
                    : notes
                      ? "Write your first note"
                      : "Write your first document"}
                </Button>
              )}
            </div>
          )}
          {records.data && records.data.total > 30 && (
            <div className="mt-4 flex items-center justify-between gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - 30))}
              >
                Previous
              </Button>
              <span className="text-xs text-muted-foreground">
                {offset + 1}–{Math.min(offset + 30, records.data.total)} of{" "}
                {records.data.total}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={offset + 30 >= records.data.total}
                onClick={() => setOffset(offset + 30)}
              >
                Next
              </Button>
            </div>
          )}
        </section>
        {notes && selected && (
          <NoteCanvas
            key={selected}
            id={selected}
            onBack={() => selectNote(null)}
          />
        )}
      </div>
      {vault && (
        <div className="mt-6 border-t border-border pt-5">
          <Button
            variant="ghost"
            aria-expanded={showUploads}
            aria-controls="library-uploads"
            onClick={() => setShowUploads(!showUploads)}
          >
            {showUploads
              ? "Hide recent uploads"
              : "Recent uploads & extraction status"}
          </Button>
          {showUploads && (
            <div id="library-uploads" className="mt-4">
              <DocumentIntake />
            </div>
          )}
        </div>
      )}
      <RecordEditor
        resource="artifacts"
        open={creating}
        onOpenChange={setCreating}
        noun={notes || newNote ? "note" : "document"}
        draftKey={notes || newNote ? "new-note" : "new-library-document"}
        defaults={{
          kind: "document",
          ...((notes || newNote) && noteType
            ? { document_type_id: noteType.id }
            : {}),
        }}
        hiddenFields={
          notes || newNote
            ? ["kind", "document_type_id", "sensitivity"]
            : ["kind"]
        }
        onSaved={(record) =>
          notes
            ? selectNote(record.id)
            : workspace?.open("artifacts", record.id, { tab: "content" })
        }
      />
      <DocumentUploadDialog open={uploading} onOpenChange={setUploading} />
    </div>
  );
}

function NoteCanvas({ id, onBack }: { id: string; onBack: () => void }) {
  const client = useQueryClient();
  const workspace = useWorkspaceContext();
  const heading = useRef<HTMLHeadingElement>(null);
  const [editingTitle, setEditingTitle] = useState(false);
  const [metadataRevision, setMetadataRevision] = useState<number>();
  const record = useQuery({
    queryKey: ["artifacts", id],
    queryFn: () => api<Artifact>(`artifacts/${id}`),
  });
  const history = useArtifactHistory(id);
  // Pin the opening version; refetching history must never replace the active writer.
  const [baseId, setBaseId] = useState<string>();
  if (!baseId && history.items[0]) setBaseId(history.items[0].id);
  const version = useQuery({
    queryKey: ["artifact-version", id, baseId],
    enabled: !!baseId,
    queryFn: () =>
      api<Schema["VersionRead"]>(`artifacts/${id}/versions/${baseId}`),
  });
  const readerReady =
    !!record.data && !history.isPending && (!baseId || !version.isPending);
  useEffect(() => {
    if (readerReady) heading.current?.focus();
  }, [readerReady]);
  if (record.error || history.error || version.error)
    return (
      <div>
        <Button variant="ghost" onClick={onBack}>
          <ArrowLeft />
          All notes
        </Button>
        <ErrorState
          error={(record.error ?? history.error ?? version.error)!}
          retry={() => {
            void record.refetch();
            void history.refetch();
            if (baseId) void version.refetch();
          }}
        />
      </div>
    );
  if (!record.data || history.isPending || (baseId && version.isPending))
    return <LoadingRows />;
  const note = record.data;
  return (
    <section
      aria-label="Note workspace"
      className="min-w-0 rounded-xl border border-border bg-card p-5 md:p-7"
    >
      <div className="mb-5 flex flex-wrap items-center gap-2">
        <Button variant="ghost" size="sm" onClick={onBack}>
          <ArrowLeft />
          All notes
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="ml-auto"
          onClick={() => workspace?.open("artifacts", id, { tab: "content" })}
        >
          <History />
          History & export
        </Button>
      </div>
      <h2
        ref={heading}
        tabIndex={-1}
        className="break-words text-2xl leading-9 font-semibold tracking-tight outline-none"
      >
        {note.title}
      </h2>
      <div className="mt-2 mb-6 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span>Updated {dateLabel(note.updated_at)}</span>
        <span aria-hidden>·</span>
        <Button
          size="sm"
          variant="link"
          className="h-auto p-0 text-xs"
          onClick={() => setEditingTitle(true)}
        >
          Edit details
        </Button>
      </div>
      {note.archived_at ? (
        <p role="status">
          This note is archived. Its saved history remains available.
        </p>
      ) : version.data && typeof version.data.payload?.text === "string" ? (
        <ArtifactWriter
          artifactId={id}
          continuous
          metadataRevision={metadataRevision}
          initial={{
            text: version.data.payload.text,
            baseVersionId: version.data.id,
            baseVersion: version.data.version,
            expectedVersion: note.row_version,
          }}
          onClose={() => {}}
          onSaved={(saved) => {
            client.setQueryData(["artifact-version", id, saved.id], saved);
            void client.invalidateQueries({ queryKey: ["artifacts"] });
            void client.invalidateQueries({
              queryKey: ["version-history", id],
            });
          }}
        />
      ) : (
        <div className="rounded-lg bg-muted/40 p-4 text-sm">
          <p>
            This note contains a stored file. Open its original and extracted
            text in the reader.
          </p>
          <Button
            variant="outline"
            className="mt-3"
            onClick={() => workspace?.open("artifacts", id, { tab: "content" })}
          >
            Open document
          </Button>
        </div>
      )}
      <DocumentTasks artifactId={id} archived={!!note.archived_at} />
      <RecordEditor
        resource="artifacts"
        record={note}
        open={editingTitle}
        onOpenChange={setEditingTitle}
        noun="note"
        onSaved={(saved) => setMetadataRevision(saved.row_version)}
      />
    </section>
  );
}
