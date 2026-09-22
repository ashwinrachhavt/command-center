"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { api, type Activity, type Page } from "@/lib/api";
import { ActivityList } from "./activity-list";
import { EmptyState, ErrorState, LoadingRows, PageHeading } from "./primitives";
export function ActivityPage() {
  const [offset, setOffset] = useState(0);
  const query = useQuery({
    queryKey: ["activity", offset],
    queryFn: () => api<Page<Activity>>(`activity?limit=30&offset=${offset}`),
  });
  return (
    <>
      <PageHeading
        title="Activity"
        description="A clear, lasting history of your workspace."
      />
      <div className="mx-5 max-w-4xl md:mx-9">
        {query.error ? (
          <ErrorState error={query.error} />
        ) : query.isPending ? (
          <LoadingRows />
        ) : query.data.items.length === 0 ? (
          <EmptyState
            title="Your story is just getting started"
            description="Created records, changes, agent runs and reviews will appear here."
          />
        ) : (
          <ActivityList events={query.data.items} />
        )}
        <div className="mt-4 flex justify-between">
          <Button
            variant="outline"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - 30))}
          >
            Previous
          </Button>
          <Button
            variant="outline"
            disabled={offset + 30 >= (query.data?.total ?? 0)}
            onClick={() => setOffset(offset + 30)}
          >
            Next
          </Button>
        </div>
      </div>
    </>
  );
}
