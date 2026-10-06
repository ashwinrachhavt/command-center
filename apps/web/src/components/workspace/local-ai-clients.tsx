"use client";

import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, KeyRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import { AnimatedIcon } from "@/components/ui/animated-icon";
import { Input } from "@/components/ui/input";
import { api, dateLabel } from "@/lib/api";
import { ErrorState, LoadingRows, Spinner } from "./primitives";

type LocalClient = {
  id: string;
  name: string;
  created_at: string;
  expires_at: string;
  revoked_at: string | null;
};

export function LocalAIClients() {
  const client = useQueryClient();
  const [name, setName] = useState("");
  const [credential, setCredential] = useState<{ id: string; token: string }>();
  const [copyNotice, setCopyNotice] = useState("");
  const [openedAt] = useState(() => Date.now());
  const creating = useRef(false);
  const clients = useQuery({
    queryKey: ["mcp-clients"],
    queryFn: ({ signal }) => api<LocalClient[]>("mcp-clients", { signal }),
  });
  const create = useMutation({
    mutationFn: async (submittedName: string) => {
      const { token, ...record } = await api<LocalClient & { token: string }>(
        "mcp-clients",
        {
          method: "POST",
          body: { name: submittedName, expires_in_days: 90 },
          // Provisioning returns its secret only once and cannot be replayed.
          retry: false,
        },
      );
      setCredential({ id: record.id, token });
      setCopyNotice("");
      client.setQueryData<LocalClient[]>(["mcp-clients"], (current) => [
        record,
        ...(current ?? []),
      ]);
      setName((current) => (current.trim() === submittedName ? "" : current));
      // The secret never enters React Query's mutation or query caches.
    },
    onSettled: () => {
      creating.current = false;
    },
  });
  const revoke = useMutation({
    mutationFn: (id: string) =>
      api<LocalClient>(`mcp-clients/${id}/revoke`, {
        method: "POST",
        retry: false,
      }),
    onSuccess: (record) => {
      client.setQueryData<LocalClient[]>(["mcp-clients"], (current) =>
        current?.map((item) => (item.id === record.id ? record : item)),
      );
      setCredential((current) =>
        current?.id === record.id ? undefined : current,
      );
    },
  });
  const copyToken = async () => {
    if (!credential) return;
    try {
      await navigator.clipboard.writeText(credential.token);
      setCopyNotice("Token copied.");
    } catch {
      setCopyNotice("Copy failed. Select the token and copy it manually.");
    }
  };

  return (
    <section
      className="rounded-xl shadow-surface bg-card p-6"
      aria-labelledby="local-clients-title"
    >
      <h2
        id="local-clients-title"
        className="flex items-center gap-2 text-sm font-medium"
      >
        <KeyRound className="size-4" />
        Local AI clients
      </h2>
      <p className="mt-2 text-xs leading-6 text-muted-foreground">
        Connect Claude Code or Codex to this workspace. Follow the Local AI
        clients setup in the repository README. Tokens expire after 90 days; you
        can revoke access here at any time.
      </p>
      <form
        className="mt-4 flex flex-wrap items-end gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (!name.trim() || creating.current || credential) return;
          creating.current = true;
          create.mutate(name.trim());
        }}
      >
        <label className="min-w-40 flex-1 text-xs" htmlFor="local-client-name">
          Client name
          <Input
            id="local-client-name"
            className="mt-2"
            placeholder="Codex on my laptop"
            value={name}
            maxLength={100}
            onChange={(event) => setName(event.target.value)}
            disabled={create.isPending}
            required
          />
        </label>
        <Button
          type="submit"
          disabled={!name.trim() || create.isPending || !!credential}
        >
          <AnimatedIcon state={create.isPending}>
            {create.isPending ? <Spinner /> : <KeyRound />}
          </AnimatedIcon>
          Create token
        </Button>
      </form>
      {create.error ? (
        <p className="mt-3 text-xs text-destructive" role="alert">
          {create.error.message} Refresh the client list before creating another
          token.
        </p>
      ) : null}
      {credential ? (
        <div className="mt-4 rounded-lg border border-border bg-background p-4">
          <p className="text-xs leading-5">
            Save this token now. It is shown once and will disappear when you
            leave this page or hide it.
          </p>
          <Input
            aria-label="New local client token"
            className="mt-3 font-mono"
            value={credential.token}
            readOnly
            autoComplete="off"
            onFocus={(event) => event.target.select()}
          />
          <div className="mt-3 flex gap-2">
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => void copyToken()}
            >
              <Copy />
              Copy token
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => {
                setCredential(undefined);
                setCopyNotice("");
              }}
            >
              Hide token
            </Button>
          </div>
          {copyNotice ? (
            <p role="status" className="mt-2 text-xs text-muted-foreground">
              {copyNotice}
            </p>
          ) : null}
        </div>
      ) : null}
      {clients.error ? (
        <ErrorState
          error={clients.error}
          retry={() => void clients.refetch()}
        />
      ) : null}
      {clients.isPending ? (
        <LoadingRows />
      ) : clients.data?.length ? (
        <ul className="mt-5 divide-y divide-border">
          {clients.data.map((item) => {
            const expired =
              Date.parse(item.expires_at) <=
              Math.max(openedAt, clients.dataUpdatedAt);
            return (
              <li
                key={item.id}
                className="flex flex-wrap items-center gap-3 py-3"
              >
                <div className="min-w-0 flex-1">
                  <p className="break-words text-sm">{item.name}</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {item.revoked_at
                      ? "Revoked"
                      : expired
                        ? "Expired"
                        : `Expires ${dateLabel(item.expires_at)}`}
                  </p>
                </div>
                {!item.revoked_at && !expired ? (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={revoke.isPending}
                    onClick={() => revoke.mutate(item.id)}
                    aria-label={`Revoke ${item.name}`}
                  >
                    Revoke
                  </Button>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : clients.data ? (
        <p className="mt-4 text-xs text-muted-foreground">
          No local clients connected.
        </p>
      ) : null}
      {revoke.error ? (
        <p role="alert" className="mt-3 text-xs text-destructive">
          {revoke.error.message}
        </p>
      ) : null}
    </section>
  );
}
