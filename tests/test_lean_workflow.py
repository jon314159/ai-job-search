"""Guards for the lean search -> rank -> apply orchestration."""

import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
SCRAPER = REPO / ".claude" / "skills" / "job-scraper" / "SKILL.md"
RANK = REPO / ".claude" / "commands" / "rank.md"
APPLY = REPO / ".claude" / "commands" / "apply.md"
OUTCOME = REPO / ".claude" / "commands" / "outcome.md"
GMAIL = REPO / ".claude" / "commands" / "gmail-sync.md"
PROFILE = (
    REPO
    / ".claude"
    / "skills"
    / "job-application-assistant"
    / "01-candidate-profile.md"
)
CLAUDE = REPO / "CLAUDE.md"
WEB_RESEARCH = REPO / ".claude" / "skills" / "job-application-assistant" / "09-web-research.md"
APPLICATION_VERIFICATION = REPO / ".claude" / "skills" / "job-application-assistant" / "10-application-verification.md"


class LeanSearchPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scraper = SCRAPER.read_text(encoding="utf-8")
        cls.rank = RANK.read_text(encoding="utf-8")

    def test_dedupe_and_gates_precede_detail_fetch(self):
        dedupe = self.scraper.index("### Step 1.5: Normalize, Deduplicate & Gate")
        fetch = self.scraper.index("### Step 2: Fetch Once, Parse & Snapshot")
        self.assertLess(dedupe, fetch)
        section = self.scraper[dedupe:fetch]
        self.assertIn("Before any `detail` or WebFetch call", section)
        self.assertIn("tracker row", section)
        self.assertIn("requisition/canonical URL", section)

    def test_snapshot_contract_is_persisted(self):
        for field in (
            "posting_snapshot",
            "snapshot_fetched_at",
            "snapshot_sha256",
            "authoritative_url",
        ):
            self.assertIn(field, self.scraper)
            self.assertIn(field, self.rank)
        self.assertIn("at most 24 hours old", " ".join(self.scraper.split()))
        self.assertIn("tools/job_state.py snapshot-path", self.scraper)
        self.assertIn("tools/job_state.py snapshot-verify", self.scraper)
        self.assertIn("tools/job_state.py snapshot-verify", self.rank)

    def test_scrape_automatically_invokes_ranking(self):
        self.assertIn("### Step 4.25: Automatically Rank the New Batch", self.scraper)
        self.assertIn("from-scrape mode", self.scraper)
        self.assertIn("do not make the user\nrun a second command", self.scraper)

    def test_rank_workers_receive_snapshot_text_and_do_not_refetch(self):
        step2 = self.rank.partition("## Step 2: Batch-Fetch and Score")[2].partition(
            "\n## "
        )[0]
        self.assertIn("verified full snapshot text", step2)
        self.assertIn("**not** make agents re-read", step2)
        self.assertIn("fetch posting URLs", step2)

    def test_referral_links_are_on_demand(self):
        self.assertIn("Generate Referral Contact Links On Demand", self.scraper)
        self.assertIn("Do not generate a contacts block for every match", self.scraper)

    def test_interrupted_entries_are_recovered_and_skipped_keys_are_not_ranked(self):
        self.assertIn("Recover interrupted work", self.scraper)
        self.assertIn("retryable `unverified`", self.scraper)
        rank_start = self.scraper.index("### Step 4.25: Automatically Rank the New Batch")
        rank_end = self.scraper.index("### Step 4.5: Generate Referral", rank_start)
        rank_section = self.scraper[rank_start:rank_end]
        self.assertIn("Never pass skipped or snapshot-less keys", rank_section)

    def test_rank_persists_hard_gates_and_evidence_confidence(self):
        for field in (
            '"eligibility_gate"',
            '"target_scope_gate"',
            '"location_note"',
            '"evidence_confidence"',
            '"source_confidence"',
        ):
            self.assertIn(field, self.rank)
        self.assertIn("never pad the actionable list below 60", self.rank.casefold())

    def test_no_new_batch_still_sweeps_deadlines(self):
        step1 = self.rank.partition("## Step 1: Load State")[2].partition("\n## Step 2")[0]
        self.assertIn("no-new run skips scoring agents but continues", step1)

    def test_standard_selection_reaches_full_apply(self):
        skill = (
            REPO
            / ".claude"
            / "skills"
            / "job-application-assistant"
            / "SKILL.md"
        ).read_text(encoding="utf-8")
        apply = APPLY.read_text(encoding="utf-8")
        self.assertIn("execute `.claude/commands/apply.md` **end to end**", skill)
        for stage in (
            "## Step 3: REVIEWER - Research & Critique",
            "## Step 5: DRAFTER - Compile & Inspect PDFs (MANDATORY)",
            "### 5d. ATS & keyword verification (CV)",
            "### Step 6b: Record the Application",
        ):
            self.assertIn(stage, apply)

    def test_shortlist_requires_a_bounded_live_availability_check(self):
        rank = self.scraper.index("### Step 4.25: Automatically Rank the New Batch")
        availability = self.scraper.index("### Step 4.6: Final Live Availability Check")
        present = self.scraper.index("### Step 5: Present Results")
        self.assertLess(rank, availability)
        self.assertLess(availability, present)
        section = self.scraper[availability:present]
        self.assertIn("exact stored application page", section)
        self.assertIn("display the expected company and title", section)
        self.assertIn("offer an application path", section)
        self.assertIn("mark\nthe entry `expired`", section)
        self.assertIn("bounded to the five displayed\njobs", section)


class LeanApplicationPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.apply = APPLY.read_text(encoding="utf-8")
        cls.profile = PROFILE.read_text(encoding="utf-8")
        cls.claude = CLAUDE.read_text(encoding="utf-8")

    def test_profile_is_the_single_factual_authority(self):
        self.assertIn("single canonical source", self.profile)
        self.assertIn("01-candidate-profile.md", self.claude)
        self.assertNotIn("@gmail.com", self.claude)
        self.assertNotIn("3.97", self.claude)
        self.assertNotIn("union of three sources", self.apply)

    def test_claude_is_a_thin_pointer_not_a_second_apply_spec(self):
        self.assertIn("Do not duplicate workflow rules", self.claude)
        self.assertNotIn("## Verification Checklist", self.claude)
        self.assertNotIn("## Workflow for New Job Applications", self.claude)
        self.assertIn("10-application-verification.md", self.apply)

    def test_reviewer_uses_compact_evidence_packet(self):
        self.assertIn("APPLICATION_EVIDENCE_PACKET", self.apply)
        reviewer = self.apply.partition("## Step 3: REVIEWER")[2].partition("\n## Step 4")[0]
        self.assertIn(
            "must not read additional candidate or template files",
            " ".join(reviewer.split()).casefold(),
        )
        self.assertIn(".codex/agents/application-reviewer.toml", reviewer)
        self.assertNotIn("You are a hiring manager proxy", reviewer)
        self.assertNotIn("The master CV baseline template", reviewer)
        self.assertNotIn("Candidate Profile section", reviewer)

    def test_cover_letter_is_conditional(self):
        self.assertIn("The lean default is CV-only", self.apply)
        self.assertIn("COVER_REQUIRED", self.apply)
        self.assertIn("Skip this entire artifact", self.apply)
        self.assertIn("N/A - not requested", self.apply)

    def test_explicit_apply_does_not_require_duplicate_authorization(self):
        self.assertIn("already authorizes drafting", self.apply)
        self.assertIn("score is below 60", " ".join(self.apply.split()))

    def test_apply_rechecks_live_availability_before_drafting(self):
        step0 = self.apply.partition("## Step 0: Parse Input")[2].partition("\n## Step 1")[0]
        self.assertIn("A valid snapshot does not prove", step0)
        self.assertIn("perform one read-only live availability check", step0)
        self.assertIn("`--evaluate-only` is always read-only", step0)
        self.assertIn("is **unverified**, not proof of expiry", step0)
        self.assertIn("different company or role is a hard stop", step0)
        self.assertIn("missing visible apply\n  control is **unverified**", step0)
        self.assertIn("Do not create documents or a tracker row", step0)

    def test_unavailable_posting_is_not_silently_marked_expired(self):
        research = WEB_RESEARCH.read_text(encoding="utf-8")
        self.assertIn("mark it\n   `unverified`", research)
        self.assertIn("affirmative closure text, HTTP 404/410", research)
        self.assertIn("never draft from a title alone", research)

    def test_common_final_verification_remains_complete(self):
        verification = APPLICATION_VERIFICATION.read_text(encoding="utf-8")
        for requirement in (
            "Factual accuracy",
            "Targeting and consistency",
            "Source and rendered quality",
            "ATS and keyword verification",
            "exactly one page",
            "text layer",
        ):
            self.assertIn(requirement, verification)

    def test_state_writers_use_the_dry_run_first_helper(self):
        self.assertIn("tools/job_state.py upsert-draft", self.apply)
        self.assertIn("dry-run JSON first", OUTCOME.read_text(encoding="utf-8"))
        self.assertIn("dry-run JSON", GMAIL.read_text(encoding="utf-8"))

    def test_behavioral_source_and_company_evidence_precede_final_score(self):
        step1 = self.apply.partition("## Step 1: DRAFTER - Evaluate Fit")[2].partition(
            "\n## Step 2"
        )[0]
        self.assertIn("02-behavioral-profile.md", step1)
        self.assertIn("Before final scoring", step1)
        self.assertIn("neutral 50 with LOW confidence", step1)

    def test_hard_gate_fail_cannot_enter_drafting(self):
        step1 = self.apply.partition("## Step 1: DRAFTER - Evaluate Fit")[2].partition(
            "\n## Step 2"
        )[0]
        self.assertIn("**FAIL is a hard stop**", step1)
        self.assertIn("do not score or draft", step1)

    def test_unique_application_manifest_is_recorded(self):
        record = self.apply.partition("### Step 6b: Record the Application")[2].partition(
            "### Application-Form Fields"
        )[0]
        self.assertIn("application_id", record)
        self.assertIn("archive_path", record)
        self.assertIn("application_manifest.json", record)


if __name__ == "__main__":
    unittest.main()
