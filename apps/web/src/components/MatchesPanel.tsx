"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { StatusChip } from "@/components/StatusChip";
import { api } from "@/lib/api";
import type { Candidate, MatchResult } from "@/lib/types";

export function MatchesPanel({
  candidate,
  onRetry,
}: {
  candidate: Candidate;
  onRetry?: () => Promise<void>;
}) {
  const [matches, setMatches] = useState<MatchResult[]>([]);
  const matchPending =
    candidate.match_run?.status === "queued" || candidate.match_run?.status === "running";
  const failed = candidate.match_run?.status === "failed";

  useEffect(() => {
    void api.matches(candidate.id).then(setMatches).catch(() => setMatches([]));
  }, [candidate.id, candidate.match_run?.status, candidate.match_run?.finished_at]);

  return (
    <section className="border border-line bg-white p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-serif text-xl">Match with JD</h2>
          <p className="mt-1 text-sm text-muted">
            Years-only is UNCLEAR. Missing is not a reject.
          </p>
        </div>
        {failed && matches.length === 0 && onRetry && (
          <button type="button" onClick={() => void onRetry()} className="bg-forest px-4 py-2 text-sm text-white">
            Retry match
          </button>
        )}
      </div>
      {failed && matches.length === 0 && (
        <div className="mt-4 border border-[var(--rust)] bg-[var(--rust-bg)] px-3 py-2 text-sm text-[var(--rust)]">
          {candidate.match_run?.error}
        </div>
      )}
      {matchPending && <p className="mt-4 text-sm text-muted">Matching the resume to the JD…</p>}
      {candidate.match_run?.status === "succeeded" && matches.length === 0 && (
        <p className="mt-4 text-sm text-muted">No requirements to match.</p>
      )}
      <ul className="mt-4 space-y-3">
        {matches.map((match) => (
          <li key={match.id} className="border border-line bg-paper px-3 py-3 text-sm">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <span className="font-medium">{match.requirement_label || match.requirement_id}</span>
              <StatusChip status={match.status} />
            </div>
            {match.requirement_priority && (
              <p className="mt-1 text-xs uppercase tracking-wide text-muted">
                {match.requirement_priority.replaceAll("_", " ")}
              </p>
            )}
            <p className="mt-2">{match.rationale}</p>
            {match.quotes.length > 0 ? (
              match.quotes.map((quote) => (
                <p key={quote} className="mt-1 text-xs text-muted">
                  Quote: {quote}
                </p>
              ))
            ) : (
              <p className="mt-1 text-xs text-muted">No evidence found</p>
            )}
          </li>
        ))}
      </ul>
      <p className="mt-3 text-xs text-muted">
        <Link href={`/jobs/${candidate.job_id}/matrix`} className="underline">
          Open job matrix
        </Link>
      </p>
    </section>
  );
}
