# HireFlow — Architecture

HireFlow is an AI-powered multi-agent system that moves recruiting from keyword screening to **evidence-based candidate validation**.

It does not answer “Does this resume match the JD?” It answers:

> What evidence do we have that this candidate meets the important requirements of the role, and what still needs to be validated?

This document is the system architecture: context, components, agents, data, APIs, runtime, security, and the phase-wise path to build it.

HireFlow **does not conduct interviews**. The recruiter (or an external tool) runs the interview. HireFlow produces a candidate-specific plan and a **downloadable interview-brief report file**, then consumes a **provided transcript** to probe coverage and build the evidence report file.

**Related:** `problem statement.md`

---

## 0. Document map

| Section | What it defines |
| --- | --- |
| 1. Problem → architecture | Why the design looks this way |
| 2. Architecture principles | Non-negotiable rules |
| 3. System context | Users, boundaries, external systems |
| 4. Logical architecture | Layers, services, agent graph |
| 5. Runtime architecture | Request paths and async jobs |
| 6. Multi-agent design | Contracts, state machine, each agent |
| 7. Domain model | Entities, statuses, evidence rules |
| 8. Persistence | Supabase tables, files, traces |
| 9. APIs | HTTP surface |
| 10. Application UX | Recruiter surfaces |
| 11. Matching and probing rules | Python example and status machine |
| 12. Cross-cutting | Auth, PII, eval, cost, failure |
| 13. Tech stack | Chosen shape and why |
| 14. Repository layout | Code boundaries |
| 15. Phase-wise delivery | What to build when |
| 16. Risks | Failure modes this architecture blocks |

---

## 1. Problem → architecture

The recruiter’s manual loop is ten steps. HireFlow maps each step to a **typed artifact** produced by a **specialized agent** (or by the recruiter), persisted by an orchestrator, and reviewed by a human.

| Manual step | Artifact | Owner |
| --- | --- | --- |
| 1. Read the resume | `Profile` + `Claim[]` with source spans | Resume Parser |
| 2. Compare to JD | `Requirement[]` | JD Parser |
| 3. Classify fit | `MatchResult` (`MATCHED` / `PARTIALLY_MATCHED` / `MISSING` / `UNCLEAR`) | Matcher |
| 4. Rank gaps | `Gap[]` | Gap Analyst |
| 5. Write questions | `InterviewPlan` | Interview Designer |
| 6. Conduct interview | External (live call, panel, ATS interview) | Recruiter — **not an agent** |
| 7. Follow up on vague answers | `ProbeResult[]` + remaining follow-ups | Prober (runs on the provided transcript) |
| 8. Review transcript | Structured `TranscriptTurn[]` | Transcript Parser |
| 9. Combine evidence | `EvidenceItem[]` | Evidence Collector |
| 10. Final assessment | `Report` + human `Decision` | Report Agent + recruiter |

There is **no Interviewer agent**. Vague answers are not probed live inside HireFlow. After the transcript is uploaded, the Prober scores coverage against each requirement’s evidence target and, where answers are shallow, emits follow-up questions for a later round.

Keyword matching is rejected as the core algorithm. A skill name is a **claim**. A match requires **application, depth, ownership, and (when possible) outcome**.

---

## 2. Architecture principles

1. **Evidence over keywords.** `"Python — 4 years"` is not `MATCHED`.
2. **Four-way classification, always.** Never collapse to match / no-match.
3. **Missing ≠ reject.** `MISSING` and `UNCLEAR` become interview probes unless the recruiter marks a deal-breaker.
4. **Candidate-specific interview plans.** Questions come from *this* resume vs *this* JD. The recruiter downloads a candidate report file with the plan and uses both outside HireFlow.
5. **Transcript in, evidence out.** HireFlow does not host the interview. A provided transcript is the only interview input.
6. **Probe the record, not the candidate.** The Prober reads the transcript, never chats with the candidate. Shallow coverage becomes remaining follow-ups, not an unbounded live loop.
7. **Humans own the hire.** Agents never write `Decision.outcome`.
8. **Traceability.** Every status, question, and report line points at a resume span or transcript turn.
9. **Deterministic agent graph.** Narrow agents, typed I/O, no “do everything” agent.
10. **Human-editable control points.** Requirements, gaps, and interview plans can be edited before the next stage runs.
11. **Phase isolation.** Later stages consume earlier artifacts; they do not silently rewrite them.
12. **Embeddings are retrieval, not judgment.** Cosine similarity may fetch candidate claims; it must not assign match status.
13. **Idempotent pipelines.** Re-running parse/match/transcript analysis for a document version replaces that version’s artifacts, not unrelated history.

---

## 3. System context

```text
┌─────────────┐                         ┌──────────────┐
│  Recruiter  │                         │   Hiring     │
│             │                         │   manager    │
└──────┬──────┘                         └──────┬───────┘
       │                                       │
       │  jobs, matrix, plans,                 │  read-only
       │  transcript upload,                   │  report
       │  reports, decisions                   │  (later)
       ▼                                       ▼
┌──────────────────────────────────────────────────────────┐
│  Vercel — recruiter web (Next.js, apps/web)              │
│  HTTPS · /backend proxy · no secrets                     │
└────────────────────────────┬─────────────────────────────┘
                             │ HIREFLOW_API_URL
                             ▼
┌──────────────────────────────────────────────────────────┐
│  Railway — FastAPI + agent runtime (apps/api)            │
└───┬────────────────────┬─────────────────────┬───────────┘
    │                    │                     │
    ▼                    ▼                     ▼
┌─────────────┐   ┌──────────────┐   ┌─────────────────┐
│ LLM provider│   │ Object store │   │ Supabase        │
│ embeddings  │   │ JD / resumes │   │ evidence tables │
└─────────────┘   │ transcripts  │   │ matches, plans  │
                  │ report files │   │ report metadata │
      │           └──────────────┘   └─────────────────┘
      ▼  (Phase 7)
┌─────────────┐
│ ATS (opt.)  │
│ Greenhouse /│
│ Lever /     │
│ email ingest│
└─────────────┘
```

The candidate is **not a HireFlow user**. They interview with the recruiter through whatever channel the team already uses (Zoom, phone, onsite, ATS). HireFlow only sees the transcript the recruiter provides.

### 3.1 Actors

| Actor | Can do | Cannot do |
| --- | --- | --- |
| **Recruiter** | Create jobs, upload JD/resumes/transcripts, edit requirements/plans, run pipelines, download candidate report files for the interview, record decisions | Be auto-overridden by an agent decision |
| **Hiring manager** (Phase 7) | Read and download evidence reports for a job | Edit match labels or run agents |
| **System / worker** | Run agent graphs, persist artifacts | Hire, reject, or talk to candidates |

### 3.2 Trust boundary

- PII lives in **Supabase tables** (names, emails, structured evidence, report metadata) and object storage (resume/transcript originals and downloadable candidate report files).
- LLM providers receive **redacted or minimized** text where practical (resume body and transcript body are unavoidable for parsing).
- Original files and report files never leave object storage except via signed download URLs.
- The Supabase service role key and LLM keys stay on **Railway** (API/workers). They are never set as Vercel browser secrets and never shipped to the client.
- Agent traces store model I/O; they are treated as PII.
- Production hosting is split: **Vercel** serves the recruiter UI; **Railway** runs FastAPI and the three graphs. Vercel does not host the API.

---

## 4. Logical architecture

### 4.1 Layers

```text
┌─────────────────────────────────────────────────────────┐
│ Presentation                                             │
│  Recruiter app                                           │
└────────────────────────────┬────────────────────────────┘
                             │ HTTPS / JSON
┌────────────────────────────▼────────────────────────────┐
│ Application API (FastAPI)                                │
│  Auth · Jobs · Candidates · Documents · Pipeline runs    │
│  Transcript ingest · Reports · Decisions                 │
└───────────────┬────────────────────────────┬────────────┘
                │ enqueue                    │ read/write
┌───────────────▼────────────┐  ┌────────────▼────────────┐
│ Orchestrator / workers     │  │ Evidence store          │
│  LangGraph pipelines       │  │  (Supabase tables)      │
│  screening graph           │  │  domain rows + traces   │
│  transcript graph          │  └────────────▲────────────┘
│  report graph              │               │
└───────────────┬────────────┘               │
                │                            │
┌───────────────▼────────────┐  ┌────────────┴────────────┐
│ Agent package              │  │ Document store (S3)     │
│  10 specialists + schemas  │  │  originals, extracted   │
└───────────────┬────────────┘  │  text, report files     │
                │               └─────────────────────────┘
┌───────────────▼────────────┐  ┌─────────────────────────┐
│ Model gateway              │  │ Observability           │
│  chat + structured output  │  │  traces, costs, eval    │
│  embeddings (retrieval)    │  └─────────────────────────┘
└────────────────────────────┘
```

### 4.2 Component responsibilities

| Component | Responsibility | Does not |
| --- | --- | --- |
| **Web app** | Recruiter workflow, optimistic polling of run status, File assistant (Phase 6) | Call LLMs directly; host interviews |
| **API** | AuthZ, validation, CRUD, start runs, transcript upload, signed uploads, file catalog + download | Embed prompt logic |
| **Orchestrator** | Load artifacts, invoke the correct graph, persist outputs, version runs | Invent business labels outside agents |
| **Agent package** | Pure functions: `(typed input, tools) → typed output` | Write to DB or HTTP |
| **Model gateway** | Provider routing, retries, JSON-schema enforcement, token accounting | Domain decisions |
| **Evidence store** | Supabase tables: source of truth for requirements, matches, evidence, report metadata, decisions | Report file bytes |
| **Document store** | Immutable originals, extracted text, and downloadable candidate report files | Structured match labels |
| **Trace store** | Agent run logs for debug and eval | Recruiter-facing copy |

### 4.3 End-to-end product flow

```text
JD ─► Resume Parsing ─► Requirement Matching ─► Gap Identification
  ─► Personalized Interview Plan + downloadable interview-brief report
  ─► Recruiter uses the file in an external interview
  ─► Provided Transcript ─► Transcript Parsing ─► Deep Probing
  ─► Evidence Collection ─► downloadable evidence report ─► Human Hiring Decision
```

---

## 5. Runtime architecture

HireFlow has **three async runtimes**. None of them is a live conversation.

### 5.1 Screening pipeline (async job)

Triggered when a recruiter parses a JD, parses a resume, or runs match+gaps (and, in Phase 3+, interview-plan generation) for a candidate.

```text
Vercel UI  --/backend-->  Railway API  --enqueue--> queue --worker--> screening graph
                                                                  │
                                                                  ├─ persist artifacts
                                                                  ├─ write interview-brief report file (Phase 3+)
                                                                  └─ emit run status (queued|running|succeeded|failed)
UI polls GET /runs/:id through the same /backend proxy
```

Long-running. Typical latency: tens of seconds to a few minutes per candidate. These jobs run on Railway, not on Vercel functions.

### 5.2 Transcript pipeline (async job)

Triggered when a recruiter uploads or pastes an interview transcript.

```text
API  --enqueue--> transcript graph
                    Transcript Parser → structured turns
                    Prober → coverage + remaining follow-ups
                    persist Transcript + ProbeResult[]
```

Typical latency: tens of seconds, depending on transcript length.

### 5.3 Report pipeline (async job)

Triggered after transcript analysis completes, or on recruiter “regenerate report”.

```text
API --enqueue--> report graph
  Evidence Collector → status updates → Report Agent
  persist Report metadata (Supabase) + immutable downloadable file (object store)
```

### 5.4 Why three graphs

| Graph | State lifetime | Failure mode |
| --- | --- | --- |
| Screening | Minutes, batchable | Retry whole stage; recruiter re-runs |
| Transcript | Minutes, per upload | Re-parse replaces that transcript version’s turns and probe results |
| Report | Minutes, once per transcript version | Regenerating creates a new report version; old reports stay |

A live interviewer agent would mix conversational failure modes with auditability. HireFlow avoids that by treating the interview as an external event and the transcript as a document.

### 5.5 File assistant (Phase 6 — sync request)

Recruiter asks for a file in plain language. This is **not** a fourth graph and **not** a live interviewer.

```text
Vercel /files  --/backend-->  Railway POST /files/locate
                                 │
                                 ├─ orchestrator builds org file catalog
                                 │    (JD, resume, transcript, match & gaps,
                                 │     interview brief, evidence report)
                                 ├─ File Locator agent (typed JSON; heuristic fallback)
                                 │    action: locate | download | read | summarize | parse
                                 ├─ on read/summarize/parse: load text for primary hit
                                 │    read → excerpt; summarize → File Summarizer (Groq)
                                 │    parse → JD/Resume/Transcript parsers or stored structured data
                                 └─ GET download path for each hit when action is download
```

Typical latency: 1–3 seconds for locate/download; 3–15 seconds for summarize/parse (Groq). The agent **selects** locators from the catalog and may **read** stored text. It does not write files, call Decision, or invent documents. Bytes come from Supabase Storage (or generated briefs) through existing download routes.

**Before production deploy:** run `/files` locally against the same Supabase project. Same `GROQ_API_KEY` for summarize/parse on raw documents. Locate/read work without Groq; summarize/parse on JD/resume/transcript need Groq.

---

## 6. Multi-agent design

### 6.1 Agent contract

Every agent:

- Accepts a **JSON Schema** input.
- Returns a **JSON Schema** output (strict / constrained decoding).
- Is **side-effect free**. Persistence is the orchestrator’s job.
- Receives only the **minimum context** needed.
- Records `model`, `prompt_version`, `input_hash`, `token_usage`, `latency_ms` via the gateway.

Shared output envelope:

```json
{
  "agent": "matcher",
  "schema_version": "1.0",
  "confidence": 0.0,
  "warnings": [],
  "payload": {}
}
```

### 6.2 Agent catalog

| Agent | Graph | Input | Output |
| --- | --- | --- | --- |
| **JD Parser** | screening | JD text + filename | `Requirement[]`, role metadata |
| **Resume Parser** | screening | Resume text + filename | `Profile`, `Claim[]` |
| **Matcher** | screening | Requirements + profile + claims | `MatchResult[]` |
| **Gap Analyst** | screening | Match results + requirement priorities | Ranked `Gap[]` |
| **Interview Designer** | screening | Gaps + profile + recruiter overrides | `InterviewPlan` (questions); orchestrator then writes the interview-brief report file |
| **Transcript Parser** | transcript | Raw transcript text + optional plan | Structured `TranscriptTurn[]` mapped to requirements when possible |
| **Prober** | transcript | Plan + evidence targets + structured turns | Per-requirement coverage, verdicts, remaining follow-up questions |
| **Evidence Collector** | report | Claims + match results + transcript + probe results | `EvidenceItem[]`, proposed `status_after_interview` |
| **Report** | report | Evidence graph + job/candidate metadata | Structured `Report` body; orchestrator renders the downloadable file |
| **File Locator** | request-path (not a graph) | Recruiter query + org file catalog | Matched locators, `action`, `want_download`, one-line summary |
| **File Summarizer** | request-path (with File Locator) | Document text + kind | Recruiter-facing summary and key points |

Supervisor / orchestrator is **code** (LangGraph for the three graphs; a FastAPI handler for File Locator), not an LLM.

There is no Interviewer agent and no turn-by-turn session graph. File Locator finds stored files and can read, summarize, or parse them on request; it does not chat with candidates.

### 6.3 Screening graph

```text
                    ┌─────────────┐
         JD file ─► │  extract    │ ─► jd_text
                    │  text       │
                    └──────┬──────┘
                           ▼
                    ┌─────────────┐
                    │ JD Parser   │ ─► requirements (editable)
                    └─────────────┘

                    ┌─────────────┐
     Resume file ─► │  extract    │ ─► resume_text
                    │  text       │
                    └──────┬──────┘
                           ▼
                    ┌─────────────┐
                    │ Resume      │ ─► profile + claims (editable)
                    │ Parser      │
                    └─────────────┘

 requirements + profile + claims
                           │
                           ▼
                    ┌─────────────┐
                    │ Matcher     │ ─► match_results
                    └──────┬──────┘
                           ▼
                    ┌─────────────┐
                    │ Gap Analyst │ ─► gaps (editable)
                    └──────┬──────┘
                           ▼
                    ┌─────────────┐
                    │ Interview   │ ─► interview_plan (editable)
                    │ Designer    │
                    └──────┬──────┘
                           ▼
                    ┌─────────────┐
                    │ Report file │ ─► interview_brief (PDF + Markdown)
                    │ renderer    │    stored on the plan; recruiter downloads
                    └─────────────┘    this for the external interview
```

Gates: if the recruiter has not confirmed requirements, matching does not run. If gaps are marked deal-breaker and the recruiter chooses not to interview, Interview Designer is skipped and no interview-brief file is written.

### 6.4 Transcript graph

```text
recruiter uploads transcript file or paste
        │
        ▼
extract text (vtt / docx / txt / pdf)
        │
        ▼
Transcript Parser
  segment speakers
  map turns to planned questions / requirements when possible
  leave unmapped content as unmatched turns (still available as evidence)
        │
        ▼
Prober (batch, per requirement in the plan — and unmatched JD must-haves)
  score transcript coverage against evidence_target
        ├─ sufficient          → coverage = met
        ├─ shallow             → still_unclear + remaining follow-ups
        ├─ not discussed       → unvalidated + remaining follow-ups
        ├─ contradiction       → flag
        └─ confirmed_missing   → flag
        │
        ▼
persist Transcript + TranscriptTurn[] + ProbeResult[]
```

The Prober does **not** ask the next question in a chat. It writes a remaining-probe list the recruiter can take to a follow-up interview, then upload a later transcript version.

### 6.5 Report graph

```text
claims + match_results + transcript turns + probe results
        │
        ▼
Evidence Collector ─► EvidenceItem[] + status_after_interview
        │
        ▼
Report Agent ─► structured Report body
        │
        ▼
Report renderer ─► immutable downloadable file (PDF + Markdown)
        │
        ▼
Recruiter Decision (not an agent)
```

### 6.6 Agent internals (behavioral spec)

#### JD Parser

- Split JD into atomic requirements (one skill, one year-band, one domain, one education bar — not a paragraph).
- `priority`: `must_have` | `nice_to_have` | `unclear_priority`.
- `category`: `skill` | `experience` | `education` | `domain` | `tooling` | `soft_skill` | `other`.
- Keep `source_quote` from the JD.
- Do not invent requirements that are not in the JD. If seniority is only implied, set `unclear_priority` and a warning.

#### Resume Parser

- Extract identity (separate, PII-tagged), work history, projects, education, skills list.
- Every skill and every project bullet becomes a `Claim` with `source_span` (`page`, `char_start`, `char_end`, `quote`).
- Implied skills in bullets are claims of type `implied_skill`, not only the skills section.
- Years-only lines (`Python — 4 years`) are claims of type `years_claim` with `skill="Python"` and `years=4`. They are **not** matches.

#### Matcher

For each requirement, inspect claims. Assign exactly one status.

Evidence dimensions the matcher scores (0/1 flags, not a hidden composite score presented as truth):

| Dimension | Question |
| --- | --- |
| `named` | Is the requirement named or clearly aliased? |
| `applied` | Is it used in a project or job bullet? |
| `complexity` | Is scale/architecture/difficulty described? |
| `professional` | Used in employment, not only coursework? |
| `ownership` | Individual contribution vs team “we”? |
| `outcome` | Measurable result? |

Label policy:

| named | applied | other depth | Status |
| --- | --- | --- | --- |
| 1 | 1 | complexity + ownership (outcome optional) | `MATCHED` |
| 1 | 1 | missing complexity or ownership | `PARTIALLY_MATCHED` |
| 1 | 0 | years-only or skills-list-only | `UNCLEAR` |
| 0 | 1 | implied in a bullet | `PARTIALLY_MATCHED` |
| 0 | 0 | nothing found | `MISSING` |
| conflicting quotes | | | `UNCLEAR` |

Rationale must quote claim IDs. Confidence is stored but **must not** override the table.

#### Gap Analyst

- Input: match results + must-have flags.
- Output: gaps for every non-`MATCHED` must-have, plus optional nice-to-haves above a severity threshold.
- `severity`: `blocker` | `high` | `medium` | `low`.
- `investigation_goal`: one sentence the interview must answer.
- `suggested_probe_themes`: list, e.g. `["artifact built", "complexity", "ownership", "outcome"]`.
- Recruiter fields later: `deal_breaker`, `skip_probe`.

#### Interview Designer

- One **primary question** per high/blocker gap.
- Optional **planned follow-ups** the recruiter can use live.
- `evidence_target`: which dimensions must become true to upgrade status.
- `missing` gaps get a fair open probe, not a gotcha.
- `unclear` / `partial` gaps ask for artifacts of work, never “Do you know Python?”
- Recruiter edits are the executed plan (`source = generated | recruiter_edited`).
- The plan is an artifact the recruiter takes into **their** interview. HireFlow does not speak these questions to the candidate.
- After the plan is persisted (generated or recruiter-edited), the orchestrator renders an **interview-brief report file** (match statuses, gaps, quotes, planned questions) and stores it on that plan. The recruiter downloads this file for the interview. A new plan version writes a new file; old files stay.

#### Transcript Parser

- Input: raw transcript text (and optional `InterviewPlan` to help mapping).
- Segment into turns with `speaker` (`recruiter` | `candidate` | `unknown`), `text`, `char_span`.
- Map turns to `requirement_id` / `planned_question_id` when the topic clearly matches. Unmapped turns stay in the record; they are still eligible as evidence.
- Do not drop off-plan discussion. Candidates often evidence a requirement without the planned wording.
- Preserve quotes verbatim. Normalization is mapping, not paraphrasing.
- Warnings if speaker diarization is missing, transcript is too short, or most turns cannot be attributed.

#### Prober

- Batch over requirements (plan items + must-haves that appeared in the transcript).
- For each requirement, read the related turns (mapped + keyword/semantic retrieval of unmapped turns).
- Classify coverage: `sufficient` | `shallow` | `not_discussed` | `confirmed_missing` | `contradiction`.
- If `shallow` or `not_discussed`, emit **remaining follow-up questions** targeting the highest missing evidence dimensions.
- Cap remaining follow-ups per requirement (default 2). Do not generate an interrogation script.
- Must not treat “I have four years of Python” as sufficient.
- Output is `ProbeResult[]`, not a chat message.

#### Evidence Collector

- Builds `EvidenceItem` rows: resume claims and transcript quotes, each with `strength`: `strong` | `weak` | `none`.
- Uses Prober verdicts as hints, but still attaches quotes.
- Proposes `status_after_interview` using the same dimension table as the Matcher, now including transcript flags.
- Records contradictions explicitly (`contradicts_claim_id`).

#### Report Agent

- Writes recruiter-facing narrative **only from EvidenceItem rows**.
- No new facts. If evidence is missing, say so.
- Includes remaining follow-ups from the Prober (unvalidated gaps).
- Includes the sentence: HireFlow does not hire; the recruiter decides.
- Does not output `advance` / `reject`. It may list **remaining risks**.
- Output is structured JSON. It does not write files.

#### Report renderer (orchestrator, not an LLM)

- Turns a structured `Report` body into immutable **Markdown and PDF** files in object storage.
- Two kinds: `interview_brief` (plan + match/gap pack for the live interview) and `evidence` (post-transcript assessment).
- Download is a signed URL. Recruiter-facing copy lives in the file, not only in a table row.

---

## 7. Domain model

### 7.1 Status vocabulary

Used everywhere. Do not invent parallel enums.

| Status | Meaning |
| --- | --- |
| `MATCHED` | Enough evidence the requirement is met |
| `PARTIALLY_MATCHED` | Some evidence; depth, recency, ownership, or complexity incomplete |
| `MISSING` | No evidence found (resume and/or transcript, depending on stage) |
| `UNCLEAR` | Named or implied, but application/depth/contribution not shown, or evidence conflicts |

Two timestamps of truth:

- `status_after_resume`
- `status_after_interview` (null until a transcript has been analyzed and the report graph has run)

### 7.2 Entity relationship

```text
User 1──* Job
Job 1──* Requirement
Job 1──* Candidate
Candidate 1──1 Profile
Candidate 1──* Claim
Candidate *──* Requirement          (via MatchResult)
MatchResult 1──0..1 Gap
Candidate 1──0..1 InterviewPlan
InterviewPlan 1──* PlannedQuestion
InterviewPlan 1──* Report            (interview_brief files stored for that interview)
Candidate 1──* Transcript           (uploaded interview records)
Transcript 1──* TranscriptTurn
Transcript 1──* ProbeResult
Candidate 1──* EvidenceItem
Candidate 1──* Report
Report 1──0..1 Decision
Job 1──* PipelineRun
```

### 7.3 Field-level entities

**Job**  
`id`, `org_id`, `title`, `status` (`draft` | `active` | `closed`), `created_by`, `created_at`

**Document**  
`id`, `owner_type` (`job` | `candidate` | `transcript`), `owner_id`, `kind` (`jd` | `resume` | `transcript`), `storage_key`, `mime`, `sha256`, `extracted_text`, `version`, `uploaded_by`

**Requirement**  
`id`, `job_id`, `document_version`, `text`, `normalized_label` (e.g. `Python`), `category`, `priority`, `source_quote`, `source_span`, `recruiter_edited`, `sort_order`

**Profile**  
`id`, `candidate_id`, `full_name`, `email`, `summary`, `years_experience`, `education[]`, `roles[]`, `skills_listed[]`, `parser_warnings[]`

**Claim**  
`id`, `candidate_id`, `kind` (`skill` | `implied_skill` | `years_claim` | `project` | `education` | `other`), `text`, `skill_label?`, `years?`, `source_span`, `quote`

**MatchResult**  
`id`, `job_id`, `candidate_id`, `requirement_id`, `status`, `confidence`, `rationale`, `dimension_flags` (json), `supporting_claim_ids[]`, `run_id`

**Gap**  
`id`, `match_result_id`, `severity`, `investigation_goal`, `suggested_probe_themes[]`, `deal_breaker` (bool, recruiter), `skip_probe` (bool, recruiter)

**InterviewPlan**  
`id`, `candidate_id`, `job_id`, `status` (`draft` | `approved` | `superseded`), `version`, `brief_report_id` (downloadable interview-brief file for this plan)

**PlannedQuestion**  
`id`, `plan_id`, `requirement_id`, `sort_order`, `prompt`, `planned_followups[]`, `evidence_target` (dimension list), `source` (`generated` | `recruiter_edited`)

**Transcript**  
`id`, `candidate_id`, `job_id`, `plan_id?`, `document_id`, `source` (`upload` | `paste`), `status` (`uploaded` | `parsed` | `analyzed` | `failed`), `version`, `warnings[]`

**TranscriptTurn**  
`id`, `transcript_id`, `speaker` (`recruiter` | `candidate` | `unknown`), `text`, `char_span`, `requirement_id?`, `question_id?`, `sort_order`

**ProbeResult**  
`id`, `transcript_id`, `requirement_id`, `verdict` (`sufficient` | `shallow` | `not_discussed` | `confirmed_missing` | `contradiction`), `missing_dimensions[]`, `supporting_turn_ids[]`, `remaining_followups[]`, `rationale`

**EvidenceItem**  
`id`, `candidate_id`, `requirement_id`, `source` (`resume` | `interview`), `quote`, `source_ref` (claim_id or turn_id), `interpretation`, `strength`, `dimensions_supported[]`

**Report**  
`id`, `candidate_id`, `job_id`, `plan_id?`, `kind` (`interview_brief` | `evidence`), `version`, `document_id` (object-store file), `body` (structured JSON for in-app view), `generated_from_run_id`, `created_at`

The recruiter-facing artifact is the **file**. The Supabase row is metadata plus a pointer. `interview_brief` is stored on the personalized interview plan and downloaded for the external interview. `evidence` is the post-transcript assessment; `Decision` attaches to that kind.

**Decision**  
`id`, `report_id`, `outcome` (`advance` | `hold` | `reject`), `notes`, `decided_by`, `decided_at`

**PipelineRun**  
`id`, `graph` (`screening` | `transcript` | `report`), `subject_type`, `subject_id`, `status`, `error`, `started_at`, `finished_at`, `trace_id`

---

## 8. Persistence

### 8.1 Supabase tables

**Supabase is the system of record for structured rows.** HireFlow does not run or connect to a self-hosted PostgreSQL instance. Match results, gaps, plans, report **metadata**, and decisions are rows in Supabase tables.

Supabase is hosted Postgres, so foreign keys, unique indexes, and JSONB still apply. JSONB is allowed for `dimension_flags`, `report.body`, `remaining_followups`, never for core foreign keys.

Suggested tables (created in the Supabase project via `infra/sql` migrations): `users`, `orgs`, `jobs`, `documents`, `requirements`, `candidates`, `profiles`, `claims`, `match_results`, `gaps`, `interview_plans`, `planned_questions`, `transcripts`, `transcript_turns`, `probe_results`, `evidence_items`, `reports`, `decisions`, `pipeline_runs`, `agent_traces`, `file_assistant_requests` (Phase 6).

Candidate reports: one metadata row per version in `reports`. The recruiter-facing copy is a **downloadable file** in object storage (`document_id`). `kind = interview_brief` is attached to `interview_plans.brief_report_id` and is what the recruiter takes into the personalized interview. `kind = evidence` is the post-transcript assessment; decisions attach via `decisions.report_id`. Regenerating writes a new file and a new row; old files and rows stay.

Indexes:

- `(job_id)` on candidates, requirements, match_results
- `(candidate_id, requirement_id)` unique on match_results per `run_id` generation (or unique on current-run view)
- `(transcript_id, sort_order)` on transcript_turns
- `(sha256)` on documents for dedup

Access:

- The FastAPI API (and workers) are the only writers. They use `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY`.
- The web app never holds the service role key. Recruiters reach data through HireFlow APIs.
- Row Level Security is enabled on every table. Policies scope rows by `org_id` so a leaked anon key cannot dump another org.
- Agents never call Supabase. The orchestrator persists typed agent output.

Apply schema with `infra/sql` against the Supabase project (`supabase db push` or the SQL editor). Do not use local SQLite as the product store.

Required env (API / workers): `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`. Optional: `SUPABASE_ANON_KEY` only if a later phase reads through RLS from the browser.

### 8.2 Object storage

Path convention:

```text
org/{org_id}/jobs/{job_id}/jd/{document_id}/original
org/{org_id}/jobs/{job_id}/candidates/{candidate_id}/resume/{document_id}/original
org/{org_id}/jobs/{job_id}/candidates/{candidate_id}/transcripts/{document_id}/original
org/{org_id}/jobs/{job_id}/candidates/{candidate_id}/reports/{report_id}/interview-brief.md
org/{org_id}/jobs/{job_id}/candidates/{candidate_id}/reports/{report_id}/interview-brief.pdf
org/{org_id}/jobs/{job_id}/candidates/{candidate_id}/reports/{report_id}/evidence.md
org/{org_id}/jobs/{job_id}/candidates/{candidate_id}/reports/{report_id}/evidence.pdf
```

Files are immutable. A new upload creates a new `documents.version` and invalidates downstream artifacts until re-run. A new plan or report version writes new report files; previous files remain downloadable.

### 8.3 Redis

- Job queue
- Rate limits

Optional on Railway. If `REDIS_URL` is unset, screening / transcript / report jobs run in-process on the API service. Add a Railway Redis plugin and a worker process when volume requires it.

No interview session locks: there is no live turn writer.

### 8.4 Trace store

Each agent invocation: input JSON, output JSON, model, tokens, latency, prompt version. May live in the Supabase `agent_traces` table initially; can move to Langfuse/OpenTelemetry later without changing domain tables.

### 8.5 Hosting (Vercel + Render)

Production is **two application hosts** plus Supabase. Do not put FastAPI on Vercel.

| Surface | Host | Why |
| --- | --- | --- |
| Recruiter web (`apps/web`) | **Vercel** | Next.js App Router; static + server proxy only |
| API + orchestrator (`apps/api`) | **Render** (free tier) | Python web service: uploads, 30s–minutes LLM graphs |
| Tables | **Supabase** | System of record (already chosen) |
| Files | **Supabase Storage** (S3-compatible later) | Immutable originals and report files |
| LLM | Groq (or the configured gateway) | Called only from the API host |

```text
Browser
  │ HTTPS
  ▼
Vercel (Next.js)
  │ server-side /backend/*  (HIREFLOW_API_URL, maxDuration 120s)
  ▼
Render (FastAPI + in-process or Redis workers)
  ├─ Supabase tables (SUPABASE_SERVICE_ROLE_KEY)
  ├─ Object storage
  └─ LLM provider (GROQ_API_KEY)
```

**Browser contract.** The UI keeps calling same-origin `/backend`. The App Router handler at `apps/web/src/app/backend/[...path]/route.ts` forwards to Render (`HIREFLOW_API_URL`). Recruiters never see the API host URL. The browser never receives service-role or LLM keys.

**Local.** `HIREFLOW_API_URL` defaults to `http://127.0.0.1:8000`. Next.js on :3000/:3001, uvicorn on :8000.

**Vercel env.** `HIREFLOW_API_URL` = Render public HTTPS origin, no trailing slash (e.g. `https://hireflow-api.onrender.com`). Root Directory = `apps/web`. Config: `apps/web/vercel.json`.

**Render env.** `SECRET_KEY`, `CORS_ORIGINS` (the Vercel origin, e.g. `https://<project>.vercel.app`, plus any custom domain), `GROQ_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`. Optional: `REDIS_URL`. Config: `render.yaml` at the repo root.

**Render process.** Blueprint installs `requirements-railway.txt` (`packages/domain`, `packages/extract`, `packages/agents`, `apps/api`), then:

```text
python -m uvicorn hireflow_api.main:app --host 0.0.0.0 --port $PORT
```

Health check: `GET /health`. Python version: `runtime.txt` (3.11.9).

**Render free tier.** Web services spin down after ~15 minutes of inactivity; the first request after sleep has a cold start (~30–60s). Long jobs (screening, report) are enqueued on the API and polled by the UI, so the Vercel proxy does not need to wait for the full graph.

**Alternative: Railway.** `railway.toml` at the repo root provides the same API deploy on a paid always-on host if cold starts are unacceptable.

**Timeouts.** Screening, transcript analyze, and evidence report exceed Vercel Hobby’s ~10s function cap. Use Vercel Pro for the `/backend` proxy, or enqueue on the API and poll so the proxy only waits for a queued run. Graphs themselves always run on Render/Railway.

**Not chosen:** FastAPI as Vercel serverless; SQLite or local disk as production object storage (the filesystem is ephemeral). Use Supabase Storage / S3 for files.

#### 8.5.1 Deploy checklist (Supabase → Render → Vercel)

**1. Supabase (database + files)**

- Create a project at [supabase.com](https://supabase.com).
- Run migrations in `infra/sql/` against the project (SQL editor or `psql` with the connection string).
- Create a **private** Storage bucket named `hireflow` (the API also attempts to create it on first upload).
- Copy **Project URL** → `SUPABASE_URL` and **service role key** → `SUPABASE_SERVICE_ROLE_KEY` (Render only; never on Vercel).

**2. Render (API)**

- In [Render](https://render.com): **New → Blueprint**, connect the GitHub repo.
- Render reads `render.yaml` and creates a free **Web Service** named `hireflow-api`.
- Set environment variables in the Render dashboard (see root `.env.example`):

  | Variable | Value |
  | --- | --- |
  | `SECRET_KEY` | Auto-generated by Blueprint, or set a long random string |
  | `CORS_ORIGINS` | Vercel URL(s), comma-separated, e.g. `https://hireflow.vercel.app` |
  | `SUPABASE_URL` | From Supabase |
  | `SUPABASE_SERVICE_ROLE_KEY` | From Supabase |
  | `GROQ_API_KEY` | From Groq |
  | `APP_ENV` | `production` (set by Blueprint) |

- Deploy; confirm `GET https://<service>.onrender.com/health` returns `{ "status": "ok" }`.
- Optional: upgrade to a paid Render plan to avoid free-tier sleep/cold starts.

**3. Vercel (recruiter web)**

- Import repo; **Root Directory** = `apps/web`.
- Environment variable:

  | Variable | Value |
  | --- | --- |
  | `HIREFLOW_API_URL` | Render public HTTPS origin, **no trailing slash** (e.g. `https://hireflow-api.onrender.com`) |

- Deploy. The UI calls same-origin `/backend/*`; `apps/web/src/app/backend/[...path]/route.ts` proxies to Render (`maxDuration` 120s in `vercel.json`).
- After first deploy, add the Vercel production URL to Render `CORS_ORIGINS` if not already set.

**4. Smoke test**

- Register / log in on Vercel.
- Create a job, upload JD + resume, run screening.
- Confirm rows appear in Supabase (`match_results`, `documents`) and files in Storage bucket `hireflow`.

**Secrets boundary**

| Host | Holds |
| --- | --- |
| Vercel | `HIREFLOW_API_URL` only |
| Render | `SECRET_KEY`, `CORS_ORIGINS`, `SUPABASE_*`, `GROQ_API_KEY` |
| Browser | Recruiter JWT only (httpOnly/localStorage per web app) |

---

## 9. APIs

All APIs require recruiter auth. There is no candidate-facing API.

### 9.1 Jobs and documents

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/jobs` | Create job |
| `GET` | `/jobs/:id` | Job + latest JD document |
| `POST` | `/jobs/:id/jd` | Upload JD (returns document id) |
| `POST` | `/jobs/:id/parse-jd` | Enqueue JD Parser |
| `GET` | `/jobs/:id/requirements` | List requirements |
| `PATCH` | `/requirements/:id` | Recruiter edit / reorder / drop |
| `POST` | `/jobs/:id/candidates` | Create candidate + resume upload |
| `POST` | `/candidates/:id/parse-resume` | Enqueue Resume Parser |
| `GET` | `/candidates/:id/profile` | Profile + claims |

### 9.2 Matching and gaps

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/candidates/:id/match` | Enqueue Matcher + Gap Analyst |
| `GET` | `/jobs/:id/matrix` | Requirement × candidate statuses |
| `GET` | `/candidates/:id/matches` | Per-requirement results + quotes |
| `GET` | `/candidates/:id/gaps` | Ranked gaps |
| `PATCH` | `/gaps/:id` | `deal_breaker`, `skip_probe` |

### 9.3 Interview plan and transcript

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/candidates/:id/interview-plan` | Enqueue Interview Designer + interview-brief file |
| `GET` | `/candidates/:id/interview-plan` | Current plan + link to stored brief file |
| `PATCH` | `/planned-questions/:id` | Edit prompt / drop / reorder (re-render brief file) |
| `POST` | `/candidates/:id/transcripts` | Upload file or paste text |
| `POST` | `/transcripts/:id/analyze` | Enqueue Transcript Parser + Prober |
| `GET` | `/transcripts/:id` | Raw + structured turns |
| `GET` | `/transcripts/:id/probes` | Coverage verdicts + remaining follow-ups |

Uploading a new transcript creates a new version. Analyze is idempotent per `transcript_id`.

### 9.4 Report and decision

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/candidates/:id/report` | Enqueue report graph (evidence file) |
| `GET` | `/candidates/:id/report` | Latest evidence report metadata + in-app body |
| `GET` | `/reports/:id/download` | Signed URL for the report file (PDF or Markdown) |
| `POST` | `/reports/:id/decision` | Human decision (evidence reports only) |

`GET /reports/:id/download` serves both `interview_brief` (the file stored for the personalized interview) and `evidence`.

### 9.5 Runs

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/runs/:id` | Status, error, links to artifacts |

Idempotency: mutating pipeline starts accept `Idempotency-Key`. Re-uploads of the same `sha256` reuse the document row.

### 9.6 File Locator

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/files/chat` | Conversational File assistant (message thread → natural-language reply) |
| `POST` | `/files/locate` | Natural-language lookup; optional read, summarize, or parse via `action` |
| `GET` | `/files/history` | Recent File assistant requests for the org (audit log) |
| `GET` | `/files/download?locator=` | Download by locator (`document:…`, `screening:…`, `report:…`) |
| `GET` | `/documents/:id/download` | Original JD, resume, or transcript bytes |

Response fields: `action` (`locate` \| `download` \| `read` \| `summarize` \| `parse`), `hits`, `answer` (text for read/summarize), `parsed` (JSON for parse), `request_id` (audit row in `file_assistant_requests`). Kinds: `jd`, `resume`, `transcript`, `screening_brief`, `interview_brief`, `evidence`. Missing files are listed as not ready; the agent does not start pipelines.

---

## 10. Application UX

Recruiter-only. No candidate interview app.

### 10.1 Recruiter information architecture

```text
/jobs
  /jobs/:id                     overview, JD, pipeline health
  /jobs/:id/requirements        editor (Phase 1)
  /jobs/:id/candidates          list + upload
  /jobs/:id/matrix              match matrix (Phase 2)
  /jobs/:id/compare             comparison board (Phase 7)
  /candidates/:id               profile + claims
  /candidates/:id/gaps          gap list
  /candidates/:id/plan          interview plan + download interview-brief file
  /candidates/:id/transcript    upload / paste / structured turns / remaining probes
  /candidates/:id/report        evidence report (view + download) + decision
  /files                        File assistant (Phase 6): find, download, read, summarize, parse
```

### 10.2 Match matrix cell

Each cell shows:

- Status chip
- Short rationale
- Click → quotes (resume and, later, transcript)
- Must-have vs nice-to-have styling

Empty evidence renders **“No evidence found”**, never a blank cell.

### 10.3 Interview plan

- Editable question list mapped to requirements
- **Download interview-brief file** (PDF / Markdown): match statuses, quotes, gaps, and the planned questions, stored on this plan
- Copy/export for use in Zoom, a panel doc, or an ATS
- No “start interview” control inside HireFlow

### 10.4 Transcript workspace

- Upload (`.txt`, `.vtt`, `.docx`, `.pdf`) or paste
- Run analysis
- Structured turns with speaker labels and requirement tags (recruiter can correct mapping)
- Per-requirement Prober verdict
- Remaining follow-up questions to take to a next round
- Support multiple transcript versions (first interview, follow-up)

### 10.5 Evidence report layout

1. Header: role, candidate, report version, timestamp, **download file**
2. Matrix: resume status → interview status → final
3. Must-haves: strongest quote, source, remaining doubt
4. Unresolved gaps and remaining follow-ups
5. Contradictions
6. Transcript coverage (discussed / shallow / not discussed / skipped in plan)
7. Remaining risks
8. Decision form (`advance` | `hold` | `reject` + notes)

The same layout is written into the stored PDF/Markdown. The interview-brief file uses the resume-only columns plus the personalized question list (no interview-status or decision form).

### 10.6 File assistant (Phase 6)

- Header control **Assistant** → `/files`
- **Chat UI:** recruiter messages on the right; assistant replies on the left in plain language
- Natural requests: find, download, read, summarize, parse — e.g. `Can you summarize Soumya's resume?`, `Download her interview brief`, `What are the gaps for Soumya?`
- Follow-ups work in thread: `Summarize it`, `Download that` (uses prior file context)
- Assistant bubbles can include file cards with **Download** and collapsible structured parse output
- API: `POST /files/chat` with message thread; `POST /files/locate` kept for direct calls
- Auto-download when the assistant resolves a single ready file and `action=download`

---

## 11. Matching, probing, and status transitions

### 11.1 Canonical example (from the problem statement)

JD must-have: Python.

**Candidate A resume:** `"Python — 4 years"`

| Dimension | Resume | Transcript says only “I have used Python for 4 years” |
| --- | --- | --- |
| named | yes | yes |
| applied | no | still no |
| complexity | no | missing |
| professional | unknown | missing |
| ownership | no | missing |
| outcome | no | missing |

- After resume: **`UNCLEAR`**. Years are not proof.
- Matcher rationale cites the years claim and the missing project evidence.
- Gap: high / blocker. Investigation goal: *Prove professional Python: system built, complexity, personal contribution, measurable outcome.*
- Interview plan primary question: *Walk me through a specific system you built with Python. What did you build, and what was yours?*
- Recruiter runs that interview externally and uploads the transcript.
- If the transcript only repeats “4 years”, Prober verdict = `shallow`. Remaining follow-ups cover: what was built, complexity, professional vs academic, individual contribution, measurable outcome (capped).
- Those follow-ups are for a **next** interview. They are not asked inside HireFlow.

**Candidate B resume:** no Python at all.

- After resume: `MISSING`
- Not auto-rejected
- Plan includes an open probe: *Have you used Python professionally? If yes, walk through a specific system.*
- Transcript with no Python discussion: `not_discussed` or, if they say they have none, `confirmed_missing`
- Transcript with depth: may become `PARTIALLY_MATCHED` or `MATCHED`

### 11.2 Status transitions after transcript analysis

| After resume | Transcript result | `status_after_interview` |
| --- | --- | --- |
| `UNCLEAR` | artifact + complexity + ownership | `MATCHED` |
| `UNCLEAR` | artifact, no ownership/complexity | `PARTIALLY_MATCHED` |
| `PARTIALLY_MATCHED` | years-only again | `UNCLEAR` or stay `PARTIALLY_MATCHED` |
| `MISSING` | demonstrates work | `MATCHED` or `PARTIALLY_MATCHED` |
| `MISSING` | candidate has no experience | `MISSING` (confirmed) |
| `MATCHED` | contradiction | `UNCLEAR` (downgrade) |
| any | requirement not discussed | unchanged; report flags **unvalidated** |

Upgrades require evidence items. Downgrades require a contradiction or explicit confirmation of absence.

---

## 12. Cross-cutting concerns

### 12.1 AuthN / AuthZ

- Recruiter: session or SSO (Phase 0: email/password or magic link is enough).
- No candidate accounts or session tokens.
- Row-level: all queries scoped by `org_id`.
- Agents run as a worker identity on Railway; they cannot call decision endpoints.
- JWT `SECRET_KEY` lives only on Railway. The Vercel proxy forwards the `Authorization` header and does not issue tokens.

### 12.2 PII and compliance

- Resumes and transcripts are PII.
- Retention policy per org (default: keep until job closed + configurable days).
- Export/delete candidate: cascade claims, turns, evidence, files.
- LLM logging: disable provider training; mark traces internal.
- Optional PII scrubber before tracing (names/emails) — never scrub before matching, because identity fields are part of the profile.

### 12.3 Prompt and schema versioning

- Each agent has `prompt_version` and `schema_version`.
- Stored on `PipelineRun` / `agent_traces`.
- Eval fixtures pin versions. Changing a prompt is a version bump, not a silent edit.

### 12.4 Evaluation

Golden set derived from the problem statement and extensions:

| Fixture | Expected resume status for Python |
| --- | --- |
| Years-only skill line | `UNCLEAR` |
| Python in skills + production system bullet with ownership | `MATCHED` |
| Python absent | `MISSING` |
| Python only in a coursework project | `PARTIALLY_MATCHED` or `UNCLEAR` |
| “Used Python” with no artifact | `UNCLEAR` |

Eval also checks:

- Interview plan contains artifact questions, not yes/no.
- A transcript that only says “I have 4 years of Python” is `shallow`, not `sufficient`.
- Remaining follow-ups target missing dimensions.
- Report contains no fact absent from evidence items.

CI runs the golden set against the agent package with recorded fixtures (LLM optional in CI via cached outputs; nightly live eval).

### 12.5 Cost and model routing

| Agent | Model tier | Reason |
| --- | --- | --- |
| Text extraction | none / OCR if needed | Deterministic |
| JD Parser, Resume Parser, Transcript Parser, File Locator, File Summarizer | fast | Volume / lookup |
| Matcher, Gap Analyst | strong | Label quality is the product |
| Interview Designer | strong | Question quality |
| Prober | strong | Must not accept vague answers |
| Evidence Collector, Report | strong | Audit-facing |

Shortlist gate (Phase 7): expensive graphs run on recruiter-shortlisted candidates first; batch match still runs for the matrix.

### 12.6 Failure handling

| Failure | Behavior |
| --- | --- |
| Extracted text empty | Run `failed`, UI shows “could not read file” |
| LLM JSON invalid | Gateway retries with repair once, then fail the run |
| Matcher missing a requirement | Orchestrator rejects partial output; no silent drop |
| Transcript has no speaker labels | Parser marks `unknown`; Prober still runs with a warning |
| Transcript too short / empty answers | Analyze succeeds with `not_discussed` / `shallow` across the plan |
| Concurrent recruiters editing a plan | Last write wins on question row + `updated_at`; approved plans are cloned to a new version |

### 12.7 Observability

- Metrics: run success rate, latency per agent, tokens per candidate, probe verdict distribution, status distribution.
- Logs: `org_id`, `job_id`, `candidate_id`, `run_id`, `trace_id`.
- Recruiter-visible: run status and warnings, not raw prompts.

---

## 13. Tech stack

Vendors can change. The domain model and graphs cannot.

| Concern | Choice | Why |
| --- | --- | --- |
| Recruiter web | Next.js (App Router) on **Vercel** | SSR for reports, one auth mode; native Next host |
| API | Python FastAPI on **Render** (or Railway) | Long-running graphs, uploads, typed pydantic schemas |
| Agent graphs | LangGraph | Explicit state machines; screening vs transcript vs report |
| Structured output | Pydantic + constrained decoding | Status enums cannot drift |
| DB | Supabase tables | Hosted Postgres; RLS; JSONB for flags and `report.body` |
| Files | S3-compatible (Supabase Storage in production) | Immutable originals (JD, resume, transcript) and candidate report files |
| Queue | Redis + arq (optional); in-process on Railway until Redis is added | Screening / transcript / report jobs |
| Text extraction | pypdf / python-docx / vtt; OCR fallback later | Phase 0–1 and transcript ingest |
| Embeddings | Optional pgvector on the Supabase project | Claim and turn retrieval aid only |
| LLM | Provider-agnostic gateway on Railway | Swap models per agent tier; keys never on Vercel |
| Observability | OpenTelemetry + `agent_traces` | Eval and cost |

**Not chosen:** an Interviewer agent, a candidate chat UI, matching by embedding nearest-neighbor, auto-reject on `MISSING`, storing match labels only in vector space, a self-hosted PostgreSQL instance, local SQLite as the system of record, **FastAPI on Vercel serverless**.

---

## 14. Repository layout

```text
apps/
  web/                      Next.js recruiter UI (Vercel; root directory apps/web)
    vercel.json
  api/                      FastAPI: routes, auth, enqueue, persistence (Railway)

packages/
  domain/                   Shared pydantic/TS types and enums
  agents/
    jd_parser/
    resume_parser/
    matcher/
    gap_analyst/
    interview_designer/
    transcript_parser/
    prober/
    evidence_collector/
    report/
    file_locator/           Phase 6: find stored files + action routing
    file_summarizer/        Phase 6: summarize document text on request
    graphs/                 screening.py, transcript.py, report.py
  extract/                  PDF/DOCX/VTT → text
  eval/                     Golden JD/resume/transcript fixtures

infra/
  sql/                      Supabase table migrations

render.yaml                 Render Blueprint (free API web service)
runtime.txt                 Python 3.11.9 for Render
requirements-railway.txt    Editable installs for domain, extract, agents, api
railway.toml                Optional paid API host (alternative to Render)
nixpacks.toml               Python 3.11 on Railway
```

Rules:

- UI never imports `packages/agents`.
- Agents never import FastAPI, SQLAlchemy, or the Supabase client.
- Persistence belongs to the API/orchestrator, which writes HireFlow tables in Supabase.
- `domain` is the contract both sides share (OpenAPI generated from pydantic).
- Vercel env is only `HIREFLOW_API_URL` (and Next public settings if any). Render holds `SECRET_KEY`, `CORS_ORIGINS`, `GROQ_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`.

Introduce an agent package in the phase that owns it. Do not stub all ten on day one.

---

## 15. Phase-wise delivery

Each phase ships a recruiter-usable slice and frozen artifacts for the next phase.

```text
Phase 0  Foundation
Phase 1  Parse JD + Resume
Phase 2  Match + Gap Identification          ← first recruiter-usable product
Phase 3  Personalized Interview Plan
Phase 4  Transcript ingest + Deep Probing
Phase 5  Evidence Report + Human Decision    ← full problem-statement loop
Phase 6  File assistant: find, read, summarize, parse
Phase 7  Scale: multi-candidate, comparison, ATS
```

### Phase 0 — Foundation

**Goal.** App shell so later agents can run and persist work.

**Build.** Auth (`recruiter`), jobs, candidates, file upload, raw text extraction, Supabase tables (schema may be sparse), Redis queue, `PipelineRun` + `agent_traces`, object storage.

**Runtime.** Local: `Web → API → Supabase tables / Storage / Queue`. Production: `Vercel web → Render API → Supabase / LLM`. No LLM required for Phase 0. Required env: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`. Production also: Render `SECRET_KEY` + `CORS_ORIGINS`; Vercel `HIREFLOW_API_URL`.

**Success.** Upload JD + N resumes; extracted text visible; failed uploads visible.

**Out of scope.** Matching, transcripts, reports.

### Phase 1 — Resume parsing and JD structuring

**Goal.** Unstructured documents become comparable objects.

**Agents.** JD Parser, Resume Parser.

**Success.** JD must-have `Python` exists as a requirement. `"Python — 4 years"` is a `years_claim`, not a match. Recruiter can edit requirements.

**APIs.** `parse-jd`, `parse-resume`, requirement PATCH, profile GET.

**Out of scope.** Status labels.

### Phase 2 — Requirement matching and gap identification

**Goal.** Replace keyword screening. First product-complete slice.

**Agents.** Matcher, Gap Analyst.

**UI.** Match matrix, gap list with quotes, deal-breaker / skip controls.

**Success.** Candidate A is not `MATCHED` on Python. Candidate B is `MISSING` and still probe-eligible. Every cell links to a quote or “no evidence found.”

**Out of scope.** Question generation, transcripts.

**Do not skip this phase.** Without it, interview plans become generic and reports become keyword summaries.

### Phase 3 — Personalized interview plan

**Goal.** Ranked gaps become an editable, candidate-specific plan the recruiter uses in an external interview.

**Agents.** Interview Designer.

**Success.** Two candidates on the same JD get different plans. Every question traces to a requirement. Recruiter can download the interview-brief file stored on that plan and run the interview without HireFlow in the room.

**Out of scope.** Transcript ingest.

### Phase 4 — Transcript ingest and deep probing

**Goal.** Consume a provided interview transcript. Refuse to treat vague answers as proof.

**Agents.** Transcript Parser, Prober.

**Success.** Recruiter can upload or paste a transcript. Turns are structured and mapped when possible. “I have used Python for 4 years” is `shallow`, with remaining follow-ups. Multiple transcript versions are supported.

**Out of scope.** Final report. Conducting the interview in-product.

### Phase 5 — Evidence collection, report, human decision

**Goal.** Close the loop. Resume + transcript → one report. Human decides.

**Agents.** Evidence Collector, Report.

**Success.** Recruiter can download an evidence report file that answers the north-star sentence without reconstructing raw docs. Status changes cite evidence IDs. Remaining follow-ups appear as unvalidated gaps. Decision is recorded and auditable.

This completes the problem-statement workflow.

### Phase 6 — File assistant

**Goal.** Recruiter asks HireFlow for any stored artifact in plain language — find it, download it, read it, summarize it, or parse it — without clicking through job → candidate → page.

**Agents.** File Locator (catalog + action routing), File Summarizer (on-demand summaries). Parse reuses JD Parser, Resume Parser, and Transcript Parser, or returns structured match/gap/plan/evidence data already in Supabase.

**Build.**

- Org file catalog (JD, resume, transcript, match & gaps, interview brief, evidence report).
- `POST /files/chat`, `POST /files/locate`, `GET /files/download`, `GET /files/history`.
- `file_assistant_requests` audit table (`infra/sql/009_phase6.sql`).
- `/files` **Assistant** chat page: message thread, file cards, structured parse in replies.

**Actions.**

| Recruiter says | Action | Output |
| --- | --- | --- |
| Find / list | `locate` | Matching files table |
| Download / save | `download` | Browser download when one ready hit |
| Read / show / view | `read` | Inline text excerpt |
| Summarize / overview | `summarize` | Summary + key points (Groq) |
| Parse / extract / break down | `parse` | Structured JSON |

**Success.**

1. Run `009_phase6.sql` in Supabase.
2. Sign in → **File assistant**.
3. Locate, download, read, summarize, and parse work for artifacts created in Phases 0–5.
4. Each request is logged in `file_assistant_requests` and appears in **Recent requests**.

**Out of scope.** Starting pipelines, hiring decisions, browsing files outside the org catalog.

**Deploy.** Same Railway env as other agents (`GROQ_API_KEY` for summarize/parse on raw documents). Vercel proxies `/backend` only; no extra env beyond `HIREFLOW_API_URL`.

### Phase 7 — Scale and hiring operations

**Goal.** Many candidates, one rubric.

**Build.** Batch screening, comparison board, shortlist, hiring-manager read-only views, workload views, eval harness in CI/nightly, cost routing, optional ATS ingest (including transcript attachments).

**Success.** One JD, many resumes, one matrix, independent plans, independent transcripts. Recruiter time is review + decision, not reconstruction.

### Dependencies

```text
0 → 1 → 2 → 3 → 4 → 5 → 6 → 7
```

Phase 3 may start once Phase 2 labels are stable. Phase 4 can ingest a transcript even without a plan (turns stay largely unmapped; Prober still scores JD must-haves). Phase 5 is incomplete without a Phase 4 transcript — a resume-only report is allowed as a **partial report** with interview columns empty.

---

## 16. Risks this architecture is designed to block

| Risk | Design response |
| --- | --- |
| False `MATCHED` on keyword-only resumes | Dimension table; years-only → `UNCLEAR` |
| Auto-reject `MISSING` | Probe-by-plan default; recruiter sets deal-breakers |
| Treating a weak transcript as proof | Prober `shallow` / `not_discussed`; remaining follow-ups |
| Building an in-product interviewer | No Interviewer agent; transcript is the only interview input |
| Unauditable AI | Quotes, IDs, traces, immutable downloadable report files |
| Recruiter distrust | Editable requirements, gaps, plans, turn mappings; human `Decision` |
| Embeddings as fake matching | Retrieval only |
| God-agent drift | Ten specialists, three graphs + File assistant, code orchestrator |
| Cost blow-up | Model tiers; Phase 7 shortlist before expensive graphs |
| Stale artifacts after re-upload | Document versions invalidate downstream until re-run |

---

## 17. Definition of done

HireFlow is complete for a role when a recruiter can:

1. Load a JD and many resumes.
2. See structured requirements and claims.
3. See `MATCHED` / `PARTIALLY_MATCHED` / `MISSING` / `UNCLEAR` per requirement, with quotes.
4. See which gaps are worth investigating.
5. Get and edit a personalized interview plan, download the stored interview-brief file, and use it outside HireFlow.
6. Provide an interview transcript.
7. See structured coverage, shallow-answer flags, and remaining follow-ups.
8. Open and download a Candidate Evidence Report file that merges resume and transcript evidence.
9. Record a human hiring decision.
10. Ask the File assistant for a stored file by candidate, role, or kind — and find, download, read, summarize, or parse it.

That is the architecture. Agents produce evidence from documents the recruiter already has. Recruiters hire.
