"use client";

import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { api, dateLabel, type Schema } from "@/lib/api";
import { useWorkspaceContext } from "./context";
import { ErrorState, LoadingRows } from "./primitives";

export function ContactProviderHistory({ contactId }: { contactId: string }) {
  const context = useWorkspaceContext();
  const history = useQuery({
    queryKey: ["contact-provider-evidence", contactId],
    queryFn: () =>
      api<Schema["DiscoveryEvidenceRead"][]>(
        `contact-discovery/contacts/${contactId}/evidence`,
      ),
  });
  if (history.isPending) return <LoadingRows />;
  if (history.error)
    return (
      <ErrorState error={history.error} retry={() => void history.refetch()} />
    );
  if (!history.data.length) return null;
  return (
    <section
      className="mt-8 border-t border-border pt-6"
      aria-label="Contact discovery evidence"
    >
      <h3 className="text-sm font-medium">Contact discovery sources</h3>
      <p className="mt-1 text-xs leading-5 text-muted-foreground">
        Provider claims as observed. These remain separate from your editable
        contact details.
      </p>
      <div className="mt-4 space-y-3">
        {history.data.map((row) => (
          <article
            key={row.source_version_id}
            className="space-y-3 rounded-lg border p-4"
          >
            <div className="flex flex-wrap justify-between gap-2 text-xs">
              <span className="font-medium capitalize">
                {row.prospect.provider}
              </span>
              <span className="text-muted-foreground">
                Observed {dateLabel(row.observed_at)}
              </span>
            </div>
            <dl className="grid grid-cols-[80px_1fr] gap-x-3 gap-y-2 text-xs">
              {[
                ["Name", row.prospect.name],
                ["Email", row.prospect.email],
                [
                  "Email status",
                  row.prospect.email_status.replaceAll("_", " "),
                ],
                ["Position", row.prospect.title],
                ["Company", row.prospect.company_name],
              ].map(([name, value]) => (
                <div key={name} className="contents">
                  <dt className="text-muted-foreground">{name}</dt>
                  <dd className="min-w-0 break-words">
                    {value || "Not provided"}
                  </dd>
                </div>
              ))}
            </dl>
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                context?.open("artifacts", row.source_artifact_id, {
                  tab: "content",
                  versionId: row.source_version_id,
                })
              }
            >
              View saved source
            </Button>
          </article>
        ))}
      </div>
    </section>
  );
}
