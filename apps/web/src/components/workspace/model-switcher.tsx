"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Check, ChevronDown, Cpu, KeyRound, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, label, type Integrations, type ModelProvider } from "@/lib/api";
import { cn } from "@/lib/utils";

export type ModelOption = {
  id: string;
  name: string;
  tag?: string;
  description: string;
};

export const MODEL_CATALOG: Record<ModelProvider, ModelOption[]> = {
  openai: [
    {
      id: "gpt-5-mini",
      name: "GPT-5 Mini",
      tag: "Default",
      description: "Fast reasoning and balanced performance for all tasks",
    },
    {
      id: "gpt-4o",
      name: "GPT-4o",
      tag: "Omni",
      description:
        "High-intelligence flagship model with deep multimodal reasoning",
    },
    {
      id: "gpt-4o-mini",
      name: "GPT-4o Mini",
      tag: "Fast",
      description:
        "Fast, lightweight model for high-frequency lightweight tasks",
    },
    {
      id: "o3-mini",
      name: "o3-mini",
      tag: "Reasoning",
      description:
        "Specialized deep reasoning model for complex logic and math",
    },
  ],
  gemini: [
    {
      id: "gemini-2.0-flash",
      name: "Gemini 2.0 Flash",
      tag: "Next-gen",
      description:
        "Next-generation speed with strong coding and multimodal capabilities",
    },
    {
      id: "gemini-1.5-pro",
      name: "Gemini 1.5 Pro",
      tag: "Large Context",
      description:
        "Exceptional 2M token context window and document understanding",
    },
    {
      id: "gemini-1.5-flash",
      name: "Gemini 1.5 Flash",
      tag: "Efficient",
      description: "Fast, cost-efficient model for quick research workflows",
    },
  ],
  mistral: [
    {
      id: "mistral-large-latest",
      name: "Mistral Large",
      tag: "Flagship",
      description:
        "Advanced reasoning, top-tier coding, and multilingual skills",
    },
    {
      id: "mistral-small-latest",
      name: "Mistral Small",
      tag: "Fast",
      description: "Cost-efficient performance for low-latency tasks",
    },
  ],
  cohere: [
    {
      id: "command-r-plus",
      name: "Command R+",
      tag: "Enterprise",
      description: "Optimized for enterprise conversational search and RAG",
    },
    {
      id: "command-r",
      name: "Command R",
      tag: "Fast",
      description: "Scalable language model for summarization and drafting",
    },
  ],
};

const PROVIDER_NAMES: Record<ModelProvider, string> = {
  openai: "OpenAI",
  gemini: "Gemini",
  mistral: "Mistral",
  cohere: "Cohere",
};

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
  const [activeTab, setActiveTab] = useState<ModelProvider>(provider);
  const [customModel, setCustomModel] = useState("");

  const integrations = useQuery({
    queryKey: ["integrations"],
    queryFn: () => api<Integrations>("integrations"),
  });

  const providers = Object.keys(MODEL_CATALOG) as ModelProvider[];
  const isProviderConnected = (p: ModelProvider) =>
    Boolean(integrations.data?.model_providers[p]);

  const handleSelect = (p: ModelProvider, m: string) => {
    onSelect(p, m);
    setOpen(false);
  };

  const handleCustomSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (customModel.trim()) {
      handleSelect(activeTab, customModel.trim());
      setCustomModel("");
    }
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled}
          className="h-8 gap-1.5 border-border bg-background/50 px-2.5 text-xs font-normal hover:bg-muted"
          aria-label="Switch AI model"
        >
          <Cpu className="size-3.5 text-primary" />
          <span className="font-medium text-foreground">
            {label(provider)} · {model}
          </span>
          <ChevronDown className="size-3 text-muted-foreground" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 p-0 sm:w-96" sideOffset={6}>
        <div className="border-b border-border p-3">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-semibold tracking-tight text-foreground">
              Select AI Model & Account
            </h3>
            <span className="text-[10px] text-muted-foreground">
              Default spend limits apply
            </span>
          </div>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            Switch provider accounts and models without manual spend setup.
          </p>
        </div>

        <Tabs
          value={activeTab}
          onValueChange={(val) => setActiveTab(val as ModelProvider)}
          className="w-full"
        >
          <div className="border-b border-border px-3 pt-2">
            <TabsList className="grid h-7 w-full grid-cols-4 bg-muted/60 p-0.5">
              {providers.map((p) => {
                const connected = isProviderConnected(p);
                return (
                  <TabsTrigger
                    key={p}
                    value={p}
                    className="relative text-[11px] data-[state=active]:bg-background"
                  >
                    {PROVIDER_NAMES[p]}
                    <span
                      className={cn(
                        "ml-1 size-1.5 rounded-full",
                        connected ? "bg-emerald-500" : "bg-amber-500",
                      )}
                      title={connected ? "Connected" : "API key needed"}
                    />
                  </TabsTrigger>
                );
              })}
            </TabsList>
          </div>

          {providers.map((p) => {
            const connected = isProviderConnected(p);
            const models = MODEL_CATALOG[p];
            return (
              <TabsContent
                key={p}
                value={p}
                className="mt-0 space-y-2 p-3 outline-none"
              >
                {!connected && (
                  <div className="flex items-center justify-between rounded-md border border-amber-500/20 bg-amber-500/10 px-2.5 py-1.5 text-[11px] text-amber-500">
                    <span className="flex items-center gap-1.5">
                      <KeyRound className="size-3" />
                      {PROVIDER_NAMES[p]} API key not set in environment
                    </span>
                    <Link
                      href="/settings"
                      onClick={() => setOpen(false)}
                      className="underline underline-offset-2 hover:text-foreground"
                    >
                      Settings
                    </Link>
                  </div>
                )}

                <div className="max-h-56 space-y-1 overflow-y-auto">
                  {models.map((opt) => {
                    const isSelected = provider === p && model === opt.id;
                    return (
                      <button
                        key={opt.id}
                        type="button"
                        onClick={() => handleSelect(p, opt.id)}
                        className={cn(
                          "flex w-full flex-col rounded-md p-2 text-left transition-colors hover:bg-muted/80",
                          isSelected && "bg-muted font-medium",
                        )}
                      >
                        <div className="flex w-full items-center justify-between">
                          <span className="text-xs text-foreground">
                            {opt.name}
                          </span>
                          <div className="flex items-center gap-1.5">
                            {opt.tag && (
                              <Badge
                                variant="secondary"
                                className="h-4 px-1 text-[9px] font-normal"
                              >
                                {opt.tag}
                              </Badge>
                            )}
                            {isSelected && (
                              <Check className="size-3 text-primary" />
                            )}
                          </div>
                        </div>
                        <p className="mt-0.5 line-clamp-1 text-[10px] text-muted-foreground">
                          {opt.description}
                        </p>
                      </button>
                    );
                  })}
                </div>

                <form
                  onSubmit={handleCustomSubmit}
                  className="flex items-center gap-1.5 border-t border-border pt-2"
                >
                  <Input
                    placeholder="Custom model ID (e.g. gpt-4.5)…"
                    value={customModel}
                    onChange={(e) => setCustomModel(e.target.value)}
                    className="h-7 text-xs"
                    aria-label="Custom model ID"
                  />
                  <Button
                    type="submit"
                    size="sm"
                    variant="secondary"
                    className="h-7 px-2 text-xs"
                    disabled={!customModel.trim()}
                  >
                    <Plus className="size-3 mr-1" />
                    Use
                  </Button>
                </form>
              </TabsContent>
            );
          })}
        </Tabs>
      </PopoverContent>
    </Popover>
  );
}
