"use client";

import { ChangeEvent, useId } from "react";

const ACCEPT = [
  ".pdf",
  ".docx",
  ".doc",
  ".txt",
  ".vtt",
  ".md",
  ".rtf",
  "application/pdf",
  "application/msword",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "text/plain",
  "text/vtt",
].join(",");

export function FilePicker({
  label,
  file,
  onFile,
  disabled,
  hint,
}: {
  label: string;
  file: File | null;
  onFile: (file: File | null) => void;
  disabled?: boolean;
  hint?: string;
}) {
  const inputId = useId();

  function onChange(event: ChangeEvent<HTMLInputElement>) {
    onFile(event.target.files?.[0] ?? null);
  }

  return (
    <div className="mt-3">
      <span className="block text-sm font-medium text-ink-900">{label}</span>
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <label
          htmlFor={inputId}
          className={`inline-flex cursor-pointer items-center rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-brand-700 ${
            disabled ? "pointer-events-none opacity-60" : ""
          }`}
        >
          Choose file
        </label>
        <input
          id={inputId}
          className="sr-only"
          type="file"
          name="file"
          accept={ACCEPT}
          disabled={disabled}
          onChange={onChange}
        />
        <span className="text-sm text-ink-500">
          {file ? `Selected: ${file.name}` : hint ?? "PDF, Word, or text file from this PC"}
        </span>
      </div>
    </div>
  );
}

export function chosenFile(form: HTMLFormElement, selected: File | null): File | null {
  if (selected && selected.size > 0) return selected;
  const input = form.querySelector('input[type="file"]') as HTMLInputElement | null;
  const file = input?.files?.[0] ?? null;
  return file && file.size > 0 ? file : null;
}
