"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { ArrowUp, Sparkles, X } from "lucide-react";
import { api } from "@/lib/api";
import type { ChatMessage, FileAssistantChatTurn, FileAssistantPageContext, FileHit } from "@/lib/types";

function newId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function contextLabel(pathname: string): string {
  if (pathname.startsWith("/candidates/")) return "Reading candidate files";
  if (pathname.startsWith("/jobs/")) return "Reading requisition files";
  return "Reading org files";
}

function pageContextFromPath(pathname: string): FileAssistantPageContext | null {
  const match = /^\/candidates\/([^/]+)/.exec(pathname);
  if (!match) return null;
  return { candidate_id: match[1], candidate_name: null, job_id: null, job_title: null };
}

function greeting(pathname: string): string {
  if (pathname.startsWith("/candidates/") && pathname.endsWith("/report")) {
    return "I can help with the evidence report — summarize it, parse gaps, or download the file.";
  }
  if (pathname.startsWith("/candidates/") && (pathname.endsWith("/plan") || pathname.endsWith("/transcript"))) {
    return "Ask about the interview brief, transcript, or match and gaps for this candidate.";
  }
  if (pathname.startsWith("/candidates/")) {
    return "I have this candidate's screening data. Ask me to summarize the resume, explain gaps, or download files.";
  }
  return "Ask me to find, download, read, summarize, or parse any JD, resume, transcript, or report in HireFlow.";
}

const SUGGESTIONS = [
  "Find Soumya's interview brief",
  "Summarize the resume",
  "What are the match and gaps?",
  "Download the screening brief",
];

export function AiAssistant() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [pageContext, setPageContext] = useState<FileAssistantPageContext | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const base = pageContextFromPath(pathname);
    if (!base?.candidate_id) {
      setPageContext(null);
      return;
    }
    let cancelled = false;
    void api
      .candidate(base.candidate_id)
      .then((candidate) => {
        if (cancelled) return;
        setPageContext({
          candidate_id: candidate.id,
          candidate_name: candidate.full_name,
          job_id: candidate.job_id,
          job_title: null,
        });
      })
      .catch(() => {
        if (!cancelled) setPageContext(base);
      });
    return () => {
      cancelled = true;
    };
  }, [pathname]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  async function downloadHit(hit: FileHit) {
    if (!hit.available) return;
    setDownloading(hit.locator);
    try {
      await api.downloadLocatedFile(hit.download_path, hit.filename);
    } finally {
      setDownloading(null);
    }
  }

  async function ask(text: string) {
    const trimmed = text.trim();
    if (!trimmed || busy) return;

    const userMessage: ChatMessage = { id: newId(), role: "user", content: trimmed };
    const nextMessages = [...messages, userMessage];
    setMessages(nextMessages);
    setDraft("");
    setBusy(true);

    const payload: FileAssistantChatTurn[] = nextMessages.map((message) => ({
      role: message.role,
      content: message.content,
      context: message.context ?? null,
    }));

    try {
      const result = await api.fileAssistantChat(payload, pageContext);
      setMessages((current) => [
        ...current,
        {
          id: newId(),
          role: "assistant",
          content: result.reply,
          hits: result.hits,
          parsed: result.parsed,
          context: result.context,
        },
      ]);
      if (result.want_download && result.hits.length === 1 && result.hits[0].available) {
        await downloadHit(result.hits[0]);
      }
    } catch (err) {
      setMessages((current) => [
        ...current,
        {
          id: newId(),
          role: "assistant",
          content: err instanceof Error ? err.message : "Something went wrong. Please try again.",
        },
      ]);
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void ask(draft);
  }

  if (pathname.startsWith("/login") || pathname.startsWith("/register")) return null;

  return (
    <>
      {!open && (
        <button
          type="button"
          onClick={() => setOpen(true)}
          aria-label="Open HireFlow assistant"
          className="fixed bottom-20 right-20 z-40 flex h-[4.5rem] w-[4.5rem] items-center justify-center rounded-full bg-brand-600 text-white shadow-[var(--shadow-lift)] transition-colors hover:bg-brand-700 focus:outline-none focus-visible:ring-4 focus-visible:ring-brand-100"
        >
          <Sparkles className="h-8 w-8" aria-hidden="true" />
        </button>
      )}

      {open && (
        <aside
          role="complementary"
          aria-label="HireFlow assistant"
          className="fixed bottom-0 right-0 top-16 z-40 flex w-full max-w-[400px] flex-col border-l border-line bg-white shadow-[var(--shadow-lift)]"
        >
          <header className="flex items-start gap-3 border-b border-line px-5 py-4">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-700">
              <Sparkles className="h-5 w-5" aria-hidden="true" />
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="text-base font-semibold text-ink-900">HireFlow assistant</h2>
              <p className="truncate text-xs text-ink-400">{contextLabel(pathname)}</p>
            </div>
            <button
              type="button"
              onClick={() => setOpen(false)}
              aria-label="Close assistant"
              className="-mr-1 rounded-lg p-1.5 text-ink-500 transition-colors hover:bg-canvas hover:text-ink-900"
            >
              <X className="h-5 w-5" aria-hidden="true" />
            </button>
          </header>

          <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto px-5 py-5">
            <p className="text-sm leading-relaxed text-ink-700">{greeting(pathname)}</p>

            {messages.map((message) =>
              message.role === "user" ? (
                <p
                  key={message.id}
                  className="ml-auto w-fit max-w-[85%] rounded-xl rounded-br-sm bg-brand-600 px-3.5 py-2.5 text-sm leading-relaxed text-white"
                >
                  {message.content}
                </p>
              ) : (
                <div key={message.id} className="max-w-[92%]">
                  <p className="rounded-xl rounded-bl-sm bg-canvas px-3.5 py-2.5 text-sm leading-relaxed text-ink-900 whitespace-pre-wrap">
                    {message.content}
                  </p>
                  {message.hits && message.hits.length > 0 && (
                    <div className="mt-2 space-y-2">
                      {message.hits.map((hit) => (
                        <div key={hit.locator} className="rounded-lg border border-line bg-white p-3 text-xs">
                          <div className="font-medium">{hit.label}</div>
                          <button
                            type="button"
                            disabled={!hit.available || downloading === hit.locator}
                            className="mt-2 rounded border border-line px-2 py-1 hover:bg-canvas disabled:opacity-50"
                            onClick={() => void downloadHit(hit)}
                          >
                            {!hit.available ? "Not ready" : downloading === hit.locator ? "Saving…" : "Download"}
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                  {message.parsed && (
                    <details className="mt-2">
                      <summary className="cursor-pointer text-xs text-ink-400">Structured output</summary>
                      <pre className="mt-1 max-h-40 overflow-auto text-[11px]">
                        {JSON.stringify(message.parsed, null, 2)}
                      </pre>
                    </details>
                  )}
                </div>
              ),
            )}

            {busy && (
              <p className="text-xs text-ink-400" role="status">
                Checking files…
              </p>
            )}
          </div>

          <div className="border-t border-line px-5 py-4">
            <div className="flex flex-wrap gap-2">
              {SUGGESTIONS.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  onClick={() => void ask(suggestion)}
                  className="rounded-full border border-line px-3 py-1.5 text-xs font-medium text-ink-700 transition-colors hover:border-brand-200 hover:text-brand-600"
                >
                  {suggestion}
                </button>
              ))}
            </div>

            <form
              onSubmit={onSubmit}
              className="mt-3 flex items-center gap-2 rounded-xl border border-line bg-canvas px-3 py-2 transition-colors focus-within:border-brand-600 focus-within:bg-white"
            >
              <input
                ref={inputRef}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="Ask about files or evidence…"
                aria-label="Message HireFlow assistant"
                className="w-full bg-transparent text-sm text-ink-900 outline-none placeholder:text-ink-400"
              />
              <button
                type="submit"
                disabled={!draft.trim() || busy}
                aria-label="Send message"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-600 text-white transition-colors hover:bg-brand-700 disabled:bg-line disabled:text-ink-400"
              >
                <ArrowUp className="h-4 w-4" aria-hidden="true" />
              </button>
            </form>
          </div>
        </aside>
      )}
    </>
  );
}
