"use client";

import { useCallback, useSyncExternalStore } from "react";
import { useAuth } from "@clerk/nextjs";

const changed = "conversation-draft-changed";
const fallback = new Map<string, string>();
const draftKey = (scope: string) => `cc:conversation-draft:${scope}`;
function readConversationDraft(scope: string) {
  const key = draftKey(scope);
  try {
    return sessionStorage.getItem(key) ?? "";
  } catch {
    return fallback.get(key) ?? "";
  }
}
function updateConversationDraft(
  scope: string,
  update: string | ((current: string) => string),
) {
  const key = draftKey(scope);
  const next =
    typeof update === "function"
      ? update(readConversationDraft(scope))
      : update;
  fallback.set(key, next);
  try {
    if (next) sessionStorage.setItem(key, next);
    else sessionStorage.removeItem(key);
  } catch {
    /* Keep drafts when tab storage is unavailable. */
  }
  window.dispatchEvent(new Event(changed));
}
const subscribe = (notify: () => void) => {
  window.addEventListener(changed, notify);
  window.addEventListener("storage", notify);
  return () => {
    window.removeEventListener(changed, notify);
    window.removeEventListener("storage", notify);
  };
};

export function useConversationDraft(scope: string) {
  const { userId } = useAuth();
  const ownedScope = `${userId ?? "signed-out"}:${scope}`;
  const read = useCallback(
    () => readConversationDraft(ownedScope),
    [ownedScope],
  );
  const value = useSyncExternalStore(subscribe, read, () => "");
  const set = useCallback(
    (update: string | ((current: string) => string)) => {
      updateConversationDraft(ownedScope, update);
    },
    [ownedScope],
  );
  const updateThread = useCallback(
    (thread: string, update: string | ((current: string) => string)) => {
      updateConversationDraft(`${userId ?? "signed-out"}:${thread}`, update);
    },
    [userId],
  );
  return [value, set, updateThread] as const;
}
