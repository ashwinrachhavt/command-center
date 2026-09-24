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
  type Schema,
} from "@/lib/api";
import { RetainedRequestIntent } from "@/lib/retained-intent";
import { ErrorState, Spinner, Status } from "./primitives";
import { useWorkspaceContext } from "./context";

const maxBytes = 20 * 1024 * 1024;
const supported =
  ".pdf,.docx,.jpg,.jpeg,.png,.txt,.md,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,image/jpeg,image/png,text/plain,text/markdown";
const supportedMediaTypes = new Set([
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "text/plain",
  "text/markdown",
  "image/jpeg",
  "image/png",
]);
const supportedExtensions = /\.(pdf|docx|jpg|jpeg|png|txt|md)$/i;

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

type UploadEntry = {
  key: string;
  file: File;
  title: string;
  state: "ready" | "uploading" | "queued" | "failed";
  error?: string;
};

function fileError(file: File) {
  if (file.size > maxBytes) return "Documents must be 20 MiB or smaller.";
  if (!supportedFile(file))
    return "Choose a PDF, DOCX, JPEG, PNG, plain text, or Markdown file.";
  return "";
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
  const [entries, setEntries] = useState<UploadEntry[]>([]);
  const [documentTypeId, setDocumentTypeId] = useState(
    artifact?.documentTypeId ?? "",
  );
  const [validation, setValidation] = useState("");
  const started = entries.some((entry) => entry.state !== "ready");
  const documentTypes = useQuery({
    queryKey: ["document-types"],
    enabled: open && !artifact,
    queryFn: () => api<DocumentType[]>("document-types"),
  });
  const policy = useQuery({
    queryKey: ["document-policy"],
    enabled: open && !artifact,
    queryFn: () => api<Schema["DocumentPolicyRead"]>("documents/policy"),
  });
  const selectedDocumentTypeId =
    documentTypeId ||
    documentTypes.data?.find((type) => type.slug === "unclassified")?.id ||
    "";
  const updateEntry = (key: string, change: Partial<UploadEntry>) =>
    setEntries((current) =>
      current.map((entry) =>
        entry.key === key ? { ...entry, ...change } : entry,
      ),
    );
  const upload = useMutation({
    mutationFn: async () => {
      if (!entries.length) throw new Error("Choose documents to upload.");
      if (!selectedDocumentTypeId) throw new Error("Choose a document type.");
      const results: DocumentImport[] = [];
      let failures = 0;
      setValidation("");
      // One bounded request at a time, with a retained key for each file. A retry
      // never resubmits a successful file or duplicates an uncertain response.
      for (const entry of entries) {
        if (entry.state === "queued") continue;
        const error =
          fileError(entry.file) ||
          (!entry.title.trim() ? "Add a title for this document." : "");
        if (error) {
          updateEntry(entry.key, { error });
          failures++;
          continue;
        }
        updateEntry(entry.key, { state: "uploading", error: undefined });
        const form = new FormData();
        form.set("file", entry.file);
        form.set("title", entry.title.trim());
        form.set("document_type_id", selectedDocumentTypeId);
        if (artifact) {
          form.set("artifact_id", artifact.id);
          form.set("expected_version", String(artifact.rowVersion));
        }
        try {
          const result = await apiForm<DocumentImport>(
            "documents/imports",
            form,
            { key: entry.key },
          );
          results.push(result);
          updateEntry(entry.key, { state: "queued" });
          client.invalidateQueries({
            queryKey: ["version-history", result.artifact_id],
          });
        } catch (error) {
          failures++;
          updateEntry(entry.key, {
            state: "failed",
            error:
              error instanceof Error
                ? error.message
                : "Upload failed. Retry this file.",
          });
        }
      }
      return { results, failures };
    },
    onSuccess: ({ results, failures }) => {
      client.invalidateQueries({ queryKey: ["document-imports"] });
      client.invalidateQueries({ queryKey: ["artifacts"] });
      if (failures) {
        setValidation(
          `${failures} file${failures === 1 ? " needs" : "s need"} attention. Successful uploads are saved; retry only the remaining files.`,
        );
        return;
      }
      toast.success(
        artifact
          ? "New original version queued for conversion"
          : entries.length === 1
            ? "Document queued for conversion"
            : `${entries.length} documents queued for conversion`,
      );
      setEntries([]);
      if (fileInput.current) fileInput.current.value = "";
      if (!artifact) setDocumentTypeId("");
      onOpenChange(false);
      if (entries.length === 1 && results[0]) onUploaded?.(results[0]);
    },
    onError: (error) => setValidation(error.message),
  });
  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        if (!upload.isPending) onOpenChange(value);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {artifact ? "Upload a new original version" : "Upload documents"}
          </DialogTitle>
          <DialogDescription>
            PDF, DOCX, JPEG, PNG, text, or Markdown up to 20 MiB per file.
            Images can be up to 25 megapixels. Originals are preserved and
            readable text is extracted in the background for review.
            {!artifact ? " Select several files to upload them together." : ""}
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
              multiple={!artifact}
              disabled={started || upload.isPending}
              onChange={(event) => {
                const files = Array.from(event.target.files ?? []);
                setEntries(
                  (artifact ? files.slice(0, 1) : files).map((file) => ({
                    key: crypto.randomUUID(),
                    file,
                    title:
                      artifact?.title ??
                      file.name.replace(/\.[^.]+$/, "").slice(0, 300),
                    state: "ready",
                    error: fileError(file),
                  })),
                );
                setValidation("");
              }}
            />
          </Field>
          <div
            className="max-h-64 space-y-3 overflow-y-auto"
            aria-live="polite"
          >
            {entries.map((entry, index) => (
              <div key={entry.key} className="space-y-2 rounded-md border p-3">
                <div className="flex items-start justify-between gap-2">
                  <p className="min-w-0 break-all text-xs">
                    {entry.file.name} · {sizeLabel(entry.file.size)}
                  </p>
                  {!started && !upload.isPending ? (
                    <Button
                      type="button"
                      size="icon-sm"
                      variant="ghost"
                      aria-label={`Remove ${entry.file.name}`}
                      onClick={() =>
                        setEntries((current) =>
                          current.filter((item) => item.key !== entry.key),
                        )
                      }
                    >
                      <X />
                    </Button>
                  ) : null}
                </div>
                <Field>
                  <FieldLabel htmlFor={`document-title-${index}`}>
                    {entries.length === 1
                      ? "Title"
                      : `Title for ${entry.file.name}`}
                  </FieldLabel>
                  <Input
                    id={`document-title-${index}`}
                    value={entry.title}
                    required
                    maxLength={300}
                    disabled={!!artifact || started || upload.isPending}
                    onChange={(event) =>
                      updateEntry(entry.key, { title: event.target.value })
                    }
                  />
                </Field>
                {entry.state === "uploading" ? (
                  <p className="text-xs">Uploading…</p>
                ) : null}
                {entry.state === "queued" ? (
                  <p className="text-xs text-muted-foreground">
                    Uploaded · queued for extraction
                  </p>
                ) : null}
                {entry.error ? (
                  <p role="alert" className="text-xs text-destructive">
                    {entry.error}
                  </p>
                ) : null}
              </div>
            ))}
          </div>
          {!artifact ? (
            <Field>
              <FieldLabel htmlFor="document-type">Document type</FieldLabel>
              <Select
                value={selectedDocumentTypeId}
                disabled={started || upload.isPending}
                onValueChange={setDocumentTypeId}
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
              <p className="text-xs text-muted-foreground">
                Choose Unclassified when the type needs review. Original
                filenames stay preserved.
                {policy.data?.classification_mode === "after_extraction" &&
                  ` Your settings send extracted text to ${policy.data.provider} for a type suggestion after extraction. You review any change.`}
              </p>
              {entries.length > 1 ? (
                <p className="text-xs text-muted-foreground">
                  Applies to all selected files.
                </p>
              ) : null}
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
            {started && !upload.isPending ? (
              <Button
                type="button"
                variant="ghost"
                onClick={() => {
                  setEntries([]);
                  setValidation("");
                  if (fileInput.current) fileInput.current.value = "";
                }}
              >
                Clear selection
              </Button>
            ) : null}
            <Button
              type="button"
              variant="outline"
              disabled={upload.isPending}
              onClick={() => onOpenChange(false)}
            >
              Keep for later
            </Button>
            <Button
              disabled={
                upload.isPending ||
                !entries.length ||
                !documentTypeId ||
                entries.some(
                  (entry) => !entry.title.trim() || !!fileError(entry.file),
                )
              }
            >
              {upload.isPending ? <Spinner /> : <FilePlus2 />}
              {validation
                ? "Retry upload"
                : entries.length > 1
                  ? `Upload ${entries.length} documents`
                  : "Upload original"}
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
  const [intent] = useState(() => new RetainedRequestIntent());
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
      const target = `documents/imports/${item.id}/${action}`;
      const body = { expected_version: item.row_version };
      const request = intent.forRequest("POST", target, body);
      return api<DocumentImport>(target, {
        method: "POST",
        key: request.key,
        body,
      });
    },
    onSuccess: (result, variables) => {
      intent.confirmRequest(
        "POST",
        `documents/imports/${variables.item.id}/${variables.action}`,
        { expected_version: variables.item.row_version },
      );
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
      const sessions = await api<Page<AgentSession>>(
        `agent-sessions?task_id=${item.task_id}&limit=1&offset=0`,
      );
      const sessionTarget = "agent-sessions";
      const sessionBody = { task_id: item.task_id };
      const session =
        sessions.items[0] ??
        (await api<AgentSession>("agent-sessions", {
          method: "POST",
          key: intent.forRequest("POST", sessionTarget, sessionBody).key,
          body: sessionBody,
        }));
      if (!sessions.items[0])
        intent.confirmRequest("POST", sessionTarget, sessionBody);
      const messageTarget = `agent-sessions/${session.id}/messages`;
      const messageBody = {
        profile: "application",
        content:
          `Read extracted document version ${item.extraction_version_id}. ` +
          "Propose evidenced profile facts with verbatim source excerpts for my review. Do not approve any facts.",
      };
      await api(messageTarget, {
        method: "POST",
        key: intent.forRequest("POST", messageTarget, messageBody).key,
        body: messageBody,
      });
      return { item, messageTarget, messageBody };
    },
    onSuccess: ({ item, messageTarget, messageBody }) => {
      intent.confirmRequest("POST", messageTarget, messageBody);
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
