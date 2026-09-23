"use client";
import { useState } from "react";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDownUp,
  ArrowUpRight,
  ChevronLeft,
  ChevronRight,
  CircleCheck,
  Filter,
  Plus,
  Search,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { RetainedRequestIntent } from "@/lib/retained-intent";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  api,
  dateLabel,
  label,
  recordName,
  type Page,
  type Resource,
  type Resources,
  type WorkspaceRecord,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  EmptyState,
  ErrorState,
  LoadingRows,
  Mark,
  PageHeading,
  Priority,
  Status,
} from "./primitives";
import { RecordEditor, resourceNames, stages } from "./record-editor";
import { deferView } from "./deferred-view";
import type { RecordDetailProps } from "./record-detail";
import { LeadDiscovery } from "./lead-discovery";
import { DocumentIntake } from "./document-intake";
import { RecordWorkButton } from "./record-agent-work";
import {
  ContactOutreach,
  defaultOutreachBrief,
  outreachActive,
} from "./contact-outreach";
import { useWorkspaceContext } from "./context";
import { ContactBatchEnrich } from "./contact-batch-enrich";
import type { ContactDiscoveryProps } from "./contact-discovery";
const DeferredContactDiscovery = deferView<ContactDiscoveryProps>(
  () =>
    import("./contact-discovery").then((module) => ({
      default: module.ContactDiscovery,
    })),
  "contact discovery",
);

const DeferredRecordDetail = deferView<RecordDetailProps>(
  () =>
    import("./record-detail").then((module) => ({
      default: module.RecordDetail,
    })),
  "record detail",
);

function field(record: WorkspaceRecord, key: string): string {
  const value = (record as unknown as Record<string, unknown>)[key];
  return value === null || value === undefined ? "" : String(value);
}

export function Records({ resource }: { resource: Resource }) {
  const search = useSearchParams();
  const context = useWorkspaceContext();
  const selected = search.get("record");
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState("all");
  const [offset, setOffset] = useState(0);
  const [ascending, setAscending] = useState(false);
  const [creating, setCreating] = useState(false);
  const [discovering, setDiscovering] = useState(false);
  const [outreachBrief, setOutreachBrief] = useState(defaultOutreachBrief);
  const limit = 20;
  const params = new URLSearchParams({
    q,
    limit: String(limit),
    offset: String(offset),
  });
  if (filter !== "all")
    params.set(resource === "opportunities" ? "stage" : "state", filter);
  const query = useQuery({
    queryKey: [resource, params.toString()],
    queryFn: ({ signal }) =>
      api<Page<WorkspaceRecord>>(`${resource}?${params}`, { signal }),
    refetchInterval: (query) =>
      resource === "contacts" &&
      query.state.data?.items.some((row) =>
        outreachActive((row as Resources["contacts"]).outreach?.state),
      )
        ? 2500
        : false,
  });
  const companyIds = [
    ...new Set(
      (query.data?.items ?? [])
        .map((record) => field(record, "company_id"))
        .filter(Boolean),
    ),
  ].sort();
  const companies = useQuery({
    queryKey: ["company-labels", companyIds],
    enabled: companyIds.length > 0,
    queryFn: ({ signal }) => {
      const lookup = new URLSearchParams(companyIds.map((id) => ["ids", id]));
      return api<Pick<Resources["companies"], "id" | "name">[]>(
        `company-labels?${lookup}`,
        { signal },
      );
    },
  });
  const client = useQueryClient();
  const [completeIntent] = useState(() => new RetainedRequestIntent());
  const complete = useMutation({
    mutationFn: (r: WorkspaceRecord) => {
      const target = `tasks/${r.id}`;
      const body = {
        expected_version: r.row_version,
        state: field(r, "state") === "done" ? "open" : "done",
      };
      const intent = completeIntent.forRequest("PATCH", target, body);
      return api(target, {
        method: "PATCH",
        body,
        key: intent.key,
      });
    },
    onSuccess: (_result, r) => {
      completeIntent.confirmRequest("PATCH", `tasks/${r.id}`, {
        expected_version: r.row_version,
        state: field(r, "state") === "done" ? "open" : "done",
      });
      client.invalidateQueries();
      toast.success("Task updated");
    },
    onError: (e) => toast.error(e.message),
  });
  const rows = ascending
    ? [...(query.data?.items ?? [])].sort((a, b) =>
        recordName(a).localeCompare(recordName(b)),
      )
    : (query.data?.items ?? []);
  const name = resourceNames[resource];
  const select = (id: string | null) => {
    const params = new URLSearchParams(search);
    params.delete("inspect");
    if (id) params.set("record", id);
    else params.delete("record");
    window.history.pushState(
      null,
      "",
      `/${resource}${params.size ? `?${params}` : ""}`,
    );
  };
  return (
    <div
      className={cn(
        "min-w-0",
        selected &&
          "md:grid md:h-[calc(100dvh-3.5rem)] md:grid-cols-[260px_minmax(0,1fr)]",
      )}
    >
      <div
        className={cn(
          "min-w-0",
          selected &&
            "hidden md:block md:overflow-y-auto md:border-r md:border-border",
        )}
      >
        <PageHeading
          title={name.plural}
          description={selected ? undefined : name.description}
          action={
            <div className="flex items-center gap-2">
              {resource === "opportunities" || resource === "contacts" ? (
                <Button
                  size={selected ? "icon-sm" : "default"}
                  variant="outline"
                  aria-label={
                    resource === "contacts"
                      ? "Discover contacts"
                      : "Discover leads"
                  }
                  onClick={() => setDiscovering(true)}
                >
                  <Search data-icon="inline-start" />
                  {!selected
                    ? resource === "contacts"
                      ? "Discover contacts"
                      : "Discover leads"
                    : null}
                </Button>
              ) : null}
              <Button
                size={selected ? "icon-sm" : "default"}
                aria-label={`New ${name.singular}`}
                onClick={() => setCreating(true)}
              >
                <Plus data-icon="inline-start" />
                {!selected && <>New {name.singular}</>}
              </Button>
            </div>
          }
        />
        {resource === "artifacts" && !selected ? <DocumentIntake /> : null}
        <div className="border-y border-border">
          <div
            className={cn(
              "flex flex-wrap items-center gap-3 px-5 py-3",
              !selected && "md:px-9",
            )}
          >
            <div className="relative w-full max-w-64">
              <Search className="absolute top-2.5 left-2.5 size-3.5 text-muted-foreground" />
              <Input
                value={q}
                onChange={(e) => {
                  setQ(e.target.value);
                  setOffset(0);
                }}
                aria-label={`Search ${name.plural.toLowerCase()}`}
                placeholder={`Search ${name.plural.toLowerCase()}…`}
                className="h-8 border-border bg-card pl-8 text-xs"
              />
            </div>
            {["opportunities", "tasks"].includes(resource) && (
              <Select
                value={filter}
                onValueChange={(v) => {
                  setFilter(v);
                  setOffset(0);
                }}
              >
                <SelectTrigger
                  className="h-8 min-w-36 text-xs"
                  aria-label="Filter by status"
                >
                  <Filter className="size-3" />
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectItem value="all">
                      All {resource === "tasks" ? "statuses" : "stages"}
                    </SelectItem>
                    {(resource === "tasks"
                      ? ["open", "in_progress", "snoozed", "done", "cancelled"]
                      : stages
                    ).map((v) => (
                      <SelectItem value={v} key={v}>
                        {label(v)}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            )}
            <Button
              variant="ghost"
              size="sm"
              className="ml-auto text-muted-foreground"
              onClick={() => setAscending(!ascending)}
              aria-pressed={ascending}
            >
              <ArrowDownUp data-icon="inline-start" />
              {ascending ? "Name A–Z (page)" : "Newest first"}
            </Button>
          </div>
          {resource === "contacts" && !selected && (
            <div className="flex flex-wrap items-start gap-3 border-t border-border px-5 py-3 md:px-9">
              <details className="min-w-0 flex-1">
                <summary className="cursor-pointer text-xs font-medium">
                  LinkedIn connection notes{" "}
                  <span className="ml-2 font-normal text-muted-foreground">
                    200 characters · Work opportunities · Customize brief
                  </span>
                </summary>
                <label className="mt-3 block max-w-2xl space-y-2 text-xs text-muted-foreground">
                  <span>
                    Your goal and writing style. Add a sample of your voice if
                    you like.
                  </span>
                  <Textarea
                    aria-label="Outreach brief"
                    value={outreachBrief}
                    maxLength={3000}
                    rows={3}
                    onChange={(event) => setOutreachBrief(event.target.value)}
                  />
                  <span className="block">
                    Quick notes use saved context and at most one targeted
                    lookup. Enrich contact runs deeper research when you need
                    it.
                  </span>
                </label>
              </details>
              <ContactBatchEnrich
                key={params.toString()}
                contacts={rows as Resources["contacts"][]}
                instructions={outreachBrief}
              />
            </div>
          )}
          {query.isPending ? (
            <LoadingRows />
          ) : query.error ? (
            <div className="px-6">
              <ErrorState error={query.error} retry={() => query.refetch()} />
            </div>
          ) : rows.length === 0 ? (
            <EmptyState
              title={
                q || filter !== "all"
                  ? "No matching records"
                  : `No ${name.plural.toLowerCase()} yet`
              }
              description={
                q || filter !== "all"
                  ? "Try a different search or clear your filters."
                  : `Create a ${name.singular} to get started.`
              }
            >
              {q || filter !== "all" ? (
                <Button
                  variant="outline"
                  onClick={() => {
                    setQ("");
                    setFilter("all");
                  }}
                >
                  Clear filters
                </Button>
              ) : (
                <Button
                  size={selected ? "icon-sm" : "default"}
                  aria-label={`New ${name.singular}`}
                  onClick={() => setCreating(true)}
                >
                  <Plus />
                  Add {name.singular}
                </Button>
              )}
            </EmptyState>
          ) : (
            <Table
              className={cn(
                resource === "contacts" &&
                  "max-md:block max-md:[&_thead]:sr-only max-md:[&_tbody]:block max-md:[&_tr]:flex max-md:[&_tr]:h-auto max-md:[&_tr]:flex-wrap max-md:[&_tr]:px-3 max-md:[&_td:nth-child(1)]:hidden max-md:[&_td:nth-child(2)]:order-1 max-md:[&_td:nth-child(2)]:w-[calc(100%-2rem)] max-md:[&_td:nth-child(3)]:hidden max-md:[&_td:nth-child(4)]:hidden max-md:[&_td:nth-child(5)]:order-3 max-md:[&_td:nth-child(5)]:w-full max-md:[&_td:nth-child(6)]:order-2 max-md:[&_td:nth-child(6)]:w-8 max-md:[&_td:nth-child(6)]:p-0",
                selected &&
                  "[&_th:not(:nth-child(2))]:hidden [&_td:not(:nth-child(2))]:hidden [&_td]:max-w-[256px] [&_td]:px-4",
              )}
            >
              <TableHeader>
                <TableRow className="bg-card/50 hover:bg-card/50">
                  <TableHead className="w-12 pl-5 md:pl-9">
                    <span className="text-[10px] text-muted-foreground">#</span>
                  </TableHead>
                  <TableHead>
                    {resource === "companies" || resource === "contacts"
                      ? "Name"
                      : "Title"}
                  </TableHead>
                  <TableHead>
                    {resource === "companies"
                      ? "Industry"
                      : resource === "artifacts"
                        ? "Kind"
                        : resource === "tasks"
                          ? "Status"
                          : "Company"}
                  </TableHead>
                  <TableHead>
                    {resource === "companies" || resource === "jobs"
                      ? "Location"
                      : resource === "contacts"
                        ? "Relationship"
                        : resource === "tasks"
                          ? "Due date"
                          : resource === "artifacts"
                            ? "Version"
                            : "Stage"}
                  </TableHead>
                  <TableHead>
                    {["tasks", "opportunities"].includes(resource)
                      ? "Priority"
                      : resource === "contacts"
                        ? "LinkedIn outreach"
                        : resource === "companies"
                          ? "Research"
                          : "Updated"}
                  </TableHead>
                  <TableHead className="w-10">
                    <span className="sr-only">Open details</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row, index) => (
                  <TableRow
                    key={row.id}
                    className={cn(
                      "group h-16",
                      selected === row.id && "bg-accent/60",
                    )}
                  >
                    <TableCell className="pl-5 text-xs text-muted-foreground md:pl-9">
                      {resource === "tasks" ? (
                        <Button
                          variant="ghost"
                          size="icon-xs"
                          disabled={
                            complete.isPending ||
                            field(row, "state") === "cancelled"
                          }
                          aria-label={`${field(row, "state") === "done" ? "Reopen" : "Complete"} ${recordName(row)}`}
                          onClick={() => complete.mutate(row)}
                        >
                          <CircleCheck
                            className={
                              field(row, "state") === "done"
                                ? "text-primary"
                                : "text-muted-foreground"
                            }
                          />
                        </Button>
                      ) : (
                        String(index + offset + 1).padStart(2, "0")
                      )}
                    </TableCell>
                    <TableCell>
                      <button
                        className="flex w-full max-w-96 items-center gap-3 text-left"
                        onClick={() => select(row.id)}
                      >
                        <Mark name={recordName(row)} />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[13px] font-medium group-hover:text-primary">
                            {recordName(row)}
                          </span>
                          <span className="mt-1 block truncate text-xs text-muted-foreground">
                            {field(
                              row,
                              resource === "companies"
                                ? "domain"
                                : resource === "contacts"
                                  ? "title"
                                  : resource === "artifacts"
                                    ? "sensitivity"
                                    : resource === "jobs"
                                      ? "work_mode"
                                      : resource === "tasks"
                                        ? "rationale"
                                        : "notes",
                            ) || `Added ${dateLabel(row.created_at)}`}
                          </span>
                        </span>
                      </button>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {resource === "companies" ? (
                        field(row, "industry") || "—"
                      ) : resource === "artifacts" ? (
                        label(field(row, "kind"))
                      ) : resource === "tasks" ? (
                        <Status value={field(row, "state")} />
                      ) : (
                        (companies.data?.find(
                          (c) => c.id === field(row, "company_id"),
                        )?.name ??
                        (field(row, "company_id") ? "Linked company" : "—"))
                      )}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {resource === "companies" || resource === "jobs" ? (
                        field(row, "location") || "—"
                      ) : resource === "contacts" ||
                        resource === "opportunities" ? (
                        <Status
                          value={field(
                            row,
                            resource === "contacts" ? "relationship" : "stage",
                          )}
                        />
                      ) : resource === "tasks" ? (
                        dateLabel(
                          field(row, "due_date") || field(row, "due_at"),
                        )
                      ) : (
                        <span className="rounded border border-border px-1.5 py-0.5 font-mono text-[10px]">
                          v{field(row, "latest_version")}
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {["tasks", "opportunities"].includes(resource) ? (
                        <Priority value={Number(field(row, "priority"))} />
                      ) : resource === "contacts" ? (
                        <ContactOutreach
                          contact={row as Resources["contacts"]}
                          instructions={outreachBrief}
                        />
                      ) : resource === "companies" ? (
                        (row as Resources["companies"]).latest_research ? (
                          <button
                            className="max-w-64 text-left hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                            onClick={() => context?.open("companies", row.id)}
                          >
                            <span className="line-clamp-2 leading-5">
                              {
                                (row as Resources["companies"]).latest_research
                                  ?.summary
                              }
                            </span>
                            <span className="mt-1 block text-[10px]">
                              Brief ·{" "}
                              {dateLabel(
                                (row as Resources["companies"]).latest_research
                                  ?.created_at,
                              )}
                            </span>
                          </button>
                        ) : (
                          <RecordWorkButton
                            resource="companies"
                            id={row.id}
                            compact
                            onStarted={() => context?.open("companies", row.id)}
                          />
                        )
                      ) : (
                        dateLabel(row.updated_at)
                      )}
                    </TableCell>
                    <TableCell className="pr-5">
                      <Button
                        size="icon-xs"
                        variant="ghost"
                        onClick={() => select(row.id)}
                        aria-label={`Open ${recordName(row)}`}
                      >
                        <ArrowUpRight />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </div>
        <div className="flex items-center justify-between px-5 py-4 text-xs text-muted-foreground md:px-9">
          <span>
            {query.data?.total ?? 0} {name.plural.toLowerCase()}
            {query.data && query.data.total > limit
              ? ` · Showing ${offset + 1}–${Math.min(offset + limit, query.data.total)}`
              : ""}
          </span>
          <div className="flex gap-1">
            <Button
              size="icon-sm"
              variant="ghost"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - limit))}
              aria-label="Previous page"
            >
              <ChevronLeft />
            </Button>
            <Button
              size="icon-sm"
              variant="ghost"
              disabled={offset + limit >= (query.data?.total ?? 0)}
              onClick={() => setOffset(offset + limit)}
              aria-label="Next page"
            >
              <ChevronRight />
            </Button>
          </div>
        </div>
      </div>
      {selected && (
        <div className="min-w-0 overflow-y-auto">
          <DeferredRecordDetail
            key={`${resource}:${selected}`}
            resource={resource}
            id={selected}
            onClose={() => select(null)}
            initialTab={
              resource === "tasks" && search.get("tab") === "conversation"
                ? "conversation"
                : undefined
            }
          />
        </div>
      )}
      {creating && (
        <RecordEditor
          resource={resource}
          open={creating}
          onOpenChange={setCreating}
          onSaved={(r) => select(r.id)}
        />
      )}
      {resource === "contacts" && discovering && (
        <DeferredContactDiscovery
          open
          onOpenChange={setDiscovering}
          onImported={select}
        />
      )}
      {resource === "opportunities" && discovering ? (
        <LeadDiscovery
          open={discovering}
          onOpenChange={setDiscovering}
          onCaptured={select}
        />
      ) : null}
    </div>
  );
}
