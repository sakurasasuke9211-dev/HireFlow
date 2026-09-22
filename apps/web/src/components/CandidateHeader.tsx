"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronLeft } from "lucide-react";
import type { Candidate } from "@/lib/types";
import { initials, matchScore } from "@/lib/screening";

const steps = [
  { key: "evidence", label: "Resume evidence", path: "" },
  { key: "interview", label: "Interview & validate", path: "/plan" },
  { key: "assessment", label: "Final assessment", path: "/report" },
];

export function CandidateHeader({
  candidate,
  jobTitle,
}: {
  candidate: Candidate;
  jobTitle: string;
}) {
  const pathname = usePathname();
  const base = `/candidates/${candidate.id}`;
  const activeIndex = pathname.endsWith("/report")
    ? 2
    : pathname.endsWith("/plan") || pathname.endsWith("/transcript")
      ? 1
      : 0;

  return (
    <div className="border-b border-line bg-white">
      <div className="mx-auto max-w-[1440px] px-6 pb-0 pt-5">
        <Link
          href={`/jobs/${candidate.job_id}`}
          className="inline-flex items-center gap-1 text-sm text-ink-500 transition-colors hover:text-brand-600"
        >
          <ChevronLeft className="h-4 w-4" aria-hidden="true" />
          {jobTitle}
        </Link>

        <div className="mt-3 flex flex-wrap items-end justify-between gap-4">
          <div className="flex items-center gap-4">
            <span className="flex h-12 w-12 items-center justify-center rounded-full bg-brand-50 text-base font-semibold text-brand-700">
              {initials(candidate.full_name)}
            </span>
            <div>
              <h1 className="text-2xl font-bold leading-tight text-ink-900">{candidate.full_name}</h1>
              <p className="mt-0.5 text-sm text-ink-500">
                {candidate.profile?.roles?.[0] ?? candidate.resume?.original_filename ?? "Candidate"}
                {candidate.profile?.years_experience != null &&
                  ` · ${candidate.profile.years_experience} yrs`}
              </p>
            </div>
          </div>
          <p className="text-sm text-ink-500">
            Resume match{" "}
            <span className="text-lg font-bold text-ink-900">{matchScore(candidate.overall_match) || "—"}%</span>
          </p>
        </div>

        <nav aria-label="Candidate stages" className="mt-5 flex gap-7 overflow-x-auto">
          {steps.map((step, i) => (
            <Link
              key={step.key}
              href={`${base}${step.path}`}
              aria-current={i === activeIndex ? "page" : undefined}
              className={`relative -mb-px shrink-0 border-b-2 pb-3 text-sm transition-colors ${
                i === activeIndex
                  ? "border-brand-600 font-semibold text-ink-900"
                  : "border-transparent text-ink-500 hover:text-ink-900"
              }`}
            >
              <span className="mr-2 text-xs text-ink-400">{i + 1}</span>
              {step.label}
            </Link>
          ))}
          <Link
            href={`${base}/transcript`}
            aria-current={pathname.endsWith("/transcript") ? "page" : undefined}
            className={`relative -mb-px shrink-0 border-b-2 pb-3 text-sm transition-colors ${
              pathname.endsWith("/transcript")
                ? "border-brand-600 font-semibold text-ink-900"
                : "border-transparent text-ink-500 hover:text-ink-900"
            }`}
          >
            Transcript
          </Link>
        </nav>
      </div>
    </div>
  );
}
