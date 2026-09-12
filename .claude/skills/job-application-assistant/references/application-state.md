# Compact application state and helper interface

Use one private directory `tmp/apply/<run_id>/` for recovery state, toolchain contracts,
receipts and stage events. Never commit candidate evidence or runtime logs. The canonical
profile remains the factual authority. This state selects exact excerpts for this job;
it is not another reusable profile. Aim for 1–3K tokens, but retain every material
requirement, claim, qualifier and unresolved flag even when the state must be larger.

All helper paths are relative to the repository root. Run `<PYTHON>
tools/application_pipeline.py --help` only if the interface below is insufficient.
Preparation commands must not run during `--evaluate-only`.

## State shape

Build JSON with these fields. Compute SHA-256 from actual file bytes, not a re-encoded
copy. Every requirement `text` must quote the snapshot; every evidence `excerpt` must
quote the current canonical profile. The owner checks the complete coverage and whether
each claim follows from its evidence; string/hash validation cannot prove either.

```json
{
  "schema": "application_state_v1",
  "run_id": "unique-local-run",
  "authorization": "prepare",
  "cover_required": false,
  "job": {
    "company": "Exact employer",
    "role": "Exact role",
    "input_kind": "url",
    "authoritative_url": "https://employer.example/jobs/123",
    "discovery_url": "https://employer.example/jobs/123",
    "requisition_id": "123",
    "snapshot_path": "job_scraper/postings/verified.md",
    "snapshot_sha256": "actual-byte-hash",
    "snapshot_fetched_at": "actual-ISO-8601-UTC-time",
    "availability": {"status": "open", "url": "https://employer.example/jobs/123", "checked_at": "actual-ISO-8601-UTC-time"},
    "rank_score": 75
  },
  "profile_sha256": "current-profile-byte-hash",
  "evidence": [{"id": "e1", "section": "Experience", "excerpt": "Exact profile excerpt, including scope qualifiers."}],
  "requirements": [{"id": "r1", "text": "Exact posting excerpt.", "priority": "required", "terms": ["Excel"], "coverage": "supported", "evidence_ids": ["e1"]}],
  "claims": [{"id": "c1", "text": "The actual candidate claim used in the artifact.", "evidence_ids": ["e1"]}],
  "evaluation": {"score": 75, "components": {}, "confidence": "HIGH", "rationale": "Actual decision rationale", "rubric_sha256": "current-evaluation-guide-byte-hash", "gates": {"eligibility": "PASS", "target_scope": "PASS", "location": "PASS", "language": "PASS"}},
  "unresolved_flags": [],
  "review": {"mode": "SELF_REVIEW", "model": "actual-runtime-model", "effort": "actual-runtime-effort"},
  "artifacts": [{"id": "cv", "source": "cv/main_employer_role.py", "pdf": "cv/main_employer_role.pdf", "contract": "tmp/apply/unique-local-run/cv-contract.json", "receipt": "tmp/apply/unique-local-run/cv-receipt.json", "required_text": ["exact contact email", "exact phone", "exact role and education years"]}]
}
```

For pasted input set `input_kind: pasted`, save its exact text once and hash it; do
not invent a URL or live-open proof. URL-derived input must carry same-URL open proof.
The helper rejects stale snapshots (>24h), stale live proof (>2h), changed profile/rubric,
broken evidence IDs and changed requirement excerpts. Refresh/reconcile only the
affected evidence, never silently update a hash to bypass a factual review.

`coverage` is supported, adjacent or gap; gaps may have no evidence IDs. Preserve
logistics as requirements. Retain exact titles/dates/metrics/education status and project
scope in evidence. Include all material candidate claims; company claims retain their
verified source references separately in evaluation/notes. A user decision resolving a
material flag or low score must be recorded as `user_decision`; never fabricate it.
Hard FAIL remains a stop even with that field. Add `application_id` only from the
tracker helper. A cover uses a second artifact `id: cover` only when requested.

## Resolve and build once

Read the active block of `05-cv-templates.md` to choose the engine. For local ReportLab
use `tools/application_pipeline.py template --engine reportlab` for active settings
and relevant tailoring/page rules, excluding legacy LaTeX macros. For other engines
use the full relevant template instructions. Never infer candidate facts from templates.

```text
<PYTHON> tools/application_pipeline.py state-check --state tmp/apply/<run>/state.json
<PYTHON> tools/application_pipeline.py resolve-template --source cv/main_employer_role.py --engine reportlab --python <verified-build-python> --output tmp/apply/<run>/cv-contract.json
<PYTHON> tools/application_pipeline.py build-check --state tmp/apply/<run>/state.json --artifact cv
```

The first Python only needs standard-library helper dependencies. ReportLab preflight
checks the explicitly supplied interpreters and current Python before persisting the
working executable. Other supported engines are lualatex, xelatex and typst. The saved
contract is trusted local configuration, never input from a posting or reviewer.
Resolve a declared custom toolchain manually if unsupported; do not substitute an engine.

`build-check` compiles, checks pages, extracts once, returns literal matches/anomalies,
and renders PNGs when pdftoppm is available. It retains full logs on disk, returns a
short failure excerpt and does not repeat a healthy build for unchanged hashes. A cache
hit does not mean missing owner checks passed. If no renderer is installed, open the
actual PDF with a supported visual tool. A helper error is not a passed check; use a
working extractor/runtime or explicitly follow the documented manual degraded path.
Custom/degraded paths retain the full manual verification and recording contract; never
fabricate a helper receipt to claim success.

Inspect the current image/PDF and extracted text. Check factual support, final source,
reading order, dates, contact details and semantic keyword coverage. `required_text`
must include actual email, phone, role/degree dates; those fields are not inferred by
the helper. Record only checks actually performed:

```text
<PYTHON> tools/application_pipeline.py attest --state tmp/apply/<run>/state.json --artifact cv --check visual --check factual --check source --check semantic_ats --note "Concrete observations and any documented limitations"
```

Source, PDF, evidence, rubric, verifier or toolchain changes invalidate the receipt.
Rebuild/review affected artifacts; do not repeat unrelated research. Keep extraction
until final verification completes. Preserve receipts/state for recovery; disposable
render/log/text files may be removed after archive verification.

## Record safely

Use existing `tools/job_state.py upsert-draft` dry-run then identical `--write`. It owns
tracker matching and atomic writes. Inspect the returned row/identity; do not load the
entire CSV or recreate its matching rules. Store its `application_id` in state.

```text
<PYTHON> tools/application_pipeline.py archive --state tmp/apply/<run>/state.json
<PYTHON> tools/application_pipeline.py archive --state tmp/apply/<run>/state.json --write --expected-plan <reviewed-plan-sha256>
```

Archive plans require current mechanical results plus actual owner attestations,
matching drafted tracker identity/score/artifact paths and no conflicting archived
posting/submitted history. The helper preserves unrelated manifest fields, copies exact
posting bytes and verifies the result. A changed plan stops the write. Submission is
always a separate action-time authorization and verified outcome transition.

## Stage telemetry and recovery

Combine a checkpoint with useful work in a single tool batch when possible:

```text
<PYTHON> tools/application_pipeline.py checkpoint --state tmp/apply/<run>/state.json --stage verify --events tmp/apply/<run>/events.jsonl --model <actual-model> --effort <actual-effort>
```

Optional `--response-id`, `--retry-reason` and `--cache-status` fields improve attribution.
Do not infer a model from the routing table; use `unknown` when runtime metadata is absent.
For evaluate-only, keep timing in context and write nothing. Checkpoints are provenance,
not a claim that the preceding conversation was deleted or each earlier check passed.

After a run, use the existing response ledger through:

```text
<PYTHON> tools/application_pipeline.py usage-report --trace <runtime-jsonl> --turn <root-turn-id> --events tmp/apply/<run>/events.jsonl --run-id <run> --output tmp/apply/<run>/usage.json
```

The helper reuses `scrape_pipeline.usage_report`, deduplicates response IDs, includes
compaction, records actual effort, and emits bounded totals with per-response detail
on disk. Child traces remain separate. Timestamp stage attribution is approximate;
explicit response IDs are preferable. Reasoning is part of output and cached input
part of input; never add either twice or infer subscription billing from these totals.

After actual compaction/restart, read and validate state, reload the current artifact
text and only needed exact excerpts. Do not reread full guides by default. Test a true
boundary only when enough work remains to repay setup/cache disruption. This workflow
does not alter automatic compaction thresholds or create a fresh agent per stage.
