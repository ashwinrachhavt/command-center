"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  Copy,
  Globe,
  Link2,
  Plus,
  Puzzle,
  RefreshCw,
  Send,
  Unplug,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api, dateLabel } from "@/lib/api";
import { EmptyState, ErrorState, PageHeading, Status } from "./primitives";

type Device = {
  id: string;
  name: string;
  paired_at: string | null;
  last_seen_at: string | null;
  revoked_at: string | null;
};
type Snapshot = {
  id: string;
  title: string;
  origin: string;
  page_url: string;
  created_at: string;
  fields: {
    id: string;
    label: string;
    type: string;
    required: boolean;
    options: string[];
  }[];
};
type FillCommand = {
  id: string;
  state: string;
  created_at: string;
  fields: Record<string, string>;
};
function FillForm({ snapshot }: { snapshot: Snapshot }) {
  const [values, setValues] = useState<Record<string, string>>({});
  const client = useQueryClient();
  const send = useMutation({
    mutationFn: () =>
      api("browser/commands", {
        method: "POST",
        body: {
          snapshot_id: snapshot.id,
          fields: Object.fromEntries(
            Object.entries(values).filter(([, v]) => v !== ""),
          ),
        },
      }),
    onSuccess: () => {
      toast.success(
        "Fill proposal sent. Review and apply it in the browser companion.",
      );
      client.invalidateQueries({ queryKey: ["browser-commands"] });
    },
    onError: (e) => toast.error(e.message),
  });
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        send.mutate();
      }}
    >
      <div className="mb-5 flex items-start gap-3">
        <Globe className="mt-1 size-4 text-primary" />
        <div>
          <h3 className="text-sm font-medium">
            {snapshot.title || "Shared form"}
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">
            {snapshot.origin} · {dateLabel(snapshot.created_at)}
          </p>
        </div>
      </div>
      <FieldGroup className="gap-4">
        {snapshot.fields.map((f) => (
          <Field key={f.id}>
            <FieldLabel htmlFor={f.id}>
              {f.label || f.id}
              {f.required ? " *" : ""}
            </FieldLabel>
            {f.type === "select" ? (
              <Select
                value={values[f.id] || "__skip"}
                onValueChange={(v) =>
                  setValues({ ...values, [f.id]: v === "__skip" ? "" : v })
                }
              >
                <SelectTrigger id={f.id}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectItem value="__skip">Leave unchanged</SelectItem>
                    {f.options.filter(Boolean).map((v) => (
                      <SelectItem value={v} key={v}>
                        {v}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            ) : (
              <Input
                id={f.id}
                value={values[f.id] ?? ""}
                onChange={(e) =>
                  setValues({ ...values, [f.id]: e.target.value })
                }
                maxLength={5000}
                placeholder="Leave blank to skip"
              />
            )}
          </Field>
        ))}
      </FieldGroup>
      <Button
        className="mt-5"
        disabled={send.isPending || Object.values(values).every((v) => !v)}
      >
        <Send />
        Send fill proposal
      </Button>
      <p className="mt-3 text-xs leading-6 text-muted-foreground">
        The companion checks the exact shared page, shows the proposed values
        and waits for you to apply them. It never clicks Submit.
      </p>
    </form>
  );
}

export function BrowserPage() {
  const client = useQueryClient();
  const [code, setCode] = useState<string>();
  const [selected, setSelected] = useState<string>();
  const devices = useQuery({
    queryKey: ["devices"],
    queryFn: () => api<Device[]>("browser/devices"),
    refetchInterval: 10000,
  });
  const snapshots = useQuery({
    queryKey: ["snapshots"],
    queryFn: () => api<Snapshot[]>("browser/snapshots"),
    refetchInterval: 10000,
  });
  const commands = useQuery({
    queryKey: ["browser-commands"],
    queryFn: () => api<FillCommand[]>("browser/commands"),
    refetchInterval: 5000,
  });
  const pair = useMutation({
    mutationFn: () =>
      api<{ code: string }>("browser/pairings", {
        method: "POST",
        body: { name: "My browser" },
      }),
    onSuccess: (data) => {
      setCode(data.code);
      client.invalidateQueries({ queryKey: ["devices"] });
    },
    onError: (e) => toast.error(e.message),
  });
  const revoke = useMutation({
    mutationFn: (id: string) =>
      api(`browser/devices/${id}/revoke`, { method: "POST" }),
    onSuccess: () => {
      client.invalidateQueries();
      toast.success("Browser access revoked");
    },
    onError: (e) => toast.error(e.message),
  });
  const snapshot =
    snapshots.data?.find((s) => s.id === selected) ?? snapshots.data?.[0];
  return (
    <>
      <PageHeading
        title="Browser companion"
        description="Bring your workspace to the forms you’re already filling out."
        action={
          <Button onClick={() => pair.mutate()} disabled={pair.isPending}>
            <Plus />
            Pair a browser
          </Button>
        }
      />
      <div className="grid gap-6 px-5 md:px-9 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]">
        <section className="flex flex-col gap-5">
          <div className="rounded-xl border border-border bg-card p-6">
            <Puzzle className="mb-4 size-7 text-primary" />
            <h2 className="text-lg font-medium">Your browser. Your session.</h2>
            <p className="mt-3 text-xs leading-6 text-muted-foreground">
              Load the local extension from <code>apps/extension</code> in
              Chrome’s Extensions page using “Load unpacked.” Then pair it here
              and share an application form from its popup.
            </p>
            <p className="mt-3 text-xs leading-6 text-muted-foreground">
              Logins and cookies stay in Chrome. Only the form fields you choose
              to share reach your workspace.
            </p>
            {code && (
              <div className="mt-5 rounded-lg border border-primary/20 bg-primary/5 p-4">
                <Field>
                  <FieldLabel htmlFor="pair-code">
                    One-time pairing code
                  </FieldLabel>
                  <div className="flex gap-2">
                    <Input
                      id="pair-code"
                      value={code}
                      readOnly
                      className="font-mono text-xs"
                    />
                    <Button
                      size="icon"
                      variant="outline"
                      aria-label="Copy pairing code"
                      onClick={async () => {
                        await navigator.clipboard.writeText(code);
                        toast.success("Pairing code copied");
                      }}
                    >
                      <Copy />
                    </Button>
                  </div>
                </Field>
                <p className="mt-2 text-[11px] text-muted-foreground">
                  Paste this in the companion within 5 minutes.
                </p>
              </div>
            )}
          </div>
          <div className="rounded-xl border border-border bg-card p-5">
            <h2 className="mb-4 text-sm font-medium">Paired browsers</h2>
            {devices.error ? (
              <ErrorState error={devices.error} />
            ) : devices.data?.filter((d) => !d.revoked_at).length === 0 ? (
              <p className="text-xs text-muted-foreground">
                No browser paired yet.
              </p>
            ) : (
              devices.data
                ?.filter((d) => !d.revoked_at)
                .map((d) => (
                  <div
                    key={d.id}
                    className="flex items-center gap-3 border-b border-border py-3 last:border-0"
                  >
                    <Link2 className="size-4 text-muted-foreground" />
                    <div className="flex-1">
                      <p className="text-xs font-medium">{d.name}</p>
                      <p className="mt-1 text-[10px] text-muted-foreground">
                        {d.paired_at
                          ? `Connected · Last seen ${dateLabel(d.last_seen_at ?? d.paired_at)}`
                          : "Waiting for pairing"}
                      </p>
                    </div>
                    <Button
                      size="icon-xs"
                      variant="ghost"
                      aria-label={`Revoke ${d.name}`}
                      onClick={() => revoke.mutate(d.id)}
                      disabled={revoke.isPending}
                    >
                      <Unplug />
                    </Button>
                  </div>
                ))
            )}
          </div>
          <div className="rounded-xl border border-border bg-card p-5">
            <h2 className="mb-3 text-sm font-medium">Recent fill proposals</h2>
            {commands.data?.map((c) => (
              <div
                className="flex items-center justify-between border-b border-border py-3 last:border-0"
                key={c.id}
              >
                <span className="text-xs text-muted-foreground">
                  {Object.keys(c.fields).length} fields ·{" "}
                  {dateLabel(c.created_at)}
                </span>
                <Status value={c.state} />
              </div>
            ))}
            {commands.data?.length === 0 && (
              <p className="text-xs text-muted-foreground">No proposals yet.</p>
            )}
          </div>
        </section>
        <section className="rounded-xl border border-border bg-card p-6">
          <div className="mb-5 flex items-center justify-between">
            <h2 className="text-sm font-medium">Shared application forms</h2>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Refresh shared forms"
              onClick={() => snapshots.refetch()}
            >
              <RefreshCw />
            </Button>
          </div>
          {snapshots.error ? (
            <ErrorState error={snapshots.error} />
          ) : snapshot ? (
            <>
              {snapshots.data && snapshots.data.length > 1 && (
                <Select value={snapshot.id} onValueChange={setSelected}>
                  <SelectTrigger className="mb-6" aria-label="Shared form">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      {snapshots.data.map((s) => (
                        <SelectItem key={s.id} value={s.id}>
                          {s.title || s.origin}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              )}
              <FillForm key={snapshot.id} snapshot={snapshot} />
            </>
          ) : (
            <EmptyState
              title="A little help, right where you need it"
              description="Open a form, click the companion and choose Share form. Its fields will appear here for you to prepare a fill proposal."
            >
              <span className="flex items-center gap-2 text-xs text-muted-foreground">
                <Check className="size-3 text-primary" />
                No browser cookies leave your device
              </span>
            </EmptyState>
          )}
        </section>
      </div>
    </>
  );
}
