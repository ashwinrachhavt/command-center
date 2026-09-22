"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { api, label, type Schema } from "@/lib/api";
import {
  canStartFreshConnectedRequest,
  RetainedRequestIntents,
} from "@/lib/retained-intent";
import { ErrorState, LoadingRows, Spinner } from "./primitives";

export function ConnectedAccounts() {
  const client = useQueryClient();
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
      return api(target, { method: "POST", body, key: request.key });
    },
    onSuccess: () => {
      intents.confirmRequest(
        "refresh",
        "POST",
        "integrations/composio/accounts/sync",
        {},
      );
      void client.invalidateQueries({ queryKey: ["connected-accounts"] });
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
    refresh.reset();
    refresh.mutate();
  };
  const startFreshSelection = () => {
    if (!chooseAccount) return;
    intents.reset(`choose:${chooseAccount.id}`);
    choose.reset();
    choose.mutate(chooseAccount);
  };
  return (
    <section className="rounded-xl border border-border bg-card p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-medium">Verified app accounts</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Refresh after connecting an app. Identity checks use your configured
            spending limits.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          disabled={refresh.isPending}
          onClick={() => refresh.mutate()}
        >
          {refresh.isPending ? <Spinner /> : <RefreshCw />}Refresh accounts
        </Button>
      </div>
      {refresh.error && (
        <div role="alert" className="mt-4 space-y-2 text-sm text-destructive">
          <p>{refresh.error.message}</p>
          <Button
            size="sm"
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
        </div>
      )}
      {choose.error && chooseAccount && (
        <div role="alert" className="mt-4 space-y-2 text-sm text-destructive">
          <p>{choose.error.message}</p>
          <Button
            size="sm"
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
        </div>
      )}
      {accounts.error ? (
        <ErrorState error={accounts.error} />
      ) : accounts.isPending ? (
        <LoadingRows />
      ) : (
        <div className="mt-5 space-y-3">
          {!accounts.data.length && (
            <p className="text-sm text-muted-foreground">
              No verified accounts yet. Connect an app below, then refresh.
            </p>
          )}
          {accounts.data.map((account) => (
            <div
              key={account.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border p-4"
            >
              <div>
                <p className="text-sm font-medium">{account.display_name}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {label(account.toolkit)} · {label(account.connection_status)}
                </p>
              </div>
              {account.selected_purpose === "outreach" ? (
                <Badge variant="outline">
                  <Check className="size-3" />
                  Outreach account
                </Badge>
              ) : (
                account.toolkit === "gmail" && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={
                      choose.isPending || account.connection_status !== "ACTIVE"
                    }
                    onClick={() => choose.mutate(account)}
                  >
                    Use for outreach
                  </Button>
                )
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
