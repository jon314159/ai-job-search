"""Guards for /gmail-sync's Gmail query semantics.

The command's stated intent is "skip sent/drafts - status signals come
from what employers send you". `in:inbox` does not mean that: it matches
only messages currently IN the inbox, so it also excludes every archived
message - and, self-defeatingly, the mail matched by the very
job-search label Step 3.1 hunts for, because the standard filter that
applies such a label also archives ("skip the inbox"). The correct
operators for the stated intent are `-in:sent -in:drafts` (review
finding F18, 2026-08-19). The failure mode is silent under-detection: a
missed rejection or interview invite just looks like "no updates".
"""
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GMAIL_SYNC = REPO / ".claude" / "commands" / "gmail-sync.md"


class TestGmailQueryOperators(unittest.TestCase):
    def setUp(self):
        self.text = GMAIL_SYNC.read_text(encoding="utf-8")

    def test_query_excludes_sent_and_drafts_explicitly(self):
        self.assertIn(
            "-in:sent -in:drafts",
            self.text,
            "the query must exclude sent/drafts with negative operators, "
            "which keep archived and label-filtered mail in scope",
        )

    def test_query_never_restricts_to_the_inbox(self):
        self.assertNotIn(
            "in:inbox",
            self.text.replace("-in:sent", "").replace("-in:drafts", ""),
            "in:inbox silently drops archived mail and everything a "
            "label-and-archive filter routed past the inbox - exactly the "
            "mail the label search in Step 3.1 exists to find",
        )


class TestOptionalSecondaryMailboxSource(unittest.TestCase):
    def setUp(self):
        self.text = GMAIL_SYNC.read_text(encoding="utf-8")

    def test_secondary_mailbox_comes_from_local_profile_configuration(self):
        self.assertIn("<SECONDARY_EMAIL>", self.text)
        self.assertIn("Mail Sync Preferences", self.text)
        self.assertIn("Codex internal browser", self.text)
        self.assertIn("https://mail.google.com/mail/", self.text)
        self.assertNotIn("external-browser", self.text)
        self.assertIn("Optional secondary Gmail browser search", self.text)
        self.assertNotIn("@njit.edu", self.text)

    def test_secondary_source_has_independent_idempotency_state(self):
        self.assertIn('"last_secondary_sync": null', self.text)
        self.assertIn('"processed_secondary_message_keys": []', self.text)
        self.assertIn("Do not advance a source's cursor", self.text)

    def test_browser_credentials_are_never_inspected(self):
        self.assertIn("Never inspect cookies", self.text)
        self.assertIn("Never use cookies, session tokens, or credentials as a key", self.text)

    def test_partial_source_failure_is_visible(self):
        self.assertIn("never describe a partial run as complete coverage", self.text)
        self.assertIn("Secondary Gmail (`<SECONDARY_EMAIL>`): <completed / not configured / unavailable, reason>", self.text)


class TestRejectionAutoWrite(unittest.TestCase):
    def setUp(self):
        self.text = GMAIL_SYNC.read_text(encoding="utf-8")

    def test_confirmed_rejections_require_local_opt_in_and_safeguards(self):
        for needle in (
            "Automatic rejection recording is disabled by default",
            "explicitly authorized",
            "full email body contains an explicit rejection or closure statement",
            "identify exactly one open tracker row",
            "all mailboxes remain read-only",
        ):
            self.assertIn(needle, self.text)

    def test_other_status_changes_still_require_approval(self):
        self.assertIn("Confirmed rejections are the sole automatic status write", self.text)
        self.assertIn(
            "Application acknowledgements, assessments, interviews, and offers still require approval",
            self.text,
        )
        self.assertNotIn("but it never writes on its own", self.text)

    def test_automatic_rejection_does_not_infer_a_submission_date(self):
        compact = " ".join(self.text.split())
        self.assertIn("do not replace the row's date with an inferred submission date", compact)
        self.assertIn("--date <email-date>` only for a drafted-row acknowledgement", compact)
        self.assertIn("For an automatically authorized rejection on a drafted row, keep the existing date", compact)


if __name__ == "__main__":
    unittest.main()
