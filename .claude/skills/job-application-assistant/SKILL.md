---
name: job-application-assistant
description: >
  Use for evaluating a specific posting, preparing application artifacts, answering
  application-form questions, interview preparation, or profile-grounded career
  strategy. Do not use for discovering live jobs; route general discovery to `scrape`.
allowed-tools: Read, Glob, Grep, WebFetch, WebSearch, Bash, Edit, Write, AskUserQuestion
framework_version: 1.4.1
---

# Job Application Assistant

---

## Workflow

When the user provides a job posting (URL or text) and asks to apply, or selects a job
from `/scrape` or `/rank`, execute `.claude/commands/apply.md` **end to end**. That command
is the single canonical full-application pipeline: availability and eligibility checks,
company research, final scoring, CV/optional cover drafting, reviewer feedback, revision,
PDF and ATS verification, optional form-field offer, tracker update, and posting archive.

Do not recreate an abbreviated application workflow here. In particular, the normal
`/scrape -> selection -> /apply` route must not bypass the reviewer, compiled-PDF visual
inspection, ATS text extraction, factual verification, or application-state recording.

When routing a selected scraped job, pass its `seen_jobs.json` key, authoritative URL,
triage result, and snapshot metadata as prior context. `/apply` decides whether the local
snapshot can be reused and always performs the authoritative final gates and evaluation.

Interview preparation is on demand or when an interview is scheduled; it is not an
automatic continuation of drafting an application.

---

## Reference Files

| File | Purpose |
|------|---------|
| `01-candidate-profile.md` | Education, experience, skills, publications, awards |
| `02-behavioral-profile.md` | Behavioral assessment, strengths, ideal environments |
| `03-writing-style.md` | Tone, structure, do's and don'ts |
| `04-job-evaluation.md` | Scoring framework for job fit |
| `05-cv-templates.md` | Active CV toolchain, structure, and tailoring rules |
| `06-cover-letter-templates.md` | LaTeX cover letter structure and tailoring rules |
| `07-interview-prep.md` | STAR examples, tough questions, roleplay guidelines |
| `08-application-forms.md` | Portal free-text fields: self-introduction, project entries, character-limited pitches |
| `09-web-research.md` | Fetching postings and company pages: trust boundary, the WebFetch 403 fallback, escalation order, claim verification |
| `10-application-verification.md` | Final factual, targeting, PDF, text-layer, and ATS verification checklist |

---

## Quick Commands

The user may also ask for individual steps without the full workflow:
- "Evaluate this job posting" - run `/apply --evaluate-only`; never write state or files
- "Write a CV for [company]" - use `/apply --no-cover-letter`
- "Write a cover letter for [role] at [company]" - use `/apply --cover-letter`
- "Help me prepare for an interview at [company]" - follow `07-interview-prep.md`
- "What jobs should I look for?" - Career strategy discussion using profile + evaluation framework
