# Job-search model routing

Use the parent skill's model defaults and delegation criteria. The current capable
agent remains execution owner, including when it is Astra. Workflow commands own
their factual, privacy, provenance, approval, dry-run, PDF/ATS, and state-write gates;
routing never weakens them.

## Workflow checkpoints

Use the parent skill for all model and work-arrangement defaults. This reference owns
only the workflow-specific review checkpoints below, so callers do not copy or fork
the routing table.

| Workflow | Review checkpoint |
|---|---|
| `/scrape` and `/rank` (including rank-from-scrape) | No separate reviewer for routine triage. |
| `/apply` | Required content checkpoint before finalization; `--evaluate-only` checks the final evaluation before presentation. Use the `application_reviewer` only when the independent-review triggers below apply. |
| `/interview` | Required content checkpoint before saving or presenting the pack. Use the `application_reviewer` only when the independent-review triggers below apply. |
| `/setup`, `/expand`, `/upskill` | Use `semantic_resolution_v1` or `strategy_review_v1` only for a consequential unresolved decision. |
| `/add-portal`, `/add-template` | Use `architecture_review_v1` only for a material unresolved shared-contract tradeoff. |
| `/outcome`, `/gmail-sync`, `/html-report`, `/notion-sync`, `/reset` | No extra reviewer for routine work; preserve command-specific approval gates. |

For `/rank`, small batches stay with the owner. If workers help, group verified
snapshots by total context size and use the parent's Luna scoring default. Parallel
tool execution is preferred to agent dispatch for simple portal calls. Routine
triage adds no company research or costly review of every posting.

## Required content checkpoints

For `/apply`, `/apply --evaluate-only`, and `/interview`, check all material claims,
requirement coverage, eligibility/fit verdicts, and source support before finalizing.
Use an independent agent when explicitly requested, when Luna authored substantive
application/interview content, or when substantial claim reframing, conflicting
evidence, or an unresolved eligibility/content risk merits a separate perspective.
A simple evaluation or minor edit with clear source support can use self-review.

While a reviewer works, perform useful independent artifact or source verification.
If the runtime forbids delegation without concurrent owner work and none remains,
use the fallback below rather than manufacturing busywork.

Use the read-only `application_reviewer` role (`gpt-5.6-sol`, high) for a substantive
independent review. A capable owner may perform ordinary review directly. Same-model
review can be independent when done by a fresh agent with a scoped evidence packet.
Independence describes the reviewer, not the model's name.

For delegated review, send a packet below 3K tokens with every decision-relevant
requirement excerpt and evidence ID. Shorter is better when sufficient. Self-review
uses the same criteria without serializing a handoff. The owner applies grounded
corrections and performs all final verification. Reconsult only for a material gap
or new evidence; no model bouncing or repeated general reviews.

## Review provenance and fallback

Record `review_mode: INDEPENDENT | SELF_REVIEW`, `review_model`, and `review_effort`
using actual runtime information (or `unknown`, never a guess). Leave historical
`ASTRA`, `SOL`, and `LUNA_FALLBACK` records unchanged.

If a reviewer is unavailable, retry once only for a plausibly transient failure;
otherwise use a suitable available reviewer or the owner's disclosed self-review.
If the user explicitly requires independent review and none is possible, report that
limitation instead of claiming completion. A model cannot supply missing facts or
authorize a disputed durable change: preserve `FLAG`/`ASK_USER` and existing gates.

## Dormant `/rank` boundary audit

This remains disabled by default. A future retrospective may enable at most five
`boundary_audit_v1` reviews only when there is no hard FAIL, a consequential unresolved
or LOW-confidence semantic field, the job is within 5 points or the next 3 positions
(whichever is fewer) of a decision boundary, and the fetch cannot resolve the field.
Retrospective evidence must explicitly justify enabling it. This is not routine scoring.
