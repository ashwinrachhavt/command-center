"use client";

import { useEffect, useRef, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Mail, Plus, ArrowUpRight, Pencil, Save } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { RichWriter } from "@/components/writing/rich-writer";
import { DraftStatus } from "@/components/writing/draft-status";
import { EmailPreview } from "@/components/writing/email-preview";
import { useWorkingDraft } from "@/components/writing/use-working-draft";
import {
  api,
  ApiError,
  dateLabel,
  type Page,
  type Resources,
  type Schema,
} from "@/lib/api";
import { ActionEditor } from "./reviewed-actions";
import { ErrorState, LoadingRows } from "./primitives";
import { RecordAgentWork } from "./record-agent-work";

type FollowUp = Schema["FollowUpRead"];
type FollowUpDraft = {
  channel: "linkedin" | "email";
  text: string;
  format: "text" | "html";
  subject: string;
  recipient_email: string;
  artifactId: string;
  expectedVersion: number;
  baseVersionId: string;
};
const selectStyle =
  "h-9 w-full rounded-lg border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

export function ContactFollowUps({
  contact,
}: {
  contact: Resources["contacts"];
}) {
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<string>();
  const [editing, setEditing] = useState<FollowUp | "new">();
  const [email, setEmail] = useState<FollowUp>();
  const list = useQuery({
    queryKey: ["follow-ups", contact.id, offset],
    queryFn: () =>
      api<Page<Schema["FollowUpSummary"]>>(
        `contacts/${contact.id}/follow-ups?limit=10&offset=${offset}`,
      ),
  });
  const detail = useQuery({
    queryKey: ["follow-up", selected],
    enabled: !!selected,
    queryFn: () => api<FollowUp>(`follow-ups/${selected}`),
  });
  const saved = detail.data;
  const payload = saved?.version.payload;
  const recipient = String(payload?.recipient_email ?? contact.email ?? "");
  const subject = String(payload?.subject ?? "");
  const linkedin = safeLinkedIn(contact.linkedin_url);
  const mailto =
    saved && recipient
      ? `mailto:${encodeURIComponent(recipient)}?${new URLSearchParams({ subject, body: saved.plain_text })}`
      : null;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-medium">Follow-ups</h3>
          <p className="mt-1 max-w-lg text-sm text-muted-foreground">
            Keep a thoughtful message ready. Save it here, then copy it for
            LinkedIn or prepare an email.
          </p>
        </div>
        <Button onClick={() => setEditing("new")}>
          <Plus />
          Write follow-up
        </Button>
      </div>
      <RecordAgentWork
        resource="contacts"
        id={contact.id}
        onDraftReady={(id) => {
          setSelected(id);
          setOffset(0);
        }}
      />
      {list.isPending && <LoadingRows />}
      {list.error && (
        <ErrorState error={list.error} retry={() => void list.refetch()} />
      )}
      {list.data?.total === 0 && (
        <p className="rounded-lg border border-dashed p-6 text-sm text-muted-foreground">
          No saved follow-ups yet. Your unfinished writing will autosave as you
          work.
        </p>
      )}
      <div className="space-y-2">
        {list.data?.items.map((item) => (
          <button
            key={item.artifact_id}
            type="button"
            aria-pressed={selected === item.artifact_id}
            onClick={() => setSelected(item.artifact_id)}
            className={`w-full rounded-lg border p-4 text-left hover:bg-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${selected === item.artifact_id ? "border-primary bg-accent/30" : "border-border"}`}
          >
            <span className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
              <span>
                {item.channel === "email" ? "Email" : "LinkedIn"} · version{" "}
                {item.version}
              </span>
              <span>{dateLabel(item.updated_at)}</span>
            </span>
            <span className="mt-2 block text-sm font-medium">
              {item.subject || item.title}
            </span>
            <span className="mt-1 line-clamp-2 block text-sm text-muted-foreground">
              {item.preview}
            </span>
          </button>
        ))}
      </div>
      {list.data && list.data.total > 10 && (
        <div className="flex items-center justify-between gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - 10))}
          >
            Previous
          </Button>
          <span className="text-xs text-muted-foreground">
            {offset + 1}–{Math.min(offset + 10, list.data.total)} of{" "}
            {list.data.total}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={offset + 10 >= list.data.total}
            onClick={() => setOffset(offset + 10)}
          >
            Next
          </Button>
        </div>
      )}
      {selected && detail.isPending && <LoadingRows />}
      {detail.error && (
        <ErrorState error={detail.error} retry={() => void detail.refetch()} />
      )}
      {saved && (
        <section
          aria-label="Saved follow-up"
          className="space-y-4 rounded-xl border p-4 sm:p-5"
        >
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h4 className="font-medium">{subject || "Saved message"}</h4>
              <p className="mt-1 text-xs text-muted-foreground">
                Version {saved.version.version} ·{" "}
                {recipient || "Copy to LinkedIn"}
              </p>
            </div>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setEditing(saved)}
            >
              <Pencil />
              Edit draft
            </Button>
          </div>
          {payload?.format === "html" ? (
            <EmailPreview html={String(payload.text ?? "")} />
          ) : (
            <p className="whitespace-pre-wrap text-sm leading-7">
              {saved.plain_text}
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(saved.plain_text);
                  toast.success("Saved message copied");
                } catch {
                  toast.error(
                    "Clipboard unavailable. Select and copy the saved message above.",
                  );
                }
              }}
            >
              <Copy />
              Copy message
            </Button>
            {linkedin && (
              <Button asChild variant="outline">
                <a href={linkedin} target="_blank" rel="noopener noreferrer">
                  Open LinkedIn
                  <ArrowUpRight />
                </a>
              </Button>
            )}
            {recipient && (
              <Button onClick={() => setEmail(saved)}>
                <Mail />
                Prepare email
              </Button>
            )}
            {mailto && mailto.length < 2000 && (
              <Button asChild variant="ghost">
                <a href={mailto}>
                  Open mail app
                  <ArrowUpRight />
                </a>
              </Button>
            )}
          </div>
          {!recipient && (
            <p className="text-xs text-muted-foreground">
              No email saved for this person. You can add one while editing the
              draft.
            </p>
          )}
          <p className="text-xs text-muted-foreground">
            Copying or opening another app does not mark this message as sent.
            Email from Command Center requires a separate review and send.
          </p>
        </section>
      )}
      {editing && (
        <FollowUpWriter
          contact={contact}
          existing={editing === "new" ? undefined : editing}
          close={() => setEditing(undefined)}
          onSaved={(result) => {
            setSelected(result.artifact.id);
            setOffset(0);
          }}
        />
      )}
      {email && (
        <ActionEditor
          close={() => setEmail(undefined)}
          seed={{
            sourceVersionId: email.version.id,
            sourceTitle: `Follow-up for ${contact.name} · version ${email.version.version}`,
            values: {
              to: String(
                email.version.payload?.recipient_email ?? contact.email ?? "",
              ),
              subject: String(email.version.payload?.subject ?? ""),
              body: String(email.version.payload?.text ?? ""),
              is_html: String(email.version.payload?.format === "html"),
            },
          }}
        />
      )}
    </div>
  );
}

function safeLinkedIn(value: string | null | undefined) {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" &&
      (url.hostname === "linkedin.com" ||
        url.hostname.endsWith(".linkedin.com"))
      ? url.href
      : null;
  } catch {
    return null;
  }
}

type WriterProps = {
  contact: Resources["contacts"];
  existing?: FollowUp;
  close: () => void;
  onSaved: (saved: FollowUp) => void;
};
function FollowUpWriter(props: WriterProps) {
  const { isLoaded, userId } = useAuth();
  if (!isLoaded || !userId) return null;
  return (
    <OwnedFollowUpWriter
      key={`${userId}-${props.existing?.artifact.id ?? props.contact.id}`}
      {...props}
      actor={userId}
    />
  );
}
function OwnedFollowUpWriter({
  contact,
  existing,
  close,
  onSaved,
  actor,
}: WriterProps & { actor: string }) {
  const client = useQueryClient();
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const payload = existing?.version.payload;
  const writing = useWorkingDraft<FollowUpDraft>(
    actor,
    `follow-up-${existing?.artifact.id ?? `${contact.id}-new`}`,
    {
      channel: payload?.channel === "email" ? "email" : "linkedin",
      text: String(payload?.text ?? ""),
      format: payload?.format === "html" ? "html" : "text",
      subject: String(payload?.subject ?? ""),
      recipient_email: String(payload?.recipient_email ?? contact.email ?? ""),
      artifactId: existing?.artifact.id ?? "",
      expectedVersion: existing?.artifact.row_version ?? 0,
      baseVersionId: existing?.version.id ?? "",
    },
  );
  const { draft, data } = writing;
  const save = useMutation({
    mutationFn: async () => {
      const snapshot = draft.getSnapshot().data;
      if (snapshot.text.length > 50_000)
        throw new Error("Keep this message under 50,000 characters.");
      await draft.flush();
      const body = {
        channel: snapshot.channel,
        text: snapshot.text,
        format: snapshot.format,
        subject: snapshot.subject,
        recipient_email: snapshot.recipient_email || null,
        ...(snapshot.artifactId
          ? {
              expected_version: snapshot.expectedVersion,
              based_on_version_id: snapshot.baseVersionId,
            }
          : {}),
      };
      const request = draft.request(
        snapshot.artifactId ? "PATCH" : "POST",
        snapshot.artifactId
          ? `follow-ups/${snapshot.artifactId}`
          : `contacts/${contact.id}/follow-ups`,
        body,
        snapshot,
      );
      const saved = await api<FollowUp>(request.target, {
        method: request.method,
        body: request.body,
        key: request.key,
      });
      return { saved, snapshot: request.snapshot };
    },
    onSuccess: async ({ saved, snapshot }) => {
      client.setQueryData(["follow-up", saved.artifact.id], saved);
      void client.invalidateQueries({ queryKey: ["follow-ups", contact.id] });
      void client.invalidateQueries({ queryKey: ["artifacts"] });
      if (active.current) onSaved(saved);
      try {
        if (await draft.clearIfUnchanged(snapshot)) {
          draft.resetIntent();
          if (active.current) close();
        } else {
          draft.resetIntent();
          draft.edit((current) => ({
            ...current,
            artifactId: saved.artifact.id,
            expectedVersion: saved.artifact.row_version,
            baseVersionId: saved.version.id,
          }));
        }
        toast.success("Follow-up saved. Nothing has been sent.");
      } catch {
        toast.message("Follow-up saved. Your working copy is still available.");
      }
    },
    onError: (error) => {
      if (error instanceof ApiError && [400, 413, 422].includes(error.status))
        draft.resetIntent();
    },
  });
  const branch = useMutation({
    mutationFn: async () => {
      const current = await api<FollowUp>(`follow-ups/${data.artifactId}`);
      if (current.artifact.archived_at)
        throw new Error(
          "This follow-up is archived. Your writing remains saved.",
        );
      draft.resetIntent();
      draft.edit((value) => ({
        ...value,
        expectedVersion: current.artifact.row_version,
      }));
      await save.mutateAsync();
    },
  });
  return (
    <Dialog open onOpenChange={(open) => !open && close()}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Follow up with {contact.name}</DialogTitle>
          <DialogDescription>
            {contact.title || "Write a thoughtful next step."} Your working copy
            autosaves; save a version when it is ready to use.
          </DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            save.mutate();
          }}
        >
          <DraftStatus
            draft={draft}
            state={writing}
            disabled={save.isPending || branch.isPending}
            preview={(copy) => `${copy.subject}\n\n${copy.text}`}
          />
          <fieldset
            disabled={writing.status === "loading"}
            className="min-w-0 space-y-4"
          >
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="space-y-2 text-sm">
                <span>Use for</span>
                <select
                  aria-label="Follow-up channel"
                  className={selectStyle}
                  value={data.channel}
                  onChange={(event) =>
                    draft.edit((current) => ({
                      ...current,
                      channel: event.target.value as FollowUpDraft["channel"],
                    }))
                  }
                >
                  <option value="linkedin">LinkedIn message</option>
                  <option value="email">Email</option>
                </select>
              </label>
              <label className="space-y-2 text-sm">
                <span>Email address (optional)</span>
                <Input
                  aria-label="Recipient email"
                  type="email"
                  value={data.recipient_email}
                  onChange={(event) =>
                    draft.edit((current) => ({
                      ...current,
                      recipient_email: event.target.value,
                    }))
                  }
                />
              </label>
            </div>
            <label className="block space-y-2 text-sm">
              <span>Subject or reminder</span>
              <Input
                aria-label="Subject or reminder"
                maxLength={300}
                value={data.subject}
                onChange={(event) =>
                  draft.edit((current) => ({
                    ...current,
                    subject: event.target.value,
                  }))
                }
                placeholder="A clear reason to reconnect"
              />
            </label>
            <RichWriter
              id="follow-up-writing"
              label="Follow-up message"
              value={data.text}
              format={data.format}
              revision={writing.editorRevision}
              disabled={writing.status === "loading"}
              placeholder={`Hi ${contact.name.split(" ")[0]},…`}
              onChange={(text, format) =>
                draft.edit((current) => ({
                  ...current,
                  text,
                  format: format === "html" ? "html" : "text",
                }))
              }
            />
          </fieldset>
          {(save.error || branch.error) && (
            <div role="alert" className="space-y-2 text-sm text-destructive">
              <p>{(branch.error ?? save.error)?.message}</p>
              {save.error instanceof ApiError &&
                save.error.status === 409 &&
                data.artifactId &&
                writing.status !== "conflict" && (
                  <Button
                    type="button"
                    variant="outline"
                    disabled={branch.isPending || save.isPending}
                    onClick={() => branch.mutate()}
                  >
                    Save as an additional version
                  </Button>
                )}
            </div>
          )}
          <div className="flex flex-wrap justify-end gap-2">
            <Button type="button" variant="ghost" onClick={close}>
              Close writer
            </Button>
            <Button
              disabled={
                save.isPending ||
                branch.isPending ||
                ["loading", "conflict"].includes(writing.status)
              }
            >
              <Save />
              {save.isPending ? "Saving follow-up…" : "Save follow-up"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
