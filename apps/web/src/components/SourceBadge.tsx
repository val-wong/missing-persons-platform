/** A small, subtle tag identifying which source contributed a case -- e.g. "FBI". Not
 * a status/alert indicator, so it deliberately uses neutral styling. */
export function SourceBadge({ code }: { code: string }) {
  return <span className="source-badge">{code.toUpperCase()}</span>;
}
