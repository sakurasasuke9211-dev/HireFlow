"use client";

import Link from "next/link";
import { ArrowRight, Briefcase, MapPin } from "lucide-react";
import type { Candidate, MatrixCell, Requirement } from "@/lib/types";
import { countStatuses, gapCount, initials, matchScore } from "@/lib/screening";
import { EvidenceStrip } from "./EvidenceStrip";

export function CandidateCard({
  candidate,
  requirements,
  cells,
}: {
  candidate: Candidate;
  requirements: Requirement[];
  cells: MatrixCell[];
}) {
  const counts = countStatuses(cells, candidate.id);
  const gaps = gapCount(cells, candidate.id);
  const score = matchScore(candidate.overall_match);

  return (
    <article className="rounded-xl border border-line bg-white p-5 shadow-[var(--shadow-card)] transition-shadow hover:shadow-[var(--shadow-lift)]">
      <div className="flex items-start gap-4">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-brand-50 text-sm font-semibold text-brand-700">
          {initials(candidate.full_name)}
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h3 className="text-lg font-semibold leading-tight text-ink-900">
              <Link
                href={`/candidates/${candidate.id}`}
                className="transition-colors hover:text-brand-600"
              >
                {candidate.full_name}
              </Link>
            </h3>
            {candidate.profile?.roles?.[0] && (
              <span className="text-sm text-ink-500">{candidate.profile.roles[0]}</span>
            )}
          </div>
          <p className="mt-1 text-sm text-ink-500">
            {candidate.resume?.original_filename ?? "Resume uploaded"}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-1 text-sm text-ink-500">
            {candidate.profile?.years_experience != null && (
              <span className="inline-flex items-center gap-1.5">
                <Briefcase className="h-4 w-4 text-ink-400" aria-hidden="true" />
                {candidate.profile.years_experience} yrs
              </span>
            )}
            {candidate.email && (
              <span className="inline-flex items-center gap-1.5">
                <MapPin className="h-4 w-4 text-ink-400" aria-hidden="true" />
                {candidate.email}
              </span>
            )}
          </div>
        </div>

        <div className="hidden shrink-0 text-right sm:block">
          <p className="text-[26px] font-bold leading-none text-ink-900">
            {score || "—"}
            {score > 0 && <span className="text-base font-medium text-ink-400">%</span>}
          </p>
          <p className="mt-1 text-xs text-ink-400">resume match</p>
        </div>
      </div>

      <div className="mt-4 border-t border-line pt-4">
        <EvidenceStrip requirements={requirements} cells={cells} candidateId={candidate.id} />
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-ink-700">
            <span className="font-semibold text-matched">{counts.matched} matched</span>
            <span className="mx-2 text-ink-400">·</span>
            <span className="text-partial">{counts.partial} partial</span>
            <span className="mx-2 text-ink-400">·</span>
            <span className="text-unclear">{counts.unclear} unclear</span>
            <span className="mx-2 text-ink-400">·</span>
            <span className="text-missing">{counts.missing} missing</span>
          </p>
          <Link
            href={`/candidates/${candidate.id}`}
            className="inline-flex items-center gap-1.5 rounded-lg bg-brand-600 px-3.5 py-2 text-sm font-semibold text-white transition-colors hover:bg-brand-700"
          >
            Review {gaps || "profile"}
            <ArrowRight className="h-4 w-4" aria-hidden="true" />
          </Link>
        </div>
      </div>
    </article>
  );
}
