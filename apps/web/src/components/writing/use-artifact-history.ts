"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { api, type Schema } from "@/lib/api";

export function useArtifactHistory(artifactId: string) {
  const query = useInfiniteQuery({
    queryKey: ["version-history", artifactId],
    enabled: !!artifactId,
    initialPageParam: null as number | null,
    queryFn: ({ pageParam }) =>
      api<Schema["VersionHistoryRead"]>(
        `artifacts/${artifactId}/version-history?limit=20${pageParam === null ? "" : `&before=${pageParam}`}`,
      ),
    getNextPageParam: (page) => page.next_before ?? undefined,
  });
  return {
    ...query,
    items: query.data?.pages.flatMap((page) => page.items) ?? [],
  };
}
