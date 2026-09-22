"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { FileText, Plus } from "lucide-react";
import { AppShell } from "@/components/AppShell";
import { api } from "@/lib/api";
import type { JobSummary } from "@/lib/types";

export default function JobsPage() {
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [title, setTitle] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      setJobs(await api.jobs());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load jobs");
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.createJob(title);
      setTitle("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create job");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell>
      <main className="mx-auto w-full max-w-[1440px] px-6 py-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-ink-900">Requisitions</h1>
            <p className="mt-1 text-sm text-ink-500">Open a role to screen candidates against its job description.</p>
          </div>
        </div>

        <form
          onSubmit={onCreate}
          className="mt-6 flex gap-3 rounded-xl border border-line bg-white p-4 shadow-[var(--shadow-card)]"
        >
          <input
            className="flex-1 rounded-lg border border-line bg-canvas px-3 py-2 text-sm outline-none focus:border-brand-600 focus:bg-white"
            placeholder="Role title, e.g. Senior Product Manager — Payments"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
          />
          <button
            type="submit"
            disabled={busy}
            className="inline-flex items-center gap-2 rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
          >
            <Plus className="h-4 w-4" aria-hidden="true" />
            {busy ? "Creating…" : "New requisition"}
          </button>
        </form>
        {error && <p className="mt-3 text-sm text-missing">{error}</p>}

        <div className="mt-8 space-y-3">
          {jobs.length === 0 && (
            <div className="rounded-xl border border-dashed border-line bg-white px-6 py-14 text-center">
              <p className="text-base font-semibold text-ink-900">No requisitions yet</p>
              <p className="mt-1 text-sm text-ink-500">Create one to upload a JD and resumes.</p>
            </div>
          )}
          {jobs.map((job) => (
            <Link
              key={job.id}
              href={`/jobs/${job.id}`}
              className="flex items-center justify-between gap-4 rounded-xl border border-line bg-white p-5 shadow-[var(--shadow-card)] transition-shadow hover:shadow-[var(--shadow-lift)]"
            >
              <div className="flex items-start gap-4">
                <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-50 text-brand-700">
                  <FileText className="h-5 w-5" aria-hidden="true" />
                </span>
                <div>
                  <h2 className="text-lg font-semibold text-ink-900">{job.title}</h2>
                  <p className="mt-1 text-sm text-ink-500">
                    {job.candidate_count} candidate{job.candidate_count === 1 ? "" : "s"} · JD{" "}
                    {job.has_jd ? "uploaded" : "missing"}
                  </p>
                </div>
              </div>
              <span className="text-sm font-medium text-brand-600">Open pipeline →</span>
            </Link>
          ))}
        </div>
      </main>
    </AppShell>
  );
}
