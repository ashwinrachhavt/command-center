"use client";

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Download, FileOutput, RotateCcw, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { api, apiDownload, label, type PdfExport } from "@/lib/api";
import { RetainedRequestIntent } from "@/lib/retained-intent";
import { Status, Spinner } from "./primitives";

export function PdfExportControl({
  artifactId,
  versionId,
  version,
  title,
  editable,
}: {
  artifactId: string;
  versionId: string;
  version: number;
  title: string;
  editable: boolean;
}) {
  const [exportIds, setExportIds] = useState<Record<string, string>>({});
  const [intent] = useState(() => new RetainedRequestIntent());
  const exportId = exportIds[versionId];
  const detail = useQuery({
    queryKey: ["pdf-export", exportId],
    enabled: !!exportId,
    queryFn: ({ signal }) =>
      api<PdfExport>(`pdf-exports/${exportId}`, { signal }),
    refetchInterval: (query) =>
      ["queued", "running"].includes(query.state.data?.state ?? "")
        ? 1000
        : false,
  });
  const create = useMutation({
    mutationFn: () => {
      const target = `artifacts/${artifactId}/versions/${versionId}/exports`;
      const body = { format: "pdf", task_id: null };
      const request = intent.forRequest("POST", target, body);
      return api<PdfExport>(target, {
        method: "POST",
        body,
        key: request.key,
      }).then((result) => ({ result, target, body }));
    },
    onSuccess: ({ result, target, body }) => {
      intent.confirmRequest("POST", target, body);
      setExportIds((current) => ({ ...current, [versionId]: result.id }));
      toast.success(`PDF export queued from version ${version}`);
    },
    onError: (error) => toast.error(error.message),
  });
  const change = useMutation({
    mutationFn: (action: "cancel" | "retry") => {
      if (!detail.data) throw new Error("The PDF export is unavailable.");
      const target = `pdf-exports/${detail.data.id}/${action}`;
      const body = { expected_version: detail.data.row_version };
      const request = intent.forRequest("POST", target, body);
      return api<PdfExport>(target, {
        method: "POST",
        body,
        key: request.key,
      }).then((result) => ({ result, target, body }));
    },
    onSuccess: ({ result, target, body }) => {
      intent.confirmRequest("POST", target, body);
      detail.refetch();
      toast.success(
        result.state === "queued"
          ? "PDF export queued again"
          : "PDF export cancelled",
      );
    },
    onError: (error) => toast.error(error.message),
  });
  const download = useMutation({
    mutationFn: async () => {
      const output = detail.data?.output;
      if (!output) throw new Error("The PDF is not ready.");
      return apiDownload(
        `artifacts/${output.artifact_id}/versions/${output.version_id}/download`,
      );
    },
    onSuccess: ({ blob, filename }) => {
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download =
        filename ?? `${title.replace(/[^a-z0-9 -]/gi, "_")}-v${version}.pdf`;
      anchor.click();
      URL.revokeObjectURL(url);
    },
    onError: (error) => toast.error(error.message),
  });
  const current =
    detail.data ??
    (create.data?.result.source.version_id === versionId
      ? create.data.result
      : undefined);

  if (!current) {
    return (
      <Button
        variant="outline"
        size="sm"
        onClick={() => create.mutate()}
        disabled={!editable || create.isPending}
        title={editable ? undefined : "Choose an editable text version"}
      >
        {create.isPending ? <Spinner /> : <FileOutput />}
        Export version {version} to PDF
      </Button>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border border-border/70 px-3 py-2">
      <span className="text-xs text-muted-foreground">
        PDF from version {version}
      </span>
      <Status value={current.state} />
      {current.state === "completed" && current.output ? (
        <Button
          variant="outline"
          size="sm"
          onClick={() => download.mutate()}
          disabled={download.isPending}
        >
          {download.isPending ? <Spinner /> : <Download />}
          Download PDF
        </Button>
      ) : null}
      {["queued", "running"].includes(current.state) ? (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => change.mutate("cancel")}
          disabled={change.isPending}
        >
          <X />
          Cancel
        </Button>
      ) : null}
      {["failed", "cancelled"].includes(current.state) ? (
        <Button
          variant="outline"
          size="sm"
          onClick={() => change.mutate("retry")}
          disabled={change.isPending || current.cleanup_pending}
        >
          <RotateCcw />
          Retry
        </Button>
      ) : null}
      {current.error_code ? (
        <span className="text-xs text-destructive">
          {label(current.error_code)}
        </span>
      ) : null}
      {current.cleanup_pending ? (
        <span className="text-xs text-muted-foreground">
          Waiting for renderer cleanup
        </span>
      ) : null}
    </div>
  );
}
