"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  Check,
  ChevronDown,
  Cpu,
  KeyRound,
  Plus,
  RefreshCw,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  api,
  type Integrations,
  type ModelProvider,
  type Schema,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const PROVIDER_NAMES: Record<ModelProvider, string> = {
  openai: "OpenAI",
  gemini: "Gemini",
  mistral: "Mistral",
  cohere: "Cohere",
};
const providers = Object.keys(PROVIDER_NAMES) as ModelProvider[];

export function ModelSwitcher({
  provider,
  model,
  onSelect,
  disabled,
}: {
  provider: ModelProvider;
  model: string;
  onSelect: (provider: ModelProvider, model: string) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const restoreFocus = useRef(false);
  const [activeTab, setActiveTab] = useState<ModelProvider>(provider);
  const [search, setSearch] = useState("");
  const [customModel, setCustomModel] = useState("");
  const integrations = useQuery({
    queryKey: ["integrations"],
    queryFn: () => api<Integrations>("integrations"),
  });
  const connected = Boolean(integrations.data?.model_providers[activeTab]);
  const catalog = useQuery({
    queryKey: ["model-catalog", activeTab],
    queryFn: () =>
      api<Schema["DiscoveredModel"][]>(`agents/models?provider=${activeTab}`),
    enabled: open && connected,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
  const models = catalog.data?.filter((option) =>
    `${option.id} ${option.name}`.toLowerCase().includes(search.toLowerCase()),
  );
  const select = (id: string) => {
    onSelect(activeTab, id);
    setOpen(false);
  };

  return (
    <Popover
      open={open}
      onOpenChange={(nextOpen) => {
        if (nextOpen) {
          setActiveTab(provider);
          setSearch("");
          setCustomModel("");
        }
        setOpen(nextOpen);
      }}
    >
      <PopoverTrigger asChild>
        <Button
          ref={trigger}
          type="button"
          variant="ghost"
          size="sm"
          disabled={disabled}
          className="h-9 min-w-0 max-w-full shrink gap-1.5 rounded-full px-3 text-xs font-normal text-muted-foreground hover:bg-muted hover:text-foreground"
          aria-label="Switch AI model"
          title={`${PROVIDER_NAMES[provider]} · ${model}`}
        >
          <Cpu className="size-3.5 shrink-0" />
          <span className="truncate">{model}</span>
          <ChevronDown className="size-3 shrink-0 text-muted-foreground" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        side="top"
        className="max-h-[var(--radix-popover-content-available-height)] w-80 max-w-[calc(100vw-2rem)] overflow-y-auto rounded-xl p-0 shadow-xl"
        sideOffset={10}
        onEscapeKeyDown={() => {
          restoreFocus.current = true;
        }}
        onCloseAutoFocus={(event) => {
          // Refresh temporarily disables its button, which can move focus outside
          // the menu. Escape must still return to the picker in that case.
          if (restoreFocus.current) {
            event.preventDefault();
            trigger.current?.focus();
            restoreFocus.current = false;
          }
        }}
      >
        <div className="border-b border-border p-3">
          <h3 className="text-sm font-semibold">Choose a model</h3>
          <p className="mt-1 text-xs text-muted-foreground">
            Choose the model for your next message.
          </p>
        </div>
        <Tabs
          value={activeTab}
          onValueChange={(value) => {
            setActiveTab(value as ModelProvider);
            setSearch("");
            setCustomModel("");
          }}
          className="px-3 pt-3"
        >
          <TabsList className="grid w-full grid-cols-4">
            {providers.map((p) => (
              <TabsTrigger key={p} value={p} className="text-xs">
                {PROVIDER_NAMES[p]}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <div
          className="space-y-3 p-3"
          role="region"
          aria-label={`${PROVIDER_NAMES[activeTab]} models`}
        >
          {integrations.isPending ? (
            <p className="text-xs" role="status">
              Checking configured providers…
            </p>
          ) : integrations.error ? (
            <div role="alert" className="text-xs">
              Could not check configured providers.
              <Button
                type="button"
                variant="link"
                size="sm"
                onClick={() => void integrations.refetch()}
              >
                Try again
              </Button>
            </div>
          ) : !connected ? (
            <p className="flex items-center gap-2 text-xs text-muted-foreground">
              <KeyRound className="size-3.5" />
              {PROVIDER_NAMES[activeTab]} API key is not configured.
              <Link
                href="/settings"
                onClick={() => setOpen(false)}
                className="underline"
              >
                Settings
              </Link>
            </p>
          ) : (
            <>
              <div className="flex items-center gap-2">
                <Input
                  aria-label="Search models"
                  placeholder="Search models…"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  className="h-8 text-xs"
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label="Refresh models"
                  disabled={catalog.isFetching}
                  onClick={() => void catalog.refetch()}
                >
                  <RefreshCw
                    className={cn(
                      "size-3.5",
                      catalog.isFetching && "animate-spin",
                    )}
                  />
                </Button>
              </div>
              {catalog.isPending ? (
                <p role="status" className="text-xs text-muted-foreground">
                  Loading available models…
                </p>
              ) : null}
              {catalog.error ? (
                <p role="alert" className="text-xs text-destructive">
                  {catalog.error.message}
                </p>
              ) : null}
              <div
                className="max-h-64 space-y-1 overflow-y-auto"
                aria-label="Available models"
              >
                {models?.map((option) => (
                  <button
                    key={option.id}
                    type="button"
                    disabled={!option.selectable}
                    onClick={() => select(option.id)}
                    className={cn(
                      "flex w-full items-start justify-between gap-2 rounded-md p-2 text-left hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50",
                      provider === activeTab &&
                        model === option.id &&
                        "bg-muted",
                    )}
                    aria-pressed={provider === activeTab && model === option.id}
                  >
                    <span className="min-w-0">
                      <span className="block break-words text-xs font-medium">
                        {option.name}
                      </span>
                      {option.name !== option.id && (
                        <span className="block break-all text-[11px] text-muted-foreground">
                          {option.id}
                        </span>
                      )}
                      {!option.selectable && (
                        <span className="block text-[11px] text-muted-foreground">
                          {option.description}
                        </span>
                      )}
                    </span>
                    {provider === activeTab && model === option.id && (
                      <Check className="size-3.5 shrink-0 text-primary" />
                    )}
                  </button>
                ))}
                {models?.length === 0 && !catalog.error && (
                  <p className="p-2 text-xs text-muted-foreground">
                    No models found.
                  </p>
                )}
              </div>
              {catalog.data && (
                <p className="text-[11px] text-muted-foreground">
                  {catalog.data.length} models returned by{" "}
                  {PROVIDER_NAMES[activeTab]}. Availability and quota are
                  controlled by your provider.
                </p>
              )}
              <form
                className="flex items-center gap-2 border-t border-border pt-3"
                onSubmit={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  if (customModel.trim()) select(customModel.trim());
                }}
              >
                <Input
                  aria-label="Custom model ID"
                  placeholder="Custom model ID…"
                  value={customModel}
                  maxLength={100}
                  onChange={(event) => setCustomModel(event.target.value)}
                  className="h-8 text-xs"
                />
                <Button
                  type="submit"
                  size="sm"
                  variant="secondary"
                  disabled={!customModel.trim()}
                >
                  <Plus className="size-3" />
                  Use
                </Button>
              </form>
            </>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
