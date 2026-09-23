"use client";

import { useState } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { api, type Schema } from "@/lib/api";
import type { DraftState, WorkingDraft } from "@/lib/working-draft";

export function DraftStatus<T extends object>({
  draft,
  state,
  preview,
  disabled = false,
}: {
  draft: WorkingDraft<T>;
  state: DraftState<T>;
  preview?: (data: T) => string;
  disabled?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(undefined);
    try {
      await action();
    } catch (error) {
      setError(error instanceof Error ? error.message : "Unable to save");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div
      className="space-y-2 text-xs text-muted-foreground"
      data-testid="draft-status"
    >
      <p>
        {state.status === "loading"
          ? "Opening draft…"
          : state.status === "saving"
            ? "Saving…"
            : state.status === "saved"
              ? "Draft saved"
              : state.status === "ready"
                ? "Unsaved changes"
                : state.status === "conflict"
                  ? "Two copies need your attention"
                  : "Unable to save draft"}
        {state.recovered && " · Recovered from this tab"}
      </p>
      {(state.error || error || state.recoveryWarning) && (
        <p role="alert" className="text-destructive">
          {error ?? state.error ?? state.recoveryWarning}
        </p>
      )}
      {state.status === "error" && (
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={busy || disabled}
          onClick={() => void run(() => draft.flush())}
        >
          Retry draft save
        </Button>
      )}
      {state.status === "conflict" && (
        <div className="space-y-2 rounded-md border p-3">
          <p>
            Compare the saved copy with your writing above. The copy you replace
            is kept in this tab for recovery.
          </p>
          <details>
            <summary className="cursor-pointer">Saved copy</summary>
            <pre className="max-h-48 overflow-auto whitespace-pre-wrap p-2 text-xs">
              {state.remote === undefined
                ? "Saved copy unavailable. Retry when connected."
                : state.remote === null
                  ? "This draft was cleared."
                  : (preview?.(state.remote) ?? "A different copy is saved.")}
            </pre>
          </details>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={busy || disabled}
              onClick={() => void run(() => draft.resolveConflict("remote"))}
            >
              Use saved copy
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={busy || disabled}
              onClick={() => void run(() => draft.resolveConflict("local"))}
            >
              Save my copy
            </Button>
          </div>
        </div>
      )}
      {state.recovery && state.status !== "conflict" && (
        <details>
          <summary className="cursor-pointer">
            Previous copy kept in this tab
          </summary>
          <pre className="max-h-48 overflow-auto whitespace-pre-wrap py-2">
            {preview?.(state.recovery) ??
              "Your previous writing is available to restore."}
          </pre>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={busy || disabled || state.status === "loading"}
            onClick={() => void run(async () => draft.recoverOtherCopy())}
          >
            Restore previous copy
          </Button>
        </details>
      )}
      <EarlierDrafts
        draft={draft}
        preview={preview}
        disabled={
          busy || disabled || ["loading", "conflict"].includes(state.status)
        }
        restore={(data) => run(async () => draft.restoreRecovery(data))}
      />
    </div>
  );
}

function EarlierDrafts<T extends object>({
  draft,
  preview,
  disabled,
  restore,
}: {
  draft: WorkingDraft<T>;
  preview?: (data: T) => string;
  disabled: boolean;
  restore: (data: T) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<string>();
  const path = `writing-drafts/${draft.scope}/recovery`;
  const history = useInfiniteQuery({
    queryKey: ["writing-recovery", draft.actor, draft.scope],
    enabled: open,
    initialPageParam: undefined as number | undefined,
    queryFn: ({ pageParam }) =>
      api<Schema["RecoveryHistory"]>(
        `${path}${pageParam ? `?before=${pageParam}` : ""}`,
      ),
    getNextPageParam: (page) => page.next_before ?? undefined,
  });
  const copy = useQuery({
    queryKey: ["writing-recovery-copy", draft.actor, draft.scope, selected],
    enabled: open && !!selected,
    queryFn: () => api<Schema["RecoveryRead"]>(`${path}/${selected}`),
    staleTime: Infinity,
  });
  return (
    <details onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary className="cursor-pointer">Earlier drafts</summary>
      {open && (
        <div className="mt-2 space-y-3 rounded-md border p-3">
          <p>
            The latest 20 working copies are kept, about five minutes apart
            while you write and before a draft is cleared. Restoring creates an
            editable draft; it does not approve or send anything.
          </p>
          {history.isPending && <p role="status">Loading earlier drafts…</p>}
          {history.error && <p role="alert">{history.error.message}</p>}
          {history.data?.pages[0].total === 0 && <p>No earlier drafts yet.</p>}
          <div className="flex flex-wrap gap-2">
            {history.data?.pages
              .flatMap((page) => page.items)
              .map((item) => (
                <Button
                  key={item.id}
                  type="button"
                  size="sm"
                  variant={selected === item.id ? "secondary" : "outline"}
                  aria-pressed={selected === item.id}
                  onClick={() => setSelected(item.id)}
                >
                  {new Date(item.created_at).toLocaleString(undefined, {
                    month: "short",
                    day: "numeric",
                    hour: "numeric",
                    minute: "2-digit",
                  })}{" "}
                  · copy {item.row_version}
                </Button>
              ))}
          </div>
          {history.hasNextPage && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={history.isFetchingNextPage}
              onClick={() => void history.fetchNextPage()}
            >
              Load earlier copies
            </Button>
          )}
          {selected && copy.isPending && (
            <p role="status">Opening earlier draft…</p>
          )}
          {copy.error && <p role="alert">{copy.error.message}</p>}
          {copy.data && (
            <>
              <pre className="max-h-48 overflow-auto whitespace-pre-wrap text-xs">
                {preview?.(copy.data.data as T) ??
                  JSON.stringify(copy.data.data, null, 2)}
              </pre>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={disabled}
                onClick={() => void restore(copy.data.data as T)}
              >
                Restore this draft
              </Button>
              <p>Your current copy stays available in this tab.</p>
            </>
          )}
        </div>
      )}
    </details>
  );
}
