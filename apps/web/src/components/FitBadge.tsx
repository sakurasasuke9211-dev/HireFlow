import type { OverallMatch, PipelineRun } from "@/lib/types";

const labels: Record<OverallMatch, string> = {
  poor: "Poor match",
  average: "Average match",
  good: "Good match",
  perfect: "Perfect match",
};

const tones: Record<OverallMatch, string> = {
  poor: "bg-[var(--rust-bg)] text-[var(--rust)] border-[var(--rust)]",
  average: "bg-[var(--warn-bg)] text-[var(--warn)] border-[var(--warn)]",
  good: "bg-[var(--ok-bg)] text-[var(--ok)] border-[var(--ok)]",
  perfect: "bg-[var(--ok-bg)] text-[var(--ok)] border-[var(--ok)]",
};

export function FitBadge({
  overallMatch,
  matchRun,
}: {
  overallMatch: OverallMatch | null | undefined;
  matchRun?: PipelineRun | null;
}) {
  const pending = matchRun?.status === "queued" || matchRun?.status === "running";
  if (pending) {
    return (
      <span className="inline-flex border border-[var(--warn)] bg-[var(--warn-bg)] px-2 py-0.5 text-xs tracking-wide text-[var(--warn)]">
        Matching
      </span>
    );
  }
  if (overallMatch) {
    return (
      <span className={`inline-flex border px-2 py-0.5 text-xs tracking-wide ${tones[overallMatch]}`}>
        {labels[overallMatch]}
      </span>
    );
  }
  return (
      <span className="inline-flex border border-line px-2 py-0.5 text-xs tracking-wide text-muted">
        Not matched
      </span>
  );
}
