"use client";

import { Direction } from "radix-ui";
import { useSyncExternalStore } from "react";

function subscribe(onChange: () => void) {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["dir"],
  });
  return () => observer.disconnect();
}

/** Keep portalled controls and their keyboard order aligned with the page. */
export function DirectionProvider({ children }: { children: React.ReactNode }) {
  const dir = useSyncExternalStore<"ltr" | "rtl">(
    subscribe,
    () => (document.documentElement.dir === "rtl" ? "rtl" : "ltr"),
    () => "ltr",
  );
  return <Direction.Provider dir={dir}>{children}</Direction.Provider>;
}
