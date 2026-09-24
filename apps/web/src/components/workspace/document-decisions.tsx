"use client";

import Link from "next/link";
import { useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api, type Schema } from "@/lib/api";
import { RetainedRequestIntent } from "@/lib/retained-intent";
import { useWorkspaceContext } from "./context";
import { ErrorState, LoadingRows, Spinner } from "./primitives";

type Policy = Schema["DocumentPolicyRead"];
type Classification = Schema["DocumentClassificationRead"];
type Decision = Schema["DocumentDecisionRead"];
type Rename = Schema["DocumentRenameRead"];
type DocumentType = { id: string; name: string; slug: string };
const selectStyle =
  "h-9 w-full rounded-md border border-input bg-background px-3 text-sm";
const percent = (value: unknown) =>
  typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "Unavailable";

function useDocumentTypes() {
  return useQuery({
    queryKey: ["document-types"],
    queryFn: () => api<DocumentType[]>("document-types"),
  });
}

function JsonDetails({ value }: { value: unknown }) {
  return (
    <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all rounded-md bg-muted/40 p-3 text-xs leading-5">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function PolicyForm({
  policy,
  types,
}: {
  policy: Policy;
  types: DocumentType[];
}) {
  const client = useQueryClient();
  const id = useId();
  const [draft, setDraft] = useState(policy);
  const [acknowledged, setAcknowledged] = useState(false);
  const [intent] = useState(() => new RetainedRequestIntent());
  const save = useMutation({
    mutationFn: () => {
      const body = {
        expected_version: draft.revision,
        classification_mode: draft.classification_mode,
        catalog_ids: draft.catalog_ids,
        rename_mode: draft.rename_mode,
        rename_template: draft.rename_template,
        timezone: draft.timezone,
        external_processing_ack: acknowledged,
      } satisfies Schema["DocumentPolicyUpdate"];
      const request = intent.forRequest("PUT", "documents/policy", body);
      return api<Policy>("documents/policy", {
        method: "PUT",
        body,
        key: request.key,
      });
    },
    onSuccess: (result) => {
      intent.reset();
      setDraft(result);
      setAcknowledged(false);
      client.setQueryData(["document-policy"], result);
      void client.invalidateQueries({ queryKey: ["document-classification"] });
      toast.success("Document settings saved.");
    },
  });
  const preview = draft.rename_template.replace(
    /\{(type|uploaded_date|short_id)\}/g,
    (_match, token: string) =>
      ({
        type: "Research paper",
        uploaded_date: "2026-01-15",
        short_id: "a1b2c3d4",
      })[token] ?? "",
  );
  return (
    <form
      className="space-y-5"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <div className="grid gap-5 sm:grid-cols-2">
        <label className="space-y-2 text-sm" htmlFor={`${id}-classification`}>
          <span>Automatic classification</span>
          <select
            id={`${id}-classification`}
            className={selectStyle}
            value={draft.classification_mode}
            disabled={save.isPending}
            onChange={(event) =>
              setDraft({
                ...draft,
                classification_mode: event.target
                  .value as Policy["classification_mode"],
              })
            }
          >
            <option value="off">Off</option>
            <option value="after_extraction">Suggest after extraction</option>
          </select>
        </label>
        <label className="space-y-2 text-sm" htmlFor={`${id}-rename`}>
          <span>Renaming</span>
          <select
            id={`${id}-rename`}
            className={selectStyle}
            value={draft.rename_mode}
            disabled={save.isPending}
            onChange={(event) =>
              setDraft({
                ...draft,
                rename_mode: event.target.value as Policy["rename_mode"],
              })
            }
          >
            <option value="off">Off</option>
            <option value="task">Create a rename task</option>
          </select>
        </label>
      </div>
      <fieldset disabled={save.isPending} className="space-y-3">
        <legend className="mb-2 text-sm font-medium">
          Classification catalog
        </legend>
        <div className="grid gap-3 sm:grid-cols-2">
          {types
            .filter((type) => type.slug !== "unclassified")
            .map((type) => (
              <label key={type.id} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={draft.catalog_ids.includes(type.id)}
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      catalog_ids: event.target.checked
                        ? [...draft.catalog_ids, type.id]
                        : draft.catalog_ids.filter(
                            (value) => value !== type.id,
                          ),
                    })
                  }
                />
                {type.name}
              </label>
            ))}
        </div>
      </fieldset>
      <label className="block space-y-2 text-sm" htmlFor={`${id}-template`}>
        <span>Vault title template</span>
        <Input
          id={`${id}-template`}
          value={draft.rename_template}
          maxLength={250}
          disabled={save.isPending}
          onChange={(event) =>
            setDraft({ ...draft, rename_template: event.target.value })
          }
        />
        <span className="block text-xs text-muted-foreground">
          Use {"{type}"}, {"{uploaded_date}"} and {"{short_id}"}. Upload dates
          use {draft.timezone}. Original filenames stay unchanged.
        </span>
        <span className="block break-words rounded-md bg-muted/40 p-3 text-xs">
          Example preview: {preview || "Enter a template"}
        </span>
      </label>
      <p className="text-xs leading-5 text-muted-foreground">
        Suggestions use extracted text sent to {policy.provider}. Provider:{" "}
        {policy.provider_ready ? "configured" : "not configured"}. Enabling
        automation applies to new completed extractions; existing documents are
        assessed only when selected. Type changes and title changes each require
        your review.
      </p>
      {draft.classification_mode === "after_extraction" && (
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            className="mt-1"
            checked={acknowledged}
            disabled={save.isPending}
            onChange={(event) => setAcknowledged(event.target.checked)}
          />
          I allow extracted text from new documents to be sent to the configured
          Jev provider.
        </label>
      )}
      {draft.revision !== policy.revision && (
        <div role="status" className="space-y-2 text-sm">
          <p>
            Settings changed since you opened this form. Your edits are still
            here.
          </p>
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              setDraft(policy);
              setAcknowledged(false);
              intent.reset();
              save.reset();
            }}
          >
            Load saved settings
          </Button>
        </div>
      )}
      {save.error && (
        <p role="alert" className="text-sm text-destructive">
          {save.error.message}
        </p>
      )}
      <Button
        disabled={
          save.isPending ||
          (draft.classification_mode === "after_extraction" &&
            (!acknowledged || !policy.provider_ready))
        }
      >
        {save.isPending && <Spinner />}Save document settings
      </Button>
    </form>
  );
}

export function DocumentSettings() {
  const policy = useQuery({
    queryKey: ["document-policy"],
    queryFn: () => api<Policy>("documents/policy"),
  });
  const types = useDocumentTypes();
  return (
    <section
      id="documents"
      aria-labelledby="document-settings-title"
      className="rounded-xl border border-border bg-card p-6"
    >
      <h2 id="document-settings-title" className="text-sm font-medium">
        Documents
      </h2>
      <p className="mb-6 mt-2 text-xs text-muted-foreground">
        Suggest a type from extracted text, then review a useful title.
      </p>
      {policy.error ? (
        <ErrorState error={policy.error} retry={() => policy.refetch()} />
      ) : types.error ? (
        <ErrorState error={types.error} retry={() => types.refetch()} />
      ) : !policy.data || !types.data ? (
        <LoadingRows />
      ) : (
        <PolicyForm policy={policy.data} types={types.data} />
      )}
    </section>
  );
}

function ModelJudgment({
  decision,
  types,
}: {
  decision: Decision;
  types: DocumentType[];
}) {
  const answers = decision.answers as Record<
    string,
    Record<string, unknown>
  > | null;
  const choice = answers?.document_type;
  const probabilities = choice?.probabilities as
    Record<string, number> | undefined;
  const selected = typeof choice?.choice === "string" ? choice.choice : null;
  const name = types.find((type) => type.id === selected)?.name ?? selected;
  const signals = [
    ["sufficient_evidence", "Readable evidence is sufficient"],
    ["incompatible_purposes", "Incompatible document purposes are present"],
    [
      "processing_instructions",
      "Instructions directed at the processor are present",
    ],
    ["explicit_commitment", "A concrete future commitment is stated"],
    ["follow_up_requested", "A reply or next action is explicitly requested"],
    ["deadline_present", "A deadline or response window is mentioned"],
  ];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="text-sm font-medium">Model judgment</h4>
        <span className="text-xs text-muted-foreground">
          {decision.provenance
            ? `${decision.provenance.replaceAll("_", " ")} result`
            : "No completed model result"}
        </span>
      </div>
      {decision.error && (
        <p role="status" className="text-sm">
          Assessment unavailable: {decision.error}
        </p>
      )}
      {answers ? (
        <dl className="space-y-2 text-sm">
          <div className="flex flex-wrap justify-between gap-2">
            <dt>Choice · document type</dt>
            <dd className="font-medium">{name}</dd>
          </div>
          <div className="flex flex-wrap justify-between gap-2">
            <dt>Selected choice probability</dt>
            <dd>{percent(selected ? probabilities?.[selected] : undefined)}</dd>
          </div>
          <div className="flex flex-wrap justify-between gap-2">
            <dt>Choice confidence</dt>
            <dd>{percent(choice?.confidence)}</dd>
          </div>
          {signals.map(([key, title]) => (
            <div key={key} className="flex flex-wrap justify-between gap-2">
              <dt>Noul · {title}</dt>
              <dd>{percent(answers[key]?.noul)}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="text-sm text-muted-foreground">
          {["queued", "running"].includes(decision.state)
            ? "Assessing the saved extraction…"
            : "No typed answer is available."}
        </p>
      )}
      {answers && <AdditionalJudgments answers={answers} />}
      <div className="rounded-md border border-border bg-muted/30 p-4">
        <h4 className="text-sm font-medium">Application policy</h4>
        <p className="mt-2 text-sm">
          A suggestion can help your review. It cannot change a type or title
          without your confirmation.
        </p>
        <p className="mt-2 text-xs text-muted-foreground">
          Commitment and follow-up signals are reading aids. A deadline mention
          does not establish urgency, an assigned task or permission to act.
        </p>
        {decision.reason_codes.length > 0 && (
          <ul className="mt-2 list-inside list-disc text-xs leading-6 text-muted-foreground">
            {decision.reason_codes.map((reason) => (
              <li key={reason}>{reason.replaceAll("_", " ")}</li>
            ))}
          </ul>
        )}
      </div>
      <details className="rounded-md border border-border p-4">
        <summary className="cursor-pointer text-sm font-medium">
          Inspect this decision
        </summary>
        <div className="mt-4 space-y-4">
          <p className="break-words text-xs">
            Requested model: {decision.requested_model}. Returned:{" "}
            {decision.returned_model ?? "unavailable"}. Resolved version:{" "}
            {decision.resolved_model ?? "unavailable"}. Cost status:{" "}
            {decision.cost_status}.
          </p>
          <div>
            <h5 className="mb-2 text-xs font-medium">Evidence sent</h5>
            <blockquote className="max-h-56 overflow-auto whitespace-pre-wrap break-words border-l-2 border-border pl-3 text-sm">
              {decision.excerpt || "No excerpt available."}
            </blockquote>
          </div>
          <div>
            <h5 className="mb-2 text-xs font-medium">
              State and source manifest
            </h5>
            <JsonDetails
              value={{
                source_version_id: decision.source_version_id,
                extraction_version_id: decision.extraction_version_id,
                state_hash: decision.state_hash,
                catalog: decision.catalog_snapshot,
                input: decision.input_manifest,
              }}
            />
          </div>
          <div>
            <h5 className="mb-2 text-xs font-medium">Exact typed questions</h5>
            <JsonDetails value={decision.questions} />
          </div>
          <div>
            <h5 className="mb-2 text-xs font-medium">
              Typed answers and usage
            </h5>
            <JsonDetails
              value={{
                answers: decision.answers,
                usage: decision.usage,
                question_version: decision.question_version,
                policy_version: decision.policy_version,
              }}
            />
          </div>
          <p className="text-xs text-muted-foreground">
            The model can misunderstand a document or miss an instruction.
            Probabilities are not guarantees. Original files and prior decisions
            stay preserved.
          </p>
        </div>
      </details>
    </div>
  );
}

function AdditionalJudgments({
  answers,
}: {
  answers: Record<string, Record<string, unknown>>;
}) {
  const fields = [
    ["relevance", "Relevance to the research question"],
    ["evidence_role", "Role in the evidence"],
    ["claim_supported", "The supplied claim is supported by this text"],
    ["output_quality", "How well this text addresses the agent request"],
    ["policy_concern", "The text raises a concern under the supplied policy"],
    [
      "action_matches_request",
      "The proposed action matches the supplied request",
    ],
  ].filter(([key]) => answers[key]);
  if (!fields.length) return null;
  return (
    <div className="space-y-3 border-t border-border pt-4">
      <h4 className="text-sm font-medium">Research and agent checks</h4>
      <dl className="space-y-4 text-sm">
        {fields.map(([key, label]) => {
          const answer = answers[key];
          const probabilities = answer.probabilities as
            Record<string, number> | undefined;
          const choice = typeof answer.choice === "string" ? answer.choice : "";
          return (
            <div key={key} className="space-y-1">
              <dt>{label}</dt>
              <dd className="font-medium">
                {answer.type === "score"
                  ? `Score: ${Number(answer.score).toFixed(2)} / 2`
                  : answer.type === "choice"
                    ? choice.replaceAll("_", " ")
                    : percent(answer.noul)}
              </dd>
              {answer.type !== "noul" && (
                <dd className="text-xs text-muted-foreground">
                  {answer.type === "choice" &&
                    `Selected probability: ${percent(probabilities?.[choice])}. `}
                  {answer.type === "score" ? "Score" : "Choice"} confidence:{" "}
                  {percent(answer.confidence)}.
                </dd>
              )}
            </div>
          );
        })}
      </dl>
      <p className="text-xs text-muted-foreground">
        These answers use the supplied question, claim, request or policy. A
        semantic match never authorizes a tool call. Inspect the exact questions
        for each rubric.
      </p>
    </div>
  );
}

const contextFields = {
  research_query: "Research question",
  claim: "Claim to check",
  agent_request: "Original agent request",
  policy: "Policy to check",
  proposed_action: "Proposed action",
} as const;
type ContextField = keyof typeof contextFields;
type AnalysisContext = Partial<Record<ContextField, string>>;

function AnalysisContextForm({
  value,
  onChange,
  disabled,
}: {
  value: AnalysisContext;
  onChange: (value: AnalysisContext) => void;
  disabled: boolean;
}) {
  const id = useId();
  return (
    <details className="rounded-md border border-border p-4">
      <summary className="cursor-pointer text-sm font-medium">
        Add research or agent checks
      </summary>
      <p className="mt-3 text-xs leading-5 text-muted-foreground">
        A research question adds relevance and evidence selection. A claim adds
        a support check. For agent review, this document’s text is the candidate
        output: provide the original request, policy or proposed action. Only
        checks with the needed context run. Up to 12,000 characters in total.
      </p>
      <div className="mt-4 grid gap-4">
        {Object.entries(contextFields).map(([key, label]) => (
          <label
            key={key}
            htmlFor={`${id}-${key}`}
            className="space-y-2 text-sm"
          >
            <span>{label}</span>
            <Textarea
              id={`${id}-${key}`}
              maxLength={4000}
              value={value[key as ContextField] ?? ""}
              disabled={disabled}
              onChange={(event) =>
                onChange({ ...value, [key]: event.target.value })
              }
            />
          </label>
        ))}
      </div>
      {value.proposed_action?.trim() && !value.agent_request?.trim() && (
        <p className="mt-2 text-xs text-muted-foreground">
          Add the original agent request to check whether the proposed action
          matches it.
        </p>
      )}
    </details>
  );
}

function TypeReview({
  snapshot,
  types,
  done,
}: {
  snapshot: Classification;
  types: DocumentType[];
  done: () => void;
}) {
  const id = useId();
  const client = useQueryClient();
  const reviewTypes = types.filter((type) =>
    snapshot.policy.catalog_ids.includes(type.id),
  );
  const [typeId, setTypeId] = useState(
    snapshot.latest_decision?.proposed_type_id ??
      (reviewTypes.some((type) => type.id === snapshot.accepted_type_id)
        ? snapshot.accepted_type_id
        : ""),
  );
  const [reason, setReason] = useState("");
  const [intent] = useState(() => new RetainedRequestIntent());
  const review = useMutation({
    mutationFn: (outcome: "accept" | "retain" | "request_better_file") => {
      if (!snapshot.source_version_id || !snapshot.extraction_version_id)
        throw new Error("A completed extraction is required for this review.");
      const path = `documents/${snapshot.artifact_id}/classification/review`;
      const body = {
        expected_version: snapshot.metadata_revision,
        source_version_id: snapshot.source_version_id,
        extraction_version_id: snapshot.extraction_version_id,
        decision_id:
          snapshot.latest_decision &&
          ["proposed", "needs_review"].includes(snapshot.latest_decision.state)
            ? snapshot.latest_decision.id
            : null,
        outcome,
        document_type_id: outcome === "accept" ? typeId : null,
        reason,
      } satisfies Schema["DocumentClassificationReviewCreate"];
      const request = intent.forRequest("POST", path, body);
      return api<Classification>(path, {
        method: "POST",
        body,
        key: request.key,
      });
    },
    onSuccess: () => {
      intent.reset();
      void client.invalidateQueries();
      toast.success("Classification review saved.");
      done();
    },
  });
  return (
    <form
      className="space-y-4 rounded-md border border-border p-4"
      onSubmit={(event) => {
        event.preventDefault();
        review.mutate("accept");
      }}
    >
      <h4 className="text-sm font-medium">Review the document type</h4>
      <label className="block space-y-2 text-sm" htmlFor={`${id}-type`}>
        <span>Confirmed type</span>
        <select
          id={`${id}-type`}
          className={selectStyle}
          value={typeId ?? ""}
          disabled={review.isPending}
          onChange={(event) => setTypeId(event.target.value)}
        >
          <option value="" disabled>
            Choose a type
          </option>
          {reviewTypes.map((type) => (
            <option key={type.id} value={type.id}>
              {type.name}
            </option>
          ))}
        </select>
      </label>
      <label className="block space-y-2 text-sm" htmlFor={`${id}-reason`}>
        <span>Reason for this review</span>
        <Textarea
          id={`${id}-reason`}
          value={reason}
          maxLength={2000}
          disabled={review.isPending}
          onChange={(event) => setReason(event.target.value)}
          required
        />
      </label>
      <p className="text-xs text-muted-foreground">
        This records a document type. Review of extracted facts and permission
        for downstream actions remain separate.
      </p>
      {review.error && (
        <p role="alert" className="text-sm text-destructive">
          {review.error.message} Your review is still here. If the source
          changed, close and reopen this review.
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <Button disabled={review.isPending || !typeId || !reason.trim()}>
          {review.isPending && <Spinner />}Confirm type
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={review.isPending || !reason.trim()}
          onClick={() => review.mutate("retain")}
        >
          Keep current type
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={review.isPending || !reason.trim()}
          onClick={() => review.mutate("request_better_file")}
        >
          Request a better file
        </Button>
        <Button
          type="button"
          variant="ghost"
          disabled={review.isPending}
          onClick={done}
        >
          Close review
        </Button>
      </div>
    </form>
  );
}

function RenamePreview({ proposal }: { proposal: Rename }) {
  const client = useQueryClient();
  const context = useWorkspaceContext();
  const [intent] = useState(() => new RetainedRequestIntent());
  const change = useMutation({
    mutationFn: (action: "apply" | "cancel") => {
      const path = `documents/renames/${proposal.id}/${action}`;
      const body = { expected_version: proposal.row_version };
      const request = intent.forRequest("POST", path, body);
      return api<Rename>(path, { method: "POST", body, key: request.key });
    },
    onSuccess: (_result, action) => {
      intent.reset();
      void client.invalidateQueries();
      toast.success(
        action === "apply"
          ? "Vault title updated. Original filename preserved."
          : "Current title kept.",
      );
    },
  });
  return (
    <section
      className="space-y-3 rounded-md border border-border p-4"
      aria-label="Rename document preview"
    >
      <h4 className="text-sm font-medium">Review the Vault title</h4>
      <dl className="space-y-2 text-sm">
        <div>
          <dt className="text-muted-foreground">Current title</dt>
          <dd className="break-words">{proposal.before_title}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Proposed title</dt>
          <dd className="break-words font-medium">
            {proposal.after_title ?? "Needs a corrected template"}
          </dd>
        </div>
      </dl>
      <p className="text-xs text-muted-foreground">
        Only the display title changes. Original filename, file bytes and saved
        versions stay preserved.
      </p>
      {proposal.error && (
        <p className="text-sm" role="status">
          {proposal.error}{" "}
          <Link className="underline" href="/settings#documents">
            Document settings
          </Link>
        </p>
      )}
      <details>
        <summary className="cursor-pointer text-xs">
          Template and fields
        </summary>
        <JsonDetails
          value={{
            template: proposal.template,
            fields: proposal.render_inputs,
            policy_revision: proposal.policy_revision,
          }}
        />
      </details>
      <div className="flex flex-wrap gap-2">
        <Button
          disabled={
            proposal.state !== "pending" ||
            !proposal.after_title ||
            change.isPending
          }
          onClick={() => change.mutate("apply")}
        >
          Apply name
        </Button>
        <Button
          variant="outline"
          disabled={
            change.isPending ||
            !["pending", "needs_correction"].includes(proposal.state)
          }
          onClick={() => change.mutate("cancel")}
        >
          Keep current name
        </Button>
        <Button
          variant="ghost"
          onClick={() => context?.open("tasks", proposal.task_id)}
        >
          Open rename task
        </Button>
      </div>
      {change.error && (
        <p role="alert" className="text-sm text-destructive">
          {change.error.message}
        </p>
      )}
    </section>
  );
}

export function DocumentDecisions({ artifactId }: { artifactId: string }) {
  const client = useQueryClient();
  const types = useDocumentTypes();
  const [acknowledged, setAcknowledged] = useState(false);
  const [analysisContext, setAnalysisContext] = useState<AnalysisContext>({});
  const [reviewSnapshot, setReviewSnapshot] = useState<Classification | null>(
    null,
  );
  const [intent] = useState(() => new RetainedRequestIntent());
  const query = useQuery({
    queryKey: ["document-classification", artifactId],
    queryFn: () =>
      api<Classification>(`documents/${artifactId}/classification`),
    refetchInterval: (query) =>
      ["queued", "running"].includes(
        query.state.data?.latest_decision?.state ?? "",
      )
        ? 2000
        : false,
  });
  const classify = useMutation({
    mutationFn: ({
      snapshot,
      context,
    }: {
      snapshot: Classification;
      context: AnalysisContext;
    }) => {
      if (!snapshot.source_version_id || !snapshot.extraction_version_id)
        throw new Error(
          "A completed extraction is required for classification.",
        );
      const path = `documents/${snapshot.artifact_id}/classification`;
      const body = {
        expected_version: snapshot.metadata_revision,
        source_version_id: snapshot.source_version_id,
        extraction_version_id: snapshot.extraction_version_id,
        external_processing_ack: true,
        ...(Object.keys(context).length ? { analysis_context: context } : {}),
      } satisfies Schema["DocumentClassificationRequest"];
      const request = intent.forRequest("POST", path, body);
      return api<Decision>(path, { method: "POST", body, key: request.key });
    },
    onSuccess: () => {
      intent.reset();
      setAcknowledged(false);
      void client.invalidateQueries({ queryKey: ["document-classification"] });
      void client.invalidateQueries({ queryKey: ["dashboard"] });
      toast.success("Classification requested.");
    },
  });
  const snapshot = query.data;
  const ready =
    !!snapshot?.source_version_id && !!snapshot.extraction_version_id;
  const running = ["queued", "running"].includes(
    snapshot?.latest_decision?.state ?? "",
  );
  return (
    <section
      className="space-y-5 rounded-xl border border-border p-5"
      aria-label="Document classification"
    >
      <div>
        <h3 className="text-sm font-medium">Document classification</h3>
        <p className="mt-1 text-xs text-muted-foreground">
          Inspect a suggestion, confirm the type, then review any proposed
          title.
        </p>
      </div>
      {query.error ? (
        <ErrorState error={query.error} retry={() => query.refetch()} />
      ) : types.error ? (
        <ErrorState error={types.error} retry={() => types.refetch()} />
      ) : !snapshot || !types.data ? (
        <LoadingRows />
      ) : (
        <>
          <dl className="grid gap-4 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-muted-foreground">Accepted type</dt>
              <dd className="mt-1 font-medium">
                {types.data.find(
                  (type) => type.id === snapshot.accepted_type_id,
                )?.name ?? "Unclassified"}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Proposed type</dt>
              <dd className="mt-1 font-medium">
                {types.data.find(
                  (type) =>
                    type.id === snapshot.latest_decision?.proposed_type_id,
                )?.name ?? "No specific type proposed"}
              </dd>
            </div>
          </dl>
          {!ready && (
            <p role="status" className="text-sm">
              Classification needs a completed text extraction. Check the
              document import or upload a clearer file.
            </p>
          )}
          {snapshot.latest_decision && (
            <ModelJudgment
              decision={snapshot.latest_decision}
              types={types.data}
            />
          )}
          {ready && (
            <div className="space-y-3 border-t border-border pt-4">
              <p className="text-xs text-muted-foreground">
                Jev reads extracted text, not the PDF or image.{" "}
                {snapshot.policy.provider_ready
                  ? `One assessment sends selected text and the context you provide to ${snapshot.policy.provider}.`
                  : "Configure a Jev provider to request an assessment. You can still review the type manually."}
              </p>
              {snapshot.policy.provider_ready && (
                <AnalysisContextForm
                  value={analysisContext}
                  disabled={running || classify.isPending}
                  onChange={(value) => {
                    setAnalysisContext(value);
                    setAcknowledged(false);
                  }}
                />
              )}
              {snapshot.policy.provider_ready && (
                <label className="flex items-start gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={acknowledged}
                    disabled={running || classify.isPending}
                    onChange={(event) => setAcknowledged(event.target.checked)}
                  />
                  Send this document’s extracted text and the context above for
                  one Jev assessment.
                </label>
              )}
              <div className="flex flex-wrap gap-2">
                <Button
                  disabled={
                    !snapshot.policy.provider_ready ||
                    !acknowledged ||
                    running ||
                    classify.isPending
                  }
                  onClick={() =>
                    classify.mutate({
                      snapshot,
                      context: Object.fromEntries(
                        Object.entries(analysisContext).filter(([, value]) =>
                          value?.trim(),
                        ),
                      ),
                    })
                  }
                >
                  {(running || classify.isPending) && <Spinner />}
                  {running
                    ? "Assessing…"
                    : snapshot.latest_decision
                      ? "Request assessment"
                      : "Classify with Jev"}
                </Button>
                <Button
                  variant="outline"
                  disabled={!!reviewSnapshot || classify.isPending}
                  onClick={() => setReviewSnapshot(snapshot)}
                >
                  Review type
                </Button>
              </div>
              {classify.error && (
                <p role="alert" className="text-sm text-destructive">
                  {classify.error.message}
                </p>
              )}
            </div>
          )}
          {reviewSnapshot && (
            <TypeReview
              snapshot={reviewSnapshot}
              types={types.data}
              done={() => setReviewSnapshot(null)}
            />
          )}
          {snapshot.pending_rename && (
            <RenamePreview
              key={snapshot.pending_rename.id}
              proposal={snapshot.pending_rename}
            />
          )}
        </>
      )}
    </section>
  );
}
