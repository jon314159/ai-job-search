"""Guards for /setup's thin-pointer privacy contract.

Candidate facts belong in the canonical profile and generated artifacts. Reusable
method/template files retain placeholders and read profile facts at runtime, preventing
personal setup data from leaking into files intended to be shared upstream.
"""
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
COMMAND = REPO / ".claude" / "commands" / "setup.md"
SKILL_DIR = REPO / ".claude" / "skills" / "job-application-assistant"
CV_TEMPLATES = SKILL_DIR / "05-cv-templates.md"
COVER_TEMPLATES = SKILL_DIR / "06-cover-letter-templates.md"


def _sections(text: str) -> dict[str, str]:
    """Split a command spec into {heading: body} by '## ' headers."""
    parts = text.split("\n## ")
    result = {}
    for part in parts[1:]:
        heading, _, body = part.partition("\n")
        result[heading.strip()] = body
    return result


def _substeps(step_body: str) -> dict[str, str]:
    """Split a step body into {'### N. ...' heading: body}."""
    parts = step_body.split("\n### ")
    result = {}
    for part in parts[1:]:
        heading, _, body = part.partition("\n")
        result[heading.strip()] = body
    return result


class SetupStep3CandidateNeutralMethods(unittest.TestCase):
    def setUp(self):
        self.step3 = _sections(COMMAND.read_text(encoding="utf-8"))["Step 3: Generate Profile Files"]

    def test_method_files_are_explicitly_candidate_neutral(self):
        self.assertIn("Keep method files candidate-neutral", self.step3)
        self.assertIn("Do not personalize", self.step3)
        for filename in (
            "04-job-evaluation.md",
            "05-cv-templates.md",
            "06-cover-letter-templates.md",
            "07-interview-prep.md",
        ):
            self.assertIn(filename, self.step3)

    def test_profile_files_own_candidate_facts(self):
        self.assertIn("01-candidate-profile.md", self.step3)
        self.assertIn("02-behavioral-profile.md", self.step3)
        self.assertIn("runtime", self.step3)

    def test_completion_summary_lists_the_cover_letter_templates(self):
        step4 = _sections(COMMAND.read_text(encoding="utf-8"))["Step 4: Confirm & Next Steps"]
        summary = step4.split("**Privacy note:**")[0]
        self.assertIn("06-cover-letter-templates.md", summary)


class TemplatesStayCandidateNeutral(unittest.TestCase):

    def test_cv_template_reads_candidate_facts_at_runtime(self):
        text = CV_TEMPLATES.read_text(encoding="utf-8")
        self.assertIn("01-candidate-profile.md", text)
        self.assertIn("at runtime", text)
        self.assertNotIn("BEGIN ACTIVE-TEMPLATE", text)

    def test_cover_letter_template_keeps_generic_tokens(self):
        text = COVER_TEMPLATES.read_text(encoding="utf-8")
        self.assertIn("01-candidate-profile.md", text)
        self.assertIn("at runtime", text)
        for token in ("[YOUR_NAME]", "[YOUR_EMAIL]", "[YOUR_PHONE]", "[YOUR_LINKEDIN_URL]"):
            self.assertIn(token, text)
        self.assertIn("\\signature{[YOUR_NAME]}", text)


if __name__ == "__main__":
    unittest.main()
