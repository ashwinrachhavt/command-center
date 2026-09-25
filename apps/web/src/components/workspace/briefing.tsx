"use client";

import { AnimatedIcon } from "@/components/ui/animated-icon";
import Link from "next/link";
import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, MessageSquare, Plus, Upload } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  api,
  ApiError,
  type Activity,
  type Page,
  type Resources,
  type Schema,
  type Space,
} from "@/lib/api";
import { RetainedRequestIntent } from "@/lib/retained-intent";
import { ActivityList } from "./activity-list";
import { useWorkspaceContext } from "./context";
import { DailyTasks, WorkQueues } from "./daily-work";
import { deferView } from "./deferred-view";
import { ErrorState, LoadingRows, PageHeading, Spinner } from "./primitives";

const DocumentUploadDialog = deferView<{
  open: boolean;
  onOpenChange: (open: boolean) => void;
}>(
  () =>
    import("./document-intake").then((module) => ({
      default: module.DocumentUploadDialog,
    })),
  "document upload",
);

export function QuickCapture({ space }: { space?: Space }) {
  const context = useWorkspaceContext();
  const client = useQueryClient();
  const [text, setText] = useState("");
  const [uploading, setUploading] = useState(false);
  const [saved, setSaved] = useState<Resources["tasks"] | null>(null);
  const [spaceId, setSpaceId] = useState("none");
  const spaces = useQuery({
    queryKey: ["spaces", "capture"],
    queryFn: () => api<Page<Space>>("spaces?state=active&limit=100"),
    enabled: !space,
  });
  const selectedSpace =
    space ?? spaces.data?.items.find((item) => item.id === spaceId);
  const unavailableSpace =
    selectedSpace?.state === "archived" ||
    (!space && spaceId !== "none" && !selectedSpace);
  // A response may be lost after commit. Preserve the original version fence
  // for the same capture even if a background read returns a newer Space.
  const target = useRef<{ signature: string; path: string } | null>(null);
  const [intent] = useState(() => new RetainedRequestIntent());
  const capture = useMutation({
    mutationFn: async ({
      content,
      destination,
    }: {
      content: string;
      destination?: Space;
    }) => {
      const body = {
        title: content.trim().split(/\r?\n/)[0].slice(0, 300),
        rationale: content,
        priority: 1,
      } satisfies Schema["TaskCreate"];
      const signature = JSON.stringify([content, destination?.id]);
      if (target.current?.signature !== signature) {
        target.current = {
          signature,
          path: destination
            ? `spaces/${destination.id}/tasks?expected_version=${destination.row_version}`
            : "tasks",
        };
      }
      const path = target.current.path;
      const request = intent.forRequest("POST", path, body);
      if (destination) {
        const result = await api<Schema["SpaceTaskRead"]>(path, {
          method: "POST",
          body,
          key: request.key,
        });
        client.setQueryData(["spaces", "detail", destination.id], result.space);
        return result.task;
      }
      return api<Resources["tasks"]>(path, {
        method: "POST",
        body,
        key: request.key,
      });
    },
    onSuccess: (task, { content }) => {
      intent.reset();
      target.current = null;
      setText((current) => (current === content ? "" : current));
      setSaved(task);
      void client.invalidateQueries({ queryKey: ["dashboard"] });
      void client.invalidateQueries({ queryKey: ["tasks"] });
      void client.invalidateQueries({ queryKey: ["activity"] });
      void client.invalidateQueries({ queryKey: ["spaces"] });
      toast.success("Task captured. Your context is saved with it.");
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) {
        target.current = null;
        void client.invalidateQueries({ queryKey: ["spaces"] });
      }
    },
  });
  return (
    <section
      aria-labelledby="capture-heading"
      className="rounded-xl shadow-surface bg-card p-5 md:p-6"
    >
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="capture-heading" className="font-medium">
            {space ? "Capture in this Space" : "Capture something"}
          </h2>
          <p id="capture-help" className="mt-1 text-sm text-muted-foreground">
            Start with a next step. Add the note or link that gives it context.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          disabled={space?.state === "archived"}
          onClick={() => setUploading(true)}
        >
          <Upload aria-hidden /> Upload document
        </Button>
      </div>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (text.trim() && !capture.isPending && !unavailableSpace)
            capture.mutate({ content: text, destination: selectedSpace });
        }}
      >
        <label htmlFor="briefing-capture" className="sr-only">
          What would you like to move forward?
        </label>
        <Textarea
          id="briefing-capture"
          aria-describedby="capture-help"
          placeholder="Prepare for Friday’s interview…"
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            if (capture.isError) capture.reset();
          }}
          maxLength={20000}
          disabled={capture.isPending || space?.state === "archived"}
          className="min-h-24 resize-y bg-background text-sm"
        />
        {!space && (
          <div className="mt-3 max-w-sm space-y-2">
            <label
              htmlFor="capture-space"
              className="text-xs text-muted-foreground"
            >
              Space (optional)
            </label>
            <Select
              value={spaceId}
              onValueChange={(value) => {
                setSpaceId(value);
                capture.reset();
              }}
              disabled={capture.isPending || spaces.isPending}
            >
              <SelectTrigger id="capture-space" className="w-full">
                <SelectValue placeholder="No Space" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">No Space</SelectItem>
                {spaces.data?.items
                  .filter((item) => item.state === "active")
                  .map((item) => (
                    <SelectItem key={item.id} value={item.id}>
                      {item.title}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
            {spaces.isPending && (
              <p className="text-xs text-muted-foreground">Loading Spaces…</p>
            )}
            {spaces.error && (
              <p role="alert" className="text-xs text-destructive">
                Spaces couldn’t load. You can still capture without a Space.{" "}
                <button
                  type="button"
                  className="underline"
                  onClick={() => void spaces.refetch()}
                >
                  Retry Spaces
                </button>
              </p>
            )}
          </div>
        )}
        {unavailableSpace && (
          <p role="alert" className="mt-2 text-sm text-muted-foreground">
            This Space is no longer active. Choose an active Space or capture
            without one.
          </p>
        )}
        {capture.error && (
          <p role="alert" className="mt-2 text-sm text-destructive">
            {capture.error.message} Your text is still here; try again.
          </p>
        )}
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-muted-foreground">
            {space
              ? "Saved as a task linked to this Space."
              : "Saved as a task. The first line becomes its title."}
          </p>
          <Button
            type="submit"
            disabled={!text.trim() || capture.isPending || unavailableSpace}
          >
            <AnimatedIcon state={capture.isPending}>
              {capture.isPending ? <Spinner /> : <Plus aria-hidden />}
            </AnimatedIcon>{" "}
            Create task
          </Button>
        </div>
      </form>
      {saved && (
        <div
          role="status"
          className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4"
        >
          <p className="min-w-0 break-words text-sm">
            Captured: <span className="font-medium">{saved.title}</span>
          </p>
          <Button
            variant="outline"
            size="sm"
            onClick={() => context?.open("tasks", saved.id)}
          >
            Open task <ArrowRight aria-hidden />
          </Button>
        </div>
      )}
      {uploading && <DocumentUploadDialog open onOpenChange={setUploading} />}
    </section>
  );
}

export function Briefing() {
  const activity = useQuery({
    queryKey: ["activity", "briefing"],
    queryFn: () => api<Page<Activity>>("activity?limit=5"),
    refetchInterval: 60_000,
  });
  return (
    <>
      <PageHeading
        title="Briefing"
        description="What matters now, what needs you, and the next step forward."
        action={
          <Button variant="outline" asChild>
            <Link href="/agents">
              <MessageSquare aria-hidden /> Ask assistant
            </Link>
          </Button>
        }
      />
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-9 px-5 pb-10 md:px-9">
        <QuickCapture />
        <div className="grid min-w-0 gap-10 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
          <div className="flex min-w-0 flex-col gap-9">
            <DailyTasks title="What matters today" />
            <section aria-labelledby="briefing-changes">
              <h2 id="briefing-changes" className="font-medium">
                What changed
              </h2>
              <p className="mb-4 mt-1 text-xs text-muted-foreground">
                Recent activity in your saved workspace. Connected apps are
                checked only when requested.
              </p>
              {activity.isPending ? (
                <LoadingRows />
              ) : activity.error ? (
                <ErrorState
                  error={activity.error}
                  retry={() => activity.refetch()}
                />
              ) : (
                <ActivityList events={activity.data.items} />
              )}
            </section>
          </div>
          <WorkQueues briefing />
        </div>
      </div>
    </>
  );
}
