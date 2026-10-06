"use client";

import dynamic from "next/dynamic";
import type { JSONContent } from "@tiptap/react";
import { Textarea } from "@/components/ui/textarea";

export type WritingFormat = "text" | "html" | "markdown";
export type RichWriterProps = {
  id: string;
  label: string;
  value: string;
  format?: WritingFormat;
  onChange: (
    value: string,
    format: WritingFormat,
    document?: JSONContent,
  ) => void;
  placeholder?: string;
  disabled?: boolean;
  /** Increment when deliberately loading another copy, never for keystrokes. */
  revision?: number;
};

// Keep the editor engine out of the shared workspace shell. Source editing
// remains available immediately without downloading Tiptap.
const TiptapWriter = dynamic(
  () => import("./tiptap-writer").then((module) => module.TiptapWriter),
  {
    loading: () => (
      <div
        role="status"
        className="min-h-56 rounded-lg border p-4 text-sm text-muted-foreground"
      >
        Loading editor…
      </div>
    ),
  },
);

// The shared writer supports these structures without changing their meaning.
// Keep unsupported legacy source intact instead of silently dropping it on import.
function needsSource(value: string, format: WritingFormat) {
  if (format === "text") return false;
  return (
    /<(?:table|img|video|audio|iframe|svg|style|script|figure|details)\b/i.test(
      value,
    ) ||
    (format === "markdown" &&
      (/!\[[^\]]*\]\(/.test(value) ||
        /^\s*\|.*\|\s*$/m.test(value) ||
        /^\s*[-*+]\s+\[[ xX]\]/m.test(value) ||
        /^\s*\[\^[^\]]+\]:/m.test(value) ||
        /^\s*\${2}/m.test(value) ||
        /<\/?[a-z][^>]*>/i.test(value)))
  );
}

export function RichWriter(props: RichWriterProps) {
  const format = props.format ?? "text";
  if (needsSource(props.value, format))
    return (
      <div className="space-y-2">
        <p className="text-xs text-muted-foreground">
          This writing contains a layout that needs source editing. Its original
          formatting is preserved.
        </p>
        <Textarea
          id={props.id}
          aria-label={props.label}
          value={props.value}
          disabled={props.disabled}
          rows={10}
          onChange={(event) => props.onChange(event.target.value, format)}
        />
      </div>
    );
  return <TiptapWriter key={props.revision ?? 0} {...props} />;
}
