"use client";
import {
  AlertCircle,
  BookOpen,
  CheckCircle2,
  ChevronRight,
  Clock,
  MessageSquarePlus,
  PenLine,
  Play,
  Search,
  StickyNote,
  Zap,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { type WorkspaceRecord, dateLabel, label } from "@/lib/api";

// ─── Archetype inference ───────────────────────────────────────────────────

type TaskArchetype =
  | "Lead Review"
  | "Outreach"
  | "Application"
  | "Research"
  | "Follow-up"
  | "Task";

const ARCHETYPE_PATTERNS: [TaskArchetype, RegExp][] = [
  ["Lead Review", /review|evaluate|assess|screen|score/i],
  ["Outreach", /outreach|reach out|contact|message|email|connect/i],
  ["Application", /apply|application|submit|interview|prep|prepare/i],
  ["Research", /research|investigate|find|explore|analyze|look up/i],
  ["Follow-up", /follow.?up|check in|remind|ping|nudge/i],
];

function inferArchetype(title: string): TaskArchetype {
  for (const [archetype, pattern] of ARCHETYPE_PATTERNS) {
    if (pattern.test(title)) return archetype;
  }
  return "Task";
}

const ARCHETYPE_META: Record<
  TaskArchetype,
  { color: string; icon: React.ReactNode; cta: string; prompt: string }
> = {
  "Lead Review": {
    color:
      "bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-300",
    icon: <BookOpen className="size-3.5" />,
    cta: "Start Review",
    prompt: "Summarize this lead and tell me if it's worth pursuing.",
  },
  Outreach: {
    color: "bg-sky-100 text-sky-700 dark:bg-sky-950 dark:text-sky-300",
    icon: <MessageSquarePlus className="size-3.5" />,
    cta: "Draft Message",
    prompt: "Draft a concise, personalized outreach message for this contact.",
  },
  Application: {
    color: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
    icon: <PenLine className="size-3.5" />,
    cta: "Prep Now",
    prompt:
      "Help me prepare for this application. What should I highlight and research first?",
  },
  Research: {
    color:
      "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
    icon: <Search className="size-3.5" />,
    cta: "Start Research",
    prompt: "Research this topic and give me a concise briefing.",
  },
  "Follow-up": {
    color: "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300",
    icon: <Clock className="size-3.5" />,
    cta: "Draft Follow-up",
    prompt: "Draft a friendly follow-up message based on this task.",
  },
  Task: {
    color: "bg-muted text-muted-foreground",
    icon: <Zap className="size-3.5" />,
    cta: "Start Working",
    prompt: "Help me figure out what I need to do for this task.",
  },
};

// ─── Priority helpers ──────────────────────────────────────────────────────

const PRIORITY_LABELS = ["Low", "Normal", "High", "Urgent"] as const;
const PRIORITY_COLORS = [
  "bg-muted text-muted-foreground",
  "bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300",
  "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
  "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300",
] as const;

// ─── State helpers ─────────────────────────────────────────────────────────

type TaskState = "open" | "in_progress" | "snoozed" | "done" | "cancelled";

const STATE_LABELS: Record<TaskState, string> = {
  open: "Open",
  in_progress: "In Progress",
  snoozed: "Snoozed",
  done: "Done",
  cancelled: "Cancelled",
};

const STATE_COLORS: Record<TaskState, string> = {
  open: "bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300 border border-blue-200 dark:border-blue-800",
  in_progress:
    "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300 border border-amber-200 dark:border-amber-800",
  snoozed:
    "bg-muted text-muted-foreground border border-border",
  done: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800",
  cancelled:
    "bg-muted text-muted-foreground border border-border line-through opacity-60",
};

// ─── Component ────────────────────────────────────────────────────────────

interface TaskActionHubProps {
  record: WorkspaceRecord;
  onStatusChange: (state: TaskState) => void;
  onOpenConversation: (prompt?: string) => void;
  isPending?: boolean;
}

export function TaskActionHub({
  record,
  onStatusChange,
  onOpenConversation,
  isPending = false,
}: TaskActionHubProps) {
  const title = String((record as Record<string, unknown>).title ?? "");
  const rationale = String(
    (record as Record<string, unknown>).rationale ?? "",
  );
  const state = String(
    (record as Record<string, unknown>).state ?? "open",
  ) as TaskState;
  const priority = Number((record as Record<string, unknown>).priority ?? 1);
  const dueDate =
    (record as Record<string, unknown>).due_date ??
    (record as Record<string, unknown>).due_at;

  const archetype = inferArchetype(title);
  const meta = ARCHETYPE_META[archetype];
  const isDone = state === "done" || state === "cancelled";
  const isInProgress = state === "in_progress";

  const primaryState: TaskState = isDone
    ? "open"
    : isInProgress
      ? "done"
      : "in_progress";

  const primaryLabel = isDone
    ? "Reopen Task"
    : isInProgress
      ? "Mark Complete"
      : meta.cta;

  const primaryIcon = isDone ? (
    <Play className="size-4" />
  ) : isInProgress ? (
    <CheckCircle2 className="size-4" />
  ) : (
    <Play className="size-4" />
  );

  return (
    <div className="flex flex-col gap-6">
      {/* ── Archetype + Status badges ─────────────────────────── */}
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${meta.color}`}
        >
          {meta.icon}
          {archetype}
        </span>
        <span
          className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${STATE_COLORS[state]}`}
        >
          {STATE_LABELS[state]}
        </span>
        {priority > 0 && (
          <span
            className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${PRIORITY_COLORS[priority]}`}
          >
            {PRIORITY_LABELS[priority]}
          </span>
        )}
        {typeof dueDate === "string" && dueDate && (
          <span className="inline-flex items-center gap-1 rounded-full bg-muted px-2.5 py-1 text-xs text-muted-foreground">
            <Clock className="size-3" />
            {dateLabel(dueDate)}
          </span>
        )}
      </div>

      {/* ── Rationale / context ───────────────────────────────── */}
      {rationale ? (
        <div className="rounded-xl border border-border bg-muted/40 px-4 py-3">
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
            Why this matters
          </p>
          <p className="text-sm leading-relaxed text-foreground">{rationale}</p>
        </div>
      ) : (
        <div className="flex items-start gap-2 rounded-xl border border-dashed border-border px-4 py-3 text-sm text-muted-foreground">
          <AlertCircle className="mt-0.5 size-4 shrink-0" />
          <span>No rationale added yet. Edit the task to explain why it matters.</span>
        </div>
      )}

      {/* ── Primary CTA ───────────────────────────────────────── */}
      {!isDone && (
        <Button
          size="lg"
          className="group w-full justify-between gap-3 rounded-xl text-base font-semibold shadow-sm"
          disabled={isPending}
          onClick={() => onStatusChange(primaryState)}
        >
          <span className="flex items-center gap-2">
            {primaryIcon}
            {primaryLabel}
          </span>
          <ChevronRight className="size-4 transition-transform group-hover:translate-x-0.5" />
        </Button>
      )}
      {isDone && (
        <Button
          variant="outline"
          size="lg"
          className="w-full justify-between gap-3 rounded-xl"
          disabled={isPending}
          onClick={() => onStatusChange("open")}
        >
          <span className="flex items-center gap-2">
            <Play className="size-4" />
            Reopen Task
          </span>
          <ChevronRight className="size-4" />
        </Button>
      )}

      {/* ── Quick Actions ─────────────────────────────────────── */}
      <div>
        <p className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
          Quick actions
        </p>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5 rounded-full text-xs"
            onClick={() => onOpenConversation(meta.prompt)}
          >
            <Zap className="size-3.5 text-amber-500" />
            {archetype === "Outreach" || archetype === "Follow-up"
              ? "Draft with AI"
              : archetype === "Research"
                ? "Research with AI"
                : "Ask AI to help"}
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5 rounded-full text-xs"
            onClick={() =>
              onOpenConversation(
                `Add detailed notes for: ${title}. What should I capture here?`,
              )
            }
          >
            <StickyNote className="size-3.5 text-blue-500" />
            Add notes
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5 rounded-full text-xs"
            onClick={() => onOpenConversation()}
          >
            <MessageSquarePlus className="size-3.5 text-violet-500" />
            Open conversation
          </Button>
        </div>
      </div>

      {/* ── Status switcher ───────────────────────────────────── */}
      {!isDone && (
        <div>
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
            Change status
          </p>
          <div className="flex flex-wrap gap-1.5">
            {(["open", "in_progress", "snoozed"] as TaskState[]).map((s) => (
              <button
                key={s}
                disabled={isPending || state === s}
                onClick={() => onStatusChange(s)}
                className={`rounded-full px-3 py-1 text-xs font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed ${
                  state === s
                    ? `${STATE_COLORS[s]} opacity-100`
                    : "bg-muted text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                }`}
              >
                {STATE_LABELS[s]}
              </button>
            ))}
            <button
              disabled={isPending}
              onClick={() => onStatusChange("done")}
              className="rounded-full bg-emerald-100 px-3 py-1 text-xs font-medium text-emerald-700 transition-all hover:bg-emerald-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed dark:bg-emerald-950 dark:text-emerald-300 dark:hover:bg-emerald-900"
            >
              ✓ Done
            </button>
            <button
              disabled={isPending}
              onClick={() => onStatusChange("cancelled")}
              className="rounded-full bg-muted px-3 py-1 text-xs font-medium text-muted-foreground transition-all hover:bg-destructive/10 hover:text-destructive focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* ── Any remaining field details ───────────────────────── */}
      {(() => {
        const extras: [string, unknown][] = Object.entries(
          record as Record<string, unknown>,
        ).filter(
          ([k, v]) =>
            ![
              "id",
              "owner_id",
              "opportunity_id",
              "title",
              "state",
              "priority",
              "rationale",
              "due_date",
              "due_at",
              "row_version",
              "created_at",
              "updated_at",
              "completed_at",
            ].includes(k) &&
            v !== null &&
            v !== "" &&
            typeof v !== "object",
        );
        if (!extras.length) return null;
        return (
          <div className="border-t border-border pt-4">
            <p className="mb-3 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              Details
            </p>
            <dl className="flex flex-col gap-3">
              {extras.map(([k, v]) => (
                <div
                  key={k}
                  className="grid grid-cols-[120px_1fr] items-start gap-4"
                >
                  <dt className="text-xs text-muted-foreground">
                    {label(k.replace(/_id$/, ""))}
                  </dt>
                  <dd className="min-w-0 break-words text-xs leading-6">
                    {String(v)}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        );
      })()}
    </div>
  );
}
