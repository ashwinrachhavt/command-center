"use client";

import { useAuth } from "@clerk/nextjs";
import { useEffect } from "react";
import { useMutation } from "@tanstack/react-query";
import { Save } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { api, ApiError, type Schema } from "@/lib/api";
import { DraftStatus } from "./draft-status";
import { RichWriter } from "./rich-writer";
import { useWorkingDraft } from "./use-working-draft";

export type ArtifactDraft = {
  text: string;
  baseVersionId: string;
  baseVersion: number;
  expectedVersion: number;
};
type Props = {
  artifactId: string;
  initial: ArtifactDraft;
  onSaved: (version: Schema["VersionRead"]) => void;
  onClose: () => void;
  continuous?: boolean;
  label?: string;
  /** An acknowledged metadata edit from this writer's details dialog. */
  metadataRevision?: number;
};

export function ArtifactWriter(props: Props) {
  const { isLoaded, userId } = useAuth();
  if (!isLoaded || !userId) return <p role="status">Opening your writer…</p>;
  return (
    <OwnedArtifactWriter
      key={`${userId}-${props.artifactId}`}
      {...props}
      actor={userId}
    />
  );
}

function OwnedArtifactWriter({
  actor,
  artifactId,
  initial,
  onSaved,
  onClose,
  continuous = false,
  label,
  metadataRevision,
}: Props & { actor: string }) {
  const writing = useWorkingDraft(actor, `artifact-${artifactId}`, initial);
  const { draft } = writing;
  useEffect(() => {
    if (
      metadataRevision &&
      writing.status !== "loading" &&
      draft.getSnapshot().data.expectedVersion === metadataRevision - 1
    ) {
      draft.edit((copy) => ({ ...copy, expectedVersion: metadataRevision }));
    }
  }, [draft, metadataRevision, writing.status]);
  const checkpoint = useMutation({
    mutationFn: async () => {
      const snapshot = draft.getSnapshot().data;
      if (snapshot.text.length > 100_000)
        throw new Error(
          "This version exceeds 100,000 characters. Split it into separate documents before saving.",
        );
      await draft.flush();
      const target = `artifacts/${artifactId}/versions`;
      const request = draft.request(
        "POST",
        target,
        {
          text: snapshot.text,
          based_on_version_id: snapshot.baseVersionId,
          expected_version: snapshot.expectedVersion,
        },
        snapshot,
      );
      const saved = await api<Schema["VersionRead"]>(target, {
        method: "POST",
        body: request.body,
        key: request.key,
      });
      return { saved, snapshot: request.snapshot };
    },
    onError: (error) => {
      if (error instanceof ApiError && [400, 413, 422].includes(error.status))
        draft.resetIntent();
    },
    onSuccess: async ({ saved, snapshot }) => {
      onSaved(saved);
      if (continuous) {
        // Keep the live editor mounted. Clearing a draft resets its initial
        // content; a notebook instead advances the base beneath current typing.
        draft.resetIntent();
        draft.edit((current) => ({
          ...current,
          baseVersionId:
            current.baseVersionId === snapshot.baseVersionId
              ? saved.id
              : current.baseVersionId,
          baseVersion:
            current.baseVersionId === snapshot.baseVersionId
              ? saved.version
              : current.baseVersion,
          expectedVersion: snapshot.expectedVersion + 1,
        }));
        toast.success("Checkpoint saved");
        return;
      }
      try {
        if (await draft.clearIfUnchanged(snapshot)) {
          draft.resetIntent();
          onClose();
          toast.success("New version saved");
        } else {
          draft.resetIntent();
          draft.edit((current) => ({
            ...current,
            baseVersionId:
              current.baseVersionId === snapshot.baseVersionId
                ? saved.id
                : current.baseVersionId,
            baseVersion:
              current.baseVersionId === snapshot.baseVersionId
                ? saved.version
                : current.baseVersion,
            expectedVersion: snapshot.expectedVersion + 1,
          }));
          toast.success(
            "Version saved. Your newer writing remains in the draft.",
          );
        }
      } catch {
        toast.message(
          "Version saved. Your working copy remains available to recover.",
        );
      }
    },
  });
  const branch = useMutation({
    mutationFn: async () => {
      const current = await api<Schema["ArtifactRead"]>(
        `artifacts/${artifactId}`,
      );
      if (current.archived_at)
        throw new Error("This document is archived. Your draft remains saved.");
      draft.resetIntent();
      draft.edit((copy) => ({ ...copy, expectedVersion: current.row_version }));
      await checkpoint.mutateAsync();
    },
  });
  return (
    <form
      className="space-y-3"
      onSubmit={(event) => {
        event.preventDefault();
        checkpoint.mutate();
      }}
    >
      <p className="text-xs text-muted-foreground">
        {continuous
          ? `Your writing autosaves. Save a checkpoint to add it to version history. Current base: version ${writing.data.baseVersion}.`
          : `Editing from version ${writing.data.baseVersion}. Save a new version before reviewing or exporting these changes.`}
      </p>
      <DraftStatus
        draft={draft}
        state={writing}
        disabled={checkpoint.isPending || branch.isPending}
        preview={(copy) => copy.text}
      />
      <RichWriter
        id={`artifact-writing-${artifactId}`}
        label={label ?? (continuous ? "Note content" : "New version content")}
        placeholder={
          continuous
            ? "Start with a thought. Make room for the next one…"
            : undefined
        }
        value={writing.data.text}
        format="markdown"
        revision={writing.editorRevision}
        disabled={writing.status === "loading"}
        onChange={(text) => draft.edit((current) => ({ ...current, text }))}
      />
      {(checkpoint.error || branch.error) && (
        <div role="alert" className="space-y-2 text-sm text-destructive">
          <p>{(branch.error ?? checkpoint.error)?.message}</p>
          {checkpoint.error instanceof ApiError &&
            checkpoint.error.status === 409 &&
            writing.status !== "conflict" && (
              <>
                <p className="text-xs text-muted-foreground">
                  Your draft retains its original source version. You can save
                  it as an additional version; the other versions stay
                  available.
                </p>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={branch.isPending || checkpoint.isPending}
                  onClick={() => branch.mutate()}
                >
                  Save as an additional version
                </Button>
              </>
            )}
        </div>
      )}
      <div className="flex flex-wrap items-center justify-end gap-2">
        {!continuous && (
          <Button type="button" variant="ghost" onClick={onClose}>
            Close writer
          </Button>
        )}
        <Button
          disabled={
            checkpoint.isPending ||
            branch.isPending ||
            writing.status === "loading" ||
            writing.status === "conflict"
          }
        >
          <Save />
          {checkpoint.isPending
            ? "Saving version…"
            : continuous
              ? "Save checkpoint"
              : "Save version"}
        </Button>
      </div>
    </form>
  );
}
