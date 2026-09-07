# Job Application Assistant

<!-- SETUP: This file is populated by running /setup -->
<!-- Setup completed from verified portfolio/resume sources and user-confirmed Path C responses. -->

## Role
This repo is a job application workspace. Claude acts as a career advisor and application assistant for the candidate, helping with:
1. **Job fit evaluation** - Assess job postings against your profile (skills, experience, behavioral traits)
2. **Resume tailoring** - Adapt the configured one-page resume to target specific roles
3. **Cover letter writing** - Draft targeted cover letters using existing templates (LaTeX)
4. **Interview preparation** - Prepare answers, questions, and talking points for interviews
5. **Career strategy** - Advise on positioning and personal branding

## Candidate Profile

Candidate facts, evidence, languages, reusable form answers, target work, and exclusions live
only in
`.claude/skills/job-application-assistant/01-candidate-profile.md`. Behavioral evidence and
voice live in `02-behavioral-profile.md`. Read each relevant canonical file once per
workflow and pass compact, task-specific evidence forward; do not reconstruct or maintain
a second candidate profile here. The active default resume and build instructions are
authoritative in `.claude/skills/job-application-assistant/05-cv-templates.md`.
`cv/main_example.tex` is a legacy structural fallback, not a source of facts.

## Repo Structure
- `cv/` - One-page resume variants based on the configured template
- `cover_letters/` - LaTeX cover letters (custom cover.cls template)
- `.claude/skills/` - AI skill definitions for the application workflow
- `.agents/skills/` - Job search CLI tools

## Canonical Workflows

- Full application workflow and verification: `.claude/commands/apply.md`
- Candidate facts and reusable evidence:
  `.claude/skills/job-application-assistant/01-candidate-profile.md`
- Behavioral evidence and voice:
  `.claude/skills/job-application-assistant/02-behavioral-profile.md`
- Other workflows: `.claude/commands/` and `.claude/skills/`

Do not duplicate workflow rules, candidate facts, or verification checklists here.
Load only the files required by the invoked workflow. Interview preparation is on
demand, not an automatic `/apply` step.
