"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { ChevronDown, FileText } from "lucide-react";
import { AppShell } from "@/components/AppShell";
import { CandidateCard } from "@/components/CandidateCard";
import { ExtractPanel } from "@/components/ExtractPanel";
import { FilePicker, chosenFile } from "@/components/FilePicker";
import { RequirementsPanel } from "@/components/RequirementsPanel";
import { api } from "@/lib/api";
import type { JobDetail, MatrixResponse } from "@/lib/types";
import { statusMeta } from "@/lib/screening";

function isPending(job: JobDetail | null): boolean {
  if (!job) return false;
  const docs = [job.jd, ...job.candidates.map((c) => c.resume)];
  const extractPending = docs.some((doc) => {
    const status = doc?.extract_run?.status;
    return status === "queued" || status === "running";
  });
  const parsePending = job.parse_run?.status === "queued" || job.parse_run?.status === "running";
  const matchPending = job.candidates.some(
    (c) => c.match_run?.status === "queued" || c.match_run?.status === "running",
  );
  return extractPending || parsePending || matchPending;
}

export default function JobDetailPage() {
  const params = useParams<{ id: string }>();
  const [job, setJob] = useState<JobDetail | null>(null);
  const [matrix, setMatrix] = useState<MatrixResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [jdFile, setJdFile] = useState<File | null>(null);
  const [jdPaste, setJdPaste] = useState("");
  const [jdMode, setJdMode] = useState<"file" | "paste">("file");
  const [resumeFile, setResumeFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [setupOpen, setSetupOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      const nextJob = await api.job(params.id);
      setJob(nextJob);
      try {
        setMatrix(await api.matrix(params.id));
      } catch {
        setMatrix(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load job");
    }
  }, [params.id]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!isPending(job)) return;
    const timer = window.setInterval(() => void load(), 1500);
    return () => window.clearInterval(timer);
  }, [job, load]);

  const thinnest = useMemo(() => {
    if (!matrix) return [];
    return matrix.requirements
      .map((req) => {
        const evidenced = matrix.cells.filter(
          (c) => c.requirement_id === req.id && c.status === "MATCHED",
        ).length;
        return { req, evidenced };
      })
      .sort((a, b) => a.evidenced - b.evidenced)
      .slice(0, 3);
  }, [matrix]);

  async function submitJd(payload: { file?: File; text?: string }) {
    setBusy(true);
    setError(null);
    try {
      await api.uploadJd(params.id, payload);
      setJdFile(null);
      setJdPaste("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  async function onJd(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (jdMode === "paste") {
      const text = jdPaste.trim();
      if (!text) {
        setError("Paste the job description text first.");
        return;
      }
      await submitJd({ text });
      return;
    }
    const file = chosenFile(event.currentTarget, jdFile);
    if (!file) {
      setError("Choose a JD file first.");
      return;
    }
    await submitJd({ file });
  }

  async function onCandidate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!fullName.trim()) {
      setError("Enter the candidate's name.");
      return;
    }
    const file = chosenFile(event.currentTarget, resumeFile);
    if (!file) {
      setError("Choose a resume file first.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.addCandidate(params.id, {
        full_name: fullName,
        email: email || undefined,
        file,
      });
      setFullName("");
      setEmail("");
      setResumeFile(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  if (!job && !error) {
    return (
      <AppShell>
        <p className="px-6 py-20 text-sm text-ink-500">Loading pipeline…</p>
      </AppShell>
    );
  }

  if (!job) {
    return (
      <AppShell>
        <p className="px-6 py-20 text-sm text-missing">{error}</p>
      </AppShell>
    );
  }

  const requirements = matrix?.requirements ?? job.requirements;
  const cells = matrix?.cells ?? [];

  return (
    <AppShell>
      <main className="mx-auto w-full max-w-[1440px] px-6 py-6">
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_300px]">
          <div>
            <section className="rounded-xl border border-line bg-white px-5 py-4 shadow-[var(--shadow-card)]">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <h1 className="text-xl font-bold text-ink-900">{job.title}</h1>
                  <p className="mt-1 text-sm text-ink-500">
                    {job.candidates.length} screened · {requirements.length} requirements tracked
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setSetupOpen((v) => !v)}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-2 text-sm font-medium text-ink-700 hover:border-brand-200 hover:text-brand-600"
                >
                  <FileText className="h-4 w-4" aria-hidden="true" />
                  Setup JD & resumes
                  <ChevronDown className={`h-4 w-4 transition-transform ${setupOpen ? "rotate-180" : ""}`} />
                </button>
              </div>
            </section>

            {setupOpen && (
              <div className="mt-4 grid gap-4 rounded-xl border border-line bg-white p-5 shadow-[var(--shadow-card)] lg:grid-cols-2">
                <form onSubmit={onJd}>
                  <h2 className="text-base font-semibold text-ink-900">Job description</h2>
                  <div className="mt-3 flex gap-2">
                    <button
                      type="button"
                      onClick={() => setJdMode("file")}
                      className={`rounded-lg px-3 py-1.5 text-sm font-medium ${
                        jdMode === "file"
                          ? "bg-brand-600 text-white"
                          : "border border-line text-ink-700 hover:bg-canvas"
                      }`}
                    >
                      Upload file
                    </button>
                    <button
                      type="button"
                      onClick={() => setJdMode("paste")}
                      className={`rounded-lg px-3 py-1.5 text-sm font-medium ${
                        jdMode === "paste"
                          ? "bg-brand-600 text-white"
                          : "border border-line text-ink-700 hover:bg-canvas"
                      }`}
                    >
                      Paste text
                    </button>
                  </div>
                  {jdMode === "file" ? (
                    <FilePicker
                      label="JD file"
                      file={jdFile}
                      disabled={busy}
                      onFile={setJdFile}
                    />
                  ) : (
                    <label className="mt-3 block text-sm">
                      <span className="font-medium text-ink-900">Paste JD</span>
                      <textarea
                        value={jdPaste}
                        onChange={(e) => setJdPaste(e.target.value)}
                        rows={8}
                        placeholder="Paste the full job description here…"
                        className="mt-2 w-full rounded-lg border border-line bg-canvas px-3 py-2.5 text-sm leading-relaxed outline-none focus:border-brand-600 focus:bg-white"
                      />
                    </label>
                  )}
                  <button
                    type="submit"
                    disabled={busy}
                    className="mt-3 rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
                  >
                    {jdMode === "paste" ? "Save pasted JD" : "Upload JD"}
                  </button>
                  <ExtractPanel title="Extracted JD" document={job.jd} />
                </form>
                <div>
                  <RequirementsPanel
                    job={job}
                    busy={busy}
                    onError={setError}
                    onChange={async () => {
                      setError(null);
                      await load();
                    }}
                  />
                  <form onSubmit={onCandidate} className="mt-4 border-t border-line pt-4">
                    <h2 className="text-base font-semibold text-ink-900">Add candidate</h2>
                    <input
                      className="mt-3 w-full rounded-lg border border-line bg-canvas px-3 py-2 text-sm"
                      placeholder="Full name"
                      value={fullName}
                      onChange={(e) => setFullName(e.target.value)}
                      required
                    />
                    <input
                      className="mt-2 w-full rounded-lg border border-line bg-canvas px-3 py-2 text-sm"
                      placeholder="Email (optional)"
                      type="email"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                    />
                    <FilePicker label="Resume file" file={resumeFile} disabled={busy} onFile={setResumeFile} />
                    <button
                      type="submit"
                      disabled={busy}
                      className="mt-3 rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
                    >
                      Upload resume
                    </button>
                  </form>
                </div>
              </div>
            )}

            {error && <p className="mt-3 text-sm text-missing">{error}</p>}

            <div className="mt-5 flex items-center justify-between">
              <p className="text-sm text-ink-500">
                Showing <span className="font-semibold text-ink-900">{job.candidates.length}</span> candidates
              </p>
              <Link href={`/jobs/${job.id}/matrix`} className="text-sm font-medium text-brand-600 hover:text-brand-700">
                Match matrix →
              </Link>
            </div>

            <div className="mt-4 space-y-4">
              {job.candidates.map((candidate) => (
                <CandidateCard
                  key={candidate.id}
                  candidate={candidate}
                  requirements={requirements}
                  cells={cells}
                />
              ))}
              {job.candidates.length === 0 && (
                <div className="rounded-xl border border-dashed border-line bg-white px-6 py-14 text-center">
                  <p className="text-base font-semibold text-ink-900">No candidates yet</p>
                  <p className="mt-1 text-sm text-ink-500">Open setup to upload resumes.</p>
                </div>
              )}
            </div>
          </div>

          <aside className="hidden xl:block">
            <section className="sticky top-[88px] rounded-xl border border-line bg-white p-5 shadow-[var(--shadow-card)]">
              <h2 className="text-base font-semibold text-ink-900">Where the funnel is thin</h2>
              <p className="mt-1 text-sm text-ink-500">Requirements the shortlist cannot evidence from resumes alone.</p>
              {thinnest.length === 0 ? (
                <p className="mt-4 text-sm text-ink-400">Run screening to see requirement coverage.</p>
              ) : (
                <ul className="mt-4 space-y-4">
                  {thinnest.map(({ req, evidenced }) => (
                    <li key={req.id}>
                      <div className="flex items-baseline justify-between gap-3">
                        <span className="text-sm font-medium text-ink-900">{req.normalized_label || req.text}</span>
                        <span className="shrink-0 text-xs text-ink-400">
                          {evidenced}/{job.candidates.length}
                        </span>
                      </div>
                      <div className="mt-2 h-1.5 w-full rounded-full bg-canvas">
                        <div
                          className={`h-full rounded-full ${
                            evidenced === 0 ? statusMeta.missing.bar : statusMeta.partial.bar
                          }`}
                          style={{
                            width: `${Math.max(6, job.candidates.length ? (evidenced / job.candidates.length) * 100 : 0)}%`,
                          }}
                        />
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </aside>
        </div>
      </main>
    </AppShell>
  );
}
