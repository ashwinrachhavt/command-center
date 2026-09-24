"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type RunEventEnvelope = {
  sequence: number;
  run_id: string;
  type: string;
  role: string;
  data: Record<string, unknown>;
  created_at: string;
};

export type StreamedMessage = { id: string; content: string };
export type StreamedTool = {
  id: string;
  name: string;
  input?: unknown;
  output?: unknown;
  errorText?: string;
  state: "input-available" | "output-available" | "output-error";
};
export type StreamConnection =
  "idle" | "connecting" | "live" | "disconnected" | "complete";

const terminalStates = new Set(["completed", "failed", "cancelled"]);
const retryableStatuses = new Set([408, 429, 500, 502, 503, 504]);
const maxEventChars = 256_000;

class StreamError extends Error {
  constructor(
    message: string,
    readonly retryable: boolean,
  ) {
    super(message);
  }
}

function record(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function parseBlock(block: string) {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  if (event !== "agent_event" || !data.length) return undefined;
  try {
    return JSON.parse(data.join("\n")) as unknown;
  } catch {
    return undefined;
  }
}

function validEnvelope(
  value: unknown,
  runId: string,
): RunEventEnvelope | undefined {
  const candidate = record(value);
  const data = record(candidate?.data);
  if (
    !candidate ||
    !data ||
    !Number.isSafeInteger(candidate.sequence) ||
    (candidate.sequence as number) <= 0 ||
    candidate.run_id !== runId ||
    typeof candidate.type !== "string" ||
    typeof candidate.role !== "string" ||
    typeof candidate.created_at !== "string"
  )
    return undefined;
  return candidate as RunEventEnvelope;
}

export function useRunEvents(runId: string, enabled: boolean) {
  const [messages, setMessages] = useState<StreamedMessage[]>([]);
  const [tools, setTools] = useState<StreamedTool[]>([]);
  const [usage, setUsage] = useState<{
    input: number;
    cachedInput: number;
    output: number;
    total: number;
  }>();
  const [runStatus, setRunStatus] = useState<{
    state: string;
    errorCode?: string;
  }>();
  const [connection, setConnection] = useState<StreamConnection>("idle");
  const [connectionError, setConnectionError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [scopeRunId, setScopeRunId] = useState(runId);
  const lastSequence = useRef(0);
  const terminalStatus = useRef(false);
  const pendingText = useRef(new Map<string, string>());
  const frame = useRef<number | undefined>(undefined);
  const [resumeSequence, setResumeSequence] = useState(0);
  const automaticAttempts = useRef(0);
  const canReconnect = useRef(true);
  const retryNotBefore = useRef(0);

  const flushText = useCallback(() => {
    if (frame.current !== undefined) cancelAnimationFrame(frame.current);
    frame.current = undefined;
    const pending = pendingText.current;
    if (!pending.size) return;
    pendingText.current = new Map();
    setMessages((current) => {
      const next = [...current];
      for (const [id, delta] of pending) {
        const index = next.findIndex((message) => message.id === id);
        if (index === -1) next.push({ id, content: delta });
        else
          next[index] = {
            ...next[index],
            content: next[index].content + delta,
          };
      }
      return next;
    });
  }, []);

  const queueText = useCallback(
    (id: string, delta: string) => {
      pendingText.current.set(id, (pendingText.current.get(id) ?? "") + delta);
      if (frame.current === undefined)
        frame.current = requestAnimationFrame(flushText);
    },
    [flushText],
  );

  // Reset before committing a different run; never paint the previous run's text.
  if (scopeRunId !== runId) {
    setScopeRunId(runId);
    setMessages([]);
    setTools([]);
    setUsage(undefined);
    setRunStatus(undefined);
    setConnection("idle");
    setConnectionError("");
    setResumeSequence(0);
  }

  useEffect(() => {
    lastSequence.current = 0;
    terminalStatus.current = false;
    automaticAttempts.current = 0;
    canReconnect.current = true;
    retryNotBefore.current = 0;
    pendingText.current.clear();
    if (frame.current !== undefined) cancelAnimationFrame(frame.current);
    frame.current = undefined;
  }, [runId]);

  useEffect(() => {
    if (!enabled || terminalStatus.current) return;
    const controller = new AbortController();
    let current = true;
    let terminal = false;

    const updateTool = (id: string, update: Partial<StreamedTool>) => {
      setTools((currentTools) => {
        const index = currentTools.findIndex((tool) => tool.id === id);
        const existing = index === -1 ? undefined : currentTools[index];
        const nextTool: StreamedTool = {
          id,
          name: update.name ?? existing?.name ?? "tool",
          state: update.state ?? existing?.state ?? "input-available",
          input: update.input ?? existing?.input,
          output: update.output ?? existing?.output,
          errorText: update.errorText ?? existing?.errorText,
        };
        if (index === -1) return [...currentTools, nextTool];
        const next = [...currentTools];
        next[index] = nextTool;
        return next;
      });
    };

    const apply = (event: RunEventEnvelope) => {
      if (event.sequence <= lastSequence.current) return;
      lastSequence.current = event.sequence;
      automaticAttempts.current = 0;
      const data = event.data;
      if (event.type === "text-delta") {
        const id = data.message_id;
        const delta = data.delta;
        if (typeof id === "string" && typeof delta === "string")
          queueText(id, delta);
      } else if (event.type === "tool-input-available") {
        if (
          typeof data.tool_call_id === "string" &&
          typeof data.tool_name === "string"
        )
          updateTool(data.tool_call_id, {
            name: data.tool_name,
            input: data.input,
            state: "input-available",
          });
      } else if (event.type === "tool-output-available") {
        if (typeof data.tool_call_id === "string")
          updateTool(data.tool_call_id, {
            output: data.output,
            state: "output-available",
          });
      } else if (event.type === "tool-output-error") {
        if (
          typeof data.tool_call_id === "string" &&
          typeof data.error_text === "string"
        )
          updateTool(data.tool_call_id, {
            errorText: data.error_text,
            state: "output-error",
          });
      } else if (event.type === "usage") {
        if (
          typeof data.input_tokens === "number" &&
          typeof data.output_tokens === "number" &&
          typeof data.total_tokens === "number"
        )
          setUsage({
            input: data.input_tokens,
            cachedInput:
              typeof data.cached_input_tokens === "number"
                ? data.cached_input_tokens
                : 0,
            output: data.output_tokens,
            total: data.total_tokens,
          });
      } else if (
        event.type === "run-status" &&
        typeof data.state === "string"
      ) {
        terminal = terminalStates.has(data.state);
        terminalStatus.current = terminal;
        setRunStatus({
          state: data.state,
          errorCode:
            typeof data.error_code === "string" ? data.error_code : undefined,
        });
        if (terminal) {
          flushText();
          setConnection("complete");
        }
      }
    };

    const connect = async () => {
      setConnection("connecting");
      setConnectionError("");
      canReconnect.current = true;
      retryNotBefore.current = 0;
      try {
        const response = await fetch(
          `/api/backend/agent-runs/${encodeURIComponent(runId)}/events?after_sequence=${lastSequence.current}`,
          {
            cache: "no-store",
            headers: { Accept: "text/event-stream" },
            signal: controller.signal,
          },
        );
        if (!current || controller.signal.aborted) return;
        if (!response.ok) {
          const after = response.headers.get("Retry-After");
          if (after) {
            const seconds = Number(after);
            const deadline = Number.isFinite(seconds)
              ? Date.now() + Math.max(0, seconds) * 1000
              : Date.parse(after);
            if (Number.isFinite(deadline)) retryNotBefore.current = deadline;
          }
          throw new StreamError(
            response.status === 401
              ? "Sign in again to reconnect live activity."
              : response.status === 403 || response.status === 404
                ? "Live activity is unavailable for this run or account."
                : `Event stream returned ${response.status}.`,
            retryableStatuses.has(response.status),
          );
        }
        if (!response.body)
          throw new StreamError(
            "Event stream returned an empty response.",
            false,
          );
        if (
          !response.headers.get("content-type")?.includes("text/event-stream")
        )
          throw new StreamError(
            "Event stream returned an unexpected response.",
            false,
          );
        setConnection("live");
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        try {
          while (current && !terminal) {
            const { done, value } = await reader.read();
            if (!current || controller.signal.aborted) return;
            buffer += decoder.decode(value, { stream: !done });
            let separator = buffer.search(/\r?\n\r?\n/);
            while (separator >= 0 && !terminal) {
              const match = buffer.slice(separator).match(/^\r?\n\r?\n/);
              const length = match?.[0].length ?? 2;
              const envelope = validEnvelope(
                parseBlock(buffer.slice(0, separator)),
                runId,
              );
              buffer = buffer.slice(separator + length);
              if (envelope) apply(envelope);
              separator = buffer.search(/\r?\n\r?\n/);
            }
            if (buffer.length > maxEventChars)
              throw new StreamError(
                "Live activity exceeded the event size limit.",
                false,
              );
            if (done) break;
          }
        } finally {
          await reader.cancel().catch(() => {});
          reader.releaseLock();
        }
        flushText();
        if (current && !terminal) {
          setResumeSequence(lastSequence.current);
          setConnection("disconnected");
          setConnectionError("Live activity disconnected.");
        }
      } catch (error) {
        if (!current || controller.signal.aborted) return;
        canReconnect.current =
          !(error instanceof StreamError) || error.retryable;
        flushText();
        setResumeSequence(lastSequence.current);
        setConnection("disconnected");
        setConnectionError(
          error instanceof Error
            ? error.message
            : "Live activity disconnected.",
        );
      }
    };

    void connect();
    return () => {
      current = false;
      controller.abort();
    };
  }, [attempt, enabled, flushText, queueText, runId]);

  useEffect(() => {
    if (
      !enabled ||
      connection !== "disconnected" ||
      terminalStatus.current ||
      !canReconnect.current
    )
      return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const schedule = () => {
      clearTimeout(timer);
      if (
        document.visibilityState === "hidden" ||
        !navigator.onLine ||
        automaticAttempts.current >= 3
      )
        return;
      timer = setTimeout(
        () => {
          automaticAttempts.current += 1;
          setAttempt((value) => value + 1);
        },
        Math.min(
          2_147_483_647,
          Math.max(
            1000 * 2 ** automaticAttempts.current * (0.5 + Math.random() * 0.5),
            retryNotBefore.current - Date.now(),
          ),
        ),
      );
    };
    schedule();
    document.addEventListener("visibilitychange", schedule);
    window.addEventListener("online", schedule);
    window.addEventListener("offline", schedule);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", schedule);
      window.removeEventListener("online", schedule);
      window.removeEventListener("offline", schedule);
    };
  }, [attempt, connection, enabled, runId]);

  useEffect(
    () => () => {
      if (frame.current !== undefined) cancelAnimationFrame(frame.current);
    },
    [],
  );

  return {
    messages,
    tools,
    usage,
    runStatus,
    connection,
    connectionError,
    lastSequence: resumeSequence,
    retry: () => {
      automaticAttempts.current = 0;
      setAttempt((value) => value + 1);
    },
  };
}
