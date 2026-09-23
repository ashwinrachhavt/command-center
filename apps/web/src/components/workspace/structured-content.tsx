import { label } from "@/lib/api";

/** Saved artifact data is displayed as content, never interpreted as markup or actions. */
export function StructuredContent({
  value,
  depth = 0,
}: {
  value: unknown;
  depth?: number;
}) {
  if (value === null || value === undefined)
    return <span className="text-muted-foreground">Not provided</span>;
  if (typeof value === "boolean") return <span>{value ? "Yes" : "No"}</span>;
  if (typeof value !== "object")
    return (
      <span className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
        {String(value)}
      </span>
    );

  if (depth >= 4)
    return (
      <pre className="max-w-full overflow-x-auto whitespace-pre-wrap break-words rounded-md bg-muted/40 p-3 text-xs">
        {JSON.stringify(value, null, 2)}
      </pre>
    );
  if (Array.isArray(value))
    return value.length ? (
      <ol className="space-y-3">
        {value.map((item, index) => (
          <li key={index} className="min-w-0 border-l-2 border-border pl-4">
            <StructuredContent value={item} depth={depth + 1} />
          </li>
        ))}
      </ol>
    ) : (
      <span className="text-muted-foreground">None</span>
    );
  const entries = Object.entries(value);
  return entries.length ? (
    <dl className="min-w-0 space-y-4">
      {entries.map(([key, item]) => (
        <div key={key} className="min-w-0 space-y-1">
          <dt className="break-words text-xs font-medium text-muted-foreground">
            {label(key)}
          </dt>
          <dd className="min-w-0 text-sm leading-6">
            <StructuredContent value={item} depth={depth + 1} />
          </dd>
        </div>
      ))}
    </dl>
  ) : (
    <span className="text-muted-foreground">No saved fields</span>
  );
}
