"use client";

import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowUpRight,
  Download,
  FilePlus2,
  RefreshCw,
  Sparkles,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  api,
  apiDownload,
  apiForm,
  type AgentSession,
  type DocumentImport,
  type Page,
} from "@/lib/api";
import { ErrorState, Spinner, Status } from "./primitives";
import { useWorkspaceContext } from "./context";

const maxBytes = 20 * 1024 * 1024;
const supported =
  ".pdf,.docx,.txt,.md,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/markdown";
const supportedMediaTypes = new Set([
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "text/plain",
  "text/markdown",
]);
const supportedExtensions = /\.(pdf|docx|txt|md)$/i;

type DocumentType = { id: string; name: string; slug?: string };

function supportedFile(file: File) {
  return (
    supportedExtensions.test(file.name) &&
    (!file.type || supportedMediaTypes.has(file.type.toLowerCase()))
  );
}

function sizeLabel(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.ceil(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function DocumentUploadDialog({
  open,
  onOpenChange,
  artifact,
  onUploaded,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  artifact?: {
    id: string;
    title: string;
    documentTypeId: string;
    rowVersion: number;
  };
  onUploaded?: (result: DocumentImport) => void;
}) {
  const client = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File>();
  const [title, setTitle] = useState(artifact?.title ?? "");
  const [documentTypeId, setDocumentTypeId] = useState(
    artifact?.documentTypeId ?? "",
  );
  const [requestKey, setRequestKey] = useState(() => crypto.randomUUID());
  const [validation, setValidation] = useState("");
  const documentTypes = useQuery({
    queryKey: ["document-types"],
    enabled: open && !artifact,
    queryFn: () => api<DocumentType[]>("document-types"),
  });
  const changed = () => {
    setRequestKey(crypto.randomUUID());
    setValidation("");
  };
  const upload = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error("Choose a document to upload.");
      if (file.size > maxBytes)
        throw new Error("Documents must be 20 MiB or smaller.");
      if (!supportedFile(file))
        throw new Error("Choose a PDF, DOCX, plain text, or Markdown file.");
      if (!title.trim()) throw new Error("Add a title for this document.");
      if (!documentTypeId) throw new Error("Choose a document type.");
      const form = new FormData();
      form.set("file", file);
      form.set("title", title.trim());
      form.set("document_type_id", documentTypeId);
      if (artifact) {
        form.set("artifact_id", artifact.id);
        form.set("expected_version", String(artifact.rowVersion));
      }
      return apiForm<DocumentImport>("documents/imports", form, {
        key: requestKey,
      });
    },
    onSuccess: (result) => {
      client.invalidateQueries({ queryKey: ["document-imports"] });
      client.invalidateQueries({ queryKey: ["artifacts"] });
      client.invalidateQueries({ queryKey: ["versions", result.artifact_id] });
      toast.success(
        artifact
          ? "New original version queued for conversion"
          : "Document queued for conversion",
      );
      setRequestKey(crypto.randomUUID());
      setFile(undefined);
      if (fileInput.current) fileInput.current.value = "";
      if (!artifact) {
        setTitle("");
        setDocumentTypeId("");
      }
      onOpenChange(false);
      onUploaded?.(result);
    },
    onError: (error) => setValidation(error.message),
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {artifact ? "Upload a new original version" : "Upload document"}
          </DialogTitle>
          <DialogDescription>
            PDF, DOCX, text, or Markdown up to 20 MiB. The original file stays
            immutable while conversion runs in the background.
          </DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            upload.mutate();
          }}
        >
          <Field>
            <FieldLabel htmlFor="document-file">Document</FieldLabel>
            <Input
              id="document-file"
              ref={fileInput}
              type="file"
              accept={supported}
              required
              onChange={(event) => {
                const next = event.target.files?.[0];
                setFile(next);
                if (next && !artifact && !title)
                  setTitle(next.name.replace(/\.[^.]+$/, ""));
                changed();
                if (next && next.size > maxBytes)
                  setValidation("Documents must be 20 MiB or smaller.");
                else if (next && !supportedFile(next))
                  setValidation(
                    "Choose a PDF, DOCX, plain text, or Markdown file.",
                  );
              }}
            />
            {file ? (
              <p className="text-[11px] text-muted-foreground">
                {file.name} · {sizeLabel(file.size)}
              </p>
            ) : null}
          </Field>
          <Field>
            <FieldLabel htmlFor="document-title">Title</FieldLabel>
            <Input
              id="document-title"
              value={title}
              required
              maxLength={300}
              disabled={!!artifact}
              onChange={(event) => {
                setTitle(event.target.value);
                changed();
              }}
            />
          </Field>
          {!artifact ? (
            <Field>
              <FieldLabel htmlFor="document-type">Document type</FieldLabel>
              <Select
                value={documentTypeId}
                onValueChange={(value) => {
                  setDocumentTypeId(value);
                  changed();
                }}
              >
                <SelectTrigger id="document-type" aria-label="Document type">
                  <SelectValue placeholder="Choose a type" />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {documentTypes.data?.map((type) => (
                      <SelectItem value={type.id} key={type.id}>
                        {type.name}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
              {documentTypes.error ? (
                <p className="text-xs text-destructive" role="alert">
                  {documentTypes.error.message}
                </p>
              ) : null}
            </Field>
          ) : null}
          {validation ? (
            <p role="alert" className="text-xs text-destructive">
              {validation} Your selection is still here; retry when ready.
            </p>
          ) : null}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Keep for later
            </Button>
            <Button
              disabled={
                upload.isPending ||
                !file ||
                !title.trim() ||
                !documentTypeId ||
                file.size > maxBytes ||
                !supportedFile(file)
              }
            >
              {upload.isPending ? <Spinner /> : <FilePlus2 />}
              {validation ? "Retry upload" : "Upload original"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function downloadOriginal(item: DocumentImport) {
  return apiDownload(
    `artifacts/${item.artifact_id}/versions/${item.source_version_id}/download`,
  ).then(({ blob, filename }) => {
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename ?? item.filename;
    anchor.click();
    URL.revokeObjectURL(url);
  });
}

export function DocumentIntake() {
  const client = useQueryClient();
  const context = useWorkspaceContext();
  const [uploading, setUploading] = useState(false);
  const actionKeys = useRef<Record<string, string>>({});
  const suggestionKeys = useRef<
    Record<string, { session: string; message: string }>
  >({});
  const imports = useQuery({
    queryKey: ["document-imports"],
    queryFn: ({ signal }) =>
      api<Page<DocumentImport>>("documents/imports?limit=20&offset=0", {
        signal,
      }),
    refetchInterval: (query) =>
      query.state.data?.items.some((item) =>
        ["queued", "running"].includes(item.state),
      )
        ? 2_000
        : false,
  });
  const stateAction = useMutation({
    mutationFn: ({
      item,
      action,
    }: {
      item: DocumentImport;
      action: string;
    }) => {
      const signature = `${item.id}:${action}`;
      actionKeys.current[signature] ??= crypto.randomUUID();
      return api<DocumentImport>(`documents/imports/${item.id}/${action}`, {
        method: "POST",
        key: actionKeys.current[signature],
        body: { expected_version: item.row_version },
      });
    },
    onSuccess: (result, variables) => {
      delete actionKeys.current[`${variables.item.id}:${variables.action}`];
      client.invalidateQueries({ queryKey: ["document-imports"] });
      toast.success(
        variables.action === "retry"
          ? "Conversion queued again"
          : "Conversion cancelled",
      );
    },
    onError: (error) => toast.error(error.message),
  });
  const download = useMutation({
    mutationFn: downloadOriginal,
    onError: (error) => toast.error(error.message),
  });
  const suggest = useMutation({
    mutationFn: async (item: DocumentImport) => {
      if (!item.extraction_version_id)
        throw new Error("The extracted version is not available yet.");
      suggestionKeys.current[item.id] ??= {
        session: crypto.randomUUID(),
        message: crypto.randomUUID(),
      };
      const keys = suggestionKeys.current[item.id];
      const sessions = await api<Page<AgentSession>>(
        `agent-sessions?task_id=${item.task_id}&limit=1&offset=0`,
      );
      const session =
        sessions.items[0] ??
        (await api<AgentSession>("agent-sessions", {
          method: "POST",
          key: keys.session,
          body: { task_id: item.task_id },
        }));
      await api(`agent-sessions/${session.id}/messages`, {
        method: "POST",
        key: keys.message,
        body: {
          profile: "application",
          content:
            `Read extracted document version ${item.extraction_version_id}. ` +
            "Propose evidenced profile facts with verbatim source excerpts for my review. Do not approve any facts.",
        },
      });
      return item;
    },
    onSuccess: (item) => {
      delete suggestionKeys.current[item.id];
      window.history.pushState(
        null,
        "",
        `/tasks?record=${item.task_id}&tab=conversation`,
      );
    },
    onError: (error) => toast.error(error.message),
  });
  return (
    <section className="border-y border-border bg-card/30 px-5 py-4 md:px-9">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-medium">Document intake</h2>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            Original files and converted text remain pinned to exact versions.
          </p>
        </div>
        <Button size="sm" onClick={() => setUploading(true)}>
          <FilePlus2 /> Upload document
        </Button>
      </div>
      {imports.error ? (
        <ErrorState error={imports.error} retry={() => imports.refetch()} />
      ) : imports.data?.items.length ? (
        <div className="mt-4 divide-y divide-border rounded-lg border border-border bg-background">
          {imports.data.items.map((item) => (
            <div
              key={item.id}
              className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center"
            >
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="truncate text-sm font-medium">
                    {item.filename}
                  </p>
                  <Status value={item.state} />
                  {item.state === "completed" ? (
                    <Badge variant="outline" className="text-primary">
                      Extracted
                    </Badge>
                  ) : null}
                </div>
                <p className="mt-1 text-[11px] text-muted-foreground">
                  {sizeLabel(item.byte_size)} · Original version{" "}
                  <span className="font-mono">
                    {item.source_version_id.slice(0, 8)}
                  </span>
                </p>
                {item.error ? (
                  <p className="mt-1 text-xs text-destructive" role="alert">
                    {item.error}
                  </p>
                ) : null}
              </div>
              <div className="flex flex-wrap items-center gap-1">
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`Download original ${item.filename}`}
                  disabled={download.isPending}
                  onClick={() => download.mutate(item)}
                >
                  <Download />
                </Button>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`Open ${item.filename}`}
                  onClick={() =>
                    context?.open("artifacts", item.artifact_id, {
                      tab: "content",
                      versionId: item.source_version_id,
                    })
                  }
                >
                  <ArrowUpRight />
                </Button>
                {["queued", "running"].includes(item.state) ? (
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={stateAction.isPending}
                    onClick={() =>
                      stateAction.mutate({ item, action: "cancel" })
                    }
                  >
                    <X /> Cancel
                  </Button>
                ) : null}
                {["failed", "cancelled"].includes(item.state) ? (
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={stateAction.isPending}
                    onClick={() =>
                      stateAction.mutate({ item, action: "retry" })
                    }
                  >
                    <RefreshCw /> Retry
                  </Button>
                ) : null}
                {item.state === "completed" ? (
                  <Button
                    size="sm"
                    disabled={suggest.isPending || !item.extraction_version_id}
                    onClick={() => suggest.mutate(item)}
                  >
                    <Sparkles /> Suggest profile facts
                  </Button>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      ) : imports.isPending ? (
        <p className="mt-4 text-xs text-muted-foreground">Loading imports…</p>
      ) : (
        <p className="mt-4 text-xs text-muted-foreground">
          No document conversions yet.
        </p>
      )}
      <DocumentUploadDialog
        open={uploading}
        onOpenChange={setUploading}
        onUploaded={(result) => context?.open("artifacts", result.artifact_id)}
      />
    </section>
  );
}

export { sizeLabel };
