"use client";



import Link from "next/link";

import { useParams } from "next/navigation";

import { useCallback, useEffect, useRef, useState } from "react";

import { ArrowRight, Quote } from "lucide-react";

import { AppShell } from "@/components/AppShell";

import { CandidateHeader } from "@/components/CandidateHeader";

import { EvidenceStrip } from "@/components/EvidenceStrip";

import { StatusChip } from "@/components/StatusChip";

import { api } from "@/lib/api";

import type { Candidate, InterviewPlanResponse, JobDetail, MatchResult, MatrixResponse, Requirement } from "@/lib/types";

import { cellsForCandidate, countMatchStatuses, countStatuses, statusMeta, toUiStatus } from "@/lib/screening";



async function withRetry<T>(

  fn: () => Promise<T>,

  attempts = 2,

  delayMs = 300,

  retryIf?: (err: Error) => boolean,

): Promise<T> {

  let last: Error | null = null;

  for (let i = 0; i < attempts; i += 1) {

    try {

      return await fn();

    } catch (err) {

      last = err instanceof Error ? err : new Error(String(err));

      const shouldRetry = retryIf?.(last) ?? /not found/i.test(last.message);

      if (i + 1 < attempts && shouldRetry) {

        await new Promise((resolve) => window.setTimeout(resolve, delayMs * (i + 1)));

        continue;

      }

      throw last;

    }

  }

  throw last ?? new Error("Request failed");

}



function isPending(candidate: Candidate | null, job: JobDetail | null): boolean {

  if (!candidate) return false;

  const statuses = [

    candidate.resume?.extract_run?.status,

    candidate.parse_run?.status,

    candidate.match_run?.status,

    job?.jd?.extract_run?.status,

    job?.parse_run?.status,

  ];

  return statuses.some((s) => s === "queued" || s === "running");

}



function matchStatusForRequirement(

  requirementId: string,

  matches: MatchResult[],

  cellStatus: string | null | undefined,

) {

  const match = matches.find((item) => item.requirement_id === requirementId);

  return match?.status ?? cellStatus ?? null;

}



export default function CandidatePage() {

  const params = useParams<{ id: string }>();

  const [candidate, setCandidate] = useState<Candidate | null>(null);

  const [job, setJob] = useState<JobDetail | null>(null);

  const [matrix, setMatrix] = useState<MatrixResponse | null>(null);

  const [matches, setMatches] = useState<MatchResult[]>([]);

  const [interviewPlan, setInterviewPlan] = useState<InterviewPlanResponse | null>(null);

  const [error, setError] = useState<string | null>(null);

  const [jobError, setJobError] = useState<string | null>(null);

  const [loading, setLoading] = useState(true);

  const [progress, setProgress] = useState<string | null>(null);

  const [busyAction, setBusyAction] = useState<
    null | "reparse" | "screen" | "downloadEvidence" | "downloadInterview"
  >(null);

  const [halted, setHalted] = useState(false);

  const screeningRef = useRef(false);



  const load = useCallback(async () => {

    const next = await withRetry(() => api.candidate(params.id));

    setCandidate(next);

    setError(null);

    let jobResult: JobDetail | null = null;

    try {

      jobResult = await withRetry(() => api.job(next.job_id), 2);

      setJobError(null);

    } catch (err) {

      jobResult = null;

      setJobError(err instanceof Error ? err.message : "Could not load requisition details.");

    }

    const [matchResult, matrixResult, planResult] = await Promise.all([

      api.matches(params.id).catch(() => [] as MatchResult[]),

      jobResult ? api.matrix(next.job_id).catch(() => null) : Promise.resolve(null),

      api.interviewPlan(params.id).catch(() => null),

    ]);

    setJob(jobResult);

    setMatches(matchResult);

    setMatrix(matrixResult);

    setInterviewPlan(planResult);

    const hasResults =

      Boolean(next.overall_match) ||

      next.match_run?.status === "succeeded" ||

      matchResult.length > 0;

    const hasProfile = Boolean(next.profile) || next.claims.length > 0;

    if (hasResults || (hasProfile && next.parse_run?.status === "succeeded")) {

      setError(null);

      setHalted(false);

      setProgress(null);

    }

    return { candidate: next, matches: matchResult, plan: planResult };

  }, [params.id]);



  useEffect(() => {

    setLoading(true);

    void load()

      .catch((err: Error) => setError(err.message))

      .finally(() => setLoading(false));

  }, [load]);



  useEffect(() => {

    if (!candidate || halted || screeningRef.current) return;



    const hasResults =

      Boolean(candidate.overall_match) ||

      candidate.match_run?.status === "succeeded" ||

      matches.length > 0;

    const hasProfile = Boolean(candidate.profile) || candidate.claims.length > 0;



    if (hasResults) {

      setError(null);

      setHalted(false);

      setProgress(null);

      return;

    }



    if (candidate.parse_run?.status === "failed" && !hasProfile) {

      setHalted(true);

      setError(candidate.parse_run.error ?? "Resume parsing failed.");

      return;

    }



    if (isPending(candidate, job)) return;



    screeningRef.current = true;

    let cancelled = false;

    void api

      .screenCandidate(candidate.id)

      .then(async (status) => {

        if (cancelled) return;

        setProgress(status.step === "ready" ? null : status.message);

        if (status.step === "blocked") {

          setHalted(true);

          setError(status.message);

        } else {

          setError(null);

          setHalted(false);

        }

        await load();

      })

      .catch((err: Error) => {

        if (cancelled) return;

        setError(err.message);

        setHalted(true);

      })

      .finally(() => {

        screeningRef.current = false;

      });

    return () => {

      cancelled = true;

    };

  }, [candidate, job, halted, load, matches.length]);



  useEffect(() => {

    const shouldPoll = isPending(candidate, job) || (candidate && !job);

    if (!shouldPoll) return;

    const timer = window.setInterval(() => void load(), 3500);

    return () => window.clearInterval(timer);

  }, [candidate, job, load]);

  const planGenerateRef = useRef(false);
  useEffect(() => {
    const matchReady =
      Boolean(candidate?.overall_match) ||
      candidate?.match_run?.status === "succeeded" ||
      matches.length > 0;
    const planPending =
      interviewPlan?.run?.status === "queued" || interviewPlan?.run?.status === "running";
    const questionCount = interviewPlan?.plan?.questions.length ?? 0;
    if (!candidate || !matchReady || planPending || questionCount > 0 || planGenerateRef.current) return;
    planGenerateRef.current = true;
    void api
      .generateInterviewPlan(candidate.id)
      .then(() => load())
      .catch(() => undefined)
      .finally(() => {
        planGenerateRef.current = false;
      });
  }, [candidate, interviewPlan, matches.length, load]);

  async function downloadEvidence() {

    if (!candidate) return;

    setBusyAction("downloadEvidence");

    setError(null);

    try {

      await api.downloadScreeningBrief(candidate.id);

    } catch (err) {

      setError(err instanceof Error ? err.message : "Download failed");

    } finally {

      setBusyAction(null);

    }

  }



  async function downloadInterviewQuestions() {

    if (!candidate) return;

    setBusyAction("downloadInterview");

    setError(null);

    try {

      let plan = interviewPlan?.plan;

      if (!plan || plan.questions.length === 0) {

        await api.generateInterviewPlan(candidate.id);

        for (let attempt = 0; attempt < 30; attempt += 1) {

          const next = await api.interviewPlan(candidate.id);

          if (next.plan && next.plan.questions.length > 0) {

            plan = next.plan;

            setInterviewPlan(next);

            break;

          }

          await new Promise((resolve) => window.setTimeout(resolve, 2000));

        }

      }

      await api.downloadInterviewBrief(candidate.id);

    } catch (err) {

      setError(err instanceof Error ? err.message : "Interview questions are not ready yet");

    } finally {

      setBusyAction(null);

    }

  }



  async function reparseResume() {

    if (!candidate) return;

    setBusyAction("reparse");

    setError(null);

    setHalted(false);

    screeningRef.current = false;

    setProgress("Re-parsing resume and rebuilding match…");

    try {

      await api.reparseResume(candidate.id);

      for (let attempt = 0; attempt < 40; attempt += 1) {

        const latest = await api.candidate(candidate.id);

        const parsing = latest.parse_run?.status === "queued" || latest.parse_run?.status === "running";

        if (!parsing && (latest.profile || latest.claims.length > 0)) break;

        await new Promise((resolve) => window.setTimeout(resolve, 1500));

      }

      const status = await api.screenCandidate(candidate.id, true);

      setProgress(status.step === "ready" ? null : status.message);

      await load();

    } catch (err) {

      setError(err instanceof Error ? err.message : "Re-parse failed");

      setHalted(true);

    } finally {

      setBusyAction(null);

    }

  }



  async function retryScreening() {

    if (!candidate) return;

    setBusyAction("screen");

    setError(null);

    setHalted(false);

    screeningRef.current = false;

    setProgress("Re-running match against the JD…");

    try {

      const status = await api.screenCandidate(candidate.id, true);

      setProgress(status.step === "ready" ? null : status.message);

      if (status.step === "blocked") {

        setHalted(true);

        setError(status.message);

      }

      await load();

    } catch (err) {

      setError(err instanceof Error ? err.message : "Screening failed");

      setHalted(true);

    } finally {

      setBusyAction(null);

    }

  }



  if (loading && !candidate) {

    return (

      <AppShell>

        <p className="px-6 py-20 text-sm text-ink-500">Loading candidate…</p>

      </AppShell>

    );

  }



  if (!candidate) {

    return (

      <AppShell>

        <p className="px-6 py-20 text-sm text-missing">{error ?? "Candidate not found"}</p>

      </AppShell>

    );

  }



  if (!job) {

    return (

      <AppShell>

        <CandidateHeader candidate={candidate} jobTitle="Requisition" />

        <main className="mx-auto w-full max-w-[1440px] px-6 py-6">

          <p className="text-sm text-ink-500">Loading requisition details…</p>

          {jobError && <p className="mt-2 text-sm text-missing">{jobError}</p>}

        </main>

      </AppShell>

    );

  }



  const requirements: Requirement[] = matrix?.requirements ?? job.requirements;

  const cells = matrix?.cells ?? [];

  const rows = cellsForCandidate(cells, candidate.id, requirements);

  const rowsWithStatus = rows.map(({ requirement, cell }) => ({

    requirement,

    cell,

    status: matchStatusForRequirement(requirement.id, matches, cell?.status),

  }));

  const counts =

    matches.length > 0

      ? countMatchStatuses(matches.map((item) => item.status))

      : countStatuses(cells, candidate.id);

  const toValidate = rowsWithStatus.filter(({ status }) => status !== "MATCHED");

  const confirmed = rowsWithStatus.filter(({ status }) => status === "MATCHED");

  const ready = Boolean(candidate.overall_match) || candidate.match_run?.status === "succeeded" || matches.length > 0;

  const planQuestions = interviewPlan?.plan?.questions ?? [];

  const planPending =

    interviewPlan?.run?.status === "queued" || interviewPlan?.run?.status === "running";

  const screeningFailed =

    !ready &&

    (candidate.parse_run?.status === "failed" || candidate.match_run?.status === "failed");

  const screeningBlocked = (halted || screeningFailed) && !ready;



  return (

    <AppShell>

      <CandidateHeader candidate={candidate} jobTitle={job.title} />

      <main className="mx-auto w-full max-w-[1440px] px-6 py-6">

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">

          <div>

            <section className="rounded-xl border border-line bg-white p-5 shadow-[var(--shadow-card)]">

              <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-400">What the resume says</h2>

              <p className="mt-2 text-base leading-relaxed text-ink-700">

                {candidate.profile?.summary ?? "No profile summary yet."}

              </p>

              {candidate.profile?.skills_listed && candidate.profile.skills_listed.length > 0 && (

                <div className="mt-4 flex flex-wrap gap-2">

                  {candidate.profile.skills_listed.map((skill) => (

                    <span key={skill} className="rounded-md bg-canvas px-2.5 py-1 text-xs font-medium text-ink-700">

                      {skill}

                    </span>

                  ))}

                </div>

              )}

            </section>



            {!ready && !screeningBlocked && (progress || isPending(candidate, job)) && (

              <p className="mt-4 text-sm text-ink-500">{progress ?? "Preparing match and gap analysis…"}</p>

            )}

            {(error || screeningFailed) && (

              <div className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3">

                <p className="text-sm text-missing">

                  {error ??

                    candidate.parse_run?.error ??

                    candidate.match_run?.error ??

                    "Screening could not finish."}

                </p>

                <div className="mt-3 flex flex-wrap gap-2">

                  <button

                    type="button"

                    disabled={busyAction !== null}

                    onClick={() => void reparseResume()}

                    className="rounded-lg border border-line bg-white px-4 py-2 text-sm font-semibold text-ink-700 disabled:opacity-60"

                  >

                    {busyAction === "reparse" ? "Working…" : "Re-parse resume"}

                  </button>

                  {screeningBlocked && (

                    <button

                      type="button"

                      disabled={busyAction !== null}

                      onClick={() => void retryScreening()}

                      className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"

                    >

                      {busyAction === "screen" ? "Retrying…" : "Retry screening"}

                    </button>

                  )}

                </div>

              </div>

            )}



            <section className="mt-6" aria-labelledby="validate-heading">

              <div className="flex items-baseline gap-3">

                <h2 id="validate-heading" className="text-xl font-bold text-ink-900">

                  Needs validation

                </h2>

                <span className="text-sm text-ink-500">{toValidate.length} requirements</span>

              </div>

              <ol className="mt-4 space-y-3">

                {toValidate.map(({ requirement, cell, status }) => {

                  const match = matches.find((m) => m.requirement_id === requirement.id);

                  const ui = toUiStatus(status);

                  const meta = statusMeta[ui];

                  const quote = match?.quotes?.[0] ?? cell?.quotes?.[0] ?? "No evidence found.";

                  return (

                    <li key={requirement.id} className="rounded-xl border border-line bg-white shadow-[var(--shadow-card)]">

                      <div className="flex items-start gap-4 p-5">

                        <span className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${meta.dot}`} aria-hidden="true" />

                        <div className="min-w-0 flex-1">

                          <div className="flex flex-wrap items-center gap-2">

                            <h3 className="text-base font-semibold text-ink-900">

                              {requirement.normalized_label || requirement.text}

                            </h3>

                            {requirement.priority === "must_have" && (

                              <span className="rounded bg-canvas px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-ink-500">

                                Must have

                              </span>

                            )}

                            <StatusChip status={status} />

                          </div>

                          <p className="mt-3 flex gap-2 text-sm italic leading-relaxed text-ink-700">

                            <Quote className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ink-400" aria-hidden="true" />

                            {quote}

                          </p>

                          <p className="mt-2 text-sm text-ink-500">{match?.rationale ?? cell?.rationale ?? ""}</p>

                        </div>

                      </div>

                    </li>

                  );

                })}

              </ol>

            </section>



            {confirmed.length > 0 && (

              <section className="mt-8">

                <h2 className="text-base font-semibold text-ink-900">Already evidenced ({confirmed.length})</h2>

                <ul className="mt-3 divide-y divide-line rounded-xl border border-line bg-white shadow-[var(--shadow-card)]">

                  {confirmed.map(({ requirement, cell, status }) => {

                    const match = matches.find((m) => m.requirement_id === requirement.id);

                    return (

                      <li key={requirement.id} className="flex items-start gap-4 px-5 py-3.5">

                        <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-matched" aria-hidden="true" />

                        <div className="min-w-0 flex-1">

                          <p className="text-sm font-medium text-ink-900">

                            {requirement.normalized_label || requirement.text}

                          </p>

                          <p className="mt-0.5 truncate text-sm text-ink-500">

                            {match?.quotes?.[0] ?? cell?.quotes?.[0] ?? "Matched"}

                          </p>

                        </div>

                      </li>

                    );

                  })}

                </ul>

              </section>

            )}



            {ready && (

              <section className="mt-8 rounded-xl border border-line bg-white p-5 shadow-[var(--shadow-card)]">

                <div className="flex flex-wrap items-center justify-between gap-3">

                  <div>

                    <h2 className="text-base font-semibold text-ink-900">Interview questions</h2>

                    <p className="mt-1 text-sm text-ink-500">

                      Generated from gaps that still need validation in the interview.

                    </p>

                  </div>

                  <Link

                    href={`/candidates/${candidate.id}/plan`}

                    className="text-sm font-semibold text-brand-600 hover:text-brand-700"

                  >

                    Open full interview kit

                  </Link>

                </div>

                {planPending && (

                  <p className="mt-4 text-sm text-ink-500">Generating interview questions…</p>

                )}

                {!planPending && planQuestions.length === 0 && (

                  <p className="mt-4 text-sm text-ink-500">

                    No questions yet.{" "}

                    <Link href={`/candidates/${candidate.id}/plan`} className="font-semibold text-brand-600">

                      Generate the interview kit

                    </Link>

                  </p>

                )}

                {planQuestions.length > 0 && (

                  <ol className="mt-4 space-y-3">

                    {planQuestions.slice(0, 5).map((question, index) => (

                      <li key={question.id} className="rounded-lg bg-canvas px-4 py-3">

                        <p className="text-xs font-semibold uppercase tracking-wide text-ink-400">

                          {question.requirement_label || `Question ${index + 1}`}

                        </p>

                        <p className="mt-1 text-sm text-ink-800">{question.prompt}</p>

                      </li>

                    ))}

                  </ol>

                )}

              </section>

            )}

          </div>



          <aside>

            <section className="sticky top-[88px] rounded-xl border border-line bg-white p-5 shadow-[var(--shadow-card)]">

              <h2 className="text-base font-semibold text-ink-900">Evidence coverage</h2>

              <div className="mt-3">

                <EvidenceStrip requirements={requirements} cells={cells} candidateId={candidate.id} size="md" />

              </div>

              <dl className="mt-4 grid grid-cols-2 gap-3">

                {(["matched", "partial", "unclear", "missing"] as const).map((status) => (

                  <div key={status} className="rounded-lg bg-canvas px-3 py-2.5">

                    <dt className="flex items-center gap-1.5 text-xs text-ink-500">

                      <span className={`h-1.5 w-1.5 rounded-full ${statusMeta[status].dot}`} aria-hidden="true" />

                      {statusMeta[status].label}

                    </dt>

                    <dd className="mt-0.5 text-lg font-bold text-ink-900">{counts[status]}</dd>

                  </div>

                ))}

              </dl>

              <div className="mt-5 border-t border-line pt-4 space-y-2">

                <button

                  type="button"

                  disabled={busyAction !== null || isPending(candidate, job)}

                  onClick={() => void reparseResume()}

                  className="w-full rounded-lg border border-line px-4 py-2.5 text-sm font-semibold text-ink-700 hover:bg-canvas disabled:opacity-50"

                >

                  {busyAction === "reparse" ? "Working…" : "Re-parse resume"}

                </button>

                <button

                  type="button"

                  disabled={busyAction !== null || isPending(candidate, job)}

                  onClick={() => void retryScreening()}

                  className="w-full rounded-lg border border-line px-4 py-2.5 text-sm font-semibold text-ink-700 hover:bg-canvas disabled:opacity-50"

                >

                  {busyAction === "screen" ? "Working…" : "Re-run screening"}

                </button>

                <button

                  type="button"

                  disabled={!ready || busyAction !== null}

                  onClick={() => void downloadEvidence()}

                  className="w-full rounded-lg bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-50"

                >

                  {busyAction === "downloadEvidence" ? "Preparing…" : "Download resume evidence"}

                </button>

                <button

                  type="button"

                  disabled={!ready || busyAction !== null}

                  onClick={() => void downloadInterviewQuestions()}

                  className="w-full rounded-lg bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-50"

                >

                  {busyAction === "downloadInterview" ? "Preparing…" : "Download interview questions"}

                </button>

                <Link

                  href={`/candidates/${candidate.id}/plan`}

                  className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-brand-700"

                >

                  Open interview kit

                  <ArrowRight className="h-4 w-4" aria-hidden="true" />

                </Link>

              </div>

            </section>

          </aside>

        </div>

      </main>

    </AppShell>

  );

}


