import type { MatchStatus, MatrixCell, OverallMatch, Requirement } from "./types";

export type UiMatchStatus = "matched" | "partial" | "missing" | "unclear";

export function toUiStatus(status: MatchStatus | null | undefined): UiMatchStatus {
  if (status === "MATCHED") return "matched";
  if (status === "PARTIALLY_MATCHED") return "partial";
  if (status === "UNCLEAR") return "unclear";
  return "missing";
}

export const statusMeta: Record<
  UiMatchStatus,
  { label: string; dot: string; text: string; chip: string; bar: string }
> = {
  matched: {
    label: "Matched",
    dot: "bg-matched",
    text: "text-matched",
    chip: "bg-emerald-50 text-matched border-emerald-200",
    bar: "bg-matched",
  },
  partial: {
    label: "Partial",
    dot: "bg-partial",
    text: "text-partial",
    chip: "bg-amber-50 text-partial border-amber-200",
    bar: "bg-partial",
  },
  unclear: {
    label: "Unclear",
    dot: "bg-unclear",
    text: "text-unclear",
    chip: "bg-violet-50 text-unclear border-violet-200",
    bar: "bg-unclear",
  },
  missing: {
    label: "Missing",
    dot: "bg-missing",
    text: "text-missing",
    chip: "bg-rose-50 text-missing border-rose-200",
    bar: "bg-missing",
  },
};

export function matchScore(overall: OverallMatch | null | undefined): number {
  if (overall === "perfect") return 95;
  if (overall === "good") return 82;
  if (overall === "average") return 68;
  if (overall === "poor") return 48;
  return 0;
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

export function countMatchStatuses(
  statuses: Array<MatchStatus | null | undefined>,
): Record<UiMatchStatus, number> {
  const counts: Record<UiMatchStatus, number> = {
    matched: 0,
    partial: 0,
    unclear: 0,
    missing: 0,
  };
  statuses.forEach((status) => {
    counts[toUiStatus(status)] += 1;
  });
  return counts;
}

export function countStatuses(
  cells: MatrixCell[],
  candidateId: string,
): Record<UiMatchStatus, number> {
  const counts: Record<UiMatchStatus, number> = {
    matched: 0,
    partial: 0,
    unclear: 0,
    missing: 0,
  };
  cells
    .filter((cell) => cell.candidate_id === candidateId)
    .forEach((cell) => {
      counts[toUiStatus(cell.status)] += 1;
    });
  return counts;
}

export function gapCount(cells: MatrixCell[], candidateId: string): number {
  return cells.filter(
    (cell) => cell.candidate_id === candidateId && cell.status !== "MATCHED",
  ).length;
}

export function cellsForCandidate(cells: MatrixCell[], candidateId: string, requirements: Requirement[]) {
  const byReq = Object.fromEntries(
    cells.filter((c) => c.candidate_id === candidateId).map((c) => [c.requirement_id, c]),
  );
  return requirements.map((req) => ({
    requirement: req,
    cell: byReq[req.id] ?? null,
  }));
}
