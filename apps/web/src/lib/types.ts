export type PipelineStatus = "queued" | "running" | "succeeded" | "failed";
export type OverallMatch = "poor" | "average" | "good" | "perfect";
export type MatchStatus = "MATCHED" | "PARTIALLY_MATCHED" | "MISSING" | "UNCLEAR";

export type PipelineRun = {
  id: string;
  graph: string;
  subject_type: string;
  subject_id: string;
  status: PipelineStatus;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
};

export type Document = {
  id: string;
  owner_type: string;
  owner_id: string;
  kind: string;
  original_filename: string;
  mime: string;
  sha256: string;
  extracted_text: string | null;
  version: number;
  created_at: string;
  extract_run: PipelineRun | null;
};

export type User = {
  id: string;
  org_id: string;
  email: string;
  name: string;
  role: string;
};

export type JobSummary = {
  id: string;
  title: string;
  status: string;
  created_at: string;
  candidate_count: number;
  has_jd: boolean;
};

export type Candidate = {
  id: string;
  job_id: string;
  full_name: string;
  email: string | null;
  created_at: string;
  resume: Document | null;
  profile: Profile | null;
  claims: Claim[];
  parse_run: PipelineRun | null;
  match_run: PipelineRun | null;
  overall_match: OverallMatch | null;
};

export type SourceSpan = {
  page: number | null;
  char_start: number | null;
  char_end: number | null;
  quote: string;
};

export type Requirement = {
  id: string;
  job_id: string;
  document_version: number;
  text: string;
  normalized_label: string;
  category: string;
  priority: string;
  source_quote: string;
  source_span: SourceSpan | null;
  recruiter_edited: boolean;
  sort_order: number;
};

export type Claim = {
  id: string;
  candidate_id: string;
  kind: string;
  text: string;
  skill_label: string | null;
  years: number | null;
  source_span: SourceSpan | null;
  quote: string;
};

export type Profile = {
  id: string;
  candidate_id: string;
  full_name: string | null;
  email: string | null;
  summary: string | null;
  years_experience: number | null;
  education: string[];
  roles: string[];
  skills_listed: string[];
  parser_warnings: string[];
};

export type JobDetail = {
  id: string;
  title: string;
  status: string;
  created_at: string;
  jd: Document | null;
  candidates: Candidate[];
  requirements: Requirement[];
  parse_run: PipelineRun | null;
};

export type DimensionFlags = {
  named: number;
  applied: number;
  complexity: number;
  professional: number;
  ownership: number;
  outcome: number;
};

export type MatchResult = {
  id: string;
  job_id: string;
  candidate_id: string;
  requirement_id: string;
  status: MatchStatus;
  confidence: number | null;
  rationale: string;
  dimension_flags: DimensionFlags;
  supporting_claim_ids: string[];
  run_id: string;
  requirement_label: string;
  requirement_priority: string | null;
  quotes: string[];
};

export type Gap = {
  id: string;
  match_result_id: string;
  requirement_id: string;
  requirement_label: string;
  status: MatchStatus | null;
  severity: string;
  investigation_goal: string;
  suggested_probe_themes: string[];
  deal_breaker: boolean;
  skip_probe: boolean;
};

export type MatrixCell = {
  candidate_id: string;
  requirement_id: string;
  status: MatchStatus | null;
  rationale: string | null;
  quotes: string[];
};

export type MatrixResponse = {
  job_id: string;
  requirements: Requirement[];
  candidates: { id: string; full_name: string; overall_match: OverallMatch | null }[];
  cells: MatrixCell[];
};

export type ScreenStatus = {
  step: string;
  message: string;
  run: PipelineRun | null;
};

export type PlannedQuestion = {
  id: string;
  plan_id: string;
  requirement_id: string;
  requirement_label: string;
  match_status: MatchStatus | null;
  sort_order: number;
  prompt: string;
  planned_followups: string[];
  evidence_target: string[];
  source: "generated" | "recruiter_edited";
  dropped: boolean;
};

export type ReportFile = {
  id: string;
  candidate_id: string;
  job_id: string;
  plan_id: string | null;
  kind: string;
  version: number;
  original_filename: string;
  mime: string;
  created_at: string;
};

export type InterviewPlan = {
  id: string;
  candidate_id: string;
  job_id: string;
  status: "draft" | "approved" | "superseded";
  version: number;
  brief_report: ReportFile | null;
  questions: PlannedQuestion[];
  run: PipelineRun | null;
  created_at: string;
};

export type InterviewPlanResponse = {
  plan: InterviewPlan | null;
  run: PipelineRun | null;
};

export type TranscriptSource = "file" | "paste";
export type TranscriptStatus = "uploaded" | "parsed" | "analyzed" | "failed";
export type Speaker = "recruiter" | "candidate" | "unknown";
export type ProbeVerdict = "sufficient" | "shallow" | "not_discussed" | "confirmed_missing" | "contradiction";

export type TranscriptTurn = {
  id: string;
  speaker: Speaker;
  text: string;
  char_start: number | null;
  char_end: number | null;
  requirement_id: string | null;
  requirement_label: string;
  question_id: string | null;
  sort_order: number;
  recruiter_edited: boolean;
};

export type ProbeResult = {
  id: string;
  requirement_id: string;
  requirement_label: string;
  verdict: ProbeVerdict;
  missing_dimensions: string[];
  supporting_turn_ids: string[];
  remaining_followups: string[];
  rationale: string;
};

export type TranscriptSummary = {
  id: string;
  candidate_id: string;
  job_id: string;
  plan_id: string | null;
  source: TranscriptSource;
  status: TranscriptStatus;
  version: number;
  warnings: string[];
  original_filename: string | null;
  created_at: string;
  run: PipelineRun | null;
};

export type TranscriptDetail = TranscriptSummary & {
  extracted_text: string | null;
  turns: TranscriptTurn[];
  probes: ProbeResult[];
};

export type DecisionOutcome = "advance" | "hold" | "reject";

export type EvidenceItem = {
  id: string;
  code: string;
  requirement_id: string;
  requirement_label: string;
  source: "resume" | "interview";
  quote: string;
  interpretation: string;
  strength: "strong" | "weak" | "none";
  dimensions_supported: string[];
  contradicts: boolean;
};

export type RequirementAssessment = {
  requirement_id: string;
  requirement_label: string;
  priority: string;
  status_after_resume: MatchStatus;
  status_after_interview: MatchStatus | null;
  final: MatchStatus;
  unvalidated: boolean;
  strongest_quote: string;
  source: "resume" | "interview" | null;
  remaining_doubt: string;
  evidence_codes: string[];
};

export type UnresolvedGap = {
  requirement_id: string;
  requirement_label: string;
  verdict: ProbeVerdict | null;
  followups: string[];
  note: string;
};

export type CoverageRow = {
  requirement_id: string;
  requirement_label: string;
  verdict: ProbeVerdict | null;
  skipped_in_plan: boolean;
};

export type ContradictionRow = {
  requirement_label: string;
  quote: string;
  interpretation: string;
  evidence_code: string;
};

export type EvidenceReportBody = {
  partial: boolean;
  headline: string;
  generated_at: string;
  transcript_id: string | null;
  transcript_version: number | null;
  overall_after_resume: OverallMatch | null;
  overall_after_interview: OverallMatch | null;
  matrix: RequirementAssessment[];
  must_haves: RequirementAssessment[];
  unresolved: UnresolvedGap[];
  contradictions: ContradictionRow[];
  coverage: CoverageRow[];
  remaining_risks: string[];
  closing: string;
  evidence: EvidenceItem[];
};

export type EvidenceReportResponse = {
  report: ReportFile | null;
  body: EvidenceReportBody | null;
  decision: Decision | null;
  run: PipelineRun | null;
};

export type Decision = {
  id: string;
  report_id: string;
  outcome: DecisionOutcome;
  notes: string;
  decided_by: string;
  decided_at: string;
};

export type FileKind =
  | "jd"
  | "resume"
  | "transcript"
  | "screening_brief"
  | "interview_brief"
  | "evidence";

export type FileHit = {
  locator: string;
  kind: FileKind;
  label: string;
  filename: string;
  job_title: string;
  candidate_name: string | null;
  download_path: string;
  available: boolean;
  reason: string;
};

export type FileAction = "locate" | "download" | "read" | "summarize" | "parse";

export type FileAssistantChatContext = {
  primary_locator: string | null;
  candidate_name: string | null;
  job_title: string | null;
  kind: FileKind | null;
};

export type FileAssistantPageContext = {
  candidate_id: string | null;
  candidate_name: string | null;
  job_id: string | null;
  job_title: string | null;
};

export type FileAssistantChatTurn = {
  role: "user" | "assistant";
  content: string;
  context?: FileAssistantChatContext | null;
};

export type FileLocatorResponse = {
  query: string;
  summary: string;
  action: FileAction;
  want_download: boolean;
  warnings: string[];
  hits: FileHit[];
  primary_locator: string | null;
  answer: string | null;
  parsed: Record<string, unknown> | null;
  request_id: string | null;
  reply: string | null;
  context: FileAssistantChatContext | null;
};

export type FileAssistantChatResponse = FileLocatorResponse & {
  reply: string;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  hits?: FileHit[];
  parsed?: Record<string, unknown> | null;
  context?: FileAssistantChatContext | null;
};

export type FileAssistantHistoryItem = {
  id: string;
  query: string;
  action: FileAction;
  summary: string;
  primary_locator: string | null;
  created_at: string;
};
