"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Save, Wallet, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Field, FieldLabel } from "@/components/ui/field";
import { Badge } from "@/components/ui/badge";
import { api, type Schema } from "@/lib/api";
import { ErrorState, LoadingRows, Spinner } from "./primitives";

type Summary = Schema["SpendingSummary"];
type RateCard = Schema["RateCardRead"];
const selectStyle =
  "h-9 w-full rounded-md border border-input bg-background px-3 text-sm";
export const money = (micros: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 4,
  }).format(micros / 1_000_000);

function micros(value: string) {
  if (!/^\d+(?:\.\d{1,6})?$/.test(value))
    throw new Error("Enter a nonnegative USD amount with up to six decimals.");
  const [whole, fraction = ""] = value.split(".");
  const amount = Number(whole) * 1_000_000 + Number(fraction.padEnd(6, "0"));
  if (!Number.isSafeInteger(amount))
    throw new Error("That amount is too large.");
  return amount;
}

function DollarField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <Field>
      <FieldLabel>
        {label}
        <span className="sr-only"> (USD)</span>
      </FieldLabel>
      <Input
        aria-label={`${label} (USD)`}
        inputMode="decimal"
        placeholder="0.00"
        required
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </Field>
  );
}

function RateCardEditor({ done }: { done: (id: string) => void }) {
  const catalog = useQuery({
    queryKey: ["spending-catalog"],
    queryFn: () => api<Schema["SpendingCatalog"]>("spending/catalog"),
  });
  const [name, setName] = useState("");
  const [source, setSource] = useState("");
  const [models, setModels] = useState([
    {
      id: crypto.randomUUID(),
      provider: "openai",
      model: "",
      input: "",
      output: "",
      fixed: "",
    },
  ]);
  const [tools, setTools] = useState<
    { id: string; slug: string; fixed: string }[]
  >([]);
  const save = useMutation({
    mutationFn: () =>
      api<RateCard>("spending/rate-cards", {
        method: "POST",
        body: {
          name,
          source_label: source,
          models: models.map((row) => ({
            provider: row.provider,
            model: row.model,
            input_per_million_micros: micros(row.input),
            output_per_million_micros: micros(row.output),
            fixed_micros: micros(row.fixed),
          })),
          tools: tools.map((row) => ({
            slug: row.slug,
            fixed_micros: micros(row.fixed),
          })),
        } satisfies Schema["RateCardCreate"],
      }),
    onSuccess: (card) => {
      done(card.id);
      toast.success("Rate card saved");
    },
  });
  return (
    <form
      className="space-y-5 rounded-lg border border-border bg-muted/20 p-4"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <div>
        <h3 className="text-sm font-medium">Create a rate card</h3>
        <p className="mt-1 text-xs text-muted-foreground">
          Enter conservative rates from your provider plan. Each card is
          immutable; new prices require a new card. Missing rates block the
          affected call.
        </p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field>
          <FieldLabel htmlFor="rate-name">Name</FieldLabel>
          <Input
            id="rate-name"
            required
            maxLength={200}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>
        <Field>
          <FieldLabel htmlFor="rate-source">Pricing source or plan</FieldLabel>
          <Input
            id="rate-source"
            required
            maxLength={500}
            value={source}
            onChange={(e) => setSource(e.target.value)}
          />
        </Field>
      </div>
      {models.map((row) => (
        <div className="space-y-3 border-t border-border pt-4" key={row.id}>
          <div className="flex items-end gap-2">
            <Field className="flex-1">
              <FieldLabel>Provider</FieldLabel>
              <select
                aria-label="Rate provider"
                className={selectStyle}
                value={row.provider}
                onChange={(e) =>
                  setModels(
                    models.map((item) =>
                      item.id === row.id
                        ? { ...item, provider: e.target.value }
                        : item,
                    ),
                  )
                }
              >
                {["openai", "gemini", "mistral", "cohere"].map((provider) => (
                  <option key={provider}>{provider}</option>
                ))}
              </select>
            </Field>
            <Field className="flex-1">
              <FieldLabel>Model ID</FieldLabel>
              <Input
                aria-label="Rate model ID"
                list={`models-${row.id}`}
                required
                maxLength={200}
                value={row.model}
                onChange={(e) =>
                  setModels(
                    models.map((item) =>
                      item.id === row.id
                        ? { ...item, model: e.target.value }
                        : item,
                    ),
                  )
                }
              />
              <datalist id={`models-${row.id}`}>
                {catalog.data?.models
                  .filter((model) => model.provider === row.provider)
                  .map((model) => (
                    <option key={model.model} value={model.model}>
                      {model.label}
                    </option>
                  ))}
              </datalist>
            </Field>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label="Remove model rate"
              onClick={() =>
                setModels(models.filter((item) => item.id !== row.id))
              }
            >
              <X />
            </Button>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            {(
              [
                ["input", "Input / million tokens"],
                ["output", "Output / million tokens"],
                ["fixed", "Additional / call"],
              ] as const
            ).map(([key, title]) => (
              <DollarField
                key={key}
                label={title}
                value={row[key]}
                onChange={(value) =>
                  setModels(
                    models.map((item) =>
                      item.id === row.id ? { ...item, [key]: value } : item,
                    ),
                  )
                }
              />
            ))}
          </div>
        </div>
      ))}
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() =>
          setModels([
            ...models,
            {
              id: crypto.randomUUID(),
              provider: "openai",
              model: "",
              input: "",
              output: "",
              fixed: "",
            },
          ])
        }
      >
        <Plus />
        Model rate
      </Button>
      {tools.map((row) => (
        <div className="flex items-end gap-2" key={row.id}>
          <Field className="flex-1">
            <FieldLabel>Connected tool ID</FieldLabel>
            <select
              className={selectStyle}
              aria-label="Connected tool ID"
              required
              value={row.slug}
              onChange={(e) =>
                setTools(
                  tools.map((item) =>
                    item.id === row.id
                      ? { ...item, slug: e.target.value }
                      : item,
                  ),
                )
              }
            >
              <option value="">Choose an operation</option>
              {catalog.data?.tools.map((tool) => (
                <option value={tool.slug} key={tool.slug}>
                  {tool.label}
                </option>
              ))}
            </select>
            {row.slug && (
              <p className="break-all text-[10px] text-muted-foreground">
                {row.slug}
              </p>
            )}
          </Field>
          <DollarField
            label="Maximum / call"
            value={row.fixed}
            onChange={(value) =>
              setTools(
                tools.map((item) =>
                  item.id === row.id ? { ...item, fixed: value } : item,
                ),
              )
            }
          />
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="Remove tool rate"
            onClick={() => setTools(tools.filter((item) => item.id !== row.id))}
          >
            <X />
          </Button>
        </div>
      ))}
      <div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() =>
            setTools([
              ...tools,
              { id: crypto.randomUUID(), slug: "", fixed: "" },
            ])
          }
        >
          <Plus />
          Connected tool rate
        </Button>
        <p className="mt-2 text-xs text-muted-foreground">
          Include account lookup and file upload operations when using connected
          apps. Enter 0 explicitly only when your plan guarantees no charge.
        </p>
        {catalog.error && (
          <ErrorState error={catalog.error} retry={() => catalog.refetch()} />
        )}
      </div>
      {save.error && (
        <p role="alert" className="text-sm text-destructive">
          {save.error.message}
        </p>
      )}
      <Button disabled={save.isPending}>
        {save.isPending ? <Spinner /> : <Save />}Save rate card
      </Button>
    </form>
  );
}

function PolicyForm({
  summary,
  cards,
}: {
  summary: Summary;
  cards: RateCard[];
}) {
  const client = useQueryClient();
  const [cardId, setCardId] = useState(summary.rate_card_id ?? "");
  const [monthly, setMonthly] = useState(
    summary.monthly_limit_micros === null
      ? ""
      : String(summary.monthly_limit_micros / 1_000_000),
  );
  const [work, setWork] = useState(
    summary.default_work_limit_micros === null
      ? ""
      : String(summary.default_work_limit_micros / 1_000_000),
  );
  const [active, setActive] = useState(summary.active);
  const [adding, setAdding] = useState(!cards.length);
  const save = useMutation({
    mutationFn: () =>
      api("spending/policy", {
        method: "PUT",
        body: {
          rate_card_id: cardId,
          monthly_limit_micros: micros(monthly),
          default_work_limit_micros: micros(work),
          active,
          expected_version: summary.row_version ?? 0,
        } satisfies Schema["PolicyUpdate"],
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["spending"] });
      toast.success("Spending limits saved");
    },
  });
  const selectedCard = cards.find((card) => card.id === cardId);
  return (
    <div className="space-y-5">
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <DollarField
            label="Monthly limit"
            value={monthly}
            onChange={setMonthly}
          />
          <DollarField
            label="Default work limit"
            value={work}
            onChange={setWork}
          />
        </div>
        <p className="text-xs text-muted-foreground">
          Calendar months use UTC. Each task, opportunity or standalone run
          shares one work budget across its model and connected-app calls.
        </p>
        <Field>
          <FieldLabel htmlFor="active-rate-card">Rate card</FieldLabel>
          <select
            id="active-rate-card"
            className={selectStyle}
            required
            value={cardId}
            onChange={(e) => setCardId(e.target.value)}
          >
            <option value="">Choose a rate card</option>
            {cards.map((card) => (
              <option value={card.id} key={card.id}>
                {card.name}
              </option>
            ))}
          </select>
        </Field>
        {selectedCard && (
          <p className="text-xs text-muted-foreground">
            {selectedCard.source_label} · {selectedCard.rates.models.length}{" "}
            model rates · {selectedCard.rates.tools.length} tool rates
          </p>
        )}
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={active}
            onChange={(e) => setActive(e.target.checked)}
          />
          Enable paid calls within these limits
        </label>
        {save.error && (
          <p role="alert" className="text-sm text-destructive">
            {save.error.message}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          <Button disabled={save.isPending || !cardId}>
            {save.isPending ? <Spinner /> : <Save />}Save limits
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => setAdding(!adding)}
          >
            {adding ? "Close rate editor" : "New rate card"}
          </Button>
        </div>
      </form>
      {adding && (
        <RateCardEditor
          done={(id) => {
            setCardId(id);
            setAdding(false);
            void client.invalidateQueries({
              queryKey: ["spending-rate-cards"],
            });
          }}
        />
      )}
    </div>
  );
}

export function SpendingSettings() {
  const summary = useQuery({
    queryKey: ["spending"],
    queryFn: () => api<Summary>("spending"),
    refetchInterval: 15000,
  });
  const cards = useQuery({
    queryKey: ["spending-rate-cards"],
    queryFn: () => api<RateCard[]>("spending/rate-cards"),
  });
  return (
    <section className="rounded-xl border border-border bg-card p-6">
      <div className="mb-5 flex items-center gap-2">
        <Wallet className="size-4 text-primary" />
        <h2 className="text-sm font-medium">Spending controls</h2>
        {summary.data && (
          <Badge variant="outline">
            {summary.data.active ? "Active" : "Paid calls paused"}
          </Badge>
        )}
      </div>
      {summary.error || cards.error ? (
        <ErrorState error={summary.error ?? cards.error!} />
      ) : !summary.data || !cards.data ? (
        <LoadingRows />
      ) : (
        <>
          {summary.data.readiness && (
            <p className="mb-4 text-sm text-muted-foreground">
              {summary.data.readiness.message}
            </p>
          )}
          {summary.data.period && (
            <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
              {(
                [
                  ["Accounted", summary.data.period.accounted_micros],
                  ["Reserved", summary.data.period.reserved_micros],
                  ["Unknown", summary.data.period.unknown_micros],
                  [
                    "Remaining",
                    Math.max(
                      0,
                      summary.data.period.limit_micros -
                        summary.data.period.committed_micros,
                    ),
                  ],
                ] as const
              ).map(([title, amount]) => (
                <div
                  key={title}
                  className="rounded-lg border border-border p-3"
                >
                  <p className="text-xs text-muted-foreground">{title}</p>
                  <p className="mt-2 font-mono text-sm">{money(amount)}</p>
                </div>
              ))}
            </div>
          )}
          <PolicyForm
            key={summary.data.row_version ?? "unconfigured"}
            summary={summary.data}
            cards={cards.data}
          />
          <p className="mt-5 text-xs leading-5 text-muted-foreground">
            {summary.data.invoice_note} Reservations also cover concurrent chats
            and specialist calls. Reaching a limit pauses work without automatic
            top-ups.
          </p>
        </>
      )}
    </section>
  );
}
