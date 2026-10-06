"use client";

import { ChainOfThoughtStep } from "@/components/ai-elements/chain-of-thought";
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
    <ChainOfThoughtStep
      icon={Icon}
      status={pending ? "active" : "complete"}
      data-tool-state={state}
      className={failed ? "text-destructive" : undefined}
      label={
        <Tool
          open={open}
          onOpenChange={(next) => setExpanded({ state, open: next })}
          className="mb-0 min-w-0 rounded-lg border-0 bg-transparent"
        >
          <CollapsibleTrigger
            title={name}
            aria-label={[title, specialist, status].filter(Boolean).join(" ")}
            className="flex min-h-8 w-full items-center gap-2 rounded-lg px-2 py-1 text-start text-xs outline-none transition-colors duration-150 ease-out hover:bg-muted/60 focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none"
          >
            <span className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-2 gap-y-1">
              <span className="min-w-0 break-words font-medium">{title}</span>
              {specialist ? (
                <span className="text-muted-foreground">{specialist}</span>
              ) : null}
              <span
                className={cn(
                  "text-[11px]",
                  failed ? "text-destructive" : "text-muted-foreground",
                )}
              >
                {status}
              </span>
            </span>
            <ChevronDown
              aria-hidden
              className={cn(
                "ms-auto size-3 shrink-0 text-muted-foreground transition-transform duration-150 ease-out motion-reduce:transition-none",
                open && "rotate-180",
              )}
            />
          </CollapsibleTrigger>
          <ToolContent className="mt-2 max-h-80 min-w-0 overflow-auto rounded-xl border border-border/50 bg-muted/30 p-3">
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
      }
    />
  );
}
