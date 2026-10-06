"use client";

import type { ReactNode } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { cn } from "@/lib/utils";

/** Keeps changing glyphs in one slot; the control owns its label and state. */
export function AnimatedIcon({
  state,
  children,
  className,
}: {
  state: string | number | boolean;
  children: ReactNode;
  className?: string;
}) {
  const reducedMotion = useReducedMotion();
  const hidden = {
    opacity: 0,
    scale: reducedMotion ? 1 : 0.25,
    filter: reducedMotion ? "blur(0px)" : "blur(4px)",
  };

  return (
    <span
      aria-hidden="true"
      data-slot="animated-icon"
      className={cn("relative inline-flex size-4 shrink-0", className)}
    >
      <AnimatePresence initial={false}>
        <motion.span
          key={String(state)}
          className="absolute inset-0 inline-flex items-center justify-center [&>svg]:size-full"
          initial={hidden}
          animate={{ opacity: 1, scale: 1, filter: "blur(0px)" }}
          exit={hidden}
          transition={{
            type: "spring",
            duration: reducedMotion ? 0 : 0.3,
            bounce: 0,
          }}
        >
          {children}
        </motion.span>
      </AnimatePresence>
    </span>
  );
}
