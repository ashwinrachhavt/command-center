"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { api, label, type Schema } from "@/lib/api";
import { ErrorState, LoadingRows, Spinner } from "./primitives";

export function ConnectedAccounts() {
  const client = useQueryClient();
  const accounts = useQuery({
    queryKey: ["connected-accounts"],
    queryFn: () =>
      api<Schema["AccountRead"][]>("integrations/composio/accounts"),
  });
  const refresh = useMutation({
    mutationFn: () =>
      api("integrations/composio/accounts/sync", { method: "POST", body: {} }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["connected-accounts"] });
      toast.success("Connected accounts refreshed");
    },
  });
  const choose = useMutation({
    mutationFn: (account: Schema["AccountRead"]) =>
      api(`integrations/composio/accounts/${account.id}/select`, {
        method: "POST",
        body: { purpose: "outreach", expected_version: account.row_version },
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["connected-accounts"] });
      toast.success("Outreach account selected");
    },
  });
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
      {(refresh.error || choose.error) && (
        <p role="alert" className="mt-4 text-sm text-destructive">
          {(refresh.error ?? choose.error)?.message}
        </p>
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
