# HireFlow — Problem Statement

## Background

Hiring teams receive large numbers of resumes for every open position. While resumes provide information about a candidate's experience, skills, projects, and education, they do not always provide enough evidence to determine whether a candidate actually meets the requirements of a role.

Traditional recruitment screening is largely based on resume review and keyword matching. A candidate may mention a required skill on their resume, but the recruiter still needs to determine:

- How deeply has the candidate used that skill?
- Where and how was it applied?
- Does the candidate have practical experience or only theoretical knowledge?
- Are important job requirements missing from the resume?
- Are some skills present but not explained well enough?
- Which claims need to be validated during an interview?

This creates significant manual effort for recruiters.

## Core Problem

Recruiters lack an efficient way to move from **resume screening to evidence-based candidate validation**.

For every candidate, recruiters must manually:

1. Read and understand the resume.
2. Compare the resume against the Job Description.
3. Identify matched, partially matched, missing, and unclear requirements.
4. Determine which gaps are important enough to investigate.
5. Create candidate-specific interview questions.
6. Conduct the interview.
7. Ask follow-up questions when answers are vague.
8. Review the interview transcript.
9. Combine resume and interview evidence.
10. Prepare a final candidate assessment.

This process becomes difficult to scale when multiple candidates apply for the same role.

## Key User Pain

The recruiter does not simply need to know:

"Does this resume match the JD?"

The recruiter needs to know:

"What evidence do I have that this candidate actually meets the important requirements of the role, and what still needs to be validated?"

Existing resume screening approaches often stop at matching candidates against keywords or skills. They do not systematically investigate gaps or validate candidate claims.

## Example

Suppose a JD lists Python as a must-have skill.

Candidate A's resume says:

"Python — 4 years"

This tells the recruiter that the candidate claims Python experience, but does not necessarily prove its depth.

The recruiter still needs to understand:

- What did the candidate build using Python?
- How complex was the work?
- Was Python actually used professionally?
- What was the candidate's individual contribution?
- What measurable outcome resulted from the work?

For another candidate, Python may not appear on the resume at all. Instead of immediately rejecting the candidate, the recruiter may want to verify whether the experience exists but was simply omitted.

Therefore, the system must distinguish between:

- **MATCHED**
- **PARTIALLY MATCHED**
- **MISSING**
- **UNCLEAR**

## Proposed Product

Build **HireFlow**, an AI-powered multi-agent candidate screening and interview system.

HireFlow should transform the recruitment workflow from:

JD → Resume → Keyword Match → Recruiter Review

into:

JD  
→ Resume Parsing  
→ Requirement Matching  
→ Gap Identification  
→ Personalized Interview  
→ Deep Probing  
→ Evidence Collection  
→ Candidate Evidence Report  
→ Human Hiring Decision
