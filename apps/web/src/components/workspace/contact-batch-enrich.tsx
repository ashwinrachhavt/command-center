"use client";

import { useRef, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { useQueryClient } from "@tanstack/react-query";
import { SearchCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { api, type Resources, type Schema } from "@/lib/api";
import { outreachActive } from "./contact-outreach";
import { useWorkspaceContext } from "./context";
import { Spinner } from "./primitives";

type Contact = Resources["contacts"];
type Result = {
  state: "starting" | "queued" | "error";
  taskId?: string;
  error?: string;
};

export function ContactBatchEnrich({
  contacts,
  instructions,
}: {
  contacts: Contact[];
  instructions: string;
}) {
  const { userId } = useAuth();
  const client = useQueryClient();
  const context = useWorkspaceContext();
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [results, setResults] = useState<Record<string, Result>>({});
  const [running, setRunning] = useState(false);
  const runningRef = useRef(false);
  const intents = useRef<Record<string, { body: string; key: string }>>({});
  const update = (id: string, result: Result) =>
    setResults((previous) => ({ ...previous, [id]: result }));

  const start = async () => {
    if (!userId || runningRef.current) return;
    runningRef.current = true;
    setRunning(true);
    // Two requests at a time enqueue independently audited tasks; no hidden bulk run.
    const pending = contacts.filter(
      (person) =>
        selected.includes(person.id) && results[person.id]?.state !== "queued",
    );
    const body = {
      research_requested: true,
      channel: "linkedin" as const,
      instructions,
    };
    const serialized = JSON.stringify(body);
    const worker = async () => {
      for (;;) {
        const person = pending.shift();
        if (!person) return;
        update(person.id, { state: "starting" });
        const storageKey = `cc:batch-enrich:${userId}:${person.id}`;
        let retained = intents.current[person.id];
        try {
          retained ??= JSON.parse(sessionStorage.getItem(storageKey) ?? "null");
        } catch {
          /* memory fallback */
        }
        const intent =
          retained?.body === serialized
            ? retained
            : { body: serialized, key: crypto.randomUUID() };
        intents.current[person.id] = intent;
        try {
          sessionStorage.setItem(storageKey, JSON.stringify(intent));
        } catch {
          /* optional journal */
        }
        try {
          const work = await api<Schema["WorkRead"]>(
            `record-work/contacts/${person.id}`,
            { method: "POST", body, key: intent.key },
          );
          update(person.id, { state: "queued", taskId: work.task_id });
          delete intents.current[person.id];
          try {
            sessionStorage.removeItem(storageKey);
          } catch {
            /* optional journal */
          }
        } catch (error) {
          update(person.id, {
            state: "error",
            error:
              error instanceof Error
                ? error.message
                : "Could not start. Try again.",
          });
        }
      }
    };
    try {
      await Promise.all([worker(), worker()]);
    } finally {
      runningRef.current = false;
      setRunning(false);
      void client.invalidateQueries({ queryKey: ["contacts"] });
      void client.invalidateQueries({ queryKey: ["tasks"] });
    }
  };

  if (!userId) return null;
  const pendingCount = selected.filter(
    (id) => results[id]?.state !== "queued",
  ).length;
  return (
    <>
      <Button
        size="sm"
        variant="outline"
        disabled={!contacts.length}
        onClick={() => setOpen(true)}
      >
        <SearchCheck />
        Batch enrich
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[85dvh] overflow-y-auto sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>Enrich selected contacts</DialogTitle>
            <DialogDescription>
              Choose up to 10 people from this page for deeper public research
              and a connection note. Each gets a tracked task. For a quick note,
              use Draft connection note on their row.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-1">
            {contacts.map((person) => {
              const result = results[person.id];
              const checked = selected.includes(person.id);
              const busy = outreachActive(person.outreach?.state);
              return (
                <div key={person.id} className="rounded-lg border p-3">
                  <label className="flex min-h-11 items-center gap-3 text-sm">
                    <Checkbox
                      className="min-h-4!"
                      aria-label={`Enrich ${person.name}`}
                      checked={checked}
                      disabled={
                        running ||
                        result?.state === "queued" ||
                        busy ||
                        (!checked && selected.length >= 10)
                      }
                      onCheckedChange={(value) =>
                        setSelected((ids) =>
                          value
                            ? [...ids, person.id]
                            : ids.filter((id) => id !== person.id),
                        )
                      }
                    />
                    <span className="min-w-0 flex-1 truncate">
                      {person.name}
                    </span>
                    {(result || busy) && (
                      <span
                        role="status"
                        className="flex items-center gap-1.5 text-xs text-muted-foreground"
                      >
                        {result?.state === "starting" && <Spinner />}
                        {result?.state === "starting"
                          ? "Starting…"
                          : result?.state === "error"
                            ? "Could not queue"
                            : busy
                              ? "In progress"
                              : "Queued"}
                      </span>
                    )}
                  </label>
                  {result?.error && (
                    <p role="alert" className="mt-2 text-xs text-destructive">
                      {result.error}
                    </p>
                  )}
                  {result?.taskId && (
                    <Button
                      size="sm"
                      variant="link"
                      className="mt-1 h-auto p-0"
                      onClick={() => {
                        setOpen(false);
                        context?.open("tasks", result.taskId!, {
                          tab: "conversation",
                        });
                      }}
                    >
                      Open task
                    </Button>
                  )}
                </div>
              );
            })}
          </div>
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs text-muted-foreground">
              {selected.length}/10 selected · Uses your outreach brief
            </p>
            <Button
              disabled={running || !pendingCount}
              onClick={() => void start()}
            >
              {running ? (
                <>
                  <Spinner />
                  Queueing…
                </>
              ) : Object.values(results).some(
                  (item) => item.state === "error",
                ) ? (
                `Retry ${pendingCount} remaining`
              ) : (
                `Enrich ${pendingCount || "selected"}`
              )}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
