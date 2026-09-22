"use client";

import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useSyncExternalStore,
} from "react";
import { FocusScope } from "@radix-ui/react-focus-scope";
import { usePathname, useSearchParams } from "next/navigation";
import { ArrowLeft, Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  api,
  recordName,
  type Page,
  type Resource,
  type WorkspaceRecord,
} from "@/lib/api";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Input } from "@/components/ui/input";
import { deferView } from "./deferred-view";
import type { RecordDetailProps } from "./record-detail";
import { RecordEditor, resourceNames } from "./record-editor";
import { ErrorState, LoadingRows, Mark } from "./primitives";

const DeferredRecordDetail = deferView<RecordDetailProps>(
  () =>
    import("./record-detail").then((module) => ({
      default: module.RecordDetail,
    })),
  "record detail",
);

export const recordResources = [
  "opportunities",
  "contacts",
  "companies",
  "jobs",
  "tasks",
  "artifacts",
] as const;
export function isResource(value: string): value is Resource {
  return recordResources.some((resource) => resource === value);
}

const Context = createContext<{
  open: (
    resource: Resource,
    id?: string,
    options?: { tab: "content"; versionId: string },
  ) => void;
  close: () => void;
} | null>(null);
export function useWorkspaceContext() {
  return useContext(Context);
}

const overlayQuery = "(max-width: 1279px)";
function subscribeToViewport(callback: () => void) {
  const media = window.matchMedia(overlayQuery);
  media.addEventListener("change", callback);
  return () => media.removeEventListener("change", callback);
}

export function WorkspaceContext({ children }: { children: React.ReactNode }) {
  const overlay = useSyncExternalStore(
    subscribeToViewport,
    () => window.matchMedia(overlayQuery).matches,
    () => false,
  );
  const pathname = usePathname();
  const search = useSearchParams();
  const frames = search
    .getAll("inspect")
    .filter((value) => {
      const [resource, id, tab, versionId, extra] = value.split(":");
      if (
        !isResource(resource) ||
        extra ||
        (id !== undefined && !/^[\w-]+$/.test(id))
      )
        return false;
      if (tab === undefined && versionId === undefined) return true;
      return (
        resource === "artifacts" &&
        !!id &&
        tab === "content" &&
        !!versionId &&
        /^[\w-]+$/.test(versionId)
      );
    })
    .slice(0, 8);
  const frameKey = frames.join(",");
  const pane = useRef<HTMLElement>(null);
  const triggers = useRef<(HTMLElement | null)[]>([]);
  const previousDepth = useRef(0);
  const update = (next: string[]) => {
    const params = new URLSearchParams(search);
    params.delete("inspect");
    next.forEach((frame) => params.append("inspect", frame));
    window.history.pushState(
      null,
      "",
      `${pathname}${params.size ? `?${params}` : ""}`,
    );
  };
  const open = (
    resource: Resource,
    id?: string,
    options?: { tab: "content"; versionId: string },
  ) => {
    const frame = id
      ? `${resource}:${id}${options ? `:${options.tab}:${options.versionId}` : ""}`
      : resource;
    if (frames.at(-1) === frame) return;
    triggers.current[frames.length] = document.activeElement as HTMLElement;
    update([...frames.slice(0, 7), frame]);
  };
  useEffect(() => {
    const trigger = triggers.current[frames.length];
    if (previousDepth.current > frames.length && trigger?.isConnected)
      trigger.focus();
    else if (frames.length) pane.current?.focus();
    previousDepth.current = frames.length;
  }, [frameKey, frames.length]);
  const close = () => {
    if (frames.length) update([]);
  };
  const back = () => update(frames.slice(0, -1));
  return (
    <Context.Provider value={{ open, close }}>
      <div
        className="relative flex min-h-0 min-w-0 flex-1"
        onKeyDown={(event) => {
          if (
            event.key === "Escape" &&
            frames.length &&
            !event.defaultPrevented &&
            (!(event.target as HTMLElement).closest(
              '[role="dialog"], [role="menu"], [role="listbox"]',
            ) ||
              (event.target as HTMLElement).closest('[role="dialog"]') ===
                pane.current)
          ) {
            event.preventDefault();
            back();
          }
        }}
      >
        <div className="min-w-0 flex-1" inert={overlay && frames.length > 0}>
          {children}
        </div>
        {frames.length > 0 && (
          <FocusScope
            asChild
            loop={overlay}
            trapped={overlay}
            onUnmountAutoFocus={(event) => event.preventDefault()}
          >
            <aside
              ref={pane}
              tabIndex={-1}
              aria-label="Related workspace"
              role={overlay ? "dialog" : undefined}
              aria-modal={overlay || undefined}
              className="fixed top-14 right-0 bottom-0 z-30 flex w-full flex-col border-l border-border bg-background shadow-xl outline-none sm:w-[380px] xl:sticky xl:top-14 xl:z-10 xl:h-[calc(100dvh-3.5rem)] xl:w-[360px] xl:shrink-0 xl:shadow-none"
            >
              <div className="flex h-12 shrink-0 items-center gap-2 border-b border-border px-3">
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Back to previous context"
                  onClick={back}
                >
                  <ArrowLeft />
                </Button>
                <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
                  Alongside {pathname.slice(1) || "overview"}
                </span>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Close related workspace"
                  onClick={close}
                >
                  <X />
                </Button>
              </div>
              {frames.map((frame, index) => {
                const [resource, id, tab, versionId] = frame.split(":") as [
                  Resource,
                  string | undefined,
                  string | undefined,
                  string | undefined,
                ];
                return (
                  <div
                    key={`${index}:${frame}`}
                    hidden={index !== frames.length - 1}
                    className="min-h-0 flex-1 overflow-y-auto"
                  >
                    {id ? (
                      <DeferredRecordDetail
                        resource={resource}
                        id={id}
                        onClose={back}
                        compact
                        initialTab={tab === "content" ? "content" : undefined}
                        pinnedVersionId={versionId}
                      />
                    ) : (
                      <RecordDirectory resource={resource} />
                    )}
                  </div>
                );
              })}
            </aside>
          </FocusScope>
        )}
      </div>
    </Context.Provider>
  );
}

function RecordDirectory({ resource }: { resource: Resource }) {
  const context = useWorkspaceContext();
  const [creating, setCreating] = useState(false);
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const params = new URLSearchParams({
    q,
    offset: String(offset),
    limit: "20",
  });
  const query = useQuery({
    queryKey: [resource, params.toString()],
    queryFn: ({ signal }) =>
      api<Page<WorkspaceRecord>>(`${resource}?${params}`, { signal }),
  });
  const name = resourceNames[resource].plural;
  return (
    <section className="p-5" aria-label={`${name} directory`}>
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2 className="text-base font-medium">{name}</h2>
        <Button
          variant="outline"
          size="icon-sm"
          aria-label={`New ${resourceNames[resource].singular}`}
          onClick={() => setCreating(true)}
        >
          <Plus />
        </Button>
      </div>
      <Input
        aria-label={`Find ${name.toLowerCase()}`}
        placeholder={`Find ${name.toLowerCase()}…`}
        value={q}
        onChange={(event) => {
          setQ(event.target.value);
          setOffset(0);
        }}
      />
      {query.isPending ? (
        <LoadingRows />
      ) : query.error ? (
        <ErrorState error={query.error} retry={() => query.refetch()} />
      ) : (
        <>
          <div className="mt-3 divide-y divide-border">
            {query.data.items.map((record) => (
              <Button
                variant="ghost"
                key={record.id}
                className="h-auto w-full justify-start gap-3 rounded-none px-0 py-4 text-left"
                onClick={() => context?.open(resource, record.id)}
              >
                <Mark name={recordName(record)} />
                <span className="min-w-0 truncate">{recordName(record)}</span>
              </Button>
            ))}
          </div>
          {!query.data.items.length && (
            <p className="py-8 text-sm text-muted-foreground">
              {q
                ? "No matching records. Try another search."
                : `No ${name.toLowerCase()} yet.`}
            </p>
          )}
          <div className="mt-4 flex items-center justify-between gap-2 text-xs text-muted-foreground">
            <span>{query.data.total} records</span>
            <Button
              size="sm"
              variant="ghost"
              disabled={!offset}
              onClick={() => setOffset(Math.max(0, offset - 20))}
            >
              Previous
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={offset + 20 >= query.data.total}
              onClick={() => setOffset(offset + 20)}
            >
              Next
            </Button>
          </div>
        </>
      )}
      {creating && (
        <RecordEditor
          resource={resource}
          open
          onOpenChange={setCreating}
          onSaved={(record) => context?.open(resource, record.id)}
        />
      )}
    </section>
  );
}
