"use client";

import { RunBadge } from "@/components/RunBadge";
import { api } from "@/lib/api";
import type { JobDetail, Requirement } from "@/lib/types";

const PRIORITIES = ["must_have", "nice_to_have", "unclear_priority"] as const;

export function RequirementsPanel({
  job,
  busy,
  onChange,
  onError,
}: {
  job: JobDetail;
  busy: boolean;
  onChange: () => Promise<void>;
  onError?: (message: string) => void;
}) {
  const parsePending =
    job.parse_run?.status === "queued" || job.parse_run?.status === "running";
  const canParse = Boolean(job.jd?.extracted_text) && !parsePending && !busy;

  async function parseJd() {
    await api.parseJd(job.id);
    await onChange();
  }

  async function save(requirement: Requirement, patch: Partial<Requirement>) {
    await api.patchRequirement(requirement.id, patch);
    await onChange();
  }

  async function drop(requirement: Requirement) {
    await api.patchRequirement(requirement.id, { dropped: true });
    await onChange();
  }

  return (
    <section className="rounded-xl border border-line bg-canvas p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-ink-900">Requirements</h2>
          <p className="mt-1 text-sm text-ink-500">Structured JD. Edit before matching.</p>
        </div>
        <div className="flex items-center gap-3">
          <RunBadge run={job.parse_run} />
          <button
            type="button"
            disabled={!canParse}
            onClick={() =>
              void parseJd().catch((err: Error) => {
                if (onError) onError(err.message);
              })
            }
            className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
          >
            Parse JD
          </button>
        </div>
      </div>

      {job.parse_run?.status === "failed" && (
        <div className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-missing">
          {job.parse_run.error ||
            "Could not parse the JD. Check GROQ_API_KEY in .env and restart the API."}
        </div>
      )}
      {parsePending && <p className="mt-4 text-sm text-ink-500">Parsing the job description…</p>}

      {(job.requirements ?? []).length === 0 && !parsePending && (
        <p className="mt-4 text-sm text-ink-500">No requirements yet. Upload or paste a JD first.</p>
      )}

      <ul className="mt-4 space-y-3">
        {(job.requirements ?? []).map((requirement) => (
          <li key={requirement.id} className="border border-line bg-paper p-3">
            <div className="flex flex-wrap items-center gap-2">
              <input
                className="min-w-[8rem] flex-1 border border-line bg-white px-2 py-1 text-sm font-medium"
                defaultValue={requirement.normalized_label}
                onBlur={(event) => {
                  const value = event.target.value.trim();
                  if (value && value !== requirement.normalized_label) {
                    void save(requirement, { normalized_label: value });
                  }
                }}
              />
              <select
                className="border border-line bg-white px-2 py-1 text-xs"
                value={requirement.priority}
                onChange={(event) => void save(requirement, { priority: event.target.value })}
              >
                {PRIORITIES.map((priority) => (
                  <option key={priority} value={priority}>
                    {priority}
                  </option>
                ))}
              </select>
              <span className="text-xs uppercase tracking-wide text-muted">{requirement.category}</span>
              {requirement.recruiter_edited && <span className="text-xs text-muted">Edited</span>}
              <button type="button" className="ml-auto text-xs text-[var(--rust)]" onClick={() => void drop(requirement)}>
                Drop
              </button>
            </div>
            <textarea
              className="mt-2 w-full border border-line bg-white px-2 py-1 text-sm"
              defaultValue={requirement.text}
              rows={2}
              onBlur={(event) => {
                const value = event.target.value.trim();
                if (value && value !== requirement.text) {
                  void save(requirement, { text: value });
                }
              }}
            />
            {requirement.source_quote && (
              <p className="mt-1 text-xs text-muted">Quote: {requirement.source_quote}</p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
