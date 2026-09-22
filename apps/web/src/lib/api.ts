import { clearSession, getToken } from "./auth";
import type { Candidate, Decision, EvidenceReportResponse, FileAssistantChatResponse, FileAssistantChatTurn, FileAssistantHistoryItem, FileAssistantPageContext, FileLocatorResponse, Gap, InterviewPlanResponse, JobDetail, JobSummary, MatchResult, MatrixResponse, PipelineRun, PlannedQuestion, ProbeResult, Requirement, ScreenStatus, TranscriptDetail, TranscriptSummary, TranscriptTurn, User } from "./types";

const API = "/backend";

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (!(init.body instanceof FormData) && !headers.has("Content-Type") && init.body) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(`${API}${path}`, { ...init, headers });
  } catch {
    throw new Error("Could not reach the API. Start the backend on port 8000.");
  }
  if (response.status === 401) {
    clearSession();
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
    }
  }
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = (await response.json()) as { detail?: string };
    if (typeof body.detail === "string") detail = body.detail;
    else if (Array.isArray(body.detail)) detail = JSON.stringify(body.detail);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function downloadAttachment(path: string, fallbackName: string) {
  const headers = new Headers();
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API}${path}`, { headers });
  if (response.status === 401) {
    clearSession();
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
    }
  }
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  const blob = await response.blob();
  const disposition = response.headers.get("content-disposition") ?? "";
  const matched = /filename="([^"]+)"/.exec(disposition);
  const filename = matched?.[1] ?? fallbackName;
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export const api = {
  register: (body: { email: string; password: string; name: string; org_name: string }) =>
    request<{ access_token: string; user: User }>("/auth/register", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  login: (body: { email: string; password: string }) =>
    request<{ access_token: string; user: User }>("/auth/login", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  me: () => request<User>("/auth/me"),
  jobs: () => request<JobSummary[]>("/jobs"),
  createJob: (title: string) =>
    request<JobDetail>("/jobs", { method: "POST", body: JSON.stringify({ title }) }),
  job: (id: string) => request<JobDetail>(`/jobs/${id}`),
  uploadJd: (jobId: string, payload: { file?: File; text?: string }) => {
    const data = new FormData();
    if (payload.file) data.append("file", payload.file);
    if (payload.text) data.append("text", payload.text);
    return request<{ document: unknown; run: PipelineRun }>(`/jobs/${jobId}/jd`, {
      method: "POST",
      body: data,
    });
  },
  addCandidate: (jobId: string, fields: { full_name: string; email?: string; file: File }) => {
    const data = new FormData();
    data.append("full_name", fields.full_name);
    if (fields.email) data.append("email", fields.email);
    data.append("file", fields.file);
    return request<Candidate>(`/jobs/${jobId}/candidates`, { method: "POST", body: data });
  },
  uploadResume: (candidateId: string, file: File) => {
    const data = new FormData();
    data.append("file", file);
    return request<{ document: unknown; run: PipelineRun }>(`/candidates/${candidateId}/resume`, {
      method: "POST",
      body: data,
    });
  },
  candidate: (id: string) => request<Candidate>(`/candidates/${id}`),
  run: (id: string) => request<PipelineRun>(`/runs/${id}`),
  parseJd: (jobId: string) =>
    request<PipelineRun>(`/jobs/${jobId}/parse-jd`, { method: "POST" }),
  parseResume: (candidateId: string) =>
    request<PipelineRun>(`/candidates/${candidateId}/parse-resume`, { method: "POST" }),
  reparseResume: (candidateId: string) =>
    request<PipelineRun>(`/candidates/${candidateId}/reparse`, { method: "POST" }),
  patchRequirement: (id: string, body: Partial<Requirement> & { dropped?: boolean }) =>
    request<Requirement | undefined>(`/requirements/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  matchCandidate: (candidateId: string) =>
    request<PipelineRun>(`/candidates/${candidateId}/match`, { method: "POST" }),
  matches: (candidateId: string) => request<MatchResult[]>(`/candidates/${candidateId}/matches`),
  gaps: (candidateId: string) => request<Gap[]>(`/candidates/${candidateId}/gaps`),
  patchGap: (id: string, body: { deal_breaker?: boolean; skip_probe?: boolean }) =>
    request<Gap>(`/gaps/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  matrix: (jobId: string) => request<MatrixResponse>(`/jobs/${jobId}/matrix`),
  screenCandidate: (candidateId: string, force = false) =>
    request<ScreenStatus>(`/candidates/${candidateId}/screen${force ? "?force=true" : ""}`, { method: "POST" }),
  interviewPlan: (candidateId: string) => request<InterviewPlanResponse>(`/candidates/${candidateId}/interview-plan`),
  generateInterviewPlan: (candidateId: string) =>
    request<PipelineRun>(`/candidates/${candidateId}/interview-plan`, { method: "POST" }),
  patchPlannedQuestion: (id: string, body: Partial<Pick<PlannedQuestion, "prompt" | "planned_followups" | "sort_order" | "dropped">>) =>
    request<PlannedQuestion>(`/planned-questions/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  downloadScreeningBrief: (candidateId: string) =>
    downloadAttachment(`/candidates/${candidateId}/screening-brief`, "screening-brief.md"),
  downloadInterviewBrief: (candidateId: string) =>
    downloadAttachment(`/candidates/${candidateId}/interview-brief`, "interview-brief.md"),
  downloadReport: (reportId: string) => downloadAttachment(`/reports/${reportId}/download`, "report.md"),
  locateFiles: (query: string) =>
    request<FileLocatorResponse>("/files/locate", {
      method: "POST",
      body: JSON.stringify({ query }),
    }),
  fileAssistantChat: (messages: FileAssistantChatTurn[], pageContext?: FileAssistantPageContext | null) =>
    request<FileAssistantChatResponse>("/files/chat", {
      method: "POST",
      body: JSON.stringify({ messages, page_context: pageContext ?? null }),
    }),
  fileAssistantHistory: () => request<FileAssistantHistoryItem[]>("/files/history"),
  downloadLocatedFile: (path: string, filename: string) => downloadAttachment(path, filename),
  transcripts: (candidateId: string) => request<TranscriptSummary[]>(`/candidates/${candidateId}/transcripts`),
  transcript: (transcriptId: string) => request<TranscriptDetail>(`/transcripts/${transcriptId}`),
  uploadTranscript: (candidateId: string, payload: { file?: File; text?: string }) => {
    const data = new FormData();
    if (payload.file) data.append("file", payload.file);
    if (payload.text) data.append("text", payload.text);
    return request<TranscriptSummary>(`/candidates/${candidateId}/transcripts`, { method: "POST", body: data });
  },
  analyzeTranscript: (transcriptId: string) =>
    request<PipelineRun>(`/transcripts/${transcriptId}/analyze`, { method: "POST" }),
  probes: (transcriptId: string) => request<ProbeResult[]>(`/transcripts/${transcriptId}/probes`),
  patchTranscriptTurn: (id: string, body: Partial<Pick<TranscriptTurn, "speaker" | "requirement_id" | "question_id">>) =>
    request<TranscriptTurn>(`/transcript-turns/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  evidenceReport: (candidateId: string) => request<EvidenceReportResponse>(`/candidates/${candidateId}/report`),
  generateEvidenceReport: (candidateId: string) =>
    request<PipelineRun>(`/candidates/${candidateId}/report`, { method: "POST" }),
  recordDecision: (reportId: string, body: { outcome: Decision["outcome"]; notes?: string }) =>
    request<Decision>(`/reports/${reportId}/decision`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
