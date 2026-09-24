"use client";
import { useLayoutEffect, useRef, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, KeyRound, Plug, Save, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import {
  ApiError,
  api,
  label,
  type Integrations,
  type Profile,
} from "@/lib/api";
import { RetainedRequestIntent } from "@/lib/retained-intent";
import { ErrorState, LoadingRows, PageHeading, Spinner } from "./primitives";
import { ProfileFacts } from "./profile-facts";
import { SpendingSettings } from "./spending";
import { LocalAIClients } from "./local-ai-clients";
import { DocumentSettings } from "./document-decisions";

type ProfileValues = Pick<
  Profile,
  "display_name" | "headline" | "location" | "timezone"
>;

function profileValues(profile: Profile): ProfileValues {
  return {
    display_name: profile.display_name,
    headline: profile.headline,
    location: profile.location,
    timezone: profile.timezone,
  };
}

function sameProfileValues(left: ProfileValues, right: ProfileValues) {
  return Object.keys(left).every(
    (key) =>
      left[key as keyof ProfileValues] === right[key as keyof ProfileValues],
  );
}

type ProfileSubmission = {
  values: ProfileValues;
  expectedVersion: number;
};

export function ProfileForm({ profile }: { profile: Profile }) {
  const [baseline, setBaseline] = useState(profile);
  const [form, setForm] = useState<ProfileValues>(() => profileValues(profile));
  const [seenProfileVersion, setSeenProfileVersion] = useState(
    profile.row_version,
  );
  const currentForm = useRef(form);
  useLayoutEffect(() => {
    currentForm.current = form;
  }, [form]);
  const [requestIntent] = useState(() => new RetainedRequestIntent());
  const dirty = !sameProfileValues(form, profileValues(baseline));
  if (profile.row_version > seenProfileVersion) {
    setSeenProfileVersion(profile.row_version);
    if (!dirty) {
      setBaseline(profile);
      setForm(profileValues(profile));
    }
  }
  const client = useQueryClient();
  const mutation = useMutation({
    mutationFn: (submission: ProfileSubmission) => {
      const body = {
        ...submission.values,
        expected_version: submission.expectedVersion,
      };
      const intent = requestIntent.forRequest("PATCH", "me", body);
      return api<Profile>("me", {
        method: "PATCH",
        body,
        key: intent.key,
      });
    },
    onSuccess: (saved, submission) => {
      setBaseline(saved);
      if (sameProfileValues(currentForm.current, submission.values)) {
        setForm(profileValues(saved));
      }
      requestIntent.confirmRequest("PATCH", "me", {
        ...submission.values,
        expected_version: submission.expectedVersion,
      });
      client.invalidateQueries({ queryKey: ["me"] });
      toast.success("Workspace profile saved");
    },
    onError: (e) => toast.error(e.message),
  });
  const reload = useMutation({
    mutationFn: (keepDraft: boolean) =>
      api<Profile>("me").then((latest) => ({ keepDraft, latest })),
    onSuccess: ({ keepDraft, latest }) => {
      setBaseline(latest);
      if (!keepDraft) setForm(profileValues(latest));
      requestIntent.reset();
      mutation.reset();
    },
    onError: (error) => toast.error(error.message),
  });
  const newerProfileAvailable = profile.row_version > baseline.row_version;
  const conflict =
    mutation.error instanceof ApiError && mutation.error.status === 409;

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        mutation.mutate({
          values: { ...form },
          expectedVersion: baseline.row_version,
        });
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
              onChange={(e) =>
                setForm((current) => ({
                  ...current,
                  [key]: e.target.value,
                }))
              }
              placeholder={
                key === "timezone" ? "America/Los_Angeles" : undefined
              }
            />
          </Field>
        ))}
      </FieldGroup>
      {newerProfileAvailable && dirty ? (
        <div className="mt-4 rounded-md border border-border p-3 text-xs">
          <p>
            A newer profile revision is available. This draft is still based on
            revision {baseline.row_version}.
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => {
                setBaseline(profile);
                requestIntent.reset();
                mutation.reset();
              }}
            >
              Keep draft on latest revision
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => {
                setBaseline(profile);
                setForm(profileValues(profile));
                requestIntent.reset();
                mutation.reset();
              }}
            >
              Discard draft and use latest
            </Button>
          </div>
        </div>
      ) : null}
      <Button className="mt-5" disabled={mutation.isPending}>
        {mutation.isPending ? <Spinner /> : <Save />}Save profile
      </Button>
      {mutation.error && (
        <p role="alert" className="mt-3 text-xs text-destructive">
          {mutation.error.message}
        </p>
      )}
      {conflict ? (
        <div className="mt-3 flex flex-wrap gap-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={reload.isPending}
            onClick={() => reload.mutate(true)}
          >
            Reload latest and keep draft
          </Button>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={reload.isPending}
            onClick={() => reload.mutate(false)}
          >
            Discard draft and reload
          </Button>
        </div>
      ) : null}
      {reload.error ? (
        <p role="alert" className="mt-3 text-xs text-destructive">
          {reload.error.message}
        </p>
      ) : null}
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
          {profile.isPending && !profile.data ? (
            <LoadingRows />
          ) : profile.data ? (
            <>
              {profile.error ? (
                <ErrorState
                  error={profile.error}
                  retry={() => void profile.refetch()}
                />
              ) : profile.isFetching ? (
                <p className="mb-4 text-xs text-muted-foreground" role="status">
                  Refreshing profile…
                </p>
              ) : null}
              <ProfileForm profile={profile.data} />
            </>
          ) : profile.error ? (
            <ErrorState
              error={profile.error}
              retry={() => void profile.refetch()}
            />
          ) : null}
        </section>
        <ProfileFacts />
        <SpendingSettings />
        <DocumentSettings />
        <LocalAIClients />
        <section className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-border bg-card p-6">
          <div>
            <h2 className="text-sm font-medium">Connected apps</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              Manage your app connections, verified accounts and outreach
              mailbox.
            </p>
          </div>
          <Button asChild variant="outline">
            <Link href="/connections">
              <Plug data-icon="inline-start" />
              Manage connected apps
            </Link>
          </Button>
        </section>
        <section className="overflow-hidden rounded-xl border border-border bg-card">
          <div className="border-b border-border p-6">
            <h2 className="flex items-center gap-2 text-sm font-medium">
              <Plug className="size-4" />
              Workspace services
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
            Keep Clerk keys there too; <code>make env-sync</code> generates the
            web configuration. Run <code>make auth-sync</code> after changing
            your Clerk application.
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
