"use client";

import {
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import { api, type AgentMessage, type Page } from "@/lib/api";

const pageSize = 100;
type Transcript = Page<AgentMessage> & { confirmedSequence?: number };
export const sessionMessageKey = (sessionId?: string) =>
  ["agent-session-messages", sessionId] as const;

function mergeMessages(...groups: AgentMessage[][]) {
  const messages = new Map<string, AgentMessage>();
  for (const group of groups)
    for (const message of group) messages.set(message.id, message);
  return [...messages.values()].sort((a, b) => a.sequence - b.sequence);
}

export function appendSavedMessage(client: QueryClient, message: AgentMessage) {
  client.setQueryData<Transcript>(
    sessionMessageKey(message.session_id),
    (cached) => {
      const items = mergeMessages(cached?.items ?? [], [message]);
      return {
        items,
        total: Math.max(cached?.total ?? 0, items.length),
        limit: pageSize,
        offset: 0,
        // A saved reply may arrive before unread messages from another tab.
        // Only paginated reads can advance the contiguous transcript cursor.
        confirmedSequence:
          cached?.confirmedSequence ?? cached?.items.at(-1)?.sequence ?? 0,
      };
    },
  );
}

export function useSessionMessages(sessionId?: string, active = false) {
  const client = useQueryClient();
  const key = sessionMessageKey(sessionId);
  return useQuery({
    queryKey: key,
    enabled: !!sessionId,
    queryFn: async ({ signal }): Promise<Transcript> => {
      const cached = client.getQueryData<Transcript>(key);
      let cursor =
        cached?.confirmedSequence ?? cached?.items.at(-1)?.sequence ?? 0;
      const received: AgentMessage[] = [];
      let page: Page<AgentMessage>;
      do {
        signal.throwIfAborted();
        page = await api<Page<AgentMessage>>(
          `agent-sessions/${sessionId}/messages?after_sequence=${cursor}&limit=${pageSize}`,
          { signal },
        );
        signal.throwIfAborted();
        received.push(...page.items);
        const next = page.items.at(-1)?.sequence ?? cursor;
        if (next <= cursor) break;
        cursor = next;
      } while (page.items.length === pageSize);
      const latest = client.getQueryData<Transcript>(key);
      const items = mergeMessages(
        cached?.items ?? [],
        latest?.items ?? [],
        received,
      );
      return {
        items,
        total: items.length,
        limit: pageSize,
        offset: 0,
        confirmedSequence: cursor,
      };
    },
    staleTime: 10_000,
    // SSE reconciles completed turns immediately. This bounded fallback also
    // discovers instructions saved in other tabs without downloading history.
    refetchInterval: active ? 15_000 : 30_000,
    refetchOnWindowFocus: "always",
    refetchOnReconnect: "always",
  });
}
