"use client";

import { AnimatedIcon } from "@/components/ui/animated-icon";
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { MailSearch } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Field, FieldLabel } from "@/components/ui/field";
import { api, type Schema } from "@/lib/api";
import {
  canStartFreshConnectedRequest,
  RetainedRequestIntent,
} from "@/lib/retained-intent";
import { ErrorState, Spinner } from "./primitives";

function gmailLink(value: unknown) {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    return url.origin === "https://mail.google.com" &&
      !url.username &&
      !url.password
      ? url.href
      : null;
  } catch {
    return null;
  }
}

/** Opening this surface reads saved account metadata only. Mail is fetched on submit. */
export function MailPull() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [intent] = useState(() => new RetainedRequestIntent());
  const accounts = useQuery({
    queryKey: ["connected-accounts"],
    enabled: open,
    queryFn: () =>
      api<Schema["AccountRead"][]>("integrations/composio/accounts"),
  });
  const account = accounts.data?.find(
    (account) =>
      account.toolkit === "gmail" &&
      account.connection_status === "ACTIVE" &&
      account.selected_purpose === "outreach",
  );
  const pull = useMutation({
    mutationFn: async (requestedQuery: string) => {
      if (!account) throw new Error("Select a verified Gmail account first.");
      const body = {
        query: requestedQuery.trim(),
        max_results: 10,
        account_id: account.id,
      };
      const request = intent.forRequest("POST", "gmail/search", body);
      const result = await api<Schema["GmailSearchRead"]>("gmail/search", {
        method: "POST",
        body,
        key: request.key,
      });
      intent.confirmRequest("POST", "gmail/search", body);
      return { ...result, query: body.query };
    },
  });
  return (
    <>
      <Button variant="outline" onClick={() => setOpen(true)}>
        <MailSearch />
        Pull email
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Pull email for this work</DialogTitle>
            <DialogDescription>
              Choose what to bring into Command Center. Gmail remains your
              inbox; nothing is fetched until you press Pull email.
            </DialogDescription>
          </DialogHeader>
          {accounts.error && <ErrorState error={accounts.error} />}
          <p className="text-sm text-muted-foreground">
            {accounts.isPending
              ? "Loading saved accounts…"
              : account
                ? `From ${account.display_name}`
                : "Select a verified Gmail outreach account in Connected apps first."}
          </p>
          <form
            className="space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              pull.mutate(query);
            }}
          >
            <Field>
              <FieldLabel htmlFor="mail-query">Email search</FieldLabel>
              <Input
                id="mail-query"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                maxLength={500}
                required
                placeholder="from:someone@example.com newer_than:14d"
              />
              <p className="text-xs text-muted-foreground">
                Use Gmail search terms. Each pull brings back up to 10 matching
                messages.
              </p>
            </Field>
            <Button disabled={!account || pull.isPending || !query.trim()}>
              <AnimatedIcon state={pull.isPending}>
                {pull.isPending ? <Spinner /> : <MailSearch />}
              </AnimatedIcon>
              Pull email
            </Button>
          </form>
          {pull.error && (
            <div role="alert" className="space-y-2 text-sm text-destructive">
              <p>{pull.error.message}</p>
              <Button
                variant="outline"
                size="sm"
                disabled={pull.isPending}
                onClick={() => {
                  if (canStartFreshConnectedRequest(pull.error)) intent.reset();
                  pull.mutate(pull.variables ?? query);
                }}
              >
                {canStartFreshConnectedRequest(pull.error)
                  ? "Try a fresh pull"
                  : "Retry this pull"}
              </Button>
            </div>
          )}
          {pull.data && (
            <section aria-label="Pulled messages" className="space-y-3">
              <p className="text-xs text-muted-foreground">
                {pull.data.messages.length} messages · {pull.data.query} ·{" "}
                {new Date(pull.data.observed_at).toLocaleString()}
              </p>
              {!pull.data.messages.length && (
                <p className="text-sm">No messages matched this search.</p>
              )}
              {pull.data.messages.map((message, index) => {
                const link = gmailLink(message.display_url);
                return (
                  <article
                    key={String(message.messageId ?? index)}
                    className="space-y-2 rounded-lg border p-4"
                  >
                    <h3 className="text-sm font-medium">
                      {String(message.subject ?? "Untitled email")}
                    </h3>
                    <p className="break-words text-xs text-muted-foreground">
                      From {String(message.sender ?? "Unknown sender")}
                    </p>
                    <details>
                      <summary className="cursor-pointer text-sm">
                        Read pulled message
                      </summary>
                      <p className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap break-words text-sm leading-7">
                        {String(
                          message.messageText ??
                            "This pull did not include message text. Open it in Gmail to read it.",
                        )}
                      </p>
                    </details>
                    {link && (
                      <a
                        href={link}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-block text-xs text-primary underline underline-offset-4"
                      >
                        Open in Gmail
                      </a>
                    )}
                  </article>
                );
              })}
              {pull.data.next_page_token && (
                <p className="text-xs text-muted-foreground">
                  More matches are available in Gmail. Narrow the search to
                  bring in another selection.
                </p>
              )}
            </section>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
