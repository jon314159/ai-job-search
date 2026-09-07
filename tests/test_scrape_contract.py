"""Tests for the /scrape Step 2 search-output contract across portal CLIs.

Mirrors the pattern of test_html_report_command.py: derive the contract from
the spec itself and compare it against the real portal CLIs, so a drift on
either side fails with a clean diff.

Why this test exists: .claude/skills/job-scraper/SKILL.md Step 2 promises
"Search output already includes title, company, location, date, and URL" for
every portal CLI, and Step 4.75's degraded scan flags "company null or empty
on every result" as a half-working parser. A CLI that quietly stops emitting
those fields flags the portal as degraded on every /scrape run while CI stays
green, breaks the seen_jobs.json dedupe (url_or_company_title_key), and leaves
/rank without a posting URL. That failure class landed for real: jobnet-search
emitted only the raw API schema and jobdanmark-search emitted companyName with
no company/location/date keys until both were normalized.

{helpers.ts, commands/search.ts} are the two files where every registered
CLI's search output currently lives (HTML-parsing portals normalize in
helpers.ts, API portals in commands/search.ts). detail.ts is deliberately
excluded: the contract is about the search output /scrape consumes.
"""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRAPER_SKILL = REPO_ROOT / ".claude" / "skills" / "job-scraper" / "SKILL.md"
PORTAL_CLIS = sorted((REPO_ROOT / ".agents" / "skills").glob("*-search"))

# Derived, never copied: a hardcoded field list drifts in lockstep with
# nothing - if Step 2's prose drops or adds a field, the known-good portals
# and this pin would keep agreeing forever while the contract changed.
_CONTRACT_SENTENCE = re.compile(r"Search output already includes ([a-zA-Z0-9\s,]+)\.", re.MULTILINE)


def derive_contract_fields() -> frozenset[str]:
    text = SCRAPER_SKILL.read_text(encoding="utf-8")
    match = _CONTRACT_SENTENCE.search(text)
    if match is None:
        raise AssertionError("Step 2 contract sentence not found in job-scraper/SKILL.md")
    fields_text = re.sub(r"\s+and\s+", ",", match.group(1))
    fields = {f.strip().lower() for f in fields_text.split(",") if f.strip()}
    return frozenset(fields)


def search_output_source(search_ts: Path) -> str:
    helpers_ts = search_ts.parent.parent / "helpers.ts"
    files = [search_ts, helpers_ts] if helpers_ts.exists() else [search_ts]
    return "\n".join(f.read_text(encoding="utf-8") for f in files)


class ScrapeSearchOutputContractTests(unittest.TestCase):
    """Every portal CLI's search output must carry the Step 2 contract fields."""

    def test_step2_contract_sentence_is_found_in_the_scraper_skill(self):
        """Guards the anchor the field list is derived from."""
        fields = derive_contract_fields()
        self.assertGreaterEqual(fields, {"title", "company", "location", "date", "url"})

    def test_every_portal_cli_emits_the_step2_contract_fields(self):
        contract = derive_contract_fields()
        failures: list[str] = []
        for portal in PORTAL_CLIS:
            search_ts = portal / "cli" / "src" / "commands" / "search.ts"
            if not search_ts.exists():
                failures.append(f"{portal.name}: no cli/src/commands/search.ts")
                continue
            source = search_output_source(search_ts)
            emitted = set(re.findall(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*):", source, re.MULTILINE))
            missing = sorted(contract - emitted)
            if missing:
                failures.append(f"{portal.name}: missing {missing} in search output")
        self.assertEqual([], failures, "; ".join(failures) or "no portal CLIs checked")



# Step 4's storage schema is structurally scoped to that section and its
# explicit seen_jobs.json fenced block.  This keeps harmless prose or heading
# changes from redirecting the test to an unrelated JSON example.
_STEP4_SECTION = re.compile(
    r"^###\s+Step\s+4:\s+Deduplicate\s+&\s+Store\b(?P<section>.*?)(?=^###\s|\Z)",
    re.DOTALL | re.MULTILINE,
)
_SEEN_SCHEMA_BLOCK = re.compile(
    r"Use this additive structure:\s*```json(?P<schema>.*?)```",
    re.DOTALL,
)


def derive_stored_fields() -> frozenset[str]:
    text = SCRAPER_SKILL.read_text(encoding="utf-8")
    section = _STEP4_SECTION.search(text)
    if section is None:
        raise AssertionError("Step 4 section not found in job-scraper/SKILL.md")
    schema = _SEEN_SCHEMA_BLOCK.search(section.group("section"))
    if schema is None:
        raise AssertionError("Step 4 seen_jobs.json schema block not found in job-scraper/SKILL.md")
    return frozenset(re.findall(r'"([a-z_]+)":', schema.group("schema")))


class SeenJobsPostingDateTests(unittest.TestCase):
    """The posting date Step 2 guarantees must survive into Step 4's storage.

    Step 2's contract promises a `date` on every portal CLI's search output and
    the test above keeps every CLI honest about emitting it. Step 1b then uses
    that date to scope the run to the last 14 days - and Step 4's schema drops
    it. `first_seen` records when this scraper first saw an entry, not when the
    employer posted it, so once the run ends nothing can tell a posting
    published yesterday from one published two years ago: the Step 1b window is
    unauditable and /rank has no freshness signal to weigh.

    That failure landed for real: a freehire-search posting dated 2024-05-13 was
    scraped and ranked Strong Fit at position 1 of 133, its own scoring note
    observing the listing "may be long stale" with nothing able to act on it.
    """

    def test_step4_schema_persists_a_posting_date(self):
        stored = derive_stored_fields()
        self.assertIn(
            "posted_date",
            stored,
            "Step 4's seen_jobs.json schema stores no posting-date field, so a "
            "posting's age is unrecoverable after the run that scraped it",
        )

    def test_step4_schema_keeps_the_expected_base_fields(self):
        self.assertGreaterEqual(
            derive_stored_fields(),
            {"title", "company", "url", "first_seen", "posted_date", "status"},
        )

    def test_the_step2_date_field_survives_into_storage(self):
        contract = derive_contract_fields()
        self.assertIn("date", contract, "Step 2 no longer guarantees a posting date")
        stored = derive_stored_fields()
        self.assertIn(
            "posted_date",
            stored,
            "Step 2 guarantees a posting `date` and CI enforces every CLI emits it, "
            "but Step 4 discards it at write time",
        )

    def test_posted_date_semantics_are_documented(self):
        """A stored field the spec never explains gets backfilled by guessing."""
        text = SCRAPER_SKILL.read_text(encoding="utf-8")
        self.assertIn("`posted_date`", text, "posted_date is in the schema but never documented")
        self.assertRegex(
            text,
            r"never infer a posting date",
            "posted_date must carry the same never-backfill rule as `deadline`",
        )


class PortalDiscoveryContractTests(unittest.TestCase):
    def test_only_cli_skills_are_typed_as_portals(self):
        portal_skills = []
        for skill in sorted((REPO_ROOT / ".agents" / "skills").glob("*/SKILL.md")):
            text = skill.read_text(encoding="utf-8")
            frontmatter = text.split("\n---", 1)[0]
            has_cli = (skill.parent / "cli" / "package.json").is_file()
            is_portal = "skill_kind: portal-search" in frontmatter
            self.assertEqual(is_portal, has_cli, skill)
            if is_portal:
                self.assertRegex(frontmatter, r"(?m)^enabled: (true|false)\b")
                portal_skills.append(skill.parent.name)
        self.assertNotIn("luna-sol-routing", portal_skills)
        self.assertEqual(len(portal_skills), 6)

    def test_scraper_filters_frontmatter_before_loading_bodies(self):
        text = SCRAPER_SKILL.read_text(encoding="utf-8")
        discovery = text.split("#### 1b.", 1)[1].split("For each **enabled**", 1)[0]
        self.assertIn("Inventory only the YAML frontmatter", discovery)
        self.assertIn("ignore unrelated skills", discovery)
        self.assertIn("Do not load a disabled portal's body", discovery)

    def test_individual_portals_do_not_claim_generic_job_discovery(self):
        for skill in PORTAL_CLIS:
            frontmatter = (skill / "SKILL.md").read_text(encoding="utf-8").split("\n---", 1)[0]
            compact = " ".join(frontmatter.split())
            self.assertIn("Use only", compact, skill.name)
            self.assertIn("/scrape selects this enabled portal", compact, skill.name)
            self.assertRegex(compact, r"Generic (?:Denmark )?job discovery routes", skill.name)


if __name__ == "__main__":
    unittest.main()
