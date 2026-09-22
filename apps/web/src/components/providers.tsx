"use client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Toaster } from "@/components/ui/sonner";
import { AppearanceProvider } from "@/components/appearance";

export function Providers({ children }: { children: React.ReactNode }) {
  const { isLoaded, userId } = useAuth();
  return (
    <AppearanceProvider>
      <QueryScope key={isLoaded ? (userId ?? "anonymous") : "resolving"}>
        {isLoaded ? (
          children
        ) : (
          <div role="status" className="p-6 text-sm text-muted-foreground">
            Loading workspace…
          </div>
        )}
      </QueryScope>
    </AppearanceProvider>
  );
}

function QueryScope({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { staleTime: 15_000, retry: false },
          mutations: { retry: false },
        },
      }),
  );
  useEffect(
    () => () => {
      void client.cancelQueries();
      client.clear();
    },
    [client],
  );
  return (
    <QueryClientProvider client={client}>
      <TooltipProvider>
        {children}
        <Toaster richColors position="bottom-right" />
      </TooltipProvider>
    </QueryClientProvider>
  );
}
