"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookmarkPlus, Brain, Pencil } from "lucide-react";
import { toast } from "sonner";
import {
  Checkpoint,
  CheckpointIcon,
  CheckpointTrigger,
} from "@/components/ai-elements/checkpoint";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  api,
  dateLabel,
  type AgentSession,
  type Page,
  type Schema,
} from "@/lib/api";
import { RetainedRequestIntent } from "@/lib/retained-intent";
import { AgentResponse } from "./agent-response";
import { MemoryPage } from "./memory";
import { ErrorState } from "./primitives";

export type SavedCheckpoint = Schema["CheckpointRead"];
export const checkpointKey = (sessionId?: string) =>
  ["session-checkpoints", sessionId] as const;

export function useSessionCheckpoints(sessionId?: string, active = false) {
  const observed = useRef<{ sessionId: string; ids: Set<string> } | null>(null);
  const query = useQuery({
    queryKey: checkpointKey(sessionId),
    enabled: !!sessionId,
    queryFn: async ({ signal }) => {
      const items: SavedCheckpoint[] = [];
      let page: Page<SavedCheckpoint>;
      do {
        page = await api<Page<SavedCheckpoint>>(
          `agent-sessions/${sessionId}/checkpoints?limit=100&offset=${items.length}`,
          { signal },
        );
        items.push(...page.items);
      } while (page.items.length && items.length < page.total);
      return items;
    },
    refetchInterval: active ? 5000 : 30000,
    refetchOnWindowFocus: "always",
    refetchOnReconnect: "always",
  });
  useEffect(() => {
    if (!sessionId || !query.data) return;
    if (
      observed.current?.sessionId === sessionId &&
      query.data.some(
        (checkpoint) =>
          checkpoint.kind === "compacted" &&
          !observed.current?.ids.has(checkpoint.id),
      )
    )
      toast.info(
        "Conversation context summarized. Your full transcript is preserved.",
      );
    observed.current = {
      sessionId,
      ids: new Set(query.data.map((checkpoint) => checkpoint.id)),
    };
  }, [sessionId, query.data]);
  return query;
}

export function ConversationCheckpoint({
  checkpoint,
}: {
  checkpoint: SavedCheckpoint;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Checkpoint aria-label={checkpoint.title} className="min-w-0">
        <CheckpointIcon />
        <CheckpointTrigger
          className="h-auto min-w-0 shrink-0 max-w-[85%] whitespace-normal py-1 text-start text-xs"
          onClick={() => setOpen(true)}
        >
          {checkpoint.title}
        </CheckpointTrigger>
      </Checkpoint>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[85dvh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{checkpoint.title}</DialogTitle>
            <DialogDescription>
              After message {checkpoint.sequence} ·{" "}
              {dateLabel(checkpoint.created_at)}. The full conversation is
              preserved.
            </DialogDescription>
          </DialogHeader>
          {checkpoint.summary ? (
            <AgentResponse>{checkpoint.summary}</AgentResponse>
          ) : (
            <p className="text-sm text-muted-foreground">
              {checkpoint.kind === "continued"
                ? "A new run continues this conversation with its saved context. Previous work remains in the transcript."
                : "A saved point in this conversation. Continue from the latest message using the composer."}
            </p>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}

export function SessionContext({
  session,
  checkpoints,
}: {
  session: AgentSession;
  checkpoints: SavedCheckpoint[];
}) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState(session.title);
  const [checkpointTitle, setCheckpointTitle] = useState("");
  const [intent] = useState(() => new RetainedRequestIntent());
  const client = useQueryClient();
  const save = useMutation({
    mutationFn: async (action: "rename" | "checkpoint") => {
      const target = `agent-sessions/${session.id}${action === "checkpoint" ? "/checkpoints" : ""}`;
      const method = action === "rename" ? "PATCH" : "POST";
      const body =
        action === "rename"
          ? { title: title.trim(), expected_version: session.row_version }
          : {
              title: checkpointTitle.trim() || "Saved checkpoint",
              expected_sequence: session.last_sequence,
            };
      const request = intent.forRequest(method, target, body);
      await api(target, { method, body, key: request.key });
      intent.confirmRequest(method, target, body);
    },
    onSuccess: (_, action) => {
      void client.invalidateQueries({ queryKey: checkpointKey(session.id) });
      void client.invalidateQueries({
        queryKey: ["agent-session"],
      });
      void client.invalidateQueries({ queryKey: ["agent-sessions"] });
      setCheckpointTitle("");
      toast.success(
        action === "rename" ? "Conversation renamed" : "Checkpoint saved",
      );
    },
    onError: () => {
      void client.invalidateQueries({
        queryKey: ["agent-session"],
      });
    },
  });
  const latestSummary = checkpoints.findLast(
    (item) => item.kind === "compacted",
  );
  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        onClick={() => {
          setTitle(session.title);
          setOpen(true);
        }}
      >
        <Brain /> Context & memory
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[85dvh] overflow-y-auto sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>Conversation context</DialogTitle>
            <DialogDescription>
              Saved context and reviewed memory for this thread. Your original
              messages remain available.
            </DialogDescription>
          </DialogHeader>
          <Tabs defaultValue="context">
            <TabsList>
              <TabsTrigger value="context">Context</TabsTrigger>
              <TabsTrigger value="memory">Memory</TabsTrigger>
            </TabsList>
            <TabsContent value="context" className="space-y-5 pt-4">
              <form
                className="flex gap-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  save.mutate("rename");
                }}
              >
                <Input
                  aria-label="Conversation name"
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  maxLength={300}
                  required
                />
                <Button
                  type="submit"
                  variant="outline"
                  disabled={save.isPending || !title.trim()}
                >
                  <Pencil /> Rename
                </Button>
              </form>
              <p className="text-sm text-muted-foreground">
                {session.last_sequence} saved messages.{" "}
                {latestSummary
                  ? `Earlier context was summarized through message ${latestSummary.sequence}; later messages continue alongside that summary when compatible with the selected agent.`
                  : "The saved transcript supplies context when this thread continues. Long conversations are summarized automatically."}
              </p>
              {latestSummary ? (
                <details>
                  <summary className="cursor-pointer text-sm font-medium">
                    Latest context summary
                  </summary>
                  <div className="pt-3">
                    <AgentResponse>{latestSummary.summary ?? ""}</AgentResponse>
                  </div>
                </details>
              ) : null}
              <form
                className="flex gap-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  save.mutate("checkpoint");
                }}
              >
                <Input
                  aria-label="Checkpoint name"
                  placeholder="Checkpoint name (optional)"
                  value={checkpointTitle}
                  onChange={(event) => setCheckpointTitle(event.target.value)}
                  maxLength={200}
                />
                <Button
                  type="submit"
                  variant="outline"
                  disabled={save.isPending || !session.last_sequence}
                >
                  <BookmarkPlus /> Save checkpoint
                </Button>
              </form>
              {save.error ? <ErrorState error={save.error} /> : null}
              <div className="space-y-2">
                {checkpoints.map((checkpoint) => (
                  <ConversationCheckpoint
                    key={checkpoint.id}
                    checkpoint={checkpoint}
                  />
                ))}
              </div>
            </TabsContent>
            <TabsContent value="memory" className="pt-4">
              <MemoryPage key={session.id} sessionId={session.id} />
              <Link
                href="/memory"
                className="mt-4 inline-block text-sm underline underline-offset-2"
              >
                Manage shared workspace memory
              </Link>
            </TabsContent>
          </Tabs>
        </DialogContent>
      </Dialog>
    </>
  );
}
