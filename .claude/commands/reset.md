# /reset - Reset Candidate Profile Data

You are resetting parts of the job search framework back to a blank state so the user can start fresh with `/setup`.

**This command is destructive.** Nothing is deleted until the user explicitly confirms. Follow these steps exactly in order.

---

## Step 0: Parse Scope from Arguments

Check `$ARGUMENTS` for a scope keyword:

- `profile` — clears candidate profile data from skill files only
- `documents` — deletes user-provided files from the `documents/` folder only
- `all` — both of the above

If `$ARGUMENTS` is empty or does not contain a recognized scope keyword, ask:

> **What would you like to reset?**
>
> - **`profile`** — Clears the canonical candidate profile, behavioral profile, and personalized search queries. Candidate-neutral methods, templates, scoring rules, and writing guidance are preserved. Use this to re-run `/setup` from scratch.
>
> - **`documents`** — Deletes all files you've placed in the `documents/` folder (CV PDFs, LinkedIn export, diplomas, references, pasted job postings, past applications). The folder structure and `README.md` are preserved.
>
> - **`all`** — Both of the above.
>
> Reply with `profile`, `documents`, or `all`.

Wait for the user's response before continuing.

---

## Step 1: Show Exactly What Will Be Cleared

Before doing anything, show the user precisely what will be wiped.

### If scope includes `profile`:

Read the current state of these files and report whether each has content or is already empty:

- `.claude/skills/job-application-assistant/01-candidate-profile.md`
- `.claude/skills/job-application-assistant/02-behavioral-profile.md`
- `.claude/skills/job-scraper/search-queries.md` *(role titles, domain keywords, and location terms only — query structure is preserved)*

This list must stay in step with what `/setup` Step 3 populates: every skill file it writes candidate data into is cleared here.

Present as:

```
## Profile reset will clear:

- 01-candidate-profile.md — [has content / already empty]
  Full file will be replaced with a blank template.

- 02-behavioral-profile.md — [has content / already empty]
  Full file will be replaced with a blank template.

- 04-job-evaluation.md, 05-cv-templates.md, 06-cover-letter-templates.md, and
  07-interview-prep.md are candidate-neutral method/template files and are not reset.
  Candidate facts, calibration, and reusable content live only in 01; behavioral
  evidence and voice live only in 02.

- job-scraper/search-queries.md — [has personalized queries / already blank]
  Your job boards, role titles, domain keywords, city, and commute tiers will be
  restored to placeholders. The query structure and filter sections are preserved.

The following files are NOT touched (they contain framework rules, not candidate data):
  - 03-writing-style.md

Outside the profile scope, `cv/main_example.tex` may still hold personal data.
`CLAUDE.md` is a thin workflow pointer and does not duplicate the profile.
```

### If scope includes `documents`:

Use Glob to list all files present in `documents/cv/`, `documents/linkedin/`, `documents/diplomas/`, `documents/references/`, `documents/postings/`, and `documents/applications/`. Present as:

```
## Documents reset will delete:

documents/cv/
  - [filename] or "(empty)"

documents/linkedin/
  - [filename] or "(empty)"

documents/diplomas/
  - [filename] or "(empty)"

documents/references/
  - [filename] or "(empty)"

documents/postings/
  - [filename] or "(empty)"

documents/applications/
  - [subfolder/filename] or "(empty)"

documents/README.md — NOT deleted (instructions file)
```

If all document subfolders are already empty, state "All document subfolders are already empty — nothing to delete." and skip the confirmation step for this scope.

---

## Step 2: Require Explicit Confirmation

Present the confirmation prompt:

> **This cannot be undone.**
>
> Type **`RESET`** (all caps) to confirm, or anything else to cancel.

Wait for the user's response.

- If the user types exactly `RESET`: proceed to Step 3.
- If the user types anything else: abort and tell them "Reset cancelled. Nothing was changed."

---

## Step 3: Execute the Reset

### Profile reset

**For `01-candidate-profile.md`**, preserve its existing YAML frontmatter (including
`framework_version`) and replace only the Markdown body with:

```markdown
# Candidate Profile

<!-- Run /setup to populate this file -->

## Identity

## Education

## Professional Experience

## Independent Projects

## Technical Skills

## Publications

## Awards

## References
```

**For `02-behavioral-profile.md`**, preserve its existing YAML frontmatter (including
`framework_version`) and replace only the Markdown body with:

```markdown
# Behavioral Profile

<!-- Run /setup to populate this file -->

## Overview

## Strongest Behavioral Traits

## How I Work Best

## Growth Areas

## Mapping to Job Posting Language

## Management Style Preferences

## Using This in Applications
```

Do not edit `04-job-evaluation.md`, `05-cv-templates.md`,
`06-cover-letter-templates.md`, or `07-interview-prep.md` during reset. They contain
candidate-neutral method/template rules only. Clearing 01 and 02 removes the personal
evidence and reusable content those files consume at runtime.

**For `.claude/skills/job-scraper/search-queries.md`**, restore the values `/setup` Step 3.9 personalized back to their placeholder tokens:

- **Search Sites**: the board names back to `[YOUR_JOB_BOARD]`, `[YOUR_INDUSTRY_JOB_BOARD]`, `[YOUR_ADDITIONAL_JOB_BOARD]`, and the LinkedIn filter back to `[YOUR_COUNTRY]` / `[YOUR_CITY]`.
- **Query Categories**: the four priority headings back to `[YOUR_PRIMARY_ROLE_TYPE]`, `[YOUR_DOMAIN_EXPERTISE]`, `[YOUR_ADJACENT_ROLE_TYPE]`, and `Broader Technical / Consulting`; inside the query blocks, the titles, skills, and domain terms back to `[YOUR_PRIMARY_JOB_TITLE_1]`, `[YOUR_PRIMARY_JOB_TITLE_2]`, `[YOUR_ADJACENT_TITLE_1]`, `[YOUR_ADJACENT_TITLE_2]`, `[YOUR_KEY_SKILL]`, `[YOUR_DOMAIN_KEYWORD_1]`, `[YOUR_DOMAIN_KEYWORD_2]`, `[YOUR_DOMAIN]`, and the location terms back to `[YOUR_CITY]`, `[YOUR_COUNTRY]`, `[YOUR_REGION]`.
- **Location Filter**: the commute tiers back to `[YOUR_CITY]`, `[ACCEPTABLE_AREA_1]`, `[ACCEPTABLE_AREA_2]`, `[BORDERLINE_AREA]`, `[TOO_FAR_AREA]`.
- Remove any extra priority categories or translated query duplicates `/setup` added beyond the four shipped tiers.

Leave the rest of the file intact: the portal-CLI and WebSearch-fallback explanation, the Language scope note, the "organize by function, not job title" guidance, and the Language, Date, and Adapting Queries sections.

### Documents reset

For each non-empty document subfolder listed in Step 1, resolve and display every target
before acting. Verify each resolved path remains inside its specifically named
`documents/` subfolder. Delete only the enumerated contents using the runtime's safe
native file operation. Do not delete the subfolders themselves or
`documents/README.md`, and never run a recursive deletion against the workspace root,
an unresolved environment variable, or an unverified wildcard.

The authorized content roots are `documents/cv/`, `documents/linkedin/`,
`documents/diplomas/`, `documents/references/`, `documents/postings/`, and
`documents/applications/`. Recursive removal is allowed only for already enumerated
application-archive children whose resolved paths passed the containment check.

---

## Step 4: Confirm What Was Done and Next Steps

After the reset is complete, report:

```
## Reset complete

### Cleared
[List each file/folder that was actually modified or cleared]

### Unchanged
[List anything that was already empty or was intentionally preserved]
```

Then tell the user what to do next based on what was reset:

**If profile was reset:**
> The skill files are now blank. Run `/setup` to repopulate them. The command auto-detects any files in your `documents/` folder and offers to read from there; otherwise it walks you through a CV import or interactive interview.
>
> Note that `cv/main_example.tex` is outside the `profile` scope and may still hold your
> personal data. `CLAUDE.md` contains only workflow rules and a pointer.

**If documents were reset:**
> The `documents/` folder is now empty. Add your career documents and run `/setup` to populate your profile. See `documents/README.md` for instructions on what to put where.

**If both were reset:**
> Both your profile files and documents folder are now empty. Add documents to `documents/` (or skip and use the CV import / interview path), then run `/setup`.
