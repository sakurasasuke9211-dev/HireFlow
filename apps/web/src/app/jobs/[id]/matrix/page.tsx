"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { FitBadge } from "@/components/FitBadge";
import { StatusChip } from "@/components/StatusChip";
import { api } from "@/lib/api";
import type { JobDetail, MatrixCell, MatrixResponse } from "@/lib/types";

export default function MatrixPage() {
  const params = useParams<{ id: string }>();
  const [job, setJob] = useState<JobDetail | null>(null);
  const [matrix, setMatrix] = useState<MatrixResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<MatrixCell | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [nextJob, nextMatrix] = await Promise.all([api.job(params.id), api.matrix(params.id)]);
    setJob(nextJob);
    setMatrix(nextMatrix);
  }, [params.id]);

  useEffect(() => {
    void load().catch((err: Error) => setError(err.message));
  }, [load]);

  const pending = (job?.candidates ?? []).some(
    (candidate) => candidate.match_run?.status === "queued" || candidate.match_run?.status === "running",
  );

  useEffect(() => {
    if (!pending) return;
    const timer = window.setInterval(() => {
      void load();
    }, 2000);
    return () => window.clearInterval(timer);
  }, [pending, load]);

  const cellMap = useMemo(() => {
    const map = new Map<string, MatrixCell>();
    for (const cell of matrix?.cells ?? []) {
      map.set(`${cell.candidate_id}:${cell.requirement_id}`, cell);
    }
    return map;
  }, [matrix]);

  async function runMatch(candidateId: string) {
    setBusyId(candidateId);
    setError(null);
    try {
      await api.matchCandidate(candidateId);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Match failed");
    } finally {
      setBusyId(null);
    }
  }

  if (!job || !matrix) {
    return (
      <AppShell>
        <p className="text-sm text-muted">{error ?? "Loading matrix…"}</p>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <p className="text-sm text-muted">
        <Link href={`/jobs/${job.id}`} className="underline">
          Back to job
        </Link>
      </p>
      <h1 className="mt-2 font-serif text-3xl">{job.title}</h1>
      <p className="mt-1 text-sm text-muted">Requirement × candidate. Empty evidence is “No evidence found”.</p>
      {error && <p className="mt-3 text-sm text-[var(--rust)]">{error}</p>}

      <div className="mt-6 overflow-x-auto border border-line bg-white">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="border-b border-line bg-[#efe9db]">
              <th className="px-3 py-2 text-left font-medium">Candidate</th>
              {matrix.requirements.map((requirement) => (
                <th key={requirement.id} className="px-3 py-2 text-left font-medium">
                  <div>{requirement.normalized_label}</div>
                  <div className="text-[11px] font-normal uppercase tracking-wide text-muted">
                    {requirement.priority.replaceAll("_", " ")}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {matrix.candidates.map((candidate) => {
              const detail = job.candidates.find((item) => item.id === candidate.id);
              return (
                <tr key={candidate.id} className="border-t border-line align-top">
                  <td className="px-3 py-3">
                    <Link href={`/candidates/${candidate.id}`} className="font-medium underline">
                      {candidate.full_name}
                    </Link>
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <FitBadge overallMatch={candidate.overall_match} matchRun={detail?.match_run} />
                      <Link href={`/candidates/${candidate.id}/plan`} className="text-xs underline">
                        Plan
                      </Link>
                      <button
                        type="button"
                        disabled={busyId === candidate.id}
                        onClick={() => void runMatch(candidate.id)}
                        className="border border-line px-2 py-1 text-xs disabled:opacity-60"
                      >
                        Match
                      </button>
                    </div>
                  </td>
                  {matrix.requirements.map((requirement) => {
                    const cell = cellMap.get(`${candidate.id}:${requirement.id}`);
                    return (
                      <td key={requirement.id} className="px-3 py-3">
                        <button
                          type="button"
                          className="text-left"
                          onClick={() => setSelected(cell ?? null)}
                        >
                          <StatusChip status={cell?.status} />
                          <p className="mt-1 line-clamp-3 text-xs text-muted">
                            {cell?.quotes[0] || (cell?.status === "MISSING" ? "No evidence found" : cell?.rationale || "Not run")}
                          </p>
                        </button>
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
        {matrix.candidates.length === 0 && (
          <p className="px-5 py-6 text-sm text-muted">Add candidates, parse resumes, then run match.</p>
        )}
      </div>

      {selected && (
        <section className="mt-6 border border-line bg-white p-5">
          <h2 className="font-serif text-xl">Evidence</h2>
          <div className="mt-2">
            <StatusChip status={selected.status} />
          </div>
          <p className="mt-3 text-sm">{selected.rationale}</p>
          {selected.quotes.length > 0 ? (
            selected.quotes.map((quote) => (
              <p key={quote} className="mt-2 text-sm text-muted">
                Quote: {quote}
              </p>
            ))
          ) : (
            <p className="mt-2 text-sm text-muted">No evidence found</p>
          )}
        </section>
      )}
    </AppShell>
  );
}
