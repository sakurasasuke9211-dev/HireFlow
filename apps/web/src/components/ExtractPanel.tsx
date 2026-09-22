import { RunBadge } from "@/components/RunBadge";
import type { Document } from "@/lib/types";

export function ExtractPanel({
  title,
  document,
}: {
  title: string;
  document: Document | null;
}) {
  if (!document) {
    return (
      <section className="border border-line bg-white p-5">
        <h2 className="font-serif text-xl">{title}</h2>
        <p className="mt-2 text-sm text-muted">No file uploaded yet.</p>
      </section>
    );
  }

  const failed = document.extract_run?.status === "failed";
  const pending =
    document.extract_run?.status === "queued" || document.extract_run?.status === "running";

  return (
    <section className="border border-line bg-white p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-serif text-xl">{title}</h2>
          <p className="mt-1 text-sm text-muted">
            {document.original_filename} · v{document.version}
          </p>
        </div>
        <RunBadge run={document.extract_run} />
      </div>

      {failed && (
        <div className="mt-4 border border-[var(--rust)] bg-[var(--rust-bg)] px-3 py-2 text-sm text-[var(--rust)]">
          {document.extract_run?.error || "could not read file"}
        </div>
      )}

      {pending && (
        <p className="mt-4 text-sm text-muted">Extracting text from the uploaded file…</p>
      )}

      {document.extracted_text && (
        <pre className="mt-4 max-h-96 overflow-auto whitespace-pre-wrap border border-line bg-paper p-4 text-sm leading-6">
          {document.extracted_text}
        </pre>
      )}
    </section>
  );
}
