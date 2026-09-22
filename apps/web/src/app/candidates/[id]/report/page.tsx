"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { CandidateHeader } from "@/components/CandidateHeader";
import { FitBadge } from "@/components/FitBadge";
import { ProbeChip } from "@/components/ProbeChip";
import { StatusChip } from "@/components/StatusChip";
import { api } from "@/lib/api";
import type { Candidate, DecisionOutcome, EvidenceReportBody, EvidenceReportResponse, JobDetail } from "@/lib/types";

export default function EvidenceReportPage() {
  const params = useParams<{ id: string }>();
  const [candidate, setCandidate] = useState<Candidate | null>(null);
  const [job, setJob] = useState<JobDetail | null>(null);
  const [payload, setPayload] = useState<EvidenceReportResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<null | "download" | "regenerate" | "decision">(null);
  const [outcome, setOutcome] = useState<DecisionOutcome>("hold");
  const [notes, setNotes] = useState("");
  const [hasAnalyzedTranscript, setHasAnalyzedTranscript] = useState<boolean | null>(null);
  const [resumeOnlyConfirmed, setResumeOnlyConfirmed] = useState(false);
  const generateRef = useRef(false);

  const load = useCallback(async () => {
    const [nextCandidate, nextReport] = await Promise.all([
      api.candidate(params.id),
      api.evidenceReport(params.id),
    ]);
    setCandidate(nextCandidate);
    setPayload(nextReport);
    setJob(await api.job(nextCandidate.job_id).catch(() => null));
    if (nextReport.decision) {
      setOutcome(nextReport.decision.outcome);
      setNotes(nextReport.decision.notes);
    }
    return { candidate: nextCandidate, report: nextReport };
  }, [params.id]);

  useEffect(() => {
    void load().catch((err: Error) => setError(err.message));
  }, [load]);

  useEffect(() => {
    void api
      .transcripts(params.id)
      .then((versions) => setHasAnalyzedTranscript(versions.some((item) => item.status === "analyzed")))
      .catch(() => setHasAnalyzedTranscript(false));
  }, [params.id]);

  const run = payload?.run ?? null;
  const pending = run?.status === "queued" || run?.status === "running";
  const body: EvidenceReportBody | null = payload?.body ?? null;
  const report = payload?.report ?? null;
  const matchReady = Boolean(candidate?.overall_match) || candidate?.match_run?.status === "succeeded";

  useEffect(() => {
    if (!candidate || pending || report || generateRef.current || !matchReady) return;
    if (hasAnalyzedTranscript === null) return;
    if (!hasAnalyzedTranscript && !resumeOnlyConfirmed) return;
    generateRef.current = true;
    void api
      .generateEvidenceReport(candidate.id)
      .then(() => load())
      .catch((err: Error) => setError(err.message))
      .finally(() => {
        generateRef.current = false;
      });
  }, [candidate, pending, report, matchReady, load, hasAnalyzedTranscript, resumeOnlyConfirmed]);

  useEffect(() => {
    if (!pending) return;
    const timer = window.setInterval(() => {
      void load();
    }, 2000);
    return () => window.clearInterval(timer);
  }, [pending, load]);

  async function regenerate(forceResumeOnly = false) {
    if (!candidate) return;
    if (!forceResumeOnly && hasAnalyzedTranscript === false && !resumeOnlyConfirmed) {
      const proceed = window.confirm(
        "No analyzed interview transcript was found. Generate a resume-only final assessment?",
      );
      if (!proceed) return;
      setResumeOnlyConfirmed(true);
    }
    setBusyAction("regenerate");
    setError(null);
    try {
      await api.generateEvidenceReport(candidate.id);
      for (let attempt = 0; attempt < 30; attempt += 1) {
        const next = await api.evidenceReport(candidate.id);
        if (next.report) {
          setPayload(next);
          break;
        }
        await new Promise((resolve) => window.setTimeout(resolve, 2000));
      }
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not generate the evidence report");
    } finally {
      setBusyAction(null);
    }
  }

  async function download() {
    if (!candidate) return;
    setBusyAction("download");
    setError(null);
    try {
      let current = payload;
      if (!current?.report) {
        await regenerate(hasAnalyzedTranscript === false);
        current = await api.evidenceReport(candidate.id);
      }
      if (!current.report) {
        throw new Error("Report is not ready yet");
      }
      await api.downloadReport(current.report.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Download failed");
    } finally {
      setBusyAction(null);
    }
  }

  async function saveDecision(event: FormEvent) {
    event.preventDefault();
    if (!report) return;
    setBusyAction("decision");
    setError(null);
    try {
      await api.recordDecision(report.id, { outcome, notes });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the decision");
    } finally {
      setBusyAction(null);
    }
  }

  if (!candidate && !error) {
    return (
      <AppShell>
        <p className="text-sm text-muted">Loading evidence report…</p>
      </AppShell>
    );
  }

  if (!candidate) {
    return (
      <AppShell>
        <p className="text-sm text-[var(--rust)]">{error}</p>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <CandidateHeader candidate={candidate} jobTitle={job?.title ?? "Requisition"} />
      <main className="mx-auto w-full max-w-[1440px] px-6 py-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-xl font-bold text-ink-900">Final assessment</h2>
            <p className="mt-1 text-sm text-ink-500">
              Resume and transcript evidence combined. HireFlow does not hire — you decide.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <FitBadge
              overallMatch={body?.overall_after_interview ?? candidate.overall_match}
              matchRun={candidate.match_run}
            />
            <button
              type="button"
              disabled={busyAction !== null || pending}
              onClick={() => void download()}
              className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
            >
              {busyAction === "download" ? "Preparing…" : "Download report"}
            </button>
            <button
              type="button"
              disabled={busyAction !== null || pending || !matchReady}
              onClick={() => void regenerate()}
              className="rounded-lg border border-line bg-white px-4 py-2 text-sm disabled:opacity-60"
            >
              {busyAction === "regenerate" ? "Working…" : "Regenerate"}
            </button>
        </div>
      </div>
      {error && <p className="mt-3 text-sm text-[var(--rust)]">{error}</p>}
      {!matchReady && (
        <p className="mt-4 text-sm text-muted">
          Match the resume to the JD first.{" "}
          <Link href={`/candidates/${candidate.id}`} className="underline">
            Open match and gaps
          </Link>
        </p>
      )}
      {matchReady && hasAnalyzedTranscript === false && !report && !resumeOnlyConfirmed && (
        <section className="mt-4 rounded-xl border border-line bg-white p-5 shadow-[var(--shadow-card)]">
          <p className="text-sm text-ink-700">
            No analyzed interview transcript yet. You can generate a resume-only final assessment, or upload a
            transcript first for combined resume + interview evidence.
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            <button
              type="button"
              disabled={busyAction !== null}
              onClick={() => {
                setResumeOnlyConfirmed(true);
                void regenerate(true);
              }}
              className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
            >
              Use resume evidence only
            </button>
            <Link
              href={`/candidates/${candidate.id}/transcript`}
              className="rounded-lg border border-line px-4 py-2 text-sm font-semibold text-ink-700 hover:bg-canvas"
            >
              Upload transcript
            </Link>
          </div>
        </section>
      )}
      {(pending || (!report && matchReady && (hasAnalyzedTranscript || resumeOnlyConfirmed))) && (
        <p className="mt-4 text-sm text-muted">Writing the candidate evidence report…</p>
      )}
      {run?.status === "failed" && !body && (
        <p className="mt-4 text-sm text-[var(--rust)]">{run.error || "Evidence report failed."}</p>
      )}

      {body && (
        <>
          {body.partial && (
            <p className="mt-6 border border-line bg-paper px-4 py-3 text-sm">
              Partial report: interview columns are empty until a transcript is analyzed.
            </p>
          )}
          <section className="mt-6 border border-line bg-white p-5">
            <p className="text-xs uppercase tracking-wide text-muted">
              Version {report?.version ?? 1} · {body.generated_at}
              {body.transcript_version ? ` · transcript v${body.transcript_version}` : ""}
            </p>
            <p className="mt-3 text-sm">{body.headline}</p>
            <p className="mt-2 text-sm text-muted">{body.closing}</p>
          </section>

          <section className="mt-6 overflow-x-auto border border-line bg-white p-5">
            <h2 className="font-serif text-xl">Matrix</h2>
            <table className="mt-4 w-full min-w-[640px] border-collapse text-sm">
              <thead>
                <tr className="text-left text-muted">
                  <th className="border-b border-line pb-2 pr-3 font-medium">Requirement</th>
                  <th className="border-b border-line pb-2 pr-3 font-medium">Resume</th>
                  <th className="border-b border-line pb-2 pr-3 font-medium">Interview</th>
                  <th className="border-b border-line pb-2 pr-3 font-medium">Final</th>
                  <th className="border-b border-line pb-2 font-medium">Evidence</th>
                </tr>
              </thead>
              <tbody>
                {body.matrix.map((row) => (
                  <tr key={row.requirement_id}>
                    <td className="border-b border-line py-2 pr-3">{row.requirement_label}</td>
                    <td className="border-b border-line py-2 pr-3">
                      <StatusChip status={row.status_after_resume} />
                    </td>
                    <td className="border-b border-line py-2 pr-3">
                      {row.status_after_interview ? (
                        <StatusChip status={row.status_after_interview} />
                      ) : (
                        <span className="text-muted">{body.partial ? "—" : "unchanged"}</span>
                      )}
                      {row.unvalidated && <span className="ml-2 text-xs text-muted">unvalidated</span>}
                    </td>
                    <td className="border-b border-line py-2 pr-3">
                      <StatusChip status={row.final} />
                    </td>
                    <td className="border-b border-line py-2 text-muted">
                      {row.evidence_codes.join(", ") || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section className="mt-6 border border-line bg-white p-5">
            <h2 className="font-serif text-xl">Must-haves</h2>
            {body.must_haves.length === 0 && <p className="mt-3 text-sm text-muted">No must-have requirements.</p>}
            <ul className="mt-4 space-y-3">
              {body.must_haves.map((row) => (
                <li key={row.requirement_id} className="border border-line bg-paper p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-medium">{row.requirement_label}</span>
                    <StatusChip status={row.final} />
                  </div>
                  <p className="mt-2 text-sm">
                    Strongest quote ({row.source ?? "none"}): {row.strongest_quote || "No evidence found"}
                  </p>
                  {row.evidence_codes.length > 0 && (
                    <p className="mt-1 text-xs uppercase tracking-wide text-muted">
                      Cited: {row.evidence_codes.join(" · ")}
                    </p>
                  )}
                  {row.remaining_doubt && <p className="mt-2 text-sm text-muted">{row.remaining_doubt}</p>}
                </li>
              ))}
            </ul>
          </section>

          <section className="mt-6 border border-line bg-white p-5">
            <h2 className="font-serif text-xl">Unresolved gaps and remaining follow-ups</h2>
            {body.unresolved.length === 0 && <p className="mt-3 text-sm text-muted">No unresolved gaps.</p>}
            <ul className="mt-4 space-y-3">
              {body.unresolved.map((row) => (
                <li key={row.requirement_id} className="border border-line bg-paper p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{row.requirement_label}</span>
                    <ProbeChip verdict={row.verdict} />
                  </div>
                  {row.note && <p className="mt-2 text-sm">{row.note}</p>}
                  {row.followups.length > 0 && (
                    <ol className="mt-3 list-decimal space-y-1 pl-5 text-sm">
                      {row.followups.map((question) => (
                        <li key={question}>{question}</li>
                      ))}
                    </ol>
                  )}
                </li>
              ))}
            </ul>
          </section>

          <section className="mt-6 border border-line bg-white p-5">
            <h2 className="font-serif text-xl">Contradictions</h2>
            {body.contradictions.length === 0 && <p className="mt-3 text-sm text-muted">None recorded.</p>}
            <ul className="mt-4 list-disc space-y-2 pl-5 text-sm">
              {body.contradictions.map((row) => (
                <li key={row.evidence_code}>
                  {row.evidence_code} {row.requirement_label}: {row.quote}
                </li>
              ))}
            </ul>
          </section>

          <section className="mt-6 border border-line bg-white p-5">
            <h2 className="font-serif text-xl">Transcript coverage</h2>
            {body.partial && <p className="mt-3 text-sm text-muted">No transcript. Interview coverage is empty.</p>}
            {!body.partial && (
              <ul className="mt-4 space-y-2">
                {body.coverage.map((row) => (
                  <li key={row.requirement_id} className="flex flex-wrap items-center justify-between gap-2 text-sm">
                    <span>
                      {row.requirement_label}
                      {row.skipped_in_plan ? <span className="text-muted"> · not in plan</span> : null}
                    </span>
                    <ProbeChip verdict={row.verdict} />
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="mt-6 border border-line bg-white p-5">
            <h2 className="font-serif text-xl">Remaining risks</h2>
            <ul className="mt-4 list-disc space-y-2 pl-5 text-sm">
              {body.remaining_risks.map((risk) => (
                <li key={risk}>{risk}</li>
              ))}
            </ul>
          </section>

          <section className="mt-6 border border-line bg-white p-5">
            <h2 className="font-serif text-xl">Decision</h2>
            <p className="mt-1 text-sm text-muted">
              Agents never write this. Record advance, hold, or reject against this report version.
            </p>
            <form onSubmit={(event) => void saveDecision(event)} className="mt-4 space-y-3">
              <div className="flex flex-wrap gap-4 text-sm">
                {(["advance", "hold", "reject"] as DecisionOutcome[]).map((value) => (
                  <label key={value} className="flex items-center gap-2">
                    <input
                      type="radio"
                      name="outcome"
                      value={value}
                      checked={outcome === value}
                      disabled={busyAction !== null}
                      onChange={() => setOutcome(value)}
                    />
                    {value}
                  </label>
                ))}
              </div>
              <label className="block text-sm">
                Notes
                <textarea
                  className="mt-1 min-h-24 w-full border border-line bg-paper px-3 py-2"
                  value={notes}
                  disabled={busyAction !== null}
                  onChange={(event) => setNotes(event.target.value)}
                />
              </label>
              <button
                type="submit"
                disabled={busyAction !== null || !report}
                className="bg-forest px-4 py-2 text-sm text-white disabled:opacity-60"
              >
                {busyAction === "decision" ? "Saving…" : payload?.decision ? "Update decision" : "Save decision"}
              </button>
              {payload?.decision && (
                <p className="text-xs text-muted">
                  Last recorded {payload.decision.outcome} at {payload.decision.decided_at}.
                </p>
              )}
            </form>
          </section>
        </>
      )}
      </main>
    </AppShell>
  );
}
