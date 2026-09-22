"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, KeyRound, Plug, Save, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { api, label, type Integrations, type Profile } from "@/lib/api";
import { ErrorState, LoadingRows, PageHeading, Spinner } from "./primitives";
import { ProfileFacts } from "./profile-facts";

function ProfileForm({ profile }: { profile: Profile }) {
  const [form, setForm] = useState({
    display_name: profile.display_name,
    headline: profile.headline,
    location: profile.location,
    timezone: profile.timezone,
  });
  const client = useQueryClient();
  const mutation = useMutation({
    mutationFn: () =>
      api("me", {
        method: "PATCH",
        body: { ...form, expected_version: profile.row_version },
      }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["me"] });
      toast.success("Workspace profile saved");
    },
    onError: (e) => toast.error(e.message),
  });
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        mutation.mutate();
      }}
    >
      <FieldGroup className="grid gap-5 sm:grid-cols-2">
        {Object.entries(form).map(([key, value]) => (
          <Field key={key}>
            <FieldLabel htmlFor={key}>
              {key === "display_name" ? "Workspace name" : label(key)}
            </FieldLabel>
            <Input
              id={key}
              value={value}
              required={key === "display_name" || key === "timezone"}
              maxLength={
                key === "headline" ? 300 : key === "timezone" ? 100 : 200
              }
              onChange={(e) => setForm({ ...form, [key]: e.target.value })}
              placeholder={
                key === "timezone" ? "America/Los_Angeles" : undefined
              }
            />
          </Field>
        ))}
      </FieldGroup>
      <Button className="mt-5" disabled={mutation.isPending}>
        {mutation.isPending ? <Spinner /> : <Save />}Save profile
      </Button>
      {mutation.error && (
        <p role="alert" className="mt-3 text-xs text-destructive">
          {mutation.error.message}
        </p>
      )}
    </form>
  );
}
export function Settings() {
  const profile = useQuery({
    queryKey: ["me"],
    queryFn: () => api<Profile>("me"),
  });
  const integrations = useQuery({
    queryKey: ["integrations"],
    queryFn: () => api<Integrations>("integrations"),
  });
  const connect = useMutation({
    mutationFn: (toolkit: string) =>
      api<{ redirect_url: string }>("integrations/composio/connect", {
        method: "POST",
        body: { toolkit },
      }),
    onSuccess: (data) => {
      const url = new URL(data.redirect_url);
      if (url.protocol === "https:") window.location.assign(url.href);
      else toast.error("The provider returned an invalid connection URL");
    },
    onError: (e) => toast.error(e.message),
  });
  return (
    <>
      <PageHeading
        title="Workspace settings"
        description="Your profile, connected services and the way your workspace works."
      />
      <div className="mx-5 flex max-w-4xl flex-col gap-8 md:mx-9">
        <section className="rounded-xl border border-border bg-card p-6">
          <h2 className="mb-1 text-sm font-medium">Your workspace</h2>
          <p className="mb-6 text-xs text-muted-foreground">
            Give your work a home. These details stay within your account.
          </p>
          {profile.error ? (
            <ErrorState error={profile.error} />
          ) : profile.isPending ? (
            <LoadingRows />
          ) : (
            <ProfileForm
              key={profile.data.row_version}
              profile={profile.data}
            />
          )}
        </section>
        <ProfileFacts />
        <section className="overflow-hidden rounded-xl border border-border bg-card">
          <div className="border-b border-border p-6">
            <h2 className="flex items-center gap-2 text-sm font-medium">
              <Plug className="size-4" />
              Connections
            </h2>
            <p className="mt-2 text-xs text-muted-foreground">
              Research services and the tools your agents can use.
            </p>
          </div>
          {integrations.error ? (
            <div className="px-6">
              <ErrorState
                error={integrations.error}
                retry={() => integrations.refetch()}
              />
            </div>
          ) : integrations.isPending ? (
            <LoadingRows />
          ) : (
            <>
              {[
                {
                  name: "Clerk",
                  description: "Shared login across your workspace and API",
                  connected: integrations.data.auth === "clerk",
                },
                {
                  name: "OpenAI",
                  description: "Models for research, writing and reasoning",
                  connected: integrations.data.model_providers.openai,
                },
                {
                  name: "Gemini",
                  description: "Models for research, writing and reasoning",
                  connected: integrations.data.model_providers.gemini,
                },
                {
                  name: "Mistral",
                  description: "Models for research, writing and reasoning",
                  connected: integrations.data.model_providers.mistral,
                },
                {
                  name: "Cohere",
                  description: "Models for research, writing and reasoning",
                  connected: integrations.data.model_providers.cohere,
                },
                {
                  name: "Composio",
                  description: "Connected app tools, scoped to your account",
                  connected: integrations.data.composio_configured,
                },
                ...integrations.data.services.map((s) => ({
                  name: s.name,
                  description:
                    s.name === "Firecrawl"
                      ? "Existing local crawling service"
                      : "Existing local web search service",
                  connected: s.state === "online",
                })),
              ].map((s) => (
                <div
                  key={s.name}
                  className="flex items-center gap-4 border-b border-border/60 px-6 py-5 last:border-0"
                >
                  <span className="flex size-9 items-center justify-center rounded-lg border border-border bg-background">
                    <KeyRound className="size-4 text-muted-foreground" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <h3 className="text-sm font-medium">{s.name}</h3>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {s.description}
                    </p>
                  </div>
                  <Badge
                    variant="outline"
                    className={
                      s.connected ? "text-primary" : "text-muted-foreground"
                    }
                  >
                    {s.connected && <Check className="size-3" />}
                    {s.connected ? "Configured" : "Not configured"}
                  </Badge>
                </div>
              ))}
              {integrations.data.composio_toolkits.map((toolkit) => (
                <div
                  key={toolkit}
                  className="flex items-center justify-between border-t border-border px-6 py-4"
                >
                  <span className="text-sm">{label(toolkit)}</span>
                  <Button
                    variant="outline"
                    disabled={connect.isPending}
                    onClick={() => connect.mutate(toolkit)}
                  >
                    Connect account
                  </Button>
                </div>
              ))}
            </>
          )}
        </section>
        <section className="rounded-xl border border-border p-6">
          <h2 className="flex items-center gap-2 text-sm font-medium">
            <ShieldCheck className="size-4 text-primary" />
            Configuration stays on your server
          </h2>
          <p className="mt-3 text-xs leading-6 text-muted-foreground">
            Put model provider and Composio keys in the root <code>.env</code>.
            Clerk’s publishable and secret keys go in <code>apps/web/.env</code>
            ; the API verifies the matching issuer. Run{" "}
            <code>make auth-check</code> after changing your Clerk application.
          </p>
          <p className="mt-3 text-xs leading-6 text-muted-foreground">
            Customize agent models, tools and skills in{" "}
            <code>agents/profiles.toml</code>. Composio toolkits need an auth
            configuration and a reviewed, pinned tool version. Secrets are never
            exposed in this settings page.
          </p>
        </section>
      </div>
    </>
  );
}
