"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { CandidateHeader } from "@/components/CandidateHeader";
import { FitBadge } from "@/components/FitBadge";
import { StatusChip } from "@/components/StatusChip";
import { api } from "@/lib/api";
import type { Candidate, InterviewPlan, InterviewPlanResponse, JobDetail, PlannedQuestion } from "@/lib/types";

function QuestionCard({
  question,
  disabled,
  onSave,
}: {
  question: PlannedQuestion;
  disabled: boolean;
  onSave: (id: string, body: { prompt?: string; planned_followups?: string[]; dropped?: boolean }) => Promise<void>;
}) {
  const [prompt, setPrompt] = useState(question.prompt);
  const [followups, setFollowups] = useState(question.planned_followups.join("\n"));

  useEffect(() => {
    setPrompt(question.prompt);
    setFollowups(question.planned_followups.join("\n"));
  }, [question.prompt, question.planned_followups]);

  const dirty =
    prompt.trim() !== question.prompt.trim() ||
    followups.split("\n").map((line) => line.trim()).filter(Boolean).join("\n") !==
      question.planned_followups.join("\n");

  return (
    <li className="rounded-xl border border-line bg-white p-4 shadow-[var(--shadow-card)]">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{question.requirement_label || "Requirement"}</span>
          <StatusChip status={question.match_status} />
        </div>
        <button
          type="button"
          disabled={disabled}
          onClick={() => void onSave(question.id, { dropped: true })}
          className="text-xs text-[var(--rust)] disabled:opacity-60"
        >
          Drop
        </button>
      </div>
      {question.evidence_target.length > 0 && (
        <p className="mt-1 text-xs uppercase tracking-wide text-muted">
          Evidence target: {question.evidence_target.join(" · ")}
        </p>
      )}
      <label className="mt-3 block text-sm">
        Primary question
        <textarea
          className="mt-1 min-h-24 w-full border border-line bg-white px-3 py-2"
          value={prompt}
          disabled={disabled}
          onChange={(event) => setPrompt(event.target.value)}
        />
      </label>
      <label className="mt-3 block text-sm">
        Planned follow-ups (one per line)
        <textarea
          className="mt-1 min-h-20 w-full border border-line bg-white px-3 py-2"
          value={followups}
          disabled={disabled}
          onChange={(event) => setFollowups(event.target.value)}
        />
      </label>
      <button
        type="button"
        disabled={disabled || !dirty || !prompt.trim()}
        onClick={() =>
          void onSave(question.id, {
            prompt: prompt.trim(),
            planned_followups: followups
              .split("\n")
              .map((line) => line.trim())
              .filter(Boolean),
          })
        }
        className="mt-3 border border-line bg-white px-3 py-1.5 text-sm disabled:opacity-60"
      >
        Save edits
      </button>
    </li>
  );
}

export default function InterviewPlanPage() {
  const params = useParams<{ id: string }>();
  const [candidate, setCandidate] = useState<Candidate | null>(null);
  const [job, setJob] = useState<JobDetail | null>(null);
  const [payload, setPayload] = useState<InterviewPlanResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<null | "download" | "regenerate" | "save">(null);
  const generateRef = useRef(false);

  const load = useCallback(async () => {
    const [nextCandidate, nextPlan] = await Promise.all([
      api.candidate(params.id),
      api.interviewPlan(params.id),
    ]);
    setCandidate(nextCandidate);
    setPayload(nextPlan);
    setJob(await api.job(nextCandidate.job_id).catch(() => null));
    return { candidate: nextCandidate, plan: nextPlan };
  }, [params.id]);

  useEffect(() => {
    void load().catch((err: Error) => setError(err.message));
  }, [load]);

  const run = payload?.run ?? payload?.plan?.run ?? null;
  const pending = run?.status === "queued" || run?.status === "running";
  const plan: InterviewPlan | null = payload?.plan ?? null;
  const matchReady = Boolean(candidate?.overall_match) || candidate?.match_run?.status === "succeeded";

  useEffect(() => {
    const needsPlan = !plan || plan.questions.length === 0;
    if (!candidate || pending || !needsPlan || generateRef.current || !matchReady) return;
    generateRef.current = true;
    void api
      .generateInterviewPlan(candidate.id)
      .then(() => load())
      .catch((err: Error) => setError(err.message))
      .finally(() => {
        generateRef.current = false;
      });
  }, [candidate, pending, plan, matchReady, load]);

  useEffect(() => {
    if (!pending) return;
    const timer = window.setInterval(() => {
      void load();
    }, 2000);
    return () => window.clearInterval(timer);
  }, [pending, load]);

  async function regenerate() {
    if (!candidate) return;
    setBusyAction("regenerate");
    setError(null);
    try {
      await api.generateInterviewPlan(candidate.id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not generate the interview plan");
    } finally {
      setBusyAction(null);
    }
  }

  async function saveQuestion(
    id: string,
    body: { prompt?: string; planned_followups?: string[]; dropped?: boolean },
  ) {
    setBusyAction("save");
    setError(null);
    try {
      await api.patchPlannedQuestion(id, body);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the question");
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
      if (!current?.plan || current.plan.questions.length === 0) {
        await api.generateInterviewPlan(candidate.id);
        for (let attempt = 0; attempt < 30; attempt += 1) {
          current = await api.interviewPlan(candidate.id);
          if (current.plan && current.plan.questions.length > 0) {
            setPayload(current);
            break;
          }
          await new Promise((resolve) => window.setTimeout(resolve, 2000));
        }
      }
      await api.downloadInterviewBrief(candidate.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Download failed");
    } finally {
      setBusyAction(null);
    }
  }

  if (!candidate && !error) {
    return (
      <AppShell>
        <p className="text-sm text-muted">Loading interview plan…</p>
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
            <h2 className="text-xl font-bold text-ink-900">Interview kit</h2>
            <p className="mt-1 text-sm text-ink-500">
              One probe per unproven requirement. Edit before you take it into the interview.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <FitBadge overallMatch={candidate.overall_match} matchRun={candidate.match_run} />
            <button
              type="button"
              disabled={busyAction !== null || pending}
              onClick={() => void download()}
              className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
            >
              {busyAction === "download" ? "Preparing…" : "Download interview questions"}
            </button>
            <Link
              href={`/candidates/${candidate.id}/transcript`}
              className="rounded-lg border border-line px-4 py-2 text-sm font-semibold text-ink-700 hover:bg-canvas"
            >
              Transcript
            </Link>
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
        {error && <p className="mt-3 text-sm text-missing">{error}</p>}
        {!matchReady && (
          <p className="mt-4 text-sm text-ink-500">
            Match the resume to the JD first.{" "}
            <Link href={`/candidates/${candidate.id}`} className="font-semibold text-brand-600">
              Open resume evidence
            </Link>
          </p>
        )}
        {(pending || (!plan && matchReady)) && (
          <p className="mt-4 text-sm text-ink-500">Writing a candidate-specific interview plan…</p>
        )}
        {run?.status === "failed" && !plan && (
          <p className="mt-4 text-sm text-missing">{run.error || "Interview plan failed."}</p>
        )}

        {plan && (
          <section className="mt-6 rounded-xl border border-line bg-white p-5 shadow-[var(--shadow-card)]">
            <h3 className="text-base font-semibold text-ink-900">Questions for this candidate</h3>
            <p className="mt-1 text-sm text-ink-500">
              Version {plan.version} · {plan.status.replaceAll("_", " ")}.
            </p>
          {plan.questions.length === 0 && (
            <p className="mt-4 text-sm text-muted">
              No questions. Remaining must-haves are MATCHED, or gaps were skipped.
            </p>
          )}
          <ul className="mt-4 space-y-4">
            {plan.questions.map((question) => (
              <QuestionCard key={question.id} question={question} disabled={busyAction !== null || pending} onSave={saveQuestion} />
            ))}
          </ul>
          </section>
        )}
      </main>
    </AppShell>
  );
}
