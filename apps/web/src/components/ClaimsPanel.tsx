"use client";

import { RunBadge } from "@/components/RunBadge";
import { api } from "@/lib/api";
import type { Candidate } from "@/lib/types";

export function ClaimsPanel({
  candidate,
  busy,
  onChange,
}: {
  candidate: Candidate;
  busy?: boolean;
  onChange: () => Promise<void>;
}) {
  const parsePending =
    candidate.parse_run?.status === "queued" || candidate.parse_run?.status === "running";
  const canParse = Boolean(candidate.resume?.extracted_text) && !parsePending && !busy;

  return (
    <section className="border border-line bg-white p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-serif text-xl">Profile and claims</h2>
          <p className="mt-1 text-sm text-muted">
            Years-only skills are claims, not matches.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <RunBadge run={candidate.parse_run} />
          <button
            type="button"
            disabled={!canParse}
            onClick={() => void api.parseResume(candidate.id).then(onChange).catch(() => onChange())}
            className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
          >
            Parse resume
          </button>
        </div>
      </div>

      {candidate.parse_run?.status === "failed" && (
        <div className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-missing">
          {candidate.parse_run.error ||
            "Could not parse the resume. Check GROQ_API_KEY in .env and restart the API."}
        </div>
      )}
      {parsePending && <p className="mt-4 text-sm text-muted">Parsing the resume…</p>}

      {candidate.profile && (
        <div className="mt-4 text-sm">
          <p>
            <span className="text-muted">Skills listed:</span>{" "}
            {candidate.profile.skills_listed.join(", ") || "—"}
          </p>
          {candidate.profile.summary && <p className="mt-2">{candidate.profile.summary}</p>}
          {candidate.profile.parser_warnings.length > 0 && (
            <p className="mt-2 text-xs text-muted">{candidate.profile.parser_warnings.join(" · ")}</p>
          )}
        </div>
      )}

      {(candidate.claims ?? []).length === 0 && !parsePending && (
        <p className="mt-4 text-sm text-muted">No claims yet. Parse the extracted resume.</p>
      )}

      <ul className="mt-4 space-y-2">
        {(candidate.claims ?? []).map((claim) => (
          <li key={claim.id} className="border border-line bg-paper px-3 py-2 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className="border border-line px-1.5 py-0.5 text-xs uppercase tracking-wide">
                {claim.kind}
              </span>
              {claim.skill_label && <span className="font-medium">{claim.skill_label}</span>}
              {claim.years != null && <span className="text-muted">{claim.years} years</span>}
            </div>
            <p className="mt-1">{claim.text}</p>
            {claim.quote && <p className="mt-1 text-xs text-muted">Quote: {claim.quote}</p>}
          </li>
        ))}
      </ul>
    </section>
  );
}
