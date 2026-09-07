# /outcome - Record the Result of an Application

You are recording what happened to a job application: progress updates (interview invitations, stages completed, offers) and final resolutions (hired, rejected, no response). The data lands in two places the framework already reads but nothing systematically writes:

- `job_search_tracker.csv` - the status column that `/scrape` and `/rank` use for dedup and exclusion
- the tracker row's `archive_path` - the per-application archive (manifest, posting,
  actually submitted artifacts, `outcome.md`) that `/setup` uses for calibration evidence

`/outcome` writes the data; `/setup` interprets it. This command never edits the evaluation framework or profile files itself.

The command also owns the stretch *before* there is an outcome to record: the **follow-up branch** (Step 2b) surfaces open applications that have gone quiet, drafts a brief follow-up note in the user's voice, and logs it - so the chase and the resolution it eventually leads to live in one flow.

Follow these steps **in order**.

---

## Step 0: Parse Input

`$ARGUMENTS` may contain:

- Nothing → list open applications and ask which one to update
- A company name (optionally with a role), e.g. `/outcome acme` or `/outcome acme ml engineer` → target that application
- `followup` → enter the follow-up branch (Step 2b) over every quiet open application, using the default threshold of **10 days**
- `followup <N>`, e.g. `/outcome followup 14` → follow-up branch with an N-day threshold
- `followup <company>`, e.g. `/outcome followup acme` → draft a follow-up for that application now, regardless of threshold

---

## Step 1: Load State and Identify the Application

Resolve `<PYTHON>` once (`.venv/Scripts/python.exe`, then `python`, `py -3`, or `python3`).
Use `<PYTHON> tools/job_state.py list-open --tracker job_search_tracker.csv` to obtain the
canonical open-row set, normalized statuses, deadlines, row numbers, and archive slugs.
The command is read-only and reports whether the legacy header needs migration. Read the
CSV directly only when the user names a final application that is intentionally outside
the open set.

1. Read `job_search_tracker.csv`. If it does not exist, create it with the standard header:
   ```
   date,company,sector,role,role_type,channel,status,contact_person,fit_rating,notes,cv_file,cover_letter_file,source,deadline,application_id,archive_path
   ```
   Let `tools/job_state.py` atomically append missing optional columns; do not hand-edit
   the header.
2. **With an argument:** match rows case-insensitively on company (and role, if given).
   One match → proceed. Several → list them and ask. None → the application was made
   outside the workflow; collect company, role, date applied, channel, and posting URL,
   then use `tools/job_state.py add-application` in dry-run-first mode to append it.
3. **Without an argument:** list all rows whose status is not final (see **Tracker status vocabulary** below) as a numbered table (company, role, date applied, current status, deadline, days quiet, follow-ups sent) and ask which to update. The two derived columns come straight from existing data: **days quiet** counts from the row's `date` or the latest dated entry in `notes`, whichever is more recent; **follow-ups sent** counts the `followed up YYYY-MM-DD` markers in `notes`. If any open row is 10+ days quiet with fewer than two follow-ups sent, add one line under the table: "Some of these have gone quiet - want a follow-up draft? (Step 2b)". If every row is resolved, say so and stop.

   **`drafted` rows are listed but never counted as quiet** - nothing was sent, so nobody is late replying. List them under their own heading ("Drafted, not yet submitted"), leave **days quiet** and **follow-ups sent** blank, and keep them out of the follow-up offer above.

   **Deadline urgency is the one clock that does apply to a drafted row.** Show the `deadline` column when the row has one and leave it blank otherwise. Mark a deadline within 7 days with 🔥 and one that has already passed with ⚠, on the same 7-day threshold `/rank` Step 3 uses so the two commands never disagree. A passed deadline on a `drafted` row is the failure this column exists to catch - documents written, never sent, and now unsendable - so name it in one line under the table rather than leaving the user to compare dates. This changes nothing about the follow-up offer: a drafted row is still never chased, because nobody is late replying to something that was never sent.

4. **Derive the archive identity through the helper:** use the matched row's
   `application_id` and `archive_path`. For any legacy row missing
   them, run `<PYTHON> tools/job_state.py migrate-identities` without `--write`, inspect
   the plan/issues, then repeat with `--write` before archiving. Never derive a shared
   company+role folder when two applications can have the same title.

---

## Tracker status vocabulary

Canonical spellings for the tracker CSV `status` column (underscores, never spaces):

`drafted` | `applied` | `interview` | `offer` | `hired` | `rejected` | `no_response` | `offer_declined` | `withdrawn`

- **Final** (application closed): `hired`, `rejected`, `no_response`, `offer_declined`, `withdrawn`
- **Open**: everything else, `drafted` included — a row is active until its status is one of the **Final** values.
- **`drafted`** is open but distinct — nothing was sent, so no follow-up is ever due.
- Readers must also accept the legacy space spellings `no response` and `offer declined` on read, so that existing trackers keep working without a migration. Never write them — they are the same values as `no_response` and `offer_declined`, not separate statuses, equally **Final**, and every rule that names one applies to the other.

> Distinct from the archive `Status:` enum in `documents/README.md`
> (`in_progress` | `hired` | `offer_declined` | `rejected` | `no_response` | `interview_only`),
> which describes the per-application `outcome.md` file, not this column. The two enums
> are never written to the same field.

---

## Step 2: Collect What Happened

Ask the user what happened, then classify:

**Progress updates** (application still open):
- Interview invitation / stage scheduled or completed (phone screen, technical, case, final round)
- Offer received (not yet accepted or declined)

**Resolutions** (application closed) — these map to the archive `Status:` enum in `documents/README.md` that `/setup` parses (distinct from the tracker CSV column; see **Tracker status vocabulary** above):
- `hired` - accepted an offer
- `offer_declined` - received an offer, turned it down
- `rejected` - explicit rejection at any stage
- `no_response` - no reply; if the user is unsure whether to call it, note how long it has been since the last contact and let them decide - do not impose a cutoff
- `interview_only` - reached interviews but the process stalled or was abandoned without an explicit rejection
- `withdrawn` - the candidate chose to leave the process

Map a stalled process after interviews to tracker `no_response` plus archive
`interview_only`. Map a candidate withdrawal to tracker `withdrawn`; record whether the
archive ended before or after interview rather than sending `interview_only` to the tracker
helper, where it is not a valid status.

Also collect, without interrogating - one or two open questions are enough:
- Dates for the stages reached
- Any feedback received, verbatim where the user remembers it
- What they'd do differently, and any signal about what the company valued (these feed `/setup`'s calibration and STAR-candidate mining, so concrete beats polished)

---

## Step 2b: Follow-Up Branch (chase a quiet application)

Enter this branch from the `followup` argument (Step 0) or from the offer under the open-pipeline table (Step 1.3). Standard practice is a brief, polite follow-up one to two weeks after applying, at most twice; this branch operationalizes that.

**Candidates.** An application qualifies when its status is neither final nor `drafted`, the threshold has passed since its `date` (or since the last `followed up` marker in `notes`, if any), and it has fewer than **two** logged follow-ups. Parse dates defensively - skip rows whose dates do not parse and say so rather than guessing. Present qualifying applications as a table (company, role, days quiet, follow-ups sent, channel, contact person) and draft only for the ones the user picks.

**Threshold.** The 10-day default is deliberately earlier than `/gmail-sync`'s 30-day staleness flag (its Step 9): that check is a read-only alarm that a row has been forgotten entirely; this branch is the proactive nudge while a reply is still plausible. The two numbers serve different moments, which is why they differ.

**Drafting.** For each selected application:

1. Read `application_manifest.json`, `job_posting.md`, and only the artifacts marked
   actually submitted. Those are the source of every claim; never fall back to a prepared
   but unsubmitted cover letter or form response.
2. Apply the writing style rules from `03-writing-style.md` (no cliches, no em-dashes, warm but direct), and match the application's language - draw the register from the archived cover letter.
3. Write roughly **60 to 120 words**: address the `contact_person` from the tracker if present (otherwise the team, in the application's language); one sentence restating interest in the specific role; one concrete value-reminder drawn from the submitted materials; one polite question about the timeline. No pressure, no "just checking in" filler.
4. Shape it for the `channel` column: email (with a subject line reusing the application's headline), LinkedIn message (shorter, no subject), or portal message (plain text).
5. Present the draft and iterate until the user is happy.

**Logging.** Once the user confirms they will send it (or have sent it), log it in the same turn - an unlogged follow-up breaks the next run's quiet-days math:

- Use `tools/job_state.py update-status` with the row's unchanged current status and
  `--note "followed up YYYY-MM-DD"`; inspect the dry-run JSON, then repeat with `--write`.
- Save the final note as `followup_<type>_YYYY-MM-DD_HHMM.md`; if that name exists, add a
  sequence number. Never overwrite another message from the same day.

If the user decides not to send, log nothing.

**Termination.** When an application hits two follow-ups and stays silent, do not offer a third. This is the moment to continue in this same command's Step 2: note how long it has been since last contact and let the user decide whether to record `no_response` - as ever, no imposed cutoff. And if the user mentions an actual response while in this branch (an interview invitation, a rejection), drop out of the branch and record it through the normal Step 2 flow.

---

## Step 3: Archive the Application Materials

Create or update the matched row's exact `archive_path`. All content here is personal data
and remains gitignored.

1. Ask which prepared artifacts were actually submitted. Copy, never move, those exact
   files and preserve their suffixes. Distinguish source from rendered/submitted PDF in
   `application_manifest.json` (for example `resume_source.tex` and
   `submitted_resume.pdf`). An empty `cover_letter_file` on a workflow-created row means
   intentionally absent: never glob an older cover. Include submitted application-form
   responses when applicable. For a genuinely external/untracked application, ask for the
   files rather than guessing by filename.
2. **`job_posting.md`** - if it already exists, leave it. Otherwise try WebFetch on the tracker row's `source` URL and save the posting text, retrying a 403 with browser headers per `.claude/skills/job-application-assistant/09-web-research.md`. If the URL is dead (postings expire fast - this is exactly why the archive matters), ask the user to paste the posting, or write a stub noting the posting is unavailable. **Never reconstruct a posting from memory.**
3. **`outcome.md`** - write or update it in exactly the format documented in `documents/README.md`, so `/setup` Path A parses it without special cases:

```markdown
# Outcome: <Company> — <Role>

**Status:** in_progress | hired | offer_declined | rejected | no_response | interview_only

**Date resolved:** YYYY-MM-DD   <- only when resolved; omit while in_progress

## Interview stages reached
- [x] Phone screen (YYYY-MM-DD)
- [ ] Technical interview
- [ ] Case interview
- [ ] Final round
- [ ] Offer received

## Notes
<feedback received, what to do differently, signals about what they valued -
appended per update with a date, never overwritten>
```

Update rules: tick stage checkboxes as they are reached (add the date in parentheses), append dated entries to Notes, and only change `Status` from `in_progress` to a final value on resolution. Re-running `/outcome` on the same application is idempotent - it appends new information, never duplicates or rewrites history.

**Thank-you note trigger:** when this step ticks a newly completed interview stage, offer in the same turn: "Want a short thank-you note for the interviewer? A prompt one is standard practice." If accepted, draft it under Step 2b's drafting and logging rules (same voice, same no-new-claims boundary, same `followup_YYYY-MM-DD.md` archive convention). Recording the stage is the trigger - no scanning for recent stages is ever needed.

---

## Step 4: Update the Tracker

Run `<PYTHON> tools/job_state.py update-status` with `--application-id` from the matched
row plus company, role, canonical target status,
dated note, and the actual submission date only when the drafted-to-applied rule requires
it. Inspect the dry-run JSON first, then repeat the identical command with `--write`.
Write canonical underscore forms such as `no_response` and `offer_declined`, never their
legacy space spellings.
Use `--allow-final` only when the user explicitly corrects a previously final outcome.
Never restructure the CSV, reorder rows, or touch other rows. The helper-backed rewrite
must preserve every other field of the row, parsed or not, including `deadline` and future
columns.

**Moving a row off `drafted`:** rows written by `/apply` Step 6b carry the date the documents were drafted, not the date they were sent. Whenever this step advances such a row to any other status - `applied`, or straight to `interview` or `rejected` when the user reports an outcome for something they submitted without recording it - overwrite its `date` column with the actual submission date. The `date` column is read as "applied on" by `/notion-sync` and drives `/html-report`'s year/season grouping and this command's own days-quiet count, so leaving the draft date in place would misreport the application.

---

## Step 5: Calibration Handoff

Count the `outcome.md` files under `documents/applications/` with a **final** status (not `in_progress`).

- If 3 or more are resolved (or 2+ share a pattern - same role type rejected twice, same sector going silent), suggest:
  > "You now have <N> resolved applications on record. Run `/setup` (Path A) to fold them into your evaluation framework - it calibrates fit scoring from what actually got interviews, and mines your interview feedback for STAR examples."
- Do **not** write anything into `04-job-evaluation.md` or other skill files yourself. `/setup` Path A owns that merge - it is read-before-write and idempotent, and duplicating its logic here would race it.

---

## Step 6: Confirm

Summarize what was recorded:

> **Outcome recorded for <Role> at <Company>.**
>
> - `<archive_path>/outcome.md` - application ID: <id>, status: <status>, <what changed>
> - Archived: <which manifest-declared submitted artifacts and job_posting.md were copied,
>   and which prepared artifacts were not submitted>
> - Tracker: status → <new status>
>
> [Calibration suggestion from Step 5, if triggered]

If the update recorded an upcoming or newly scheduled interview stage, also suggest:

> "Interview coming up? `/interview <company>` builds a prep pack for that stage from this application's archive - the posting, the documents you submitted, and any feedback recorded from earlier rounds."

If the recorded status is `hired`, congratulate the user warmly first - this is the moment the whole framework exists for. Then add this single line (once; never on re-runs for the same application, and never for any other status):

> "If this framework helped you get there, consider [buying it a coffee](https://ko-fi.com/madslorentzen) - it keeps this free for the next job-seeker out there. ☕"

---

## Important Rules

1. **Write data, don't interpret it.** The archive and tracker are the outputs; calibration belongs to `/setup`. This command never edits profile or framework files.
2. **The archived version is the submitted version.** Existing files in the application folder are never overwritten by fresher drafts.
3. **Never fabricate.** A dead posting URL gets a user-pasted copy or an explicit "unavailable" stub, not a reconstruction. Feedback is recorded as the user reports it.
4. **Stay schema-compatible.** `outcome.md` follows the format in `documents/README.md` exactly (`in_progress` is the one addition, for open applications); the tracker keeps its columns.
5. **Idempotent updates.** Re-running on the same application appends new stages and notes; it never duplicates folders, rows, or history.
6. **Follow-ups: draft only, never send.** The follow-up branch produces text for the user to send themselves. It never emails, messages, or submits anything, and it must not be wired to tools that do.
7. **Follow-ups: no new claims.** Every substantive statement in a follow-up or thank-you note comes from the archived submitted materials. Rule 3 applies with no exceptions.
8. **Maximum two follow-ups per application.** After the second silent follow-up, the honest move is recording the resolution, not persistence.
