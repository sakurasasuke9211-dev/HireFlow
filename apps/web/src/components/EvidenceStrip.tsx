"use client";

import type { MatrixCell, Requirement } from "@/lib/types";
import { statusMeta, toUiStatus } from "@/lib/screening";

export function EvidenceStrip({
  requirements,
  cells,
  candidateId,
  size = "sm",
}: {
  requirements: Requirement[];
  cells: MatrixCell[];
  candidateId: string;
  size?: "sm" | "md";
}) {
  const byReq = Object.fromEntries(
    cells.filter((c) => c.candidate_id === candidateId).map((c) => [c.requirement_id, c]),
  );

  return (
    <div
      className={`flex w-full gap-1 ${size === "sm" ? "h-1.5" : "h-2.5"}`}
      role="img"
      aria-label={`Evidence coverage across ${requirements.length} requirements`}
    >
      {requirements.map((req) => {
        const cell = byReq[req.id];
        const ui = toUiStatus(cell?.status);
        const meta = statusMeta[ui];
        return (
          <span
            key={req.id}
            title={`${req.normalized_label || req.text}: ${meta.label}`}
            className={`flex-1 rounded-full ${meta.bar} ${ui === "missing" ? "opacity-40" : ""}`}
          />
        );
      })}
    </div>
  );
}
