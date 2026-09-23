"use client";

import { useSyncExternalStore } from "react";

const changed = "command-center:panel-preference";
const fallback = new Map<string, boolean>();

function subscribe(listener: () => void) {
  window.addEventListener("storage", listener);
  window.addEventListener(changed, listener);
  return () => {
    window.removeEventListener("storage", listener);
    window.removeEventListener(changed, listener);
  };
}

export function usePanelOpen(panel: "navigation" | "chat-history") {
  const key = `command-center:${panel}:open`;
  const open = useSyncExternalStore(
    subscribe,
    () => {
      if (fallback.has(key)) return fallback.get(key)!;
      try {
        return localStorage.getItem(key) !== "false";
      } catch {
        return fallback.get(key) ?? true;
      }
    },
    () => true,
  );
  const setOpen = (value: boolean) => {
    try {
      localStorage.setItem(key, String(value));
      fallback.delete(key);
    } catch {
      // Keep the controls usable when browser storage is restricted.
      fallback.set(key, value);
    }
    window.dispatchEvent(new Event(changed));
  };
  return [open, setOpen] as const;
}
