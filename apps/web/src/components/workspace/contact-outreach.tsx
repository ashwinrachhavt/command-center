"use client";

import { AnimatedIcon } from "@/components/ui/animated-icon";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, Copy, Mail, Pencil, SearchCheck } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  api,
  dateLabel,
  runFailureMessage,
  type Resources,
  type Schema,
} from "@/lib/api";
import { safeLinkedIn } from "@/lib/linkedin";
import type { WriterProps } from "./contact-follow-ups";
import { deferView } from "./deferred-view";
import { RecordWorkButton } from "./record-agent-work";
import { Spinner } from "./primitives";
import { useWorkspaceContext } from "./context";

const FollowUpWriter = deferView<WriterProps>(
  () =>
    import("./contact-follow-ups").then((module) => ({
      default: module.FollowUpWriter,
    })),
  "connection note editor",
);

export const defaultOutreachBrief =
  "Connect with this person and explore work opportunities at their company. Be friendly, direct and specific. Use my reviewed background where relevant. Write a LinkedIn connection note within 200 characters.";
export const outreachActive = (state?: string) =>
  !!state && ["queued", "running", "waiting_for_user"].includes(state);

export function ContactOutreach({
  contact,
  instructions,
}: {
  contact: Resources["contacts"];
  instructions: string;
}) {
  const client = useQueryClient();
  const context = useWorkspaceContext();
  const [researchOpen, setResearchOpen] = useState(false);
  const [editing, setEditing] = useState<Schema["FollowUpRead"]>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const outreach = contact.outreach;
  const research = outreach?.research;
  const busy = outreachActive(outreach?.state);
  const linkedin = safeLinkedIn(contact.linkedin_url);
  const message = outreach?.message ?? "";
  const edit = async () => {
    if (!outreach?.artifact_id) return;
    setLoading(true);
    setError("");
    try {
      setEditing(
        await api<Schema["FollowUpRead"]>(`follow-ups/${outreach.artifact_id}`),
      );
    } catch (error) {
      setError(
        error instanceof Error
          ? error.message
          : "Could not load the note. Try again.",
      );
    } finally {
      setLoading(false);
    }
  };
  return (
    <div
      className="w-full md:w-80 space-y-2 py-3 whitespace-normal"
      aria-label={`Outreach for ${contact.name}`}
    >
      <Button
        size="sm"
        variant="outline"
        onClick={() =>
          context?.open("contacts", contact.id, { tab: "follow-ups" })
        }
      >
        <Mail />
        Email & follow-ups
      </Button>
      {message && (
        <p className="text-xs leading-5 text-foreground">{message}</p>
      )}
      {message && (
        <div className="flex flex-wrap items-center gap-1">
          <Button
            size="sm"
            variant="secondary"
            disabled={message.length > 200}
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(message);
                toast.success("Connection note copied");
              } catch {
                setError(
                  "Clipboard unavailable. Select and copy the note above.",
                );
              }
            }}
          >
            <Copy />
            Copy note
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={loading}
            onClick={() => void edit()}
            aria-label={`Edit note for ${contact.name}`}
          >
            <AnimatedIcon state={loading}>
              {loading ? <Spinner /> : <Pencil />}
            </AnimatedIcon>
            Edit
          </Button>
          {linkedin && (
            <Button asChild size="sm" variant="ghost">
              <a href={linkedin} target="_blank" rel="noopener noreferrer">
                LinkedIn
                <ArrowUpRight />
              </a>
            </Button>
          )}
          <span
            className={`ms-auto text-[10px] tabular-nums ${message.length > 200 ? "text-destructive" : "text-muted-foreground"}`}
          >
            {message.length}/200
          </span>
        </div>
      )}
      {research && (
        <button
          className="flex items-center gap-1.5 text-start text-[11px] text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          onClick={() => setResearchOpen(true)}
        >
          <SearchCheck className="size-3.5 shrink-0" />
          {research.identity === "uncertain"
            ? "Identity needs review"
            : research.company
              ? `${research.role ? `${research.role} · ` : ""}${research.company}`
              : "Current company unconfirmed"}
          <span className="underline underline-offset-2">Sources</span>
        </button>
      )}
      {outreach && busy && (
        <div className="flex items-center gap-2 text-[11px]" role="status">
          {outreach.state !== "waiting_for_user" && <Spinner />}
          <span>
            {outreach.state === "queued"
              ? "Queued"
              : outreach.state === "waiting_for_user"
                ? "Needs your input"
                : "Preparing your note"}
          </span>
          <button
            className="underline underline-offset-2"
            onClick={() =>
              context?.open("tasks", outreach.task_id, { tab: "conversation" })
            }
          >
            Open work
          </button>
        </div>
      )}
      {outreach && !busy && !message && (
        <p className="text-[11px] text-muted-foreground">
          {outreach.state === "failed"
            ? runFailureMessage(outreach.error_code)
            : outreach.state === "cancelled"
              ? "Work cancelled"
              : "No saved note yet."}
        </p>
      )}
      {message && outreach?.state === "failed" && (
        <p className="text-[11px] text-muted-foreground">
          Last attempt failed. Your saved note is still available.
        </p>
      )}
      {!busy && (
        <RecordWorkButton
          resource="contacts"
          id={contact.id}
          compact
          request={{
            connection_note: true,
            channel: "linkedin",
            instructions,
          }}
        />
      )}
      {!busy && (
        <RecordWorkButton
          resource="contacts"
          id={contact.id}
          compact
          request={{
            research_requested: true,
            channel: "linkedin",
            instructions,
          }}
        />
      )}
      {error && (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      )}
      {researchOpen && research && (
        <Dialog open onOpenChange={setResearchOpen}>
          <DialogContent className="max-h-[85dvh] overflow-y-auto sm:max-w-xl">
            <DialogHeader>
              <DialogTitle>Research for {contact.name}</DialogTitle>
              <DialogDescription>
                Source-backed findings for your note. Saved contact fields stay
                as you entered them.
              </DialogDescription>
            </DialogHeader>
            <p className="text-sm leading-6">{research.summary}</p>
            {research.caveats && (
              <p className="rounded-lg bg-muted p-3 text-sm leading-6">
                {research.caveats}
              </p>
            )}
            {(["identity_evidence", "employment_evidence"] as const).map(
              (kind) =>
                research[kind]?.length ? (
                  <div key={kind} className="space-y-2">
                    <h4 className="text-xs font-medium">
                      {kind === "identity_evidence"
                        ? "Person match"
                        : "Current work"}
                    </h4>
                    {research[kind].map((citation, index) => {
                      const source = outreach?.sources.find(
                        (source) =>
                          source.version_id === citation.source_version_id,
                      );
                      return (
                        <blockquote
                          key={`${citation.source_version_id}:${index}`}
                          className="space-y-1 border-s-2 ps-3 text-sm leading-6"
                        >
                          <p>{citation.quote}</p>
                          {source && (
                            <a
                              className="break-all text-xs text-primary underline"
                              href={source.url}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              {new URL(source.url).hostname} · captured{" "}
                              {dateLabel(source.retrieved_at)}
                            </a>
                          )}
                        </blockquote>
                      );
                    })}
                  </div>
                ) : null,
            )}
            <p className="text-xs text-muted-foreground">
              Sources support the agent’s assessment; they can be outdated or
              incomplete. Review uncertain details before using them.
            </p>
            <RecordWorkButton
              resource="contacts"
              id={contact.id}
              compact
              disabled={busy}
              request={{
                research_requested: true,
                channel: "linkedin",
                instructions,
              }}
            />
          </DialogContent>
        </Dialog>
      )}
      {editing && (
        <FollowUpWriter
          contact={contact}
          existing={editing}
          close={() => setEditing(undefined)}
          onSaved={() => {
            void client.invalidateQueries({ queryKey: ["contacts"] });
          }}
        />
      )}
    </div>
  );
}
