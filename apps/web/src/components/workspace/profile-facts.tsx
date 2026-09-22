"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowUpRight,
  Check,
  FileCheck2,
  Pencil,
  Plus,
  RotateCcw,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  api,
  label,
  type DocumentImport,
  type FactRevision,
  type Page,
  type ProfileFact,
  type ResumeSelection,
  type WorkspaceRecord,
} from "@/lib/api";
import { RetainedRequestIntent } from "@/lib/retained-intent";
import { ErrorState, LoadingRows, Spinner } from "./primitives";
import { sizeLabel } from "./document-intake";
import { useWorkspaceContext } from "./context";

const factFields: ProfileFact["field"][] = [
  "full_name",
  "email",
  "phone",
  "location",
  "headline",
  "website",
  "linkedin",
  "summary",
  "skill",
  "experience",
  "education",
  "answer",
];

function ResumeSelector({ selection }: { selection: ResumeSelection }) {
  const client = useQueryClient();
  const [versionId, setVersionId] = useState(selection.version_id ?? "none");
  const [intent] = useState(() => new RetainedRequestIntent());
  const imports = useQuery({
    queryKey: ["document-imports", "resume-options"],
    queryFn: () =>
      api<Page<DocumentImport>>("documents/imports?limit=100&offset=0"),
  });
  const artifacts = useQuery({
    queryKey: ["artifacts", "resume-options"],
    queryFn: () => api<Page<WorkspaceRecord>>("artifacts?limit=100&offset=0"),
  });
  const documentTypes = useQuery({
    queryKey: ["document-types"],
    queryFn: () =>
      api<{ id: string; name: string; slug?: string }[]>("document-types"),
  });
  const resumeTypeIds = new Set(
    (documentTypes.data ?? [])
      .filter((type) =>
        [type.slug, type.name].some((value) =>
          value?.toLowerCase().includes("resume"),
        ),
      )
      .map((type) => type.id),
  );
  const resumeArtifactIds = new Set(
    (artifacts.data?.items ?? [])
      .filter((artifact) =>
        resumeTypeIds.has(
          String(
            (artifact as unknown as Record<string, unknown>).document_type_id,
          ),
        ),
      )
      .map((artifact) => artifact.id),
  );
  const options = Array.from(
    new Map(
      (imports.data?.items ?? [])
        .filter((item) => resumeArtifactIds.has(item.artifact_id))
        .map((item) => [item.source_version_id, item]),
    ).values(),
  );
  const save = useMutation({
    mutationFn: (submittedVersionId: string) => {
      const target = "profile/default-resume";
      const body = {
        version_id: submittedVersionId === "none" ? null : submittedVersionId,
        expected_version: selection.row_version,
      };
      const request = intent.forRequest("POST", target, body);
      return api<ResumeSelection>(target, {
        method: "POST",
        key: request.key,
        body,
      }).then((result) => ({ result, target, body }));
    },
    onSuccess: ({ target, body }) => {
      intent.confirmRequest("POST", target, body);
      client.invalidateQueries({ queryKey: ["default-resume"] });
      toast.success("Default resume version saved");
    },
    onError: (error) => toast.error(error.message),
  });
  return (
    <div className="space-y-4">
      <div className="flex items-start gap-3">
        <FileCheck2 className="mt-0.5 size-4 text-primary" />
        <div>
          <h2 className="text-sm font-medium">Default resume</h2>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            Agents use this exact original version. Uploading a newer version
            does not change the selection.
          </p>
        </div>
      </div>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <Field className="min-w-0 flex-1">
          <FieldLabel htmlFor="default-resume">Pinned version</FieldLabel>
          <Select value={versionId} onValueChange={setVersionId}>
            <SelectTrigger id="default-resume" aria-label="Default resume">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value="none">No default resume</SelectItem>
                {options.map((item) => (
                  <SelectItem
                    key={item.source_version_id}
                    value={item.source_version_id}
                  >
                    {item.filename} · {item.source_version_id.slice(0, 8)}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </Field>
        <Button
          onClick={() => save.mutate(versionId)}
          disabled={
            save.isPending || versionId === (selection.version_id ?? "none")
          }
        >
          {save.isPending ? <Spinner /> : <Check />} Save exact version
        </Button>
      </div>
      {selection.version_id ? (
        <p className="text-[11px] text-muted-foreground">
          Current: {selection.filename ?? selection.title} ·{" "}
          {selection.byte_size
            ? sizeLabel(selection.byte_size)
            : "size unavailable"}{" "}
          · {selection.version_id}
        </p>
      ) : (
        <p className="text-[11px] text-muted-foreground">
          No resume version is currently selected.
        </p>
      )}
      {imports.error || artifacts.error || documentTypes.error ? (
        <ErrorState
          error={imports.error ?? artifacts.error ?? documentTypes.error!}
          retry={() => {
            imports.refetch();
            artifacts.refetch();
            documentTypes.refetch();
          }}
        />
      ) : null}
    </div>
  );
}

type FactDraft = {
  field: ProfileFact["field"];
  value: string;
  context: string;
  valid_until: string;
};

const emptyDraft: FactDraft = {
  field: "headline",
  value: "",
  context: "",
  valid_until: "",
};

function FactEditor({
  fact,
  open,
  onOpenChange,
}: {
  fact?: ProfileFact;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const client = useQueryClient();
  const [draft, setDraft] = useState<FactDraft>(() =>
    fact
      ? {
          field: fact.field,
          value: fact.current.value,
          context: fact.current.context ?? "",
          valid_until: fact.current.valid_until?.slice(0, 16) ?? "",
        }
      : emptyDraft,
  );
  const [intent] = useState(() => new RetainedRequestIntent());
  const [error, setError] = useState("");
  const change = (next: Partial<FactDraft>) => {
    setDraft((current) => ({ ...current, ...next }));
    setError("");
  };
  const save = useMutation({
    mutationFn: () => {
      const evidence = fact?.current;
      const body = {
        value: draft.value.trim(),
        context: draft.context.trim() || undefined,
        valid_until: draft.valid_until
          ? new Date(draft.valid_until).toISOString()
          : undefined,
        ...(fact
          ? {
              expected_version: fact.row_version,
              source_version_id: evidence?.source_version_id ?? undefined,
              source_excerpt: evidence?.source_excerpt ?? undefined,
            }
          : { field: draft.field }),
      };
      const target = fact
        ? `profile/facts/${fact.id}/versions`
        : "profile/facts";
      const request = intent.forRequest("POST", target, body);
      return api(target, {
        method: "POST",
        body,
        key: request.key,
      }).then((result) => ({ result, target, body }));
    },
    onSuccess: ({ target, body }) => {
      intent.confirmRequest("POST", target, body);
      client.invalidateQueries({ queryKey: ["profile-facts"] });
      toast.success(
        fact ? "New fact revision proposed" : "Fact proposed for review",
      );
      onOpenChange(false);
    },
    onError: (nextError) => setError(nextError.message),
  });
  const valid =
    !!draft.value.trim() &&
    draft.value.trim().length <= 4000 &&
    draft.context.length <= 1000 &&
    (draft.field !== "answer" || !!draft.context.trim());
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {fact ? "Propose an updated fact" : "Propose a profile fact"}
          </DialogTitle>
          <DialogDescription>
            Saving creates a proposal. It does not make the value available to
            agents until you approve that exact revision.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <Field>
            <FieldLabel htmlFor="fact-field">Field</FieldLabel>
            <Select
              value={draft.field}
              disabled={!!fact}
              onValueChange={(value) =>
                change({ field: value as ProfileFact["field"] })
              }
            >
              <SelectTrigger id="fact-field">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {factFields.map((field) => (
                    <SelectItem key={field} value={field}>
                      {label(field)}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </Field>
          <Field>
            <FieldLabel htmlFor="fact-value">Value</FieldLabel>
            <Textarea
              id="fact-value"
              rows={4}
              maxLength={4000}
              value={draft.value}
              onChange={(event) => change({ value: event.target.value })}
            />
          </Field>
          <Field>
            <FieldLabel htmlFor="fact-context">
              Context {draft.field === "answer" ? "(required)" : "(optional)"}
            </FieldLabel>
            <Textarea
              id="fact-context"
              rows={2}
              maxLength={1000}
              value={draft.context}
              onChange={(event) => change({ context: event.target.value })}
              placeholder={
                draft.field === "answer"
                  ? "The exact question or situation this answer applies to"
                  : "Where or when this fact applies"
              }
            />
          </Field>
          <Field>
            <FieldLabel htmlFor="fact-valid-until">
              Valid until (optional)
            </FieldLabel>
            <Input
              id="fact-valid-until"
              type="datetime-local"
              value={draft.valid_until}
              onChange={(event) => change({ valid_until: event.target.value })}
            />
          </Field>
          {fact?.current.source_excerpt ? (
            <p className="rounded-md bg-muted p-3 text-xs leading-5 text-muted-foreground">
              Evidence remains pinned to the current source version: “
              {fact.current.source_excerpt}”
            </p>
          ) : null}
          {error ? (
            <p role="alert" className="text-xs text-destructive">
              {error} Your draft is still here; refresh the facts if another
              review changed it.
            </p>
          ) : null}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Keep draft
          </Button>
          <Button
            disabled={!valid || save.isPending}
            onClick={() => save.mutate()}
          >
            {save.isPending ? <Spinner /> : <Plus />}{" "}
            {error ? "Retry proposal" : "Save proposal"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function SourceLink({ revision }: { revision: FactRevision }) {
  const context = useWorkspaceContext();
  if (!revision.source_artifact_id || !revision.source_version_id) return null;
  return (
    <Button
      variant="link"
      className="h-auto p-0 text-xs"
      onClick={() =>
        context?.open("artifacts", revision.source_artifact_id!, {
          tab: "content",
          versionId: revision.source_version_id!,
        })
      }
    >
      Open pinned source <ArrowUpRight />
    </Button>
  );
}

function FactCard({ fact }: { fact: ProfileFact }) {
  const client = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [reviewIntent] = useState(() => new RetainedRequestIntent());
  const review = useMutation({
    mutationFn: ({
      revision,
      decision,
    }: {
      revision: FactRevision;
      decision: "approved" | "rejected" | "revoked";
    }) => {
      const target = `profile/facts/${fact.id}/reviews`;
      const body = {
        expected_version: fact.row_version,
        revision_id: revision.id,
        decision,
        reason: reason.trim() || undefined,
      };
      const intent = reviewIntent.forRequest("POST", target, body);
      return api(target, {
        method: "POST",
        key: intent.key,
        body,
      }).then((result) => ({ result, target, body }));
    },
    onSuccess: ({ target, body }, variables) => {
      reviewIntent.confirmRequest("POST", target, body);
      setReason((current) =>
        current.trim() === (body.reason ?? "") ? "" : current,
      );
      setError("");
      client.invalidateQueries({ queryKey: ["profile-facts"] });
      toast.success(`Fact ${variables.decision}`);
    },
    onError: (nextError) => setError(nextError.message),
  });
  const pending = fact.current.id !== fact.active?.id;
  return (
    <article className="rounded-lg border border-border bg-background p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-medium">{label(fact.field)}</h3>
        {pending ? <Badge variant="secondary">Pending proposal</Badge> : null}
        {fact.active ? (
          <Badge variant="outline" className="text-primary">
            Active approved
          </Badge>
        ) : null}
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <section aria-label={`Active approved ${label(fact.field)}`}>
          <p className="text-[10px] font-medium tracking-wide text-muted-foreground uppercase">
            Active approved revision
          </p>
          {fact.active ? (
            <>
              <p className="mt-2 whitespace-pre-wrap text-sm leading-6">
                {fact.active.value}
              </p>
              {fact.active.context ? (
                <p className="mt-1 text-xs text-muted-foreground">
                  Context: {fact.active.context}
                </p>
              ) : null}
              <div className="mt-2 flex items-center gap-3">
                <SourceLink revision={fact.active} />
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={review.isPending}
                  onClick={() =>
                    review.mutate({
                      revision: fact.active!,
                      decision: "revoked",
                    })
                  }
                >
                  <RotateCcw /> Revoke
                </Button>
              </div>
            </>
          ) : (
            <p className="mt-2 text-xs text-muted-foreground">
              No approved value is active.
            </p>
          )}
        </section>
        <section aria-label={`Current proposal ${label(fact.field)}`}>
          <p className="text-[10px] font-medium tracking-wide text-muted-foreground uppercase">
            {pending ? "Current proposal" : "Current revision"}
          </p>
          <p className="mt-2 whitespace-pre-wrap text-sm leading-6">
            {fact.current.value}
          </p>
          {fact.current.context ? (
            <p className="mt-1 text-xs text-muted-foreground">
              Context: {fact.current.context}
            </p>
          ) : null}
          {fact.current.source_excerpt ? (
            <blockquote className="mt-2 border-l-2 border-primary/30 pl-3 text-xs leading-5 text-muted-foreground">
              {fact.current.source_excerpt}
            </blockquote>
          ) : null}
          <div className="mt-2">
            <SourceLink revision={fact.current} />
          </div>
          {fact.current.review_state === "proposed" ? (
            <div className="mt-3 flex flex-wrap gap-2">
              <Button
                size="sm"
                disabled={review.isPending}
                onClick={() =>
                  review.mutate({
                    revision: fact.current,
                    decision: "approved",
                  })
                }
              >
                <Check /> Approve exact revision
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={review.isPending}
                onClick={() =>
                  review.mutate({
                    revision: fact.current,
                    decision: "rejected",
                  })
                }
              >
                <X /> Reject
              </Button>
            </div>
          ) : null}
          <Button
            variant="ghost"
            size="sm"
            className="mt-2"
            onClick={() => setEditing(true)}
          >
            <Pencil /> Propose edit
          </Button>
        </section>
      </div>
      <Field className="mt-4">
        <FieldLabel htmlFor={`fact-reason-${fact.id}`}>
          Review note (optional)
        </FieldLabel>
        <Input
          id={`fact-reason-${fact.id}`}
          value={reason}
          maxLength={2000}
          onChange={(event) => {
            setReason(event.target.value);
            setError("");
          }}
        />
      </Field>
      {error ? (
        <div className="mt-3 flex flex-wrap items-center gap-2" role="alert">
          <p className="text-xs text-destructive">
            {error} The review note is still here.
          </p>
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              client.invalidateQueries({ queryKey: ["profile-facts"] })
            }
          >
            Refresh facts
          </Button>
        </div>
      ) : null}
      <FactEditor fact={fact} open={editing} onOpenChange={setEditing} />
    </article>
  );
}

export function ProfileFacts() {
  const [creating, setCreating] = useState(false);
  const facts = useQuery({
    queryKey: ["profile-facts"],
    queryFn: () => api<Page<ProfileFact>>("profile/facts?limit=100&offset=0"),
  });
  const resume = useQuery({
    queryKey: ["default-resume"],
    queryFn: () => api<ResumeSelection>("profile/default-resume"),
  });
  return (
    <>
      <section className="rounded-xl border border-border bg-card p-6">
        {resume.error ? (
          <ErrorState error={resume.error} retry={() => resume.refetch()} />
        ) : resume.isPending ? (
          <LoadingRows />
        ) : (
          <ResumeSelector
            key={`${resume.data.row_version}:${resume.data.version_id}`}
            selection={resume.data}
          />
        )}
      </section>
      <section className="rounded-xl border border-border bg-card p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-medium">Reviewed candidate facts</h2>
            <p className="mt-1 max-w-2xl text-xs leading-5 text-muted-foreground">
              Pending proposals stay separate from active approved revisions.
              Agents receive only active, unexpired approved facts.
            </p>
          </div>
          <Button size="sm" onClick={() => setCreating(true)}>
            <Plus /> Propose fact
          </Button>
        </div>
        {facts.error ? (
          <ErrorState error={facts.error} retry={() => facts.refetch()} />
        ) : facts.isPending ? (
          <LoadingRows />
        ) : facts.data.items.length ? (
          <div className="mt-5 space-y-4">
            {facts.data.items.map((fact) => (
              <FactCard key={`${fact.id}:${fact.row_version}`} fact={fact} />
            ))}
          </div>
        ) : (
          <p className="mt-5 text-sm text-muted-foreground">
            No candidate facts have been proposed.
          </p>
        )}
      </section>
      <FactEditor open={creating} onOpenChange={setCreating} />
    </>
  );
}
