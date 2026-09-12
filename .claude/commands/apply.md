# /apply - Staged Job Application Workflow

You are running one staged job-application workflow. The current capable owner performs
the work; an independent reviewer is conditional under Step 3. The job posting is
provided below as `$ARGUMENTS` (either a URL or pasted text).

Follow these steps **exactly in order**. Do not skip steps.

**Standing rule — write durable confirmed facts back to the profile.** If the user
explicitly confirms or corrects a reusable candidate fact that is not already in
`01-candidate-profile.md` — a metric, project detail, skill, or scope correction — update
that file in the same turn. A detail supplied only for this draft is not a durable profile
update. Do not leave a confirmed reusable fact living only in the conversation or draft.

This is not bookkeeping. A fact that exists only in chat **will be treated as unsupported by a later session and stripped from drafts as a fabrication.** Anything absent from the canonical profile does not exist as far as future drafting is concerned, and the loss is silent — a real achievement quietly disappears from every subsequent CV.

This rule is the input side of the Step 3 Factual Grounding Audit. Write confirmed facts to
`01-candidate-profile.md`, the single factual source. `CLAUDE.md` contains workflow rules
and `cv/main_example.tex` is structural; never copy the fact into either merely to satisfy
a three-way consistency check.

## Execution and context policy

The lean default is CV-only. Run every applicable stage in order, including final
source, PDF, ATS and state verification. A hard eligibility, target-scope, location
or language FAIL stops scoring/drafting. A material FLAG or score below 60 needs the
user's judgment. Preparation never authorizes submission or changes to final outcomes.
`--evaluate-only` is entirely read-only, including cache, checkpoint and state files.

Resolve Python once (project virtualenv, python, py -3, python3). Load only the current
stage, through the following command from the repository root:

```text
<PYTHON> tools/application_pipeline.py stage <name>
```

| Order | Name | Work |
|---|---|---|
| 0 | input | Flags, snapshot and live availability, identity |
| 1 | evaluate | Hard gates, bounded company research, final score |
| 2 | draft | Relevant evidence, active template, CV and optional cover |
| 3 | review | Required content checkpoint; conditional independent reviewer |
| 4 | revise | Supported edits and unresolved flags |
| 5 | verify | Compile, actual visual inspection, extraction and ATS |
| 6 | record | Final checklist, direct form edits, tracker/archive dry-run/write, final answer |

Stage text comes from
`.claude/skills/job-application-assistant/references/apply-workflow.md`, the single
detailed contract. Do not read that entire file at startup. If the helper is
unavailable, read only the corresponding numbered Step section. A stage pointer
does not make any required checks optional. Evaluate-only stops after its review
in Step 1. Only load cover/form instructions when their branch is requested.

Within a stage, reuse unchanged material already present. Across an actual context
boundary or compaction, reload validated compact state and needed source excerpts.
Keep application identity/authorization, normalized requirements, exact relevant
candidate evidence, current artifact content/hashes, verification receipts and flags.
Full evaluation/style/template/research guides are stage-only references. A changed
claim, rubric, profile, posting or artifact invalidates the affected checks.

This reduces new input; it cannot delete existing runtime conversation history.
Do not claim that reading a smaller object evicted earlier messages. Batch independent
mechanical operations and preserve one state-write owner. Do not spawn agents or
change runtime compaction/model settings merely to match a stage. Use the current
capable owner and the existing conditional review routing. Consider a supported
context boundary only for substantial remaining work; never assume it is free.

At Step 2, load
`.claude/skills/job-application-assistant/references/application-state.md` for the
private evidence-state and helper interface. Validate/reload that state after a real
boundary. Record stage checkpoints in the same tool batch as useful work where possible,
with actual model/effort, cache/retry information and response ID if available. For
Steps 0–1, hold stage timing in memory until preparation is allowed; evaluate-only
never writes telemetry. Report measured usage separately from estimates. No prompt
cache discount or subscription-allowance saving is assumed.
