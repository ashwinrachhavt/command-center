"use client";

import { useEffect, useId, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Check, Minus, ScanText } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { api, type Schema } from "@/lib/api";
import { useWorkspaceContext } from "./context";
import { Spinner } from "./primitives";

type KeywordMatch = Schema["ApplicationKeywordMatchRead"];
type Source = Schema["MaterialSourceRead"];
type Props = {
  actor: string;
  taskId: string;
  resumeVersionId?: string;
  jobVersionId?: string;
  disabled?: boolean;
  loading?: boolean;
  onPendingChange?: (pending: boolean) => void;
};

export function ApplicationKeywordMatch(props: Props) {
  return (
    <KeywordCheck
      key={JSON.stringify([
        props.actor,
        props.taskId,
        props.resumeVersionId,
        props.jobVersionId,
      ])}
      {...props}
    />
  );
}

function KeywordCheck({
  taskId,
  resumeVersionId,
  jobVersionId,
  disabled = false,
  loading = false,
  onPendingChange,
}: Props) {
  const id = useId();
  const [editor, setEditor] = useState("");
  const keywords = editor
    .split(/[,\n]/)
    .map((term) => term.trim())
    .filter(Boolean);
  const validation =
    keywords.length > 50
      ? "Use up to 50 keywords."
      : keywords.some((term) => [...term].length > 80)
        ? "Keep each keyword to 80 characters or fewer."
        : null;
  const check = useMutation({
    mutationFn: async (body: {
      resume_version_id: string;
      job_version_id: string;
      keywords: string[] | null;
    }) => {
      const result = await api<KeywordMatch>(
        `applications/${taskId}/keyword-match`,
        { method: "POST", body },
      );
      if (
        result.job.version_id !== body.job_version_id ||
        result.resume.version_id !== body.resume_version_id
      )
        throw new Error(
          "The report did not match the selected source versions. Check again.",
        );
      return result;
    },
  });
  useEffect(() => {
    onPendingChange?.(check.isPending);
    return () => onPendingChange?.(false);
  }, [check.isPending, onPendingChange]);

  const missing =
    !resumeVersionId && !jobVersionId
      ? "Save a job description and choose a résumé to check keyword coverage."
      : !jobVersionId
        ? "Save a job-description checkpoint to check keyword coverage."
        : !resumeVersionId
          ? "Choose a saved résumé to check keyword coverage."
          : null;
  const frozen = disabled || loading || check.isPending;

  return (
    <section
      aria-labelledby={`${id}-title`}
      className="min-w-0 space-y-3 rounded-md border p-3"
    >
      <div className="space-y-1">
        <h4 id={`${id}-title`} className="text-sm font-semibold">
          Keyword coverage
        </h4>
        <p className="text-xs leading-5 text-muted-foreground">
          Compare the selected résumé’s text with your saved job description.
          This is text coverage, not an employer ATS ranking or an eligibility
          decision. No AI generation is used.
        </p>
      </div>
      <details>
        <summary className="cursor-pointer text-sm leading-6 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          Choose keywords (optional)
        </summary>
        <div className="mt-3 space-y-2">
          <Label htmlFor={`${id}-keywords`}>Keywords to check</Label>
          <Textarea
            id={`${id}-keywords`}
            value={editor}
            disabled={frozen}
            aria-invalid={!!validation}
            aria-describedby={`${id}-help${validation ? ` ${id}-validation` : ""}`}
            placeholder="Python, project management, customer research"
            onChange={(event) => {
              if (frozen) return;
              setEditor(event.target.value);
              check.reset();
            }}
          />
          <p
            id={`${id}-help`}
            className="text-xs leading-5 text-muted-foreground"
          >
            Separate up to 50 keywords with commas or new lines, up to 80
            characters each. Leave empty to detect terms from the saved job
            description. Your list can include terms outside the description.
          </p>
          {validation && (
            <p
              id={`${id}-validation`}
              role="alert"
              className="text-xs text-destructive"
            >
              {validation}
            </p>
          )}
        </div>
      </details>
      {loading ? (
        <p role="status" className="text-xs text-muted-foreground">
          Loading saved sources…
        </p>
      ) : (
        missing && <p className="text-xs text-muted-foreground">{missing}</p>
      )}
      <Button
        size="sm"
        variant="outline"
        disabled={frozen || !!missing || !!validation}
        onClick={() => {
          if (frozen || validation || !resumeVersionId || !jobVersionId) return;
          check.mutate({
            resume_version_id: resumeVersionId,
            job_version_id: jobVersionId,
            keywords: keywords.length ? keywords : null,
          });
        }}
      >
        {check.isPending ? <Spinner /> : <ScanText aria-hidden="true" />}
        {check.isPending
          ? "Checking keywords…"
          : check.error
            ? "Retry keyword check"
            : "Check job keywords"}
      </Button>
      {check.isPending && (
        <p role="status" className="text-xs text-muted-foreground">
          Checking the selected saved versions…
        </p>
      )}
      {check.error && (
        <p role="alert" className="text-sm text-destructive">
          {check.error.message}
        </p>
      )}
      {check.data && !check.isPending && !check.error && (
        <KeywordReport result={check.data} />
      )}
    </section>
  );
}

function KeywordReport({ result }: { result: KeywordMatch }) {
  const { analysis } = result;
  const matched = analysis.keywords.filter((keyword) => keyword.matched);
  const missing = analysis.keywords.filter((keyword) => !keyword.matched);
  return (
    <div className="space-y-3 border-t pt-3">
      <div role="status" className="space-y-1">
        {analysis.score === null ? (
          <p className="text-sm">
            No keywords were detected. Add your own list above to check
            coverage.
          </p>
        ) : (
          <p className="text-sm font-medium">
            {analysis.score}% · {analysis.matched_count} of{" "}
            {analysis.keyword_count} keywords found
          </p>
        )}
        <p className="text-xs text-muted-foreground">
          {analysis.mode === "selected"
            ? "Checked your selected keywords."
            : "Checked keywords detected in the saved job description."}
        </p>
      </div>
      {analysis.keyword_count > 0 && (
        <div className="grid min-w-0 gap-3 sm:grid-cols-2">
          <KeywordTerms label="Matched" keywords={matched} />
          <KeywordTerms label="Missing" keywords={missing} />
        </div>
      )}
      {analysis.limit_reached && (
        <p className="text-xs leading-5 text-muted-foreground">
          The detected keyword list reached its limit. Choose your own list to
          focus on the terms that matter to you.
        </p>
      )}
      {result.job_truncated && (
        <p className="text-xs leading-5 text-muted-foreground">
          This check uses the saved, shortened job description.
        </p>
      )}
      <div className="space-y-1 text-xs text-muted-foreground">
        <p>Saved sources used:</p>
        <ul className="space-y-1">
          <li>
            <SourceLink label="Job description" source={result.job} />
          </li>
          <li>
            <SourceLink label="Résumé" source={result.resume} />
          </li>
          {result.resume_source.version_id !== result.resume.version_id && (
            <li>
              <SourceLink label="Résumé text" source={result.resume_source} />
            </li>
          )}
        </ul>
      </div>
    </div>
  );
}

function KeywordTerms({
  label,
  keywords,
}: {
  label: "Matched" | "Missing";
  keywords: KeywordMatch["analysis"]["keywords"];
}) {
  return (
    <div className="min-w-0 space-y-2">
      <h5 className="text-xs font-medium">
        {label} ({keywords.length})
      </h5>
      {keywords.length ? (
        <ul aria-label={`${label} keywords`} className="flex flex-wrap gap-1.5">
          {keywords.map((keyword) => (
            <li key={keyword.term} className="min-w-0 max-w-full">
              <Badge
                variant={keyword.matched ? "secondary" : "outline"}
                className="h-auto max-w-full items-start py-1 whitespace-normal"
              >
                {keyword.matched ? (
                  <Check aria-hidden="true" className="mt-0.5 shrink-0" />
                ) : (
                  <Minus aria-hidden="true" className="mt-0.5 shrink-0" />
                )}
                <span className="min-w-0 break-words [overflow-wrap:anywhere]">
                  {keyword.term}
                </span>
              </Badge>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-muted-foreground">None</p>
      )}
    </div>
  );
}

function SourceLink({ label, source }: { label: string; source: Source }) {
  const workspace = useWorkspaceContext();
  const text = `${label}: ${source.title} · version ${source.version}${source.archived ? " (archived)" : ""}`;
  return workspace ? (
    <Button
      type="button"
      variant="link"
      className="h-auto max-w-full justify-start px-0 py-1 text-left text-xs whitespace-normal [overflow-wrap:anywhere]"
      onClick={() =>
        workspace.open("artifacts", source.artifact_id, {
          tab: "content",
          versionId: source.version_id,
        })
      }
    >
      {text}
    </Button>
  ) : (
    <span className="break-words [overflow-wrap:anywhere]">{text}</span>
  );
}
