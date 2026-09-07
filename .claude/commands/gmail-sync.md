# /gmail-sync - Sync Application Status from Authorized Gmail Sources

Scan the authorized Gmail sources configured for this workspace for status signals on
tracked job applications: interview invites, assessment links, offers, and rejections.
The primary source is the connected Gmail account. A secondary Gmail/Workspace mailbox
is optional and comes only from the local candidate profile. For every detected change,
wait for approval before writing unless the profile records explicit standing
authorization for the narrow automatic-rejection rule in Step 5.

Unlike `/outcome` (which asks the user what happened), `/gmail-sync` classifies real emails
on its own. Automatic rejection recording is disabled by default. It becomes available
only when `01-candidate-profile.md` says `Automatic rejection recording: explicitly authorized`,
a value that may be set only after the user grants standing authorization.
Every other classified change is presented as a batch before it touches
`job_search_tracker.csv` or the matched row's exact `archive_path/outcome.md`. Because a
wrong write silently corrupts application history, every automatic or proposed change
must cite its source email and every uncertain case must be surfaced instead of guessed.

Follow these steps **in order**.

---

## Step 0: Prerequisites

1. Read only the **Mail Sync Preferences** block in `01-candidate-profile.md`. Set
   `<SECONDARY_EMAIL>` only when it contains a real address rather than a placeholder or
   `none`; otherwise skip every secondary-source step. Set `<AUTO_REJECTION>` true only
   for the exact explicitly-authorized value above; missing, placeholder, or ambiguous
   values mean false.
2. Confirm the Gmail connector tools are available for the primary account. If not, mark
   **Primary Gmail: unavailable** for this run; do not attempt it through Bash, IMAP, or
   another channel.
3. When `<SECONDARY_EMAIL>` is set, confirm browser control is available for the Codex internal browser.
   Open `https://mail.google.com/mail/`, use the visible Google account
   switcher, and select that already-saved account. Do not assume a fixed `/u/0/` or `/u/1/`
   slot: verify the visible account identity names `<SECONDARY_EMAIL>` before reading mail.
   Never inspect cookies, browser storage, saved-password stores, or the credential value
   itself. If control is unavailable, the account is absent, or authentication is required,
   mark **Secondary Gmail: unavailable** and tell the user what must be connected or signed
   in; do not enter, extract, reset, or expose credentials.
4. Continue with whichever configured source is available, but never describe a partial run as complete coverage.
   If no configured source is available, report the blockers and
   stop without changing sync state.

---

## Step 1: Parse Input

`$ARGUMENTS` may contain:

- Nothing → default lookback (see Step 3)
- A company name, e.g. `/gmail-sync acme` → scope the search to that one tracked application
- `since <YYYY-MM-DD>` → override the lookback start date for this run only (does not change the persisted state file)

---

## Step 2: Load State

Resolve `<PYTHON>` once (`.venv/Scripts/python.exe`, then `python`, `py -3`, or `python3`).
Run `<PYTHON> tools/job_state.py list-open --tracker job_search_tracker.csv` once and use its
normalized open rows and archive slugs throughout the run. This removes repeated status
and path parsing while keeping the tracker read-only until a rejection qualifies for the
automatic-write rule or the user approves another status change.

1. Read `job_search_tracker.csv`. If it does not exist, tell the user there is nothing to sync against yet (suggest `/outcome` or `/apply` first) and stop. Do not create it here - `/gmail-sync` never originates new applications, only updates existing ones.
2. Read `gmail_sync/state.json` (create if missing: `{"last_sync": null, "last_secondary_sync": null, "processed_message_ids": [], "processed_secondary_message_keys": []}`). Treat missing secondary fields as `null` and `[]`; this is an additive migration, not a reset. If legacy `last_njit_sync` or `processed_njit_message_keys` fields exist, migrate their values to the generic secondary fields without discarding history.
3. Build the set of **open applications**: tracker rows whose `status` is not **Final**
   (per `/outcome`'s **Tracker status vocabulary**). Use each row's `application_id` and `archive_path`; legacy rows are
   migration proposals, not a reason to derive a shared company+role folder. Reuse that
   exact path for any verified write in Step 7a.

   **`drafted` rows stay in this set, and are the reason it is worth searching.** `/apply` writes them but never submits; the user submits by hand and may not think to run `/outcome`. A reply arriving against a row still marked `drafted` is exactly that case, and the row holds the company name the search needs.
4. If `$ARGUMENTS` named a company, filter this set to the matching row(s) (case-insensitive). No match → tell the user and stop, do not guess.

---

## Step 3: Search Configured Mailboxes

Primary Gmail lookback: `since <date>` if given, else `state.last_sync` if set, else
`newer_than:30d`. Secondary Gmail lookback: `since <date>` if given, else
`state.last_secondary_sync` if set, else `newer_than:30d`. Keep the cursors independent so
an unavailable source catches up on its next successful run.

### Primary Gmail connector search

1. Call `list_labels` and look for a user label whose name suggests job-search email (e.g. contains "job", "application", "career" case-insensitively). Note its `id` if found.
2. Normalize each open application's company name for matching later (lowercase; strip `inc`, `inc.`, `llc`, `ltd`, `a/s`, `corp`, `corporation`, `group`; strip punctuation; collapse whitespace).
3. Build a Gmail query combining (with `OR` groups via `{}`):
   - `label:<id>` if a job-search label was found
   - A quoted-name OR-group of the open applications' company names, e.g. `{"Acme Corp" "BigCo"}`
   - A sender-domain OR-group of common ATS platforms: `{from:greenhouse.io from:lever.co from:myworkday.com from:ashbyhq.com from:smartrecruiters.com from:icims.com from:bamboohr.com}`
   - The lookback bound, e.g. `newer_than:30d` or `after:2026/06/15`
   - `-in:sent -in:drafts` (status signals come from what employers send you, not what you sent them; the negative operators keep **archived** mail and label-filtered mail in scope - restricting to the Inbox instead would silently drop both, including exactly the mail matched by the job-search label from step 1, since the standard filter that applies such a label also archives it)

Example: `newer_than:30d -in:sent -in:drafts ({"Acme Corp" "BigCo"} OR {from:greenhouse.io from:lever.co from:myworkday.com from:ashbyhq.com})`

4. Call `search_threads` with `view: THREAD_VIEW_MINIMAL`, `pageSize: 50`, paginating via `pageToken` until exhausted or results are clearly outside the relevant window.

### Optional secondary Gmail browser search

5. When `<SECONDARY_EMAIL>` is configured, use its verified Codex internal-browser tab and the visible Gmail search box. Build the same broad company-name and ATS-domain search used for primary Gmail, with the secondary lookback bound and `-in:sent -in:drafts`. A browser-visible job-search label may be included by display name, but never invent a label or reuse an account-specific label ID from primary Gmail.
6. Review the visible results through the mailbox UI. Open each candidate conversation and expand/read the full relevant message body before classifying it; a list-row preview or snippet is not sufficient. Keep the mailbox read-only: do not mark read/unread intentionally, label, archive, delete, reply, forward, or send.
7. For each secondary message, build a deterministic source key for local deduplication. Prefer a stable browser-visible message or thread URL plus the exact message timestamp. If no stable URL is exposed, use `secondary:` followed by the normalized sender, subject, and exact received timestamp. Never use cookies, session tokens, or credentials as a key.

---

## Step 4: Filter to New Mail

For each returned thread, inspect its messages' IDs against `state.processed_message_ids`. Skip a thread entirely if every message in it is already processed. For threads with unprocessed messages, call `get_thread` with `messageFormat: FULL_CONTENT` to get full bodies - **classification in Step 5 must never be based on the snippet/subject alone**, since snippets truncate the exact phrase that distinguishes "we'd like to schedule a call" from "thanks for applying."

For secondary Gmail, compare each deterministic source key from Step 3.7 against
`state.processed_secondary_message_keys`. Skip keys already recorded. Full-body
classification still applies: open and read the message through the browser before Step 5.

---

## Step 5: Classify Each Unprocessed Message

For each new message, first try to match it to one open application: compare the normalized sender domain / display name / subject / body against the normalized company names from Step 3. No confident match (company genuinely absent, or ambiguous between two tracked companies) → do not propose a write; record it in the Step 6 summary as "unmatched" and move to the next message.

For a matched message, classify by content (require the signal phrase in the subject or the first few lines - a company name appearing only deep in a forwarded thread or newsletter footer is not a signal):

| Signal | Example phrasing | Tracker `status` | `outcome.md` action |
|---|---|---|---|
| Application ack | "we've received your application" | `drafted` -> `applied`, otherwise *(no change)* | On a `drafted` row this is the one email that proves the user submitted by hand, and it arrives within a day of them doing so - propose the move with `date` set to the email's date. On any other status it is noise. |
| OA / assessment | "online assessment", "coding challenge", "complete your assessment", HackerRank/Codility links | `interview` | Tick nearest matching stage checkbox (or add a Notes line if no checkbox fits - assessments aren't always a listed stage) |
| Interview invite/scheduled | "schedule a call", "phone screen", "technical interview", "next round", "onsite", "final round" | `interview` | Tick the matching stage checkbox with the email's date |
| Offer extended | "pleased to offer", "extend an offer", "offer letter" | `offer` | Tick "Offer received" checkbox. **Never propose `hired` or `offer_declined` from an email** - accepting or declining is the user's decision, not something to infer. Flag prominently in the Step 6 summary as needing the user's decision, separate from the plain approve/skip table. |
| Rejection | "moving forward with other candidates", "not selected", "unable to proceed", "decided not to continue" | `rejected` | Set `Status: rejected`, `Date resolved:` to the email's date. Apply automatically only when all safeguards below pass. |

**Conflict rule:** if the classified signal contradicts the application's current final-ness (e.g. a "moving forward" email arrives for a company whose tracker row briefly shows a `rejected`-adjacent recent write already, or a rejection arrives after an offer was already proposed this run) - do not propose overwriting it. Record it as a conflict in Step 6 for manual `/outcome` resolution instead.

### Conditional automatic rejection authorization

Write a rejection without additional approval only when `<AUTO_REJECTION>` is true and
all of these are true:

1. The full email body contains an explicit rejection or closure statement; a subject, snippet, portal newsletter, expired posting, or generic application-status link is not enough.
2. The sender, company, role, and requisition evidence identify exactly one open tracker row. If the company has multiple open applications, the role or requisition must disambiguate the target.
3. The tracker row is not already final, and the message does not conflict with an offer, interview, or other stronger or more recent signal.

If authorization is disabled or any safeguard fails, write nothing and place the change
under **Proposed Changes** or **Needs Manual Review**, as applicable. Any standing
authorization covers only the tracker and its application archive; all mailboxes remain read-only.

---

## Step 6: Write Confirmed Rejections and Present Remaining Updates

Partition the classified changes before presenting the summary:

1. **Automatic rejections:** only when `<AUTO_REJECTION>` is true, execute Step 7a for each rejection that passes every Step 5 safeguard and record it under **Automatically Written Rejections**. Otherwise put the rejection in **Proposed Changes**.
2. **Approval-required changes:** keep application acknowledgements, assessments, interview updates, and offers read-only until the user approves them. Put these under **Proposed Changes**.

Present one combined summary so the user can see both what was written automatically and what still needs a decision:

```
## Mail Sync - Results and Proposed Updates - YYYY-MM-DD

Primary Gmail: <scanned N threads / unavailable>. Secondary Gmail (`<SECONDARY_EMAIL>`): <scanned N conversations / not configured / unavailable>. State the lookback used for each available source.

### Automatically Written Rejections
| Company | Role | Previous -> Written Status | Source Account and Email (date) |
|---|---|---|---|
| ... | ... | applied -> rejected | "Subject line" (2026-07-09) |

### Proposed Changes Requiring Approval (reply "approve all", or list which to skip, e.g. "skip 2")
| # | Company | Role | Signal | Current -> Proposed Status | Source Account and Email (date) |
|---|---|---|---|---|---|
| 1 | ... | ... | Interview invite | applied -> interview | "Subject line" (2026-07-10) |
| 2 | ... | ... | Offer extended | interview -> offer | "Subject line" (2026-07-12) |
| 3 | ... | ... | Application ack | drafted -> applied, date -> 2026-07-02 | "Subject line" (2026-07-02) |

A proposed acknowledgement leaving `drafted` shows its date change in the status cell, as row 3 does: that row was never recorded as submitted, so Step 7a is about to replace the drafting date. Say that the date is taken from the email and ask whether the user knows the real submission date.

If an automatic rejection closes a `drafted` row, write the authorized rejection but do
not replace the row's date with an inferred submission date. Record the email date in the
source-qualified note as an unverified upper bound and invite the user to correct the date.

### Needs Manual Review (conflicting signal - not written, use /outcome)
- **<Company>** - <what conflicted and why it wasn't written>

### Unmatched Emails (no change written)
- "<subject>" from <sender> - looked job-related but couldn't be confidently linked to a tracked application.

### Stale Applications (30+ days, no activity)
- **<Company>** - last activity YYYY-MM-DD, still `<status>`.
```

If the approval-required Proposed Changes table is empty, skip Step 7 and continue to Step 8 - automatic rejections have already been written and there is nothing else to approve. Offers still land in the approval-required table (the tracker moves to `offer`); it is only `hired`/`offer_declined` that are never proposed.

---

## Step 7: Wait for Approval for Non-Rejection Changes

Enter this step only when the approval-required Proposed Changes table contains at least one row. Automatic rejections have already been written under the standing authorization and are not part of this approval decision. Do not write any remaining proposed change before an explicit response arrives.

- "approve all" / "yes" / equivalent → every row in the Proposed Changes table proceeds to Step 7a.
- A partial response, e.g. "approve 1, skip 2" or "just the interview one" → only the specified rows proceed.
- "no" / decline / no changes wanted → no proposed rows proceed; go straight to Step 8 (Update State).

Approving the remaining batch in one reply is expected UX - the requirement is that the reply happens before any non-rejection write, not that the user approves row by row.

### Step 7a: Write Approved Updates

Run this step for every automatically authorized rejection and every non-rejection row the user approved:

1. **Tracker (`job_search_tracker.csv`):** update the matched row's `status` column per the Step 5 table, and append to `notes`: `<date> gmail-sync [primary Gmail|secondary <SECONDARY_EMAIL>]: <signal> ("<email subject>")`. Never restructure the CSV, reorder rows, or touch unrelated rows - same rule `/outcome` follows. The rewrite touches only `status`, `notes` (and `date` for an approved drafted-row acknowledgement): preserve every other field of the row, parsed or not, so the `deadline` column written by `/apply` Step 6b - or any column added in the future - is never blanked by a status sync.

   Execute that mutation through `<PYTHON> tools/job_state.py update-status`: first inspect
   the dry-run JSON, then repeat the identical command with `--write` only for an
   automatically authorized rejection or an approved non-rejection row. Pass
   `--date <email-date>` only for a drafted-row acknowledgement whose date change the
   user approved. Never use
   `--allow-final`; conflicting final rows remain manual-review cases.

   **If an approved acknowledgement matched a row still marked `drafted`,** set `date`
   to the email's date after the Step 6 disclosure. For an automatically authorized
   rejection on a drafted row, keep the existing date and put the email-date upper bound
   only in the source-qualified note; changing that inferred date requires approval.
2. **`outcome.md`:** tick the relevant stage checkbox (adding the date in parentheses) or update `Status`/`Date resolved` per the table. Append a dated entry to `## Notes`, never overwrite existing Notes history:
   ```
   YYYY-MM-DD (via /gmail-sync): <one-line summary of what the email said>. Source: <primary Gmail|secondary <SECONDARY_EMAIL>>, "<subject>" from <sender>, <email date>.
   ```
3. If no archive folder/`outcome.md` exists yet for a matched application, create the folder and a minimal `outcome.md` following the exact format in `documents/README.md`, same as `/outcome` would. This is the normal case for a row that was still `drafted`: `/apply` Step 6b writes the tracker row and only `/outcome` Step 3 ever creates the archive, so the folder legitimately does not exist yet. It is also the case for a row added by hand.

Approval-required rows the user skipped are left untouched - no tracker write, no `outcome.md` write - but their Gmail message IDs or secondary source keys are still marked processed in Step 8, so the same email isn't re-proposed every run.

---

## Step 8: Update State

For each source that was successfully scanned:

- Add every primary Gmail message ID processed this run - approved, skipped, unmatched, or filtered as noise - to `processed_message_ids`, and set `last_sync` to today's date.
- Add every secondary Gmail source key processed this run to `processed_secondary_message_keys`, and set `last_secondary_sync` to today's date.

Do not advance a source's cursor when that source was unavailable or its search did not complete. This makes re-running idempotent without hiding mail missed during a browser, login, connector, or Duo failure.

---

## Step 9: Staleness Check

For open applications with **no** matching activity found this run, check the tracker's `date` column and the most recent dated Notes entry in their `outcome.md`. If the most recent of those is 30+ days old, flag the application as "needs follow-up" in the closing summary below. This is surfaced only - never write anything for staleness.

**Skip `drafted` rows here** - nothing was sent, so no one is late replying.

---

## Step 10: Present Closing Summary

Confirm what actually happened, distinct from the Step 6 proposal:

```
## Mail Sync - Done - YYYY-MM-DD

### Source Coverage
- Primary Gmail: <completed / unavailable, reason>
- Secondary Gmail (`<SECONDARY_EMAIL>`): <completed / not configured / unavailable, reason>

### Written
| Company | Role | Signal | Tracker Status | Source Email |
|---|---|---|---|---|
| ... | ... | Interview invite | applied -> interview | "Subject line", 2026-07-10 |

### Skipped (not written)
- **<Company>** - <signal> declined by user.

### Offers Requiring Your Decision
- **<Company>** - offer written 2026-07-12 ("<subject>"). Tracker set to `offer`; run `/outcome <company>` to record accept/decline once you decide.

### Stale Applications (30+ days, no activity)
- **<Company>** - last activity YYYY-MM-DD, still `<status>`.
```

If nothing was proposed this run, a brief note is enough instead of an empty summary.

If this run pushed the count of applications with a **final** `outcome.md` status to 3+ (or resolved a second application sharing a pattern), suggest the same `/setup` Path A calibration handoff `/outcome` suggests - do not duplicate that logic, just point the user there.

---

## Important Rules

1. **Classify from full email bodies, never snippets.** A status-changing proposal requires having actually fetched and read the message via `get_thread`/`get_message`.
2. **Confirmed rejections are the sole automatic status write.** They may be written without another prompt only when the local profile explicitly authorizes it and every Step 5 safeguard passes. Application acknowledgements, assessments, interviews, and offers still require approval before tracker or archive writes.
3. **Never propose `hired` or `offer_declined`.** Those require the user's real-world decision; `/gmail-sync` stops at proposing `offer` and flags it.
4. **A conflicting signal against an already-final or already-written status is a manual-review flag, not a proposed overwrite.** When in doubt, don't propose it - surface it.
5. **Append-only to `outcome.md` Notes**, same as `/outcome`. Never rewrite or delete existing history.
6. **Idempotent by source-qualified identity.** Use primary Gmail message IDs and deterministic secondary source keys. Re-running must never re-propose, or duplicate a tracker note or Notes entry for, the same email.
7. **Never fabricate a match.** If the company can't be confidently identified from the email, it goes in "Unmatched," not a guess.
8. **Read-only against all mailboxes.** This command reads and classifies; it does not label, archive, delete, reply, forward, or send.
9. **All state is personal data.** `gmail_sync/state.json`, `job_search_tracker.csv`, and `documents/applications/**` are gitignored - never suggest committing them.
