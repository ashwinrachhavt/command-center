"use client";

import { useState } from "react";
import {
  Check,
  ChevronDown,
  LoaderCircle,
  Wrench,
  XCircle,
} from "lucide-react";
import {
  Tool,
  ToolContent,
  ToolInput,
  ToolOutput,
  type ToolPart,
} from "@/components/ai-elements/tool";
import { CollapsibleTrigger } from "@/components/ui/collapsible";
import { label } from "@/lib/api";
import { cn } from "@/lib/utils";

const toolLabels: Record<string, string> = {
  catalog_search: "Finding tools",
  catalog_execute: "Using workspace tool",
  document_read: "Reading document",
  cc_documents_list_imports: "Finding uploaded documents",
  cc_documents_get_import: "Checking document extraction",
  gmail_search: "Searching Gmail",
  research_search: "Searching sources",
  connected_accounts: "Checking connected apps",
  ask_user: "Asking you",
  task: "Delegating work",
};

export function activityToolLabel(name: string, input?: unknown) {
  if (
    name === "catalog_execute" &&
    input &&
    typeof input === "object" &&
    "tool_name" in input &&
    typeof input.tool_name === "string"
  ) {
    return (
      toolLabels[input.tool_name] ??
      label(input.tool_name.replace(/^(api_|cc_)/, ""))
    );
  }
  return toolLabels[name] ?? label(name);
}

export function ActivityTool({
  name,
  state,
  input,
  output,
  errorText,
  role,
  summary,
  title: displayTitle,
}: {
  name: string;
  state: ToolPart["state"];
  input?: unknown;
  output?: unknown;
  errorText?: string;
  role?: string;
  summary?: string;
  title?: string;
}) {
  const [expanded, setExpanded] = useState<{ state: string; open: boolean }>();
  const failed = state === "output-error" || state === "output-denied";
  const pending = state === "input-available" || state === "input-streaming";
  // Each transition resets the default: errors open, successful results fold away.
  const open = expanded?.state === state ? expanded.open : failed;
  const title = displayTitle ?? activityToolLabel(name, input);
  const status = failed ? "Error" : pending ? "Running" : "Completed";
  const specialist =
    role && role !== "lead" && role !== "assistant" ? label(role) : undefined;
  const Icon = failed ? XCircle : pending ? LoaderCircle : Check;
  return (
    <Tool
      open={open}
      onOpenChange={(next) => setExpanded({ state, open: next })}
      className="mb-0 min-w-0 rounded-2xl border-border/60 bg-background/50 data-[state=closed]:w-fit data-[state=closed]:max-w-full"
    >
      <CollapsibleTrigger
        title={name}
        aria-label={[title, specialist, status].filter(Boolean).join(" ")}
        className="flex min-h-9 w-full items-center gap-2 rounded-2xl px-3 py-1.5 text-left text-xs outline-none hover:bg-muted/60 focus-visible:ring-2 focus-visible:ring-ring"
      >
        <Icon
          aria-hidden
          className={cn(
            "size-3.5 shrink-0",
            pending && "motion-safe:animate-spin",
            failed ? "text-destructive" : "text-muted-foreground",
          )}
        />
        <span className="min-w-0 truncate font-medium">{title}</span>
        {specialist ? (
          <span className="truncate text-muted-foreground">{specialist}</span>
        ) : null}
        <span className="sr-only"> {status}</span>
        <ChevronDown
          aria-hidden
          className={cn(
            "ml-auto size-3 shrink-0 text-muted-foreground transition-transform motion-reduce:transition-none",
            open && "rotate-180",
          )}
        />
      </CollapsibleTrigger>
      <ToolContent className="max-h-80 min-w-0 overflow-auto border-t border-border/50 p-3">
        <p className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
          <Wrench className="size-3" />
          {name} · {status}
        </p>
        {summary ? (
          <p className="text-sm whitespace-pre-wrap">{summary}</p>
        ) : null}
        {input !== undefined ? <ToolInput input={input} /> : null}
        {output !== undefined || errorText ? (
          <ToolOutput output={output} errorText={errorText} />
        ) : (
          <p className="text-xs text-muted-foreground">
            {pending
              ? "Waiting for the result…"
              : "No result was recorded for this step."}
          </p>
        )}
      </ToolContent>
    </Tool>
  );
}
