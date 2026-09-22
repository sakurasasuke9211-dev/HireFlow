"use client";

import { useEffect, useState } from "react";
import { StatusChip } from "@/components/StatusChip";
import { api } from "@/lib/api";
import type { Candidate, Gap } from "@/lib/types";

export function GapsPanel({ candidate }: { candidate: Candidate }) {
  const [gaps, setGaps] = useState<Gap[]>([]);

  useEffect(() => {
    void api.gaps(candidate.id).then(setGaps).catch(() => setGaps([]));
  }, [candidate.id, candidate.match_run?.status, candidate.match_run?.finished_at]);

  if (gaps.length === 0 && candidate.match_run?.status !== "succeeded") {
    return null;
  }

  return (
    <section className="border border-line bg-white p-5">
      <h2 className="font-serif text-xl">Gaps analysis</h2>
      <p className="mt-1 text-sm text-muted">What still needs evidence before a hiring decision.</p>
      {gaps.length === 0 && <p className="mt-4 text-sm text-muted">No gaps. Every must-have is MATCHED.</p>}
      <ul className="mt-4 space-y-3">
        {gaps.map((gap) => (
          <li key={gap.id} className="border border-line bg-paper p-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{gap.requirement_label}</span>
              <StatusChip status={gap.status} />
              <span className="text-xs uppercase tracking-wide text-muted">{gap.severity}</span>
            </div>
            <p className="mt-2">{gap.investigation_goal}</p>
            {gap.suggested_probe_themes.length > 0 && (
              <p className="mt-1 text-xs text-muted">{gap.suggested_probe_themes.join(" · ")}</p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
