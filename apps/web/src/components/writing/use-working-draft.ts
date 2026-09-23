"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import { WorkingDraft } from "@/lib/working-draft";

/** Mount the containing writer keyed by actor + scope. */
export function useWorkingDraft<T extends object>(
  actor: string,
  scope: string,
  initial: T,
) {
  const [draft] = useState(() => new WorkingDraft(actor, scope, initial));
  const state = useSyncExternalStore(
    draft.subscribe,
    draft.getSnapshot,
    draft.getSnapshot,
  );
  useEffect(() => {
    void draft.start();
    return () => draft.stop();
  }, [draft]);
  return { draft, ...state };
}
