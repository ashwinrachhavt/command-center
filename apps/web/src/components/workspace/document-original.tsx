"use client";

import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { api, label, type DocumentImport, type Schema } from "@/lib/api";
import { AgentResponse } from "./agent-response";
import { useWorkspaceContext } from "./context";
import { ErrorState } from "./primitives";

/** Read the extraction pinned to this original, never a later derived version. */
export function DocumentOriginal({ imported }: { imported?: DocumentImport }) {
  const workspace = useWorkspaceContext();
  const extracted = useQuery({
    queryKey: [
      "artifact-version",
      imported?.extraction_artifact_id,
      imported?.extraction_version_id,
    ],
    enabled:
      !!imported?.extraction_artifact_id && !!imported.extraction_version_id,
    queryFn: () =>
      api<Schema["VersionRead"]>(
        `artifacts/${imported!.extraction_artifact_id}/versions/${imported!.extraction_version_id}`,
      ),
  });
  const hasExtraction =
    !!imported?.extraction_artifact_id && !!imported.extraction_version_id;
  return (
    <div className="min-w-0 space-y-4">
      <div className="rounded-lg border border-border bg-muted/30 p-4 text-sm leading-6">
        <p className="break-words font-medium">
          {imported?.filename ?? "Original file"}
        </p>
        <p className="mt-1 text-muted-foreground">
          Your original file is stored intact. Download it above to open it.
        </p>
        {imported && (
          <p className="mt-1 text-xs text-muted-foreground">
            {imported.media_type} ·{" "}
            {Math.max(1, Math.ceil(imported.byte_size / 1024)).toLocaleString()}{" "}
            KB
          </p>
        )}
        {!hasExtraction && (
          <p role="status" className="mt-2 text-xs text-muted-foreground">
            Text extraction is{" "}
            {imported?.state ? label(imported.state) : "not available"}. The
            original remains available.
          </p>
        )}
        {hasExtraction && (
          <Button
            className="mt-3"
            variant="outline"
            size="sm"
            onClick={() =>
              workspace?.open("artifacts", imported!.extraction_artifact_id!, {
                tab: "content",
                versionId: imported!.extraction_version_id!,
              })
            }
          >
            Open extracted text
          </Button>
        )}
      </div>
      {hasExtraction && (
        <section
          aria-label="Extracted text preview"
          className="min-w-0 rounded-lg border border-border p-4"
        >
          <h3 className="mb-1 text-sm font-medium">Text from this original</h3>
          <p className="mb-4 text-xs leading-5 text-muted-foreground">
            Extracted text may simplify the original layout. Check the original
            when formatting matters.
          </p>
          {extracted.isPending ? (
            <p role="status" className="text-sm text-muted-foreground">
              Loading extracted text…
            </p>
          ) : extracted.error ? (
            <ErrorState
              error={extracted.error}
              retry={() => extracted.refetch()}
            />
          ) : (
            <div
              className="max-h-[60vh] overflow-auto break-words rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              tabIndex={0}
              role="region"
              aria-label="Document text"
            >
              <AgentResponse>
                {String(
                  extracted.data.payload?.text ||
                    "No text was extracted from this file.",
                )}
              </AgentResponse>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
