"use client";

import type { AgentMessage } from "@/lib/api";
import { Button } from "@/components/ui/button";

export function AnswerReuseNotice({
  message,
  onFresh,
  disabled,
}: {
  message: AgentMessage;
  onFresh?: () => void;
  disabled?: boolean;
}) {
  const cache = message.answer_cache;
  if (!cache) return null;
  return (
    <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
      <span>
        Reused saved answer from{" "}
        <time dateTime={cache.source_completed_at}>
          {new Date(cache.source_completed_at).toLocaleString()}
        </time>
        .
      </span>
      {onFresh ? (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={disabled}
          onClick={onFresh}
        >
          Get a fresh answer
        </Button>
      ) : null}
    </div>
  );
}
