"use client";

import { ArrowUpRight } from "lucide-react";
import { Mark, Status, Priority } from "./primitives";
import { WorkspaceRecord } from "@/lib/api";
import { cn } from "@/lib/utils";

interface OpportunityCardProps {
  opportunity: WorkspaceRecord;
  companyName?: string;
  onClick: () => void;
  isSelected?: boolean;
}

function recordName(record: WorkspaceRecord): string {
  if ("title" in record && record.title) return record.title;
  if ("name" in record && record.name) return record.name;
  return "Untitled";
}

function dateLabel(date: string | null | undefined): string {
  if (!date) return "—";
  const d = new Date(date);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;

  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function OpportunityCard({
  opportunity,
  companyName,
  onClick,
  isSelected,
}: OpportunityCardProps) {
  const title = recordName(opportunity);
  const notes = "notes" in opportunity ? opportunity.notes : null;
  const stage = "stage" in opportunity ? opportunity.stage : null;
  const priority = "priority" in opportunity ? opportunity.priority : null;
  const updatedAt = opportunity.updated_at;

  return (
    <button
      onClick={onClick}
      className={cn(
        "group relative flex w-full flex-col gap-3 rounded-xl border border-border bg-card p-5 text-left transition-all hover:border-border/80 hover:shadow-sm",
        isSelected && "border-primary/50 bg-accent/30 shadow-sm"
      )}
    >
      <div className="flex items-start gap-3">
        <Mark name={title} />
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <h3 className="text-sm font-semibold leading-snug text-foreground transition-colors group-hover:text-primary">
              {title}
            </h3>
            <ArrowUpRight className="size-4 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
          </div>
          {companyName && (
            <p className="mt-1 text-xs text-muted-foreground">
              {companyName}
            </p>
          )}
        </div>
      </div>

      {notes && (
        <p className="line-clamp-2 text-xs leading-relaxed text-muted-foreground">
          {notes}
        </p>
      )}

      <div className="flex items-center justify-between gap-3 pt-1">
        <div className="flex items-center gap-2">
          {stage && <Status value={stage} />}
          {typeof priority === "number" && <Priority value={priority} />}
        </div>
        <span className="text-xs text-muted-foreground">
          {dateLabel(updatedAt)}
        </span>
      </div>
    </button>
  );
}
