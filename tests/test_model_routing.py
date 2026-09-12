"""Semantic contract tests for the repository's adaptive routing rules."""
import unittest
from pathlib import Path
import tomllib


REPO = Path(__file__).resolve().parent.parent


def read(path: str) -> str:
    return (REPO / path).read_text(encoding="utf-8")


class ModelRoutingContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = read(".agents/skills/luna-sol-routing/SKILL.md")
        cls.routing = read(".agents/skills/luna-sol-routing/references/job-search-workflow.md")
        cls.packet = read(".agents/skills/luna-sol-routing/references/task-packet.md")
        cls.rank = read(".claude/commands/rank.md")
        cls.apply = read(".claude/skills/job-application-assistant/references/apply-workflow.md")
        cls.interview = read(".claude/commands/interview.md")
        cls.scrape = read(".claude/skills/job-scraper/SKILL.md")
        cls.config = tomllib.loads(read(".codex/config.toml"))
        cls.reviewer = read(".codex/agents/application-reviewer.toml")

    def test_workflow_arrangements_preserve_small_task_ownership(self):
        for workflow in ("/scrape", "/rank", "/outcome", "/gmail-sync", "/html-report", "/notion-sync", "/reset"):
            self.assertIn(workflow, self.routing)
        self.assertIn("small batches stay with the owner", self.routing)
        self.assertIn("No separate reviewer for routine triage", self.routing)
        self.assertIn("Normal `/scrape` stays with the current capable owner", self.scrape)

    def test_small_repository_tasks_do_not_load_routing(self):
        agents = read("AGENTS.md")
        self.assertIn("small local", agents)
        self.assertIn("do not load the routing skill", agents)
        self.assertIn("Do not load for a small local edit", self.skill)

    def test_obsolete_gemini_agent_is_removed(self):
        self.assertFalse((REPO / ".claude" / "agents" / "gemini-research-expert.md").exists())

    def test_codex_model_stack_is_project_scoped_and_concrete(self):
        self.assertEqual(self.config["model"], "gpt-5.6-terra")
        self.assertEqual(self.config["model_reasoning_effort"], "medium")
        self.assertEqual(self.config["agents"]["default_subagent_model"], "gpt-5.6-luna")
        self.assertEqual(self.config["agents"]["default_subagent_reasoning_effort"], "low")
        self.assertEqual(self.config["agents"]["max_concurrent_threads_per_session"], 1)
        for expected in ("gpt-5.6-sol", 'model_reasoning_effort = "high"', 'sandbox_mode = "read-only"', "artifact_review_v1"):
            self.assertIn(expected, self.reviewer)

    def test_routing_assigns_sol_to_employer_facing_work(self):
        for workflow in ("`/apply` and `/interview`", "Independent CV, cover-letter, or interview-prep review"):
            self.assertIn(workflow, self.skill)
        for expected in ("`gpt-5.6-sol`, high", "`gpt-5.6-terra`, medium", "`gpt-5.6-luna`, low", "`gpt-6-astra`, high"):
            self.assertIn(expected, self.skill)
        self.assertIn("cannot upgrade an active Terra task", self.skill)
        self.assertIn("Use the parent skill for all model", self.routing)
        self.assertNotIn("Terra/Medium owner runs tools", self.routing)

    def test_packet_contracts_and_limits(self):
        for schema in ("semantic_resolution_v1", "artifact_review_v1", "strategy_review_v1", "architecture_review_v1", "boundary_audit_v1"):
            self.assertIn(schema, self.packet)
        self.assertIn("never over 3K", self.packet)
        self.assertIn("below 3K tokens", self.routing)
        for forbidden in ("full profiles", "full chats", "inbox contents", "full posting"):
            self.assertIn(forbidden, self.packet + self.routing)

    def test_fallback_and_no_bouncing_are_explicit(self):
        self.assertIn("retry once", self.routing.lower())
        for document in (self.routing, self.apply, self.interview):
            self.assertIn("review_mode: INDEPENDENT | SELF_REVIEW", document)
            self.assertIn("review_model", document)
        self.assertIn("no model bouncing", self.routing)
        self.assertIn("plausibly transient failure", self.routing)

    def test_rank_has_no_routine_reviewer_with_dormant_boundary_exception(self):
        self.assertIn("routing skill's Luna scoring default", self.rank)
        self.assertIn("routine `/rank` never adds an independent reviewer", self.rank)
        self.assertIn("disabled", self.rank.lower())
        for criterion in ("no hard FAIL", "5 points or the next 3 positions", "fetch cannot resolve", "at most five"):
            self.assertIn(criterion, self.rank)

    def test_apply_and_interview_required_hooks(self):
        self.assertIn("required", self.apply.lower())
        self.assertIn("artifact_review_v1", self.apply)
        self.assertIn("--evaluate-only", self.apply)
        self.assertIn("every decision-relevant requirement excerpt", self.apply.lower())
        apply_step_1 = self.apply.split("## Step 2:", 1)[0]
        self.assertIn("artifact_review_v1", apply_step_1)
        self.assertIn("job-search model routing", apply_step_1)
        self.assertNotIn("gpt-5.6-sol", apply_step_1)
        self.assertIn("review verdict", apply_step_1)
        self.assertNotIn("Re-fetch only", self.apply)
        self.assertIn("must not fetch sources itself", self.apply)
        self.assertIn("Required Codex review checkpoint", self.interview)
        self.assertIn("artifact_review_v1", self.interview)
        self.assertIn("before Step 4", self.interview)
        self.assertLess(
            self.interview.index("Required Codex review checkpoint"),
            self.interview.index("save the finalized pack"),
        )

if __name__ == "__main__":
    unittest.main()
