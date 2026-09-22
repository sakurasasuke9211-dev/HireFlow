"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { CandidateHeader } from "@/components/CandidateHeader";
import { FilePicker, chosenFile } from "@/components/FilePicker";
import { ProbeChip } from "@/components/ProbeChip";
import { api } from "@/lib/api";
import type { Candidate, JobDetail, Requirement, Speaker, TranscriptDetail, TranscriptSummary } from "@/lib/types";

function isPending(item: TranscriptSummary | TranscriptDetail | null): boolean {
  if (!item) return false;
  if (item.status === "analyzed" || item.status === "failed") return false;
  const status = item.run?.status;
  if (status === "queued" || status === "running") return true;
  if (status === "failed") return false;
  return item.status === "uploaded" || item.status === "parsed";
}

function speakerLabel(speaker: Speaker) {
  if (speaker === "recruiter") return "Recruiter";
  if (speaker === "candidate") return "Candidate";
  return "Unknown";
}

export default function TranscriptPage() {
  const params = useParams<{ id: string }>();
  const [candidate, setCandidate] = useState<Candidate | null>(null);
  const [job, setJob] = useState<JobDetail | null>(null);
  const [versions, setVersions] = useState<TranscriptSummary[]>([]);
  const [detail, setDetail] = useState<TranscriptDetail | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [paste, setPaste] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<null | "upload" | "analyze" | "saveTurn">(null);
  const analyzeRef = useRef(false);

  const loadList = useCallback(async () => {
    const [nextCandidate, nextVersions] = await Promise.all([
      api.candidate(params.id),
      api.transcripts(params.id).catch(() => [] as TranscriptSummary[]),
    ]);
    setCandidate(nextCandidate);
    setVersions(nextVersions);
    setJob(await api.job(nextCandidate.job_id).catch(() => null));
    return nextVersions;
  }, [params.id]);

  const loadDetail = useCallback(async (transcriptId: string) => {
    const next = await api.transcript(transcriptId);
    setDetail(next);
    setSelectedId(next.id);
    return next;
  }, []);

  useEffect(() => {
    void loadList()
      .then(async (nextVersions) => {
        const latest = nextVersions[0];
        if (latest) await loadDetail(latest.id);
      })
      .catch((err: Error) => setError(err.message));
  }, [loadList, loadDetail]);

  useEffect(() => {
    if (!detail || !isPending(detail)) return;
    const timer = window.setInterval(() => {
      void loadDetail(detail.id).then(() => loadList());
    }, 2000);
    return () => window.clearInterval(timer);
  }, [detail, loadDetail, loadList]);

  useEffect(() => {
    if (!detail || analyzeRef.current) return;
    if (detail.status !== "uploaded" || !detail.extracted_text) return;
    if (detail.run?.status === "queued" || detail.run?.status === "running") return;
    analyzeRef.current = true;
    void api
      .analyzeTranscript(detail.id)
      .then(() => loadDetail(detail.id))
      .catch(() => {})
      .finally(() => {
        analyzeRef.current = false;
      });
  }, [detail, loadDetail]);

  async function onUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const selected = chosenFile(event.currentTarget, file);
    const pasted = paste.trim();
    if (!selected && !pasted) {
      setError("Upload a transcript file or paste the text");
      return;
    }
    setBusyAction("upload");
    setError(null);
    try {
      const created = await api.uploadTranscript(params.id, {
        file: selected ?? undefined,
        text: selected ? undefined : pasted,
      });
      setFile(null);
      setPaste("");
      await loadList();
      await loadDetail(created.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the transcript");
    } finally {
      setBusyAction(null);
    }
  }

  async function analyze() {
    if (!detail) return;
    setBusyAction("analyze");
    setError(null);
    try {
      await api.analyzeTranscript(detail.id);
      await loadDetail(detail.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not analyze the transcript");
    } finally {
      setBusyAction(null);
    }
  }

  async function saveTurn(turnId: string, body: { speaker?: Speaker; requirement_id?: string | null }) {
    setBusyAction("saveTurn");
    setError(null);
    try {
      await api.patchTranscriptTurn(turnId, body);
      if (detail) await loadDetail(detail.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the turn");
    } finally {
      setBusyAction(null);
    }
  }

  if (!candidate && !error) {
    return (
      <AppShell>
        <p className="text-sm text-muted">Loading transcript…</p>
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

  const requirements: Requirement[] = job?.requirements ?? [];
  const pending = isPending(detail);
  const remaining = (detail?.probes ?? []).flatMap((probe) =>
    (probe.remaining_followups ?? []).map((question) => ({
      requirement: probe.requirement_label,
      verdict: probe.verdict,
      question,
    })),
  );

  return (
    <AppShell>
      <CandidateHeader candidate={candidate} jobTitle={job?.title ?? "Requisition"} />
      <main className="mx-auto w-full max-w-[1440px] px-6 py-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-xl font-bold text-ink-900">Interview transcript</h2>
            <p className="mt-1 text-sm text-ink-500">
              Upload or paste the interview record. HireFlow validates answers against requirements.
            </p>
          </div>
        <div className="flex flex-wrap items-center gap-2">
          {versions.length > 0 && (
            <label className="text-sm">
              Version
              <select
                className="ml-2 border border-line bg-white px-2 py-2"
                value={selectedId ?? ""}
                disabled={busyAction !== null}
                onChange={(event) => {
                  const nextId = event.target.value;
                  setSelectedId(nextId);
                  void loadDetail(nextId).catch((err: Error) => setError(err.message));
                }}
              >
                {versions.map((item) => (
                  <option key={item.id} value={item.id}>
                    v{item.version} · {item.source} · {item.status.replaceAll("_", " ")}
                  </option>
                ))}
              </select>
            </label>
          )}
          <button
            type="button"
            disabled={busyAction !== null || pending || !detail}
            onClick={() => void analyze()}
            className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
          >
            {busyAction === "analyze" || pending ? "Analyzing…" : "Analyze transcript"}
          </button>
          <Link
            href={`/candidates/${candidate.id}/report`}
            className="bg-forest px-4 py-2 text-sm text-white"
          >
            Evidence report
          </Link>
        </div>
      </div>
      {error && <p className="mt-3 text-sm text-[var(--rust)]">{error}</p>}

      <form onSubmit={(event) => void onUpload(event)} className="mt-8 border border-line bg-white p-5">
        <h2 className="font-serif text-xl">Add a transcript</h2>
        <p className="mt-1 text-sm text-muted">
          A new upload creates a new version. Analysis maps turns and scores coverage. Years-only answers stay shallow.
        </p>
        <FilePicker
          label="Transcript file"
          file={file}
          onFile={setFile}
          disabled={busyAction !== null}
          hint="PDF, Word, text, or VTT from this PC"
        />
        <label className="mt-4 block text-sm">
          Or paste the transcript
          <textarea
            className="mt-1 min-h-32 w-full border border-line bg-paper px-3 py-2"
            value={paste}
            disabled={busyAction !== null}
            onChange={(event) => setPaste(event.target.value)}
            placeholder="Recruiter: Walk me through a system you built with Python.&#10;Candidate: I have used Python for 4 years."
          />
        </label>
        <button
          type="submit"
          disabled={busyAction !== null}
          className="mt-4 rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
        >
          {busyAction === "upload" ? "Saving…" : "Save transcript"}
        </button>
      </form>

      {!detail && (
        <p className="mt-6 text-sm text-muted">No transcript yet. Upload a file or paste the interview notes.</p>
      )}

      {detail && pending && (
        <p className="mt-6 text-sm text-muted">
          {detail.status === "parsed" ? "Scoring coverage against the JD…" : "Reading the transcript…"}
        </p>
      )}
      {detail?.run?.status === "failed" && (
        <p className="mt-6 text-sm text-[var(--rust)]">{detail.run.error || "Transcript analysis failed."}</p>
      )}

      {detail && detail.warnings.length > 0 && (
        <ul className="mt-6 list-disc space-y-1 pl-5 text-sm text-muted">
          {detail.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}

      {detail && detail.probes.length > 0 && (
        <section className="mt-8 border border-line bg-white p-5">
          <h2 className="font-serif text-xl">Coverage</h2>
          <p className="mt-1 text-sm text-muted">
            Prober verdicts from this transcript. Shallow and not discussed stay unvalidated until a follow-up interview.
          </p>
          <ul className="mt-4 space-y-3">
            {detail.probes.map((probe) => (
              <li key={probe.id} className="border border-line bg-paper p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-medium">{probe.requirement_label || "Requirement"}</span>
                  <ProbeChip verdict={probe.verdict} />
                </div>
                <p className="mt-2 text-sm">{probe.rationale}</p>
                {probe.missing_dimensions.length > 0 && (
                  <p className="mt-2 text-xs uppercase tracking-wide text-muted">
                    Missing: {probe.missing_dimensions.join(" · ")}
                  </p>
                )}
                {probe.remaining_followups.length > 0 && (
                  <ol className="mt-3 list-decimal space-y-1 pl-5 text-sm">
                    {probe.remaining_followups.map((question) => (
                      <li key={question}>{question}</li>
                    ))}
                  </ol>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {remaining.length > 0 && (
        <section className="mt-6 border border-line bg-white p-5">
          <h2 className="font-serif text-xl">Remaining follow-ups</h2>
          <p className="mt-1 text-sm text-muted">
            Take these to a later interview, then upload another transcript version. They are not asked inside HireFlow.
          </p>
          <ol className="mt-4 list-decimal space-y-2 pl-5 text-sm">
            {remaining.map((item) => (
              <li key={`${item.requirement}-${item.question}`}>
                <span className="text-muted">{item.requirement}: </span>
                {item.question}
              </li>
            ))}
          </ol>
        </section>
      )}

      {detail && detail.turns.length > 0 && (
        <section className="mt-6 border border-line bg-white p-5">
          <h2 className="font-serif text-xl">Turns</h2>
          <p className="mt-1 text-sm text-muted">
            Correct speaker or requirement mapping if the parser missed it. Analyze again to refresh coverage.
          </p>
          <ul className="mt-4 space-y-3">
            {detail.turns.map((turn) => (
              <li key={turn.id} className="border border-line bg-paper p-4">
                <div className="flex flex-wrap items-center gap-3 text-sm">
                  <label>
                    Speaker
                    <select
                      className="ml-2 border border-line bg-white px-2 py-1"
                      value={turn.speaker}
                      disabled={busyAction !== null || pending}
                      onChange={(event) => void saveTurn(turn.id, { speaker: event.target.value as Speaker })}
                    >
                      <option value="recruiter">Recruiter</option>
                      <option value="candidate">Candidate</option>
                      <option value="unknown">Unknown</option>
                    </select>
                  </label>
                  <label>
                    Requirement
                    <select
                      className="ml-2 border border-line bg-white px-2 py-1"
                      value={turn.requirement_id ?? ""}
                      disabled={busyAction !== null || pending}
                      onChange={(event) =>
                        void saveTurn(turn.id, { requirement_id: event.target.value || null })
                      }
                    >
                      <option value="">Unmapped</option>
                      {requirements.map((requirement) => (
                        <option key={requirement.id} value={requirement.id}>
                          {requirement.normalized_label || requirement.text}
                        </option>
                      ))}
                    </select>
                  </label>
                  {turn.recruiter_edited && <span className="text-xs uppercase tracking-wide text-muted">Edited</span>}
                </div>
                <p className="mt-3 text-sm">
                  <span className="text-muted">{speakerLabel(turn.speaker)}: </span>
                  {turn.text}
                </p>
              </li>
            ))}
          </ul>
        </section>
      )}
      </main>
    </AppShell>
  );
}
