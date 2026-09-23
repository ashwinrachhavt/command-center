"use client";

import {
  CheckCircle2,
  Clock,
  MessageSquare,
  Play,
  RotateCcw,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { type WorkspaceRecord, dateLabel, label } from "@/lib/api";

type TaskState = "open" | "in_progress" | "snoozed" | "done" | "cancelled";

const STATE_LABELS: Record<TaskState, string> = {
  open: "Open",
  in_progress: "In progress",
  snoozed: "Snoozed",
  done: "Done",
  cancelled: "Cancelled",
};
const PRIORITY_LABELS = ["Low", "Normal", "High", "Urgent"] as const;

interface TaskActionHubProps {
  record: WorkspaceRecord;
  onStatusChange: (state: TaskState) => void;
  onOpenConversation: () => void;
  isPending?: boolean;
}

export function TaskActionHub({
  record,
  onStatusChange,
  onOpenConversation,
  isPending = false,
}: TaskActionHubProps) {
  const task = record as Record<string, unknown>;
  const rawState = typeof task.state === "string" ? task.state : "";
  const state = Object.hasOwn(STATE_LABELS, rawState)
    ? (rawState as TaskState)
    : undefined;
  const rationale =
    typeof task.rationale === "string" ? task.rationale.trim() : "";
  const priority =
    typeof task.priority === "number" && Number.isInteger(task.priority)
      ? PRIORITY_LABELS[task.priority]
      : undefined;
  const due = task.due_date ?? task.due_at;
  const dueDate =
    typeof due === "string" && due && !Number.isNaN(Date.parse(due))
      ? due
      : undefined;
  const finished = state === "done" || state === "cancelled";

  return (
    <div className="flex flex-col gap-5" aria-busy={isPending}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={state === "in_progress" ? "default" : "secondary"}>
          {state
            ? STATE_LABELS[state]
            : rawState
              ? label(rawState)
              : "Unknown status"}
        </Badge>
        <Badge variant={priority === "Urgent" ? "destructive" : "outline"}>
          {priority ? `${priority} priority` : "Priority not set"}
        </Badge>
        <Badge variant="outline">
          <Clock data-icon="inline-start" aria-hidden="true" />
          {dueDate ? (
            <time dateTime={dueDate}>Due {dateLabel(dueDate)}</time>
          ) : (
            "No due date"
          )}
        </Badge>
      </div>

      <div className="flex flex-col gap-2">
        <h3 className="text-sm font-medium">Why this matters</h3>
        <p className="whitespace-pre-wrap break-words text-sm leading-6 text-muted-foreground">
          {rationale || "No rationale added yet."}
        </p>
      </div>

      {state && (
        <div
          className="flex flex-wrap gap-2"
          role="group"
          aria-label="Task status actions"
        >
          {finished ? (
            <Button
              type="button"
              variant="outline"
              disabled={isPending}
              onClick={() => onStatusChange("open")}
            >
              <RotateCcw data-icon="inline-start" aria-hidden="true" />
              Reopen task
            </Button>
          ) : (
            <>
              {state !== "in_progress" && (
                <Button
                  type="button"
                  disabled={isPending}
                  onClick={() => onStatusChange("in_progress")}
                >
                  <Play data-icon="inline-start" aria-hidden="true" />
                  {state === "snoozed" ? "Resume task" : "Start task"}
                </Button>
              )}
              <Button
                type="button"
                variant={state === "in_progress" ? "default" : "outline"}
                disabled={isPending}
                onClick={() => onStatusChange("done")}
              >
                <CheckCircle2 data-icon="inline-start" aria-hidden="true" />
                Complete task
              </Button>
              {state !== "snoozed" && (
                <Button
                  type="button"
                  variant="outline"
                  disabled={isPending}
                  onClick={() => onStatusChange("snoozed")}
                >
                  <Clock data-icon="inline-start" aria-hidden="true" />
                  Snooze
                </Button>
              )}
              <Button
                type="button"
                variant="ghost"
                disabled={isPending}
                onClick={() => onStatusChange("cancelled")}
              >
                Cancel task
              </Button>
            </>
          )}
        </div>
      )}

      <div>
        <Button
          type="button"
          variant="outline"
          disabled={isPending}
          onClick={() => onOpenConversation()}
        >
          <MessageSquare data-icon="inline-start" aria-hidden="true" />
          Open conversation
        </Button>
      </div>
    </div>
  );
}
