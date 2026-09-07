---
framework_version: 1.0.2
---

# Agent Guidelines: AI Job Search

This workspace is structured to manage job search activities, scraper tools, CVs, cover letters, and interview preparation.

## Thin-Pointer Design (Single Source of Truth)

To prevent duplication and configuration drift across different AI agent frameworks (Claude Code, Google Antigravity, Codex, Cursor, Gemini CLI, etc.), this workspace uses a unified thin-pointer design. All agent runtimes should load the canonical specifications and candidate profiles from the files and directories below:

1. **Personal Candidate Profile:**
   - Candidate facts, contact details, education, evidence, languages, reusable answers,
     and target preferences live only in
     [.claude/skills/job-application-assistant/01-candidate-profile.md](.claude/skills/job-application-assistant/01-candidate-profile.md).
     Behavioral evidence and voice live in `02-behavioral-profile.md`. [CLAUDE.md](CLAUDE.md)
     contains thin workflow pointers; it must not duplicate candidate facts or workflow rules.
2. **Canonical Workflow Specifications:**
   - The step-by-step instructions and triggers for tasks (setup, scrape, rank, apply, upskill, interview) are defined in the [.claude/](.claude/) directory (specifically under `.claude/skills/` and `.claude/commands/`).
   - Do not duplicate these rules or specifications. Treat `.claude/` files as the single source of truth.
3. **Portal Search Skills:**
   - Job-portal search CLIs live under [.agents/skills/](.agents/skills/) in the portable Agent Skills format (with a `SKILL.md` per portal). Codex and Antigravity discover these automatically; the `/scrape` workflow in [.claude/skills/job-scraper/](.claude/skills/job-scraper/) orchestrates them.
4. **Codex Model Routing:**
   - For named job-search workflows, model/delegation decisions, or independent
     review decisions, consult the project-local
     [.agents/skills/luna-sol-routing/SKILL.md](.agents/skills/luna-sol-routing/SKILL.md)
     for proportionate model selection and command review routing. For small local
     edits and read-only lookups that need no routing decision, keep the current
     capable owner and do not load the routing skill.
