"use client";

import { AnimatedIcon } from "@/components/ui/animated-icon";
import { useRef, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, Search, UserPlus, Check } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { api, dateLabel, type Resources, type Schema } from "@/lib/api";
import { ErrorState, LoadingRows, Spinner } from "./primitives";

type Snapshot = Schema["DiscoveryRead"];
type Prospect = Schema["Prospect"];
type Provider = {
  id: "apollo" | "hunter";
  name: string;
  configured: boolean;
  setup_variable: string;
  documentation_url: string;
  description: string;
};
const selectStyle =
  "h-9 w-full rounded-lg border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

function missingFields(contact: Resources["contacts"], person: Prospect) {
  return (["email", "title", "linkedin_url"] as const).filter(
    (field) => !contact[field] && !!person[field],
  );
}

function useProviders() {
  return useQuery({
    queryKey: ["contact-discovery-providers"],
    queryFn: () => api<Provider[]>("contact-discovery/providers"),
  });
}

// Keep an unresolved paid request's key across dialog closure and reload in this tab.
function useDiscoveryRequests() {
  const { userId } = useAuth();
  const inMemory = useRef(new Map<string, string>());
  return async <T,>(
    route: string,
    body: unknown,
    fresh = false,
  ): Promise<T> => {
    if (!userId) throw new Error("Sign in before discovering contacts");
    const signature = JSON.stringify({ route, body });
    const storageKey = `cc:discovery-intent:${userId}:${signature}`;
    let key = fresh ? undefined : inMemory.current.get(storageKey);
    try {
      if (!fresh) key ??= sessionStorage.getItem(storageKey) ?? undefined;
    } catch {
      /* memory survives until reload */
    }
    key ??= crypto.randomUUID();
    inMemory.current.set(storageKey, key);
    try {
      sessionStorage.setItem(storageKey, key);
    } catch {
      /* session storage can be unavailable */
    }
    const result = await api<T>(`contact-discovery/${route}`, {
      method: "POST",
      body,
      key,
    });
    inMemory.current.delete(storageKey);
    try {
      sessionStorage.removeItem(storageKey);
    } catch {
      /* optional browser storage */
    }
    return result;
  };
}

export type ContactDiscoveryProps = {
  open: boolean;
  onOpenChange: (value: boolean) => void;
  company?: Resources["companies"];
  onImported?: (id: string) => void;
  initialProvider?: "apollo" | "hunter";
};
export function ContactDiscovery({
  open,
  onOpenChange,
  company,
  onImported,
  initialProvider = "apollo",
}: ContactDiscoveryProps) {
  const providers = useProviders();
  const request = useDiscoveryRequests();
  const router = useRouter();
  const client = useQueryClient();
  const [provider, setProvider] = useState<"apollo" | "hunter">(
    initialProvider,
  );
  const [domain, setDomain] = useState(company?.domain ?? "");
  const [title, setTitle] = useState("");
  const [snapshot, setSnapshot] = useState<Snapshot>();
  const [revealed, setRevealed] = useState<Record<string, Snapshot>>({});
  const [imported, setImported] = useState<
    Record<string, Resources["contacts"]>
  >({});
  const [freshRequest, setFreshRequest] = useState(false);
  const recent = useQuery({
    queryKey: ["contact-discovery-recent"],
    queryFn: () => api<Snapshot[]>("contact-discovery/recent"),
    enabled: open,
  });
  const search = useMutation({
    mutationFn: ({
      body,
      fresh,
    }: {
      body: {
        provider: "apollo" | "hunter";
        domain: string;
        title: string;
        page: number;
      };
      fresh?: boolean;
    }) => request<Snapshot>("search", body, fresh),
    onSuccess: (data) => {
      setSnapshot(data);
      setRevealed({});
      void client.invalidateQueries({ queryKey: ["contact-discovery-recent"] });
    },
  });
  const reveal = useMutation({
    mutationFn: ({
      body,
      fresh,
    }: {
      body: { source_version_id: string; external_id: string };
      fresh?: boolean;
    }) => request<Snapshot>("reveal", body, fresh),
    onSuccess: (data, variables) => {
      if (data.result.items.length)
        setRevealed((current) => ({
          ...current,
          [variables.body.external_id]: data,
        }));
      else
        toast.info(
          "Apollo did not find a complete profile. No contact was added.",
        );
      void client.invalidateQueries({ queryKey: ["contact-discovery-recent"] });
    },
  });
  const add = useMutation({
    mutationFn: ({ source, person }: { source: Snapshot; person: Prospect }) =>
      request<Schema["ImportRead"]>("import", {
        source_version_id: source.source_version_id,
        external_id: person.external_id,
        company_id: company?.id ?? null,
      }),
    onSuccess: (data, { person }) => {
      setImported((current) => ({
        ...current,
        [`${person.provider}:${person.external_id}`]: data.contact,
      }));
      void client.invalidateQueries({ queryKey: ["contacts"] });
      toast.success(
        data.created
          ? "Contact added"
          : "Existing contact found; your details were kept",
      );
    },
  });
  const fill = useMutation({
    mutationFn: ({
      source,
      person,
      contact,
    }: {
      source: Snapshot;
      person: Prospect;
      contact: Resources["contacts"];
    }) =>
      request<Resources["contacts"]>("fill-missing", {
        source_version_id: source.source_version_id,
        external_id: person.external_id,
        contact_id: contact.id,
        expected_version: contact.row_version,
        fields: missingFields(contact, person),
      }),
    onSuccess: (contact, { person }) => {
      setImported((current) => ({
        ...current,
        [`${person.provider}:${person.external_id}`]: contact,
      }));
      void client.invalidateQueries({ queryKey: ["contacts"] });
      toast.success("Missing contact details filled");
    },
  });
  const selectedProvider = providers.data?.find((item) => item.id === provider);
  const busy =
    search.isPending || reveal.isPending || add.isPending || fill.isPending;
  const searchBody = (page = 1) => ({
    provider,
    domain: domain.trim(),
    title: provider === "apollo" ? title.trim() : "",
    page,
  });
  const currentError = search.error ?? reveal.error ?? add.error ?? fill.error;
  const openContact = (id: string) => {
    onOpenChange(false);
    if (onImported) onImported(id);
    else router.push(`/contacts?record=${encodeURIComponent(id)}`);
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92dvh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>
            Discover contacts{company ? ` at ${company.name}` : ""}
          </DialogTitle>
          <DialogDescription>
            Find people, inspect the source, then add the contacts you want to
            work with.
          </DialogDescription>
        </DialogHeader>
        {providers.error && (
          <ErrorState
            error={providers.error}
            retry={() => void providers.refetch()}
          />
        )}
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            reveal.reset();
            add.reset();
            search.mutate({ body: searchBody() });
          }}
        >
          <fieldset disabled={busy} className="grid gap-3 sm:grid-cols-2">
            <label className="space-y-1 text-sm">
              Provider
              <select
                aria-label="Discovery provider"
                className={selectStyle}
                value={provider}
                onChange={(event) =>
                  setProvider(event.target.value as "apollo" | "hunter")
                }
              >
                <option value="apollo">Apollo</option>
                <option value="hunter">Hunter</option>
              </select>
            </label>
            <label className="space-y-1 text-sm">
              Company domain
              <Input
                aria-label="Company domain"
                placeholder="example.com"
                autoComplete="off"
                required
                maxLength={2000}
                value={domain}
                onChange={(event) => setDomain(event.target.value)}
              />
            </label>
            {provider === "apollo" && (
              <label className="space-y-1 text-sm sm:col-span-2">
                Job title{" "}
                <span className="text-muted-foreground">(optional)</span>
                <Input
                  aria-label="Job title filter"
                  placeholder="Engineering manager"
                  maxLength={200}
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                />
              </label>
            )}
          </fieldset>
          <p className="text-xs leading-5 text-muted-foreground">
            {selectedProvider?.description} Results are saved privately.
            Matching searches reuse results for one hour.
          </p>
          {selectedProvider && !selectedProvider.configured ? (
            <p className="rounded-lg border border-dashed p-3 text-sm">
              {selectedProvider.name} needs setup.{" "}
              <Link
                href="/connections"
                className="underline underline-offset-4"
              >
                Open Connected apps
              </Link>{" "}
              to configure it.
            </p>
          ) : (
            <Button
              type="submit"
              disabled={busy || !selectedProvider?.configured || !domain.trim()}
            >
              <AnimatedIcon state={search.isPending}>
                {search.isPending ? <Spinner /> : <Search />}
              </AnimatedIcon>
              Search {provider === "apollo" ? "Apollo" : "Hunter"}
            </Button>
          )}
        </form>
        {recent.data && recent.data.length > 0 && (
          <label className="space-y-1 text-xs text-muted-foreground">
            Revisit saved discovery
            <select
              aria-label="Saved discovery"
              className={selectStyle}
              value={snapshot?.source_version_id ?? ""}
              disabled={busy}
              onChange={(event) => {
                const saved = recent.data.find(
                  (item) => item.source_version_id === event.target.value,
                );
                if (saved) {
                  setSnapshot(saved);
                  setRevealed({});
                }
              }}
            >
              <option value="">Choose a saved result</option>
              {recent.data.map((item) => (
                <option
                  key={item.source_version_id}
                  value={item.source_version_id}
                >
                  {String(item.query.provider)} · {String(item.query.domain)} ·{" "}
                  {String(item.query.operation)} · {dateLabel(item.observed_at)}
                </option>
              ))}
            </select>
          </label>
        )}
        {currentError && (
          <div
            role="alert"
            className="space-y-2 rounded-lg border border-destructive/40 p-3 text-sm"
          >
            <p>{currentError.message}</p>
            {(search.error || reveal.error) && (
              <>
                <p className="text-xs text-muted-foreground">
                  Retrying keeps the same request. A new provider request may
                  consume additional credits if the previous outcome is unknown.
                </p>
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={busy}
                    onClick={() => {
                      if (search.error && search.variables)
                        search.mutate({ ...search.variables, fresh: false });
                      else if (reveal.variables)
                        reveal.mutate({ ...reveal.variables, fresh: false });
                    }}
                  >
                    Retry same request
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    onClick={() => setFreshRequest(true)}
                  >
                    Start a new request…
                  </Button>
                </div>
              </>
            )}
          </div>
        )}
        {freshRequest && (
          <div role="alert" className="space-y-3 rounded-lg border p-4">
            <p className="text-sm">
              Check usage in your provider account first. Continue only if you
              want a separate request, which may use credits.
            </p>
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => setFreshRequest(false)}>
                Cancel
              </Button>
              <Button
                onClick={() => {
                  setFreshRequest(false);
                  if (search.error && search.variables)
                    search.mutate({ ...search.variables, fresh: true });
                  else if (reveal.variables)
                    reveal.mutate({ ...reveal.variables, fresh: true });
                }}
              >
                Make new provider request
              </Button>
            </div>
          </div>
        )}
        {providers.isPending && <LoadingRows />}
        {snapshot && (
          <section aria-label="Discovery results" className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
              <span>
                {snapshot.result.total.toLocaleString()} provider results ·{" "}
                {String(snapshot.query.provider)} ·{" "}
                {dateLabel(snapshot.observed_at)}
              </span>
              {snapshot.cached && (
                <Badge variant="secondary">Saved result reused</Badge>
              )}
            </div>
            {snapshot.result.items.length === 0 && (
              <div className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
                No people found for this request. Try another company domain or
                a broader title.
              </div>
            )}
            {snapshot.result.items.map((preview) => {
              const source = revealed[preview.external_id] ?? snapshot;
              const person =
                revealed[preview.external_id]?.result.items[0] ?? preview;
              const importedId =
                imported[`${person.provider}:${person.external_id}`];
              return (
                <article
                  key={person.external_id}
                  className="flex flex-wrap items-start justify-between gap-4 rounded-xl shadow-surface bg-card p-4"
                >
                  <div className="min-w-0 flex-1 space-y-1">
                    <h3 className="break-words text-sm font-medium">
                      {person.name}
                    </h3>
                    <p className="break-words text-sm text-muted-foreground">
                      {[person.title, person.company_name]
                        .filter(Boolean)
                        .join(" · ") || "Role not provided"}
                    </p>
                    {person.email && (
                      <p className="break-all text-sm">{person.email}</p>
                    )}
                    <p className="text-xs text-muted-foreground">
                      {!person.name_complete
                        ? "Partial profile · reveal to see available contact details"
                        : `Email status reported by ${person.provider}: ${person.email_status.replaceAll("_", " ")}`}
                    </p>
                    {(person.sources?.length ?? 0) > 0 && (
                      <div className="flex flex-wrap gap-3 pt-1">
                        {(person.sources ?? [])
                          .slice(0, 3)
                          .map((url, index) => (
                            <a
                              key={url}
                              href={url}
                              target="_blank"
                              rel="noreferrer"
                              className="inline-flex items-center gap-1 text-xs underline underline-offset-4"
                            >
                              Source {index + 1}
                              <ArrowUpRight className="size-3" />
                            </a>
                          ))}
                      </div>
                    )}
                  </div>
                  <div className="shrink-0 space-y-2">
                    {importedId &&
                      missingFields(importedId, person).length > 0 && (
                        <div className="max-w-52 space-y-1">
                          <Button
                            size="sm"
                            disabled={busy}
                            onClick={() =>
                              fill.mutate({
                                source,
                                person,
                                contact: importedId,
                              })
                            }
                          >
                            <AnimatedIcon state={fill.isPending}>
                              {fill.isPending ? <Spinner /> : <UserPlus />}
                            </AnimatedIcon>
                            Fill missing details
                          </Button>
                          <p className="text-xs text-muted-foreground">
                            Add{" "}
                            {missingFields(importedId, person)
                              .map((field) => field.replaceAll("_", " "))
                              .join(", ")}{" "}
                            from this result. Current values stay unchanged.
                          </p>
                        </div>
                      )}
                    {importedId ? (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => openContact(importedId.id)}
                      >
                        <Check />
                        Open contact
                      </Button>
                    ) : !person.name_complete ? (
                      person.provider === "apollo" ? (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={busy}
                          onClick={() => {
                            search.reset();
                            add.reset();
                            reveal.mutate({
                              body: {
                                source_version_id: snapshot.source_version_id,
                                external_id: person.external_id,
                              },
                            });
                          }}
                        >
                          {reveal.isPending &&
                          reveal.variables?.body.external_id ===
                            person.external_id ? (
                            <Spinner />
                          ) : (
                            <Search />
                          )}
                          Reveal profile
                        </Button>
                      ) : (
                        <span className="text-xs text-muted-foreground">
                          No name available
                        </span>
                      )
                    ) : (
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={busy}
                        onClick={() => {
                          search.reset();
                          reveal.reset();
                          add.mutate({ source, person });
                        }}
                      >
                        {add.isPending &&
                        add.variables?.person.external_id ===
                          person.external_id ? (
                          <Spinner />
                        ) : (
                          <UserPlus />
                        )}
                        Add contact
                      </Button>
                    )}
                  </div>
                </article>
              );
            })}
            {snapshot.query.operation === "search" &&
              (snapshot.result.page > 1 || snapshot.result.has_more) && (
                <div className="flex items-center justify-between gap-2">
                  <Button
                    variant="outline"
                    disabled={busy || snapshot.result.page <= 1}
                    onClick={() =>
                      search.mutate({
                        body: {
                          provider: snapshot.query.provider as
                            "apollo" | "hunter",
                          domain: String(snapshot.query.domain),
                          title: String(snapshot.query.title ?? ""),
                          page: snapshot.result.page - 1,
                        },
                      })
                    }
                  >
                    Previous
                  </Button>
                  <span className="text-xs text-muted-foreground">
                    Page {snapshot.result.page}
                  </span>
                  <Button
                    variant="outline"
                    disabled={
                      busy ||
                      !snapshot.result.has_more ||
                      snapshot.result.page >= 500
                    }
                    onClick={() =>
                      search.mutate({
                        body: {
                          provider: snapshot.query.provider as
                            "apollo" | "hunter",
                          domain: String(snapshot.query.domain),
                          title: String(snapshot.query.title ?? ""),
                          page: snapshot.result.page + 1,
                        },
                      })
                    }
                  >
                    Next page
                  </Button>
                </div>
              )}
          </section>
        )}
      </DialogContent>
    </Dialog>
  );
}

export function ContactDiscoveryConnections() {
  const providers = useProviders();
  const [setup, setSetup] = useState<Provider>();
  const [discovering, setDiscovering] = useState<"apollo" | "hunter">();
  return (
    <section aria-label="Contact discovery apps" className="space-y-4">
      <div>
        <h2 className="text-base font-medium">Contact discovery</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Find the right people at companies you care about.
        </p>
      </div>
      {providers.error && (
        <ErrorState
          error={providers.error}
          retry={() => void providers.refetch()}
        />
      )}
      {providers.isPending && <LoadingRows />}
      <div className="grid gap-5 lg:grid-cols-2">
        {providers.data?.map((provider) => (
          <article
            key={provider.id}
            className="space-y-4 rounded-xl shadow-surface bg-card p-5"
          >
            <div className="flex items-center justify-between gap-3">
              <h3 className="font-medium">{provider.name}</h3>
              <Badge variant="secondary">
                {provider.configured ? "Key configured" : "Setup needed"}
              </Badge>
            </div>
            <p className="text-sm leading-6 text-muted-foreground">
              {provider.description}
            </p>
            <p className="text-xs text-muted-foreground">
              Access and available credits are checked when you make a request.
            </p>
            <Button
              variant="outline"
              onClick={() =>
                provider.configured
                  ? setDiscovering(provider.id)
                  : setSetup(provider)
              }
            >
              {provider.configured
                ? "Discover contacts"
                : `Set up ${provider.name}`}
            </Button>
          </article>
        ))}
      </div>
      <Dialog
        open={!!setup}
        onOpenChange={(open) => {
          if (!open) setSetup(undefined);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Set up {setup?.name}</DialogTitle>
            <DialogDescription>
              Contact discovery uses your own provider account and its available
              API credits.
            </DialogDescription>
          </DialogHeader>
          <ol className="list-decimal space-y-3 ps-5 text-sm leading-6">
            <li>
              Get an API key with access to the discovery endpoints in your{" "}
              <a
                href={setup?.documentation_url}
                target="_blank"
                rel="noreferrer"
                className="underline underline-offset-4"
              >
                provider account
              </a>
              .
            </li>
            <li>
              Add{" "}
              <code className="rounded bg-muted px-1">
                {setup?.setup_variable}
              </code>{" "}
              to Command Center’s root <code>.env</code>, then recreate the API
              service with <code>docker compose up -d api</code>.
            </li>
            <li>Recheck setup, then try a search from Contacts.</li>
          </ol>
          <Button
            onClick={() => {
              void providers.refetch();
              setSetup(undefined);
            }}
          >
            Recheck setup
          </Button>
        </DialogContent>
      </Dialog>
      {discovering && (
        <ContactDiscovery
          open
          onOpenChange={(open) => {
            if (!open) setDiscovering(undefined);
          }}
          initialProvider={discovering}
        />
      )}
    </section>
  );
}
