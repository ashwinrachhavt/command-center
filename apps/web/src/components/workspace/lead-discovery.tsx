"use client";

import { AnimatedIcon } from "@/components/ui/animated-icon";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, AlertCircle, Check, Search } from "lucide-react";
import { toast } from "sonner";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
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
import { Textarea } from "@/components/ui/textarea";
import { api, type CapturedLead, type PublicSearchResult } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Spinner } from "./primitives";

export function LeadDiscovery({
  open,
  onOpenChange,
  onCaptured,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCaptured: (opportunityId: string) => void;
}) {
  const client = useQueryClient();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<PublicSearchResult[]>([]);
  const [selected, setSelected] = useState<PublicSearchResult>();
  const [roleTitle, setRoleTitle] = useState("");
  const [companyName, setCompanyName] = useState("");
  const [snippet, setSnippet] = useState("");
  const [searchKey, setSearchKey] = useState<string>();
  const [captureKey, setCaptureKey] = useState<string>();

  const search = useMutation({
    mutationFn: ({ key }: { key: string }) =>
      api<PublicSearchResult[]>("research/search", {
        method: "POST",
        key,
        body: { query: query.trim(), limit: 8 },
      }),
    onSuccess: (items) => {
      setResults(items);
      setSelected(undefined);
      setRoleTitle("");
      setCompanyName("");
      setSnippet("");
      setSearchKey(undefined);
    },
  });

  const capture = useMutation({
    mutationFn: ({ key }: { key: string }) =>
      api<CapturedLead>("leads/capture", {
        method: "POST",
        key,
        body: {
          url: selected?.url,
          title: roleTitle.trim(),
          company_name: companyName.trim(),
          snippet: snippet.trim() || undefined,
        },
      }),
    onSuccess: (lead) => {
      setCaptureKey(undefined);
      client.invalidateQueries({ queryKey: ["opportunities"] });
      toast.success(lead.created ? "Lead added to CRM" : "Lead already in CRM");
      onOpenChange(false);
      onCaptured(lead.opportunity_id);
    },
  });

  const runSearch = () => {
    if (!query.trim() || search.isPending) return;
    const key = searchKey ?? crypto.randomUUID();
    setSearchKey(key);
    search.mutate({ key });
  };
  const runCapture = () => {
    if (
      !selected ||
      !roleTitle.trim() ||
      !companyName.trim() ||
      capture.isPending
    )
      return;
    const key = captureKey ?? crypto.randomUUID();
    setCaptureKey(key);
    capture.mutate({ key });
  };
  const reviseCapture = (change: () => void) => {
    change();
    setCaptureKey(undefined);
    capture.reset();
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Discover job leads</DialogTitle>
          <DialogDescription>
            Search public job pages, confirm the role and company, then capture
            the selected lead in your CRM.
          </DialogDescription>
        </DialogHeader>

        <form
          className="flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            runSearch();
          }}
        >
          <Input
            aria-label="Search public job pages"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setSearchKey(undefined);
              search.reset();
            }}
            maxLength={500}
            placeholder="e.g. staff product engineer climate software"
          />
          <Button type="submit" disabled={!query.trim() || search.isPending}>
            <AnimatedIcon state={search.isPending}>
              {search.isPending ? <Spinner /> : <Search />}
            </AnimatedIcon>
            Search
          </Button>
        </form>

        {search.error ? (
          <RequestError
            title="Public search failed"
            error={search.error}
            action="Check the research provider, then retry. Your query is still here."
            onRetry={runSearch}
          />
        ) : results.length ? (
          <div className="space-y-2" aria-label="Public job search results">
            {results.map((result) => {
              const active = selected?.url === result.url;
              return (
                <button
                  type="button"
                  key={result.url}
                  aria-pressed={active}
                  className={cn(
                    "w-full rounded-lg border p-3 text-start transition-colors hover:bg-accent/50",
                    active && "border-primary bg-accent/60",
                  )}
                  onClick={() =>
                    reviseCapture(() => {
                      setSelected(result);
                      setRoleTitle(result.title);
                      setCompanyName("");
                      setSnippet(result.content);
                    })
                  }
                >
                  <span className="flex items-start gap-3">
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-medium">
                        {result.title}
                      </span>
                      <span className="mt-1 block truncate text-xs text-primary">
                        {result.url}
                      </span>
                      <span className="mt-2 line-clamp-2 block text-xs leading-5 text-muted-foreground">
                        {result.content || "No search excerpt was returned."}
                      </span>
                    </span>
                    {active ? (
                      <Check className="mt-0.5 size-4 text-primary" />
                    ) : null}
                  </span>
                </button>
              );
            })}
          </div>
        ) : search.isSuccess ? (
          <p className="rounded-lg border border-dashed p-5 text-center text-sm text-muted-foreground">
            No public job pages matched this search. Try a different role,
            company, or location.
          </p>
        ) : null}

        {selected ? (
          <div className="space-y-4 border-t pt-4">
            <p className="text-sm font-medium">Confirm CRM fields</p>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field>
                <FieldLabel htmlFor="lead-role-title">Role title</FieldLabel>
                <Input
                  id="lead-role-title"
                  value={roleTitle}
                  maxLength={300}
                  onChange={(event) =>
                    reviseCapture(() => setRoleTitle(event.target.value))
                  }
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="lead-company-name">
                  Company name
                </FieldLabel>
                <Input
                  id="lead-company-name"
                  value={companyName}
                  maxLength={200}
                  placeholder="Enter the employer name"
                  onChange={(event) =>
                    reviseCapture(() => setCompanyName(event.target.value))
                  }
                />
              </Field>
            </div>
            <Field>
              <FieldLabel htmlFor="lead-search-excerpt">
                Search excerpt
              </FieldLabel>
              <Textarea
                id="lead-search-excerpt"
                value={snippet}
                maxLength={3000}
                rows={4}
                onChange={(event) =>
                  reviseCapture(() => setSnippet(event.target.value))
                }
              />
              <p className="text-xs text-muted-foreground">
                This excerpt is saved as search evidence. Enrich the lead after
                capture to fetch and version the public source page.
              </p>
            </Field>
          </div>
        ) : null}

        {capture.error ? (
          <RequestError
            title="Lead capture failed"
            error={capture.error}
            action="Review the fields or retry. Your selection and edits are still here."
            onRetry={runCapture}
          />
        ) : null}

        <DialogFooter>
          <Button
            onClick={runCapture}
            disabled={
              !selected ||
              !roleTitle.trim() ||
              !companyName.trim() ||
              capture.isPending
            }
          >
            <AnimatedIcon state={capture.isPending}>
              {capture.isPending ? <Spinner /> : <Plus />}
            </AnimatedIcon>
            Capture to CRM
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RequestError({
  title,
  error,
  action,
  onRetry,
}: {
  title: string;
  error: Error;
  action: string;
  onRetry: () => void;
}) {
  return (
    <Alert variant="destructive">
      <AlertCircle />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>
        <p>{error.message}</p>
        <p className="mt-1">{action}</p>
        <Button variant="outline" className="mt-3" onClick={onRetry}>
          Retry
        </Button>
      </AlertDescription>
    </Alert>
  );
}
