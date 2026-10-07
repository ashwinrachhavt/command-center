"use client";

import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, FileUp } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { api, dateLabel } from "@/lib/api";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingRows, Status } from "./primitives";

type AutomationApplication = {
  id: string;
  company: string;
  job_title: string;
  job_url: string;
  job_location: string | null;
  status: string;
  adapter_platform: string | null;
  submit_authorized_at: string | null;
  last_run_id: string | null;
  last_run: {
    id: string;
    state: string;
    mode: string;
    attempt: number;
    error: string | null;
  } | null;
};

const runStates = {
  queued: "Queued",
  running: "Running",
  completed: "Completed",
  failed: "Failed",
  outcome_unknown: "Outcome unknown",
  cancelled: "Cancelled",
} as const;

export function ApplicationsAutomation() {
  const heading = useRef<HTMLHeadingElement>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const list = useQuery({
    queryKey: ["applications-automation"],
    queryFn: ({ signal }) =>
      api<{ items: AutomationApplication[]; total: number }>(
        "applications-automation/applications?limit=100",
        { signal },
      ),
    refetchInterval: 20000,
  });
  function choose(id: string | null) {
    setSelected(id);
    requestAnimationFrame(() => heading.current?.focus());
  }
  return (
    <div className="mx-auto max-w-[1600px] p-5 md:p-8">
      <header className="mb-7 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="mb-2 text-xs font-medium tracking-wide text-muted-foreground">
            APPLICATION AUTOMATION
          </p>
          <h1
            ref={heading}
            tabIndex={-1}
            className="text-2xl font-semibold tracking-tight"
          >
            Automation runs
          </h1>
          <p className="mt-2 max-w-xl text-sm leading-6 text-muted-foreground">
            Queue browser runs from uploaded postings. Runs end ready for
            review; nothing is submitted automatically.
          </p>
        </div>
        <CsvUpload />
      </header>
      <div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(240px,340px)_minmax(0,1fr)]">
        <section aria-label="Automation application list" className="min-w-0">
          {list.error ? (
            <ErrorState error={list.error} retry={() => list.refetch()} />
          ) : list.isPending ? (
            <LoadingRows />
          ) : list.data?.items.length ? (
            <div className="overflow-hidden rounded-xl shadow-surface bg-card">
              {list.data.items.map((item) => (
                <button
                  type="button"
                  key={item.id}
                  aria-current={selected === item.id ? "true" : undefined}
                  onClick={() => choose(item.id)}
                  className={cn(
                    "flex w-full flex-col gap-2 border-b p-5 text-start last:border-0 hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
                    selected === item.id && "bg-primary/5",
                  )}
                >
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <span className="min-w-0 flex-1 break-words text-sm font-medium">
                      {item.job_title}
                    </span>
                    <Status value={item.status} />
                  </div>
                  <span className="break-all text-xs text-muted-foreground">
                    {item.company} · {new URL(item.job_url).hostname}
                  </span>
                  {item.last_run && (
                    <span className="text-xs text-muted-foreground">
                      Last run:{" "}
                      {runStates[
                        item.last_run.state as keyof typeof runStates
                      ] ?? item.last_run.state}
                      {item.last_run.mode === "submit" ? " · submit mode" : ""}
                    </span>
                  )}
                </button>
              ))}
            </div>
          ) : (
            <EmptyState
              title="No automated applications yet"
              description="Upload a CSV of postings to queue browser runs."
            />
          )}
        </section>
        {selected && (
          <RunDetail
            key={selected}
            id={selected}
            back={() => choose(null)}
          />
        )}
      </div>
    </div>
  );
}

function CsvUpload() {
  const client = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const upload = useMutation({
    mutationFn: async (file: File) => {
      const body = new FormData();
      body.set("file", file);
      return api<{ accepted_count: number; rejected_count: number }>(
        "applications-automation/csv",
        { method: "POST", body },
      );
    },
    onSuccess: (result) => {
      void client.invalidateQueries({ queryKey: ["applications-automation"] });
      toast.success(
        `Imported ${result.accepted_count} application${result.accepted_count === 1 ? "" : "s"}` +
          (result.rejected_count ? ` · ${result.rejected_count} rejected` : ""),
      );
    },
  });
  return (
    <div className="flex items-center gap-2">
      <input
        ref={inputRef}
        type="file"
        accept=".csv,text/csv"
        className="hidden"
        aria-label="Upload applications CSV"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) upload.mutate(file);
          event.target.value = "";
        }}
      />
      <Button
        variant="outline"
        disabled={upload.isPending}
        onClick={() => inputRef.current?.click()}
      >
        <FileUp />
        {upload.isPending ? "Importing…" : "Upload CSV"}
      </Button>
    </div>
  );
}

function RunDetail({ id, back }: { id: string; back: () => void }) {
  const client = useQueryClient();
  const detail = useQuery({
    queryKey: ["applications-automation", id],
    queryFn: () => api<AutomationApplication>(`applications-automation/applications/${id}`),
  });
  const authorize = useMutation({
    mutationFn: () =>
      api(`applications-automation/applications/${id}/authorization`, {
        method: "POST",
        body: {},
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["applications-automation"] });
      toast.success("Submission authorized — review before any submission.");
    },
  });
  const revoke = useMutation({
    mutationFn: () =>
      api(`applications-automation/applications/${id}/authorization`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["applications-automation"] });
      toast.success("Submission authorization revoked.");
    },
  });
  const run = useMutation({
    mutationFn: () =>
      api(`applications-automation/applications/${id}/runs`, {
        method: "POST",
        body: { mode: "fill_only" },
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["applications-automation"] });
      toast.success("Automation run queued.");
    },
  });
  const item = detail.data;
  return (
    <section
      aria-label="Automation run detail"
      className="min-w-0 rounded-xl shadow-surface bg-card p-5 md:p-6"
    >
      <Button variant="ghost" size="sm" className="mb-4 -ms-2" onClick={back}>
        All applications
      </Button>
      {detail.error ? (
        <ErrorState error={detail.error} retry={() => detail.refetch()} />
      ) : !item ? (
        <LoadingRows />
      ) : (
        <>
          <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <h2 tabIndex={-1} className="break-words text-xl font-semibold tracking-tight">
                {item.job_title}
              </h2>
              <p className="mt-1 break-all text-xs text-muted-foreground">
                {item.company} · {new URL(item.job_url).hostname}
              </p>
            </div>
            <Status value={item.status} />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              disabled={run.isPending}
              onClick={() => run.mutate()}
            >
              Queue run
            </Button>
            {item.submit_authorized_at ? (
              <Button variant="outline" disabled={revoke.isPending} onClick={() => revoke.mutate()}>
                Revoke authorization
              </Button>
            ) : (
              <Button variant="outline" disabled={authorize.isPending} onClick={() => authorize.mutate()}>
                <Check />
                Authorize submission
              </Button>
            )}
          </div>
          <p className="mt-3 text-xs leading-5 text-muted-foreground">
            {item.submit_authorized_at
              ? `Submission authorized ${dateLabel(item.submit_authorized_at)}. A run in submit mode may record a submission; everything else ends ready for review.`
              : "Runs end ready for review. Authorizing submission allows a future submit-mode run."}
          </p>
          {item.last_run && (
            <div className="mt-6 rounded-lg border bg-background/50 p-4">
              <p className="text-xs font-medium text-muted-foreground">LAST RUN</p>
              <p className="mt-2 text-sm font-medium">
                {runStates[item.last_run.state as keyof typeof runStates] ?? item.last_run.state}
                {" · "}
                attempt {item.last_run.attempt}
                {item.last_run.mode === "submit" ? " · submit mode" : ""}
              </p>
              {item.last_run.error && (
                <p className="mt-1 break-words text-xs text-muted-foreground">
                  {item.last_run.error}
                </p>
              )}
            </div>
          )}
        </>
      )}
    </section>
  );
}
