# Local scrape execution

`tools/scrape_pipeline.py` is stdlib-only and makes no network/model calls. Run it from
the code checkout using the resolved Python executable and explicit private `<BASE>`.
Store captures and manifests under `<BASE>/job_scraper/run_<id>/` (ignored by Git).
This reference supplies mechanics; the scraper and `/rank` remain the source of gates,
coverage lanes, live checks, score evidence, and presentation rules.

## Discovery and evidence

1. Save each portal's JSON directly to a file. For browser/WebSearch leads save an array
   of cards with `url`, `title`, `company`, `location`, `date`, `portal`, `source`, and any
   explicit `requisition_id`. Preserve unknown values rather than guessing. Browser
   extraction should select result cards / the posting container, not the whole page.
   `prepare` strips description bodies and extra metadata from model-facing cards;
   the original file remains available for targeted checks. It accepts arrays or
   `{"results": [...]}` envelopes. Missing identity fields fail visibly as degraded data.
2. Run:
   ```text
   <PYTHON> tools/scrape_pipeline.py prepare --base <BASE> --input <source.json> <source2.json> --output <run>/cards.json
   <PYTHON> tools/scrape_pipeline.py page --input <run>/cards.json --offset 0
   ```
   Follow `next_offset`; never stop after the first page. The summary includes counts,
   recovered pending work, consolidated exact identities, and candidates. Keep the
   explicit `metadata_conflicts` unresolved until the full posting verifies them; do not
   hard-exclude a merged record using only one alias's conflicting location/remote field.
   Keep the
   source files for portal-health inspection. `page` returns at most five cards and
   12,000 serialized characters by default. Do not reprint earlier pages.
3. Apply profile-specific cheap gates before fetching. Save full selected-posting text
   directly from the fetch/browser tool to a UTF-8 file. For CLI detail JSON, extract its
   description in deterministic code into that file; do not have the model transcribe
   it. Preserve explicit structured source fields in the record. `snapshot_format: html`
   extracts readable text and removes scripts/styles/navigation; use only on the selected
   posting container, not a search page or a page containing several job descriptions.
   Prefer an existing portal's tested text extraction over this generic fallback.

## Persist and score

A payload is an array of additive seen-job updates:

```json
[{"url":"https://employer.example/jobs/42","company":"Example","title":"Analyst",
  "status":"new","source":"cli","portal":"example-search",
  "snapshot_source":"<absolute UTF-8 text file path>","snapshot_format":"text"}]
```

Include the existing `key` on updates, all known provenance fields, and normal gate /
score fields. Search-only failures use `skipped` plus `skip_reason` without invented
snapshots. Do not submit sparse duplicate records over existing rich records. A revived
expired record requires a fresh source and `live_open_verified: true` backed by a real
live check. This flag is an attestation, not something the offline helper can verify.

```text
<PYTHON> tools/scrape_pipeline.py persist --base <BASE> --payload <run>/updates.json
<PYTHON> tools/scrape_pipeline.py persist --base <BASE> --payload <run>/updates.json --write
<PYTHON> tools/scrape_pipeline.py plan --base <BASE> --keys <key1> <key2> --output <run>/analysis
<PYTHON> tools/scrape_pipeline.py page --input <run>/analysis/packets.json --offset 0
```

`persist` validates the batch first, writes exact UTF-8 bytes, verifies file hashes, then
atomically replaces seen state. Snapshots have URL-hash + content-hash names; existing
single-hash snapshots remain supported. One owner writes state; do not run concurrent
writers. Tracker columns and other records are untouched. Keep validation summaries,
not the full state, in context.

`plan` checks caches and prepares all bounded packets in code in one call; use it for
batches instead of one model/tool round trip for each cache lookup. It returns counts
and a manifest, writing `cached.json`, `packets.json`, and `held.json`. Follow all pages
of packets and inspect held reasons; a stale/broken job does not strand other jobs.
Read cached results with `page` only when needed for integration. `plan --force` bypasses
reuse for explicit reassessment. For a targeted single-job continuation, `packet --base
<BASE> --key <key> --part <part>` is also available.

`packet` verifies snapshot hash and 24-hour freshness and returns metadata plus at most
6,000 posting characters (adjustable 256–12,000). Follow every `next_part` and preserve
quoted restrictions, required/preferred distinctions, and conflicts in a concise
checklist. Nothing is silently discarded; even a long unbroken paragraph is split
losslessly. A final decision requires every part. The helper cannot prove the model
understood a clause; this is the same evidence-review responsibility as before.

Store the normal `/rank` JSON result, with `key`, `snapshot_sha256`, and
`reviewed_parts: [0,1,...]`, through:

```text
<PYTHON> tools/scrape_pipeline.py cache --base <BASE> --result <run>/analyses.json
```

Supply an array of completed results to store them in one call; the whole array is
validated before caching any result. For one object use `--key <key>`. Use the same
`--budget` as the packet reads. The cache fingerprints the snapshot,
identity, profiles, preferences, rubric, and packet version. Missing inputs, stale or
tampered snapshots, dismissed/tracked/expired state, or changed inputs prevent reuse.
Explicit reassessment/`--all` uses `--force` on lookup. Cache only completed triage;
`/apply` still conducts its full evaluation. The helper validates all score dimensions,
gates, confidence, and evidence, computes weighted score/verdict, and preserves the
rest of the result. Cache hits do not skip live checks or deadline sweeps.

For final state updates, map the normal result to `status: ranked` or the existing
veto/expiry treatment; submit through `persist`. Do not mark a hard-gate failure ranked.
Geographic priority, shortlist diversity, tie-breaking, confidence caveats, and the
below-60 rule remain exactly as specified in `/rank`; the helper does not substitute
numeric score sorting for those judgments.

Immediately before the final live checks and shortlist selection, build the active queue
from both state files in one deterministic pass:

```text
<PYTHON> tools/scrape_pipeline.py queue --base <BASE> --output <run>/active_queue.json
<PYTHON> tools/scrape_pipeline.py page --input <run>/active_queue.json --offset 0
```

Follow every `next_offset`. `queue` excludes ranked entries that already match a drafted,
applied, interview, offer, or other tracker row, including applications recorded after the
job was ranked. It also excludes exact URL/requisition matches to final tracker rows while
allowing a genuinely distinct later requisition with the same company and title. Never
construct the carry-forward shortlist directly from raw `seen_jobs.json`.

## Recovery and usage

Keep a short run manifest with stage names, completed job keys, source attempts and
outcomes, and pending questions. Reuse evidence for a URL already checked during this
run. Retry only a plausibly transient error through the existing bounded fallback;
do not repeat the same employer search or full page read after compaction. The final
availability check remains a separate necessary live check.

When the runtime exposes response usage, keep its response IDs and stage assignments
in a JSON object such as `{"response-id":"discovery"}`. For Codex saved traces:

```text
<PYTHON> tools/scrape_pipeline.py usage --trace <trace.jsonl> --turn <scrape-turn-id> --stages <run>/stages.json --output <run>/usage.json
```

Omit `--stages` if unavailable: totals remain exact, stage is `unassigned`. The report
deduplicates response IDs, includes compaction, excludes later turns, and keeps per-call
records on disk while printing totals by model/stage. It uses `token_usage_record`, not
legacy cumulative counters. No telemetry means `available: false`, not zero tokens.
Import any child traces separately and deduplicate response IDs before combining totals;
do not add a parent's reported child total a second time. Character-based packet token
estimates are labeled estimates and are never substituted for runtime usage.
