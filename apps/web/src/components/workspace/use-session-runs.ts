"use client";

import { useQuery } from "@tanstack/react-query";
import { api, type Page, type Run } from "@/lib/api";

export const activeRunStates = new Set([
  "queued",
  "running",
  "waiting_for_user",
]);

export function useSessionRuns(sessionId?: string, limit = 10) {
  return useQuery({
    queryKey: ["agent-session-runs", sessionId, limit],
    enabled: !!sessionId,
    queryFn: ({ signal }) =>
      api<Page<Run>>(`agent-sessions/${sessionId}/runs?limit=${limit}`, {
        signal,
      }),
    refetchInterval: (query) =>
      query.state.data?.items.some((run) => activeRunStates.has(run.state))
        ? 10_000
        : 30_000,
    refetchOnWindowFocus: "always",
    refetchOnReconnect: "always",
  });
}
