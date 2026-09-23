"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { ContactProviderHistory } from "./contact-provider-history";
import { Button } from "@/components/ui/button";
import { api, type Page, type Schema } from "@/lib/api";
import { useWorkspaceContext } from "./context";
import { ErrorState, LoadingRows } from "./primitives";

export function ContactImportHistory({ contactId }: { contactId: string }) {
  return (
    <>
      <LinkedInImportHistory contactId={contactId} />
      <ContactProviderHistory contactId={contactId} />
    </>
  );
}
function LinkedInImportHistory({ contactId }: { contactId: string }) {
  const context = useWorkspaceContext();
  const history = useInfiniteQuery({
    queryKey: ["contact-observations", contactId],
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      api<Page<Schema["ContactObservationRead"]>>(
        `contacts/${contactId}/observations?limit=10&offset=${pageParam}`,
      ),
    getNextPageParam: (page) =>
      page.offset + page.items.length < page.total
        ? page.offset + page.items.length
        : undefined,
  });
  if (history.isPending) return <LoadingRows />;
  if (history.error)
    return (
      <ErrorState error={history.error} retry={() => void history.refetch()} />
    );
  if (!history.data.pages[0].total) return null;
  return (
    <section
      className="mt-8 border-t border-border pt-6"
      aria-label="Imported contact history"
    >
      <h3 className="text-sm font-medium">LinkedIn export history</h3>
      <p className="mt-1 text-xs leading-5 text-muted-foreground">
        Values as exported. Employment may have changed; your current contact
        details remain editable above.
      </p>
      <div className="mt-4 flex flex-col gap-4">
        {history.data.pages
          .flatMap((page) => page.items)
          .map((row) => (
            <div key={row.id} className="rounded-lg border border-border p-4">
              <dl className="grid grid-cols-[100px_1fr] gap-x-4 gap-y-2 text-xs leading-5">
                {[
                  ["First name", row.first_name],
                  ["Last name", row.last_name],
                  ["Email", row.email],
                  ["Company", row.company],
                  ["Position", row.position],
                  ["Connected on", row.connected_on],
                  ["LinkedIn URL", row.linkedin_url],
                ].map(([name, value]) => (
                  <div key={name} className="contents">
                    <dt className="text-muted-foreground">{name}</dt>
                    <dd className="min-w-0 break-words">
                      {value || "Not provided"}
                    </dd>
                  </div>
                ))}
              </dl>
              <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                <span className="text-xs text-muted-foreground">
                  Source row {row.source_row} · Imported{" "}
                  {new Date(row.imported_at).toLocaleDateString()}
                </span>
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
                  View source
                </Button>
              </div>
            </div>
          ))}
        {history.hasNextPage && (
          <Button
            variant="outline"
            disabled={history.isFetchingNextPage}
            onClick={() => void history.fetchNextPage()}
          >
            {history.isFetchingNextPage
              ? "Loading history…"
              : "Load more history"}
          </Button>
        )}
      </div>
    </section>
  );
}
