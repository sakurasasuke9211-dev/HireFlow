import type { ProbeVerdict } from "@/lib/types";

const tones: Record<string, string> = {
  sufficient: "bg-[var(--ok-bg)] text-[var(--ok)] border-[var(--ok)]",
  shallow: "bg-[var(--warn-bg)] text-[var(--warn)] border-[var(--warn)]",
  not_discussed: "border-line text-muted",
  confirmed_missing: "bg-[var(--rust-bg)] text-[var(--rust)] border-[var(--rust)]",
  contradiction: "bg-[var(--rust-bg)] text-[var(--rust)] border-[var(--rust)]",
};

const labels: Record<string, string> = {
  sufficient: "sufficient",
  shallow: "shallow",
  not_discussed: "not discussed",
  confirmed_missing: "confirmed missing",
  contradiction: "contradiction",
};

export function ProbeChip({ verdict }: { verdict: ProbeVerdict | null | undefined }) {
  if (!verdict) {
    return (
      <span className="inline-flex border border-dashed border-line px-2 py-0.5 text-[11px] uppercase tracking-wide text-muted">
        Not run
      </span>
    );
  }
  return (
    <span className={`inline-flex border px-2 py-0.5 text-[11px] uppercase tracking-wide ${tones[verdict] ?? "border-line"}`}>
      {labels[verdict] ?? verdict}
    </span>
  );
}
