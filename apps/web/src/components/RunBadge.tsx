import type { PipelineRun } from "@/lib/types";

const labels: Record<string, string> = {
  queued: "Queued",
  running: "Running",
  succeeded: "Ready",
  failed: "Failed",
};

export function RunBadge({ run }: { run: PipelineRun | null | undefined }) {
  if (!run) {
    return (
      <span className="inline-flex border border-line px-2 py-0.5 text-xs uppercase tracking-wide text-muted">
        No file
      </span>
    );
  }
  const tone =
    run.status === "failed"
      ? "bg-[var(--rust-bg)] text-[var(--rust)] border-[var(--rust)]"
      : run.status === "succeeded"
        ? "bg-[var(--ok-bg)] text-[var(--ok)] border-[var(--ok)]"
        : "bg-[var(--warn-bg)] text-[var(--warn)] border-[var(--warn)]";
  return (
    <span className={`inline-flex border px-2 py-0.5 text-xs uppercase tracking-wide ${tone}`}>
      {labels[run.status] ?? run.status}
    </span>
  );
}
