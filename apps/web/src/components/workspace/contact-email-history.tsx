"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { api, type Page, type Schema } from "@/lib/api";
import { ErrorState, Status } from "./primitives";
import { ReviewedActionDialog } from "./reviewed-actions";
import { sendTimeLabel } from "./email-delivery";

export function ContactEmailHistory({ recipient }: { recipient: string }) {
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<string>();
  const history = useQuery({
    queryKey: ["reviewed-actions", "contact", recipient, offset],
    queryFn: () =>
      api<Page<Schema["ActionRead"]>>(
        `reviewed-actions?${new URLSearchParams({ recipient, kind: "gmail_send", limit: "10", offset: String(offset) })}`,
      ),
    refetchInterval: 10000,
  });
  return (
    <section
      aria-label="Email delivery history"
      className="space-y-3 rounded-xl border p-4"
    >
      <h3 className="text-sm font-medium">Emails & scheduled sends</h3>
      <p className="text-xs text-muted-foreground">
        Messages to {recipient} prepared or sent from Command Center. Open a
        scheduled email to edit its timing or cancel it.
      </p>
      {history.error && (
        <ErrorState
          error={history.error}
          retry={() => void history.refetch()}
        />
      )}
      {history.isPending && (
        <p role="status" className="text-sm">
          Loading emails…
        </p>
      )}
      {history.data?.total === 0 && (
        <p className="text-sm text-muted-foreground">
          No email proposals yet. Prepare a saved draft for review below.
        </p>
      )}
      {history.data?.items.map((action) => (
        <button
          key={action.id}
          type="button"
          className="flex w-full items-center justify-between gap-3 rounded-lg border p-3 text-start hover:bg-muted/50"
          onClick={() => setSelected(action.id)}
        >
          <span className="min-w-0">
            <span className="block truncate text-sm font-medium">
              {String(action.current.payload.subject || "No subject")}
            </span>
            <span className="mt-1 block text-xs text-muted-foreground">
              {action.state === "succeeded" && action.attempt?.completed_at
                ? `Sent ${sendTimeLabel(action.attempt.completed_at)}`
                : action.current.scheduled_for
                  ? `${action.state === "proposed" ? "Proposed time" : "Send time"}: ${sendTimeLabel(action.current.scheduled_for)}`
                  : "Send after review"}
            </span>
          </span>
          <Status
            value={
              action.state === "queued" && action.current.scheduled_for
                ? "scheduled"
                : action.state
            }
          />
        </button>
      ))}
      {!!history.data && history.data.total > 10 && (
        <div className="flex justify-between gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={!offset}
            onClick={() => setOffset(Math.max(0, offset - 10))}
          >
            Previous emails
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={offset + 10 >= history.data.total}
            onClick={() => setOffset(offset + 10)}
          >
            Next emails
          </Button>
        </div>
      )}
      {selected && (
        <ReviewedActionDialog
          actionId={selected}
          close={() => setSelected(undefined)}
        />
      )}
    </section>
  );
}
