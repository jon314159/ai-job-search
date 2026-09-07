---
name: luna-sol-routing
description: >
  Use when selecting a model or work arrangement, considering delegation or an
  independent review, or running a named job-search workflow with explicit routing
  defaults. Do not load for a small local edit or lookup handled by the current
  capable owner.
---

# Adaptive model routing

Optimize for a correct completed task, including coordination, verification, and
rework. Keep one execution owner, normally the current capable agent. The existing
skill name and path remain for compatibility. Explicit user choices take priority.

## Choose the work arrangement first

- Finish small edits, short lookups, small batches, and clear local fixes directly.
  Do not delegate merely to use a cheaper model or to satisfy a model preference.
- Prefer existing scripts and parallel tool calls for mechanical work. Several
  independent CLI calls do not need several agents.
- Delegate only a bounded task that can run independently alongside useful owner
  work, when the expected savings or separate perspective outweigh context setup
  and integration. Use coarse batches or separate file ownership, not an agent per
  item. Reuse a suitable worker for a related batch.
- Workers return evidence and results; the owner integrates and verifies them.
  Keep tracker/profile writes and other shared mutations with the owner. Reviewers
  are read-only. Workers do not delegate further unless the task requires it.

## Model and effort defaults

These are the project's Codex roles, not a claim that a model can repair missing
evidence or authorization. The project-local `.codex/config.toml` makes
`gpt-5.6-terra` at medium effort the default for a **new trusted-project task**.
Codex does not silently swap the primary model in the middle of a task. Start a new
task with the stated model and effort when a workflow below calls for a non-default
owner; record the model that actually ran, never the intended one.

| Work | Model and reasoning | Use |
|---|---|---|
| `/apply` and `/interview` | `gpt-5.6-sol`, high | Start the workflow in a new Sol/High task. It owns evaluation, research, drafting, revisions, and final verification. |
| Independent CV, cover-letter, or interview-prep review | `gpt-5.6-sol`, high | Use the project `application_reviewer` role with a compact, read-only `artifact_review_v1` packet when an independent review is warranted. |
| `/setup`, `/rank`, `/expand`, and `/upskill` | `gpt-5.6-terra`, medium | Default owner for evidence-grounded evaluation, interactive edits, and supported routine decisions. |
| `/scrape` orchestration | `gpt-5.6-terra`, medium | Keep live fetches, deduplication, gates, and state integration with the owner; use Luna only for a substantial, independent, fixed-rubric batch. |
| `/gmail-sync`, `/outcome`, and routine tracking | `gpt-5.6-luna`, low | Use only for a fresh, narrowly scoped routine task. Keep tracker/profile writes with its single owner; do not delegate shared mutations merely to use Luna. |
| Clear repeatable extraction, normalization, or scoring | `gpt-5.6-luna`, low | Bounded, checkable work. Raise to medium only for a genuinely multi-criterion scoring batch. |
| Exceptional unresolved architecture, difficult debugging, or consequential tradeoffs | `gpt-6-astra`, high | Rare escalation after focused evidence gathering; use only for the hard decision, not normal job-search operations. |

Keep an already suitable Terra, Sol, or other capable owner rather than creating a
handoff solely to match a table row. Increase depth when missing reasoning causes
errors, not for routine formatting or a failed command with an obvious cause. Strong
models can implement and verify as well as advise. A capable Astra owner handles its
own hard decision unless an independent review or separable investigation adds value.

## Codex runtime boundaries

- The default in `.codex/config.toml` affects new Codex tasks only. Select
  `gpt-5.6-sol` with high reasoning before starting `/apply` or `/interview`; a
  configuration file cannot upgrade an active Terra task.
- The default spawned-agent setting is Luna/Low. The only workflow-specific role is
  `.codex/agents/application-reviewer.toml`, which pins the independent reviewer to
  Sol/High and read-only access. Use that role only under the review triggers below.
- A separate reviewer is conditional, not ceremonial. `/apply` and `/interview`
  always require the content checkpoint, but an evidence-clear edit may receive a
  documented self-review. Never describe self-review as independent.
- Cursor, Claude Code, and other runtimes do not load `.codex/config.toml`. Follow
  the same workload roles only when their own runtime exposes the named models and
  effort controls; otherwise preserve the evidence and review gates and record the
  actual substitution.

## Reviews and escalation

For a named job-search workflow, read
[references/job-search-workflow.md](references/job-search-workflow.md) for its review
checkpoint and evidence gates. Routine repository work that does not invoke one of
those workflows does not need that reference. Verification is always required; a
separate agent is conditional on material uncertainty, substantive content risk, or
an explicit request. Never describe the owner's own review as independent.

For a separate review or decision, use
[references/task-packet.md](references/task-packet.md). Include only decisive
evidence and acceptance criteria. Reproduce a bug and gather a useful trace before
asking for debugging advice when feasible. Apply supported corrections, then verify;
reconsult only for new evidence or an unresolved material issue. Do not stop with a
known defect merely because one revision has been used.

## Runtime and fallback

- Use supported model/effort controls only. Subagent selection does not switch the
  parent model, and this skill does not change app settings or saved automations.
- In runtimes exposing `fork_turns`, use `fork_turns: "none"` and scoped context
  for model overrides; full-history forks inherit the parent and reject overrides.
  An assigned reviewer answers its packet directly without reapplying owner routing.
- If delegation or a model is unavailable, continue with a suitable available
  owner/model and disclose a material substitution. Retry once only for a plausibly
  transient failure. Do not create a chain of fallback agents.
- A missing model alone is not a reason to ask permission. Preserve unresolved
  factual/eligibility flags and actual authorization gates; seek direction only
  when evidence or an authorized decision is genuinely missing.
- Run checks proportional to the change; stop after adequate verification. Adjust
  defaults from observed completion time, retries, corrections, and usage when
  available. Do not claim benchmarked savings or infer Codex allowance from API prices.

Model roles and Light/Low terminology follow
[OpenAI model guidance](https://learn.chatgpt.com/docs/models). The routing choices
above are workspace defaults, not a claim of a universally optimal model.
