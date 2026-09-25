"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Info, Plug, RefreshCw } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { api, type Integrations, type Schema } from "@/lib/api";
import {
  canStartFreshConnectedRequest,
  RetainedRequestIntents,
} from "@/lib/retained-intent";
import { ErrorState, LoadingRows, PageHeading, Spinner } from "./primitives";
import { ContactDiscoveryConnections } from "./contact-discovery";

import {
  ConnectedAppCard,
  connectedApps,
  type ConnectedApp,
} from "./connected-app-card";

const pendingConnectionKey = "command-center:pending-app-connection";
type PendingConnection = { expiresAt: number; refreshKey: string };

function pendingConnection(): PendingConnection | null {
  try {
    const value = JSON.parse(
      sessionStorage.getItem(pendingConnectionKey) ?? "null",
    );
    if (
      value &&
      typeof value.refreshKey === "string" &&
      typeof value.expiresAt === "number" &&
      value.expiresAt > Date.now()
    )
      return value;
  } catch {
    // A blocked or expired browser store must not prevent an explicit refresh.
  }
  return null;
}

function rememberConnection() {
  const pending = {
    expiresAt: Date.now() + 30 * 60 * 1000,
    refreshKey: crypto.randomUUID(),
  };
  try {
    sessionStorage.setItem(pendingConnectionKey, JSON.stringify(pending));
  } catch {
    // The provider callback can still trigger verification without storage.
  }
}

function forgetConnection() {
  try {
    sessionStorage.removeItem(pendingConnectionKey);
  } catch {
    // Storage may be unavailable in a restricted browser context.
  }
}

export function ConnectedAccounts() {
  const client = useQueryClient();
  const searchParams = useSearchParams();
  const returnedFromProvider = searchParams.get("connected") === "1";
  const connectionFailed =
    returnedFromProvider && searchParams.get("status") === "failed";
  const automaticRefreshStarted = useRef(false);
  const [setupApp, setSetupApp] = useState<ConnectedApp | null>(null);
  const setupTrigger = useRef<HTMLElement | null>(null);
  const integrations = useQuery({
    queryKey: ["integrations"],
    queryFn: () => api<Integrations>("integrations"),
  });
  const [intents] = useState(() => new RetainedRequestIntents());
  const accounts = useQuery({
    queryKey: ["connected-accounts"],
    queryFn: () =>
      api<Schema["AccountRead"][]>("integrations/composio/accounts"),
  });
  const refresh = useMutation({
    mutationFn: () => {
      const target = "integrations/composio/accounts/sync";
      const body = {};
      const request = intents.forRequest("refresh", "POST", target, body);
      return api<Schema["AccountRead"][]>(target, {
        method: "POST",
        body,
        key: pendingConnection()?.refreshKey ?? request.key,
      });
    },
    onSuccess: (rows) => {
      intents.confirmRequest(
        "refresh",
        "POST",
        "integrations/composio/accounts/sync",
        {},
      );
      forgetConnection();
      client.setQueryData(["connected-accounts"], rows);
      if (returnedFromProvider) {
        const url = new URL(window.location.href);
        for (const key of [
          "connected",
          "status",
          "connected_account_id",
          "toolkit",
        ])
          url.searchParams.delete(key);
        window.history.replaceState(
          null,
          "",
          url.pathname + url.search + url.hash,
        );
      }
      toast.success("Connected accounts refreshed");
    },
  });
  const choose = useMutation({
    mutationFn: (account: Schema["AccountRead"]) => {
      const target = `integrations/composio/accounts/${account.id}/select`;
      const body = {
        purpose: "outreach",
        expected_version: account.row_version,
      };
      const request = intents.forRequest(
        `choose:${account.id}`,
        "POST",
        target,
        body,
      );
      return api(target, {
        method: "POST",
        body,
        key: request.key,
      });
    },
    onSuccess: (_result, account) => {
      intents.confirmRequest(
        `choose:${account.id}`,
        "POST",
        `integrations/composio/accounts/${account.id}/select`,
        { purpose: "outreach", expected_version: account.row_version },
      );
      void client.invalidateQueries({ queryKey: ["connected-accounts"] });
      toast.success("Outreach account selected");
    },
  });
  const chooseAccount = choose.variables;
  const startFreshRefresh = () => {
    intents.reset("refresh");
    if (pendingConnection()) rememberConnection();
    refresh.reset();
    refresh.mutate();
  };
  const startFreshSelection = () => {
    if (!chooseAccount) return;
    intents.reset(`choose:${chooseAccount.id}`);
    choose.reset();
    choose.mutate(chooseAccount);
  };
  const connect = useMutation({
    mutationFn: async (app: ConnectedApp) => {
      const data = await api<{ redirect_url: string }>(
        "integrations/composio/connect",
        {
          method: "POST",
          body: { toolkit: app.toolkit },
        },
      );
      let url: URL;
      try {
        url = new URL(data.redirect_url);
      } catch {
        throw new Error(
          "The app returned an invalid connection link. Please try again.",
        );
      }
      if (url.protocol !== "https:" || url.username || url.password)
        throw new Error(
          "The app returned an invalid connection link. Please try again.",
        );
      return url.href;
    },
    onSuccess: (url) => {
      rememberConnection();
      window.location.assign(url);
    },
  });
  const canRefresh = Boolean(
    integrations.data?.composio_configured &&
    integrations.data.composio_toolkits.some((toolkit) =>
      connectedApps.some((app) => app.toolkit === toolkit),
    ),
  );
  const { mutate: refreshAccounts } = refresh;
  useEffect(() => {
    if (connectionFailed) {
      forgetConnection();
      return;
    }
    const verifyReturn = () => {
      if (
        !canRefresh ||
        automaticRefreshStarted.current ||
        document.visibilityState === "hidden" ||
        (!returnedFromProvider && !pendingConnection())
      )
        return;
      automaticRefreshStarted.current = true;
      if (!pendingConnection()) rememberConnection();
      refreshAccounts();
    };
    verifyReturn();
    window.addEventListener("pageshow", verifyReturn);
    window.addEventListener("focus", verifyReturn);
    return () => {
      window.removeEventListener("pageshow", verifyReturn);
      window.removeEventListener("focus", verifyReturn);
    };
  }, [canRefresh, connectionFailed, refreshAccounts, returnedFromProvider]);
  return (
    <>
      <PageHeading
        title="Connected apps"
        description="Your tools, connected to the work you do here."
        action={
          <Button
            variant="outline"
            disabled={!canRefresh || refresh.isPending}
            onClick={() => refresh.mutate()}
          >
            {refresh.isPending ? (
              <Spinner />
            ) : (
              <RefreshCw data-icon="inline-start" />
            )}
            {refresh.isPending ? "Refreshing accounts…" : "Refresh accounts"}
          </Button>
        }
      />
      <div className="mx-5 mb-10 flex max-w-5xl flex-col gap-6 md:mx-9">
        <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
          Connect an account and we’ll verify it when you return. Gmail is only
          read when you explicitly ask to pull email. External changes still
          need your review.
        </p>
        {connectionFailed ? (
          <Alert variant="destructive">
            <Info />
            <AlertTitle>Connection wasn’t completed</AlertTitle>
            <AlertDescription>
              Choose Connect to try again and finish authorization in the app.
            </AlertDescription>
          </Alert>
        ) : (
          (returnedFromProvider || refresh.isPending) &&
          !refresh.isSuccess &&
          !refresh.error && (
            <Alert>
              <Plug />
              <AlertTitle>Verifying your connection…</AlertTitle>
              <AlertDescription>
                Checking the connected account and saving it to your workspace.
                This does not pull your email.
              </AlertDescription>
            </Alert>
          )
        )}
        {integrations.error && (
          <ErrorState
            error={integrations.error}
            retry={() => void integrations.refetch()}
          />
        )}
        {accounts.error && (
          <ErrorState
            error={accounts.error}
            retry={() => void accounts.refetch()}
          />
        )}
        {refresh.error && (
          <Alert variant="destructive">
            <Info />
            <AlertTitle>Accounts could not be refreshed</AlertTitle>
            <AlertDescription>
              <p>{refresh.error.message}</p>
              <Button
                className="mt-2 w-fit"
                variant="outline"
                disabled={refresh.isPending}
                onClick={
                  canStartFreshConnectedRequest(refresh.error)
                    ? startFreshRefresh
                    : () => refresh.mutate()
                }
              >
                {canStartFreshConnectedRequest(refresh.error)
                  ? "Start a fresh refresh"
                  : "Retry the same refresh"}
              </Button>
            </AlertDescription>
          </Alert>
        )}
        {choose.error && chooseAccount && (
          <Alert variant="destructive">
            <Info />
            <AlertTitle>Outreach account was not changed</AlertTitle>
            <AlertDescription>
              <p>{choose.error.message}</p>
              <Button
                className="mt-2 w-fit"
                variant="outline"
                disabled={choose.isPending}
                onClick={
                  canStartFreshConnectedRequest(choose.error)
                    ? startFreshSelection
                    : () => choose.mutate(chooseAccount)
                }
              >
                {canStartFreshConnectedRequest(choose.error)
                  ? "Start a fresh account selection"
                  : "Retry the same account selection"}
              </Button>
            </AlertDescription>
          </Alert>
        )}
        {connect.error && (
          <Alert variant="destructive">
            <Info />
            <AlertTitle>{connect.variables?.name} could not connect</AlertTitle>
            <AlertDescription>
              {connect.error.message} You can try Connect again.
            </AlertDescription>
          </Alert>
        )}
        {integrations.isPending || accounts.isPending ? (
          <LoadingRows />
        ) : integrations.data && accounts.data ? (
          <div className="grid items-start gap-5 lg:grid-cols-2">
            {connectedApps.map((app) => (
              <ConnectedAppCard
                key={app.toolkit}
                app={app}
                accounts={accounts.data.filter(
                  (account) => account.toolkit === app.toolkit,
                )}
                configured={
                  integrations.data.composio_configured &&
                  integrations.data.composio_toolkits.includes(app.toolkit)
                }
                connecting={
                  connect.isPending &&
                  connect.variables?.toolkit === app.toolkit
                }
                connectionPending={connect.isPending}
                selecting={choose.isPending}
                selectedAccountId={chooseAccount?.id}
                onConnect={() => connect.mutate(app)}
                onSetup={() => {
                  setupTrigger.current = document.activeElement as HTMLElement;
                  setSetupApp(app);
                }}
                onSelect={(account) => choose.mutate(account)}
              />
            ))}
          </div>
        ) : null}
        <ContactDiscoveryConnections />
        <p className="max-w-2xl text-xs leading-5 text-muted-foreground">
          Status reflects the last account verification. Refresh after
          connecting or changing access in an app. Account checks use your
          configured spending limits.
        </p>
      </div>
      <Dialog
        open={setupApp !== null}
        onOpenChange={(open) => {
          if (!open) setSetupApp(null);
        }}
      >
        <DialogContent
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            setupTrigger.current?.focus();
          }}
        >
          <DialogHeader>
            <DialogTitle>Set up {setupApp?.name}</DialogTitle>
            <DialogDescription>
              This app needs a server connection configuration before you can
              link your account.
            </DialogDescription>
          </DialogHeader>
          <ol className="flex list-decimal flex-col gap-3 ps-5 text-sm leading-6">
            <li>
              In Composio, create an auth configuration for {setupApp?.name}{" "}
              with the access you want to grant.
            </li>
            <li>
              In the project’s root <code>.env</code>, set{" "}
              <code>COMPOSIO_API_KEY</code> and add the auth configuration ID
              under
              <code> {setupApp?.toolkit} </code> in{" "}
              <code>CC_COMPOSIO_AUTH_CONFIGS</code>.
            </li>
            <li>
              Restart the API and workers, then reload this page and choose
              Connect. Complete authorization in the app and return here to
              refresh accounts.
            </li>
          </ol>
          <p className="text-xs leading-5 text-muted-foreground">
            Credentials stay on your server. Connecting an account does not
            approve sending or publishing.
          </p>
          <Button
            variant="outline"
            onClick={() => {
              void integrations.refetch();
              setSetupApp(null);
            }}
          >
            Check configuration again
          </Button>
        </DialogContent>
      </Dialog>
    </>
  );
}
