import csv
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "tools" / "job_state.py"
HEADER = [
    "date",
    "company",
    "sector",
    "role",
    "role_type",
    "channel",
    "status",
    "contact_person",
    "fit_rating",
    "notes",
    "cv_file",
    "cover_letter_file",
    "source",
    "deadline",
    "application_id",
    "archive_path",
]


def run_cli(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    return result


def write_rows(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


class JobStateCliTests(unittest.TestCase):
    def test_snapshot_path_hash_and_verification_are_deterministic(self):
        url = "https://careers.example/jobs/analyst-123"
        expected_name = hashlib.sha256(url.encode("utf-8")).hexdigest() + ".md"
        path_plan = json.loads(
            run_cli("snapshot-path", "--url", url).stdout
        )
        self.assertTrue(path_plan["posting_snapshot"].endswith(expected_name))

        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / expected_name
            snapshot.write_text("Full posting text\n", encoding="utf-8")
            hash_plan = json.loads(
                run_cli("snapshot-hash", "--path", str(snapshot)).stdout
            )
            fetched_at = datetime.now(timezone.utc).isoformat()
            verify = json.loads(
                run_cli(
                    "snapshot-verify",
                    "--path",
                    str(snapshot),
                    "--expected-sha",
                    hash_plan["snapshot_sha256"],
                    "--fetched-at",
                    fetched_at,
                ).stdout
            )
            self.assertTrue(verify["valid"])

            mismatch = json.loads(
                run_cli(
                    "snapshot-verify",
                    "--path",
                    str(snapshot),
                    "--expected-sha",
                    "0" * 64,
                    "--fetched-at",
                    fetched_at,
                ).stdout
            )
            self.assertFalse(mismatch["valid"])

    def test_url_normalization_removes_tracking_and_preserves_identity_fields(self):
        first = json.loads(
            run_cli(
                "normalize-url",
                "--url",
                "HTTPS://Careers.Example/jobs/123?utm_source=x&job=42&b=2#apply",
            ).stdout
        )["canonical_url"]
        second = json.loads(
            run_cli(
                "normalize-url",
                "--url",
                "https://careers.example/jobs/123?b=2&job=42&utm_medium=email",
            ).stdout
        )["canonical_url"]
        self.assertEqual(first, second)
        self.assertIn("job=42", first)
        self.assertNotIn("utm_", first)

    def test_slug_matches_documented_single_component_rule(self):
        cases = [
            ("Novo Nordisk A/S", "Data Scientist", "novo_nordisk_as_data_scientist"),
            ("Acme", "Data Scientist / ML Engineer", "acme_data_scientist_ml_engineer"),
            ("Ørsted A/S", "ML Engineer", "ørsted_as_ml_engineer"),
            ("../..", "Data Scientist", "data_scientist"),
        ]
        for company, role, expected in cases:
            with self.subTest(company=company, role=role):
                result = run_cli("slug", "--company", company, "--role", role)
                self.assertEqual(json.loads(result.stdout)["archive_slug"], expected)

    def test_slug_rejects_an_empty_result(self):
        result = run_cli(
            "slug", "--company", "../..", "--role", "///", check=False
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("safe archive name", result.stderr)

    def test_upsert_is_dry_run_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            tracker = Path(directory) / "tracker.csv"
            result = run_cli(
                "upsert-draft",
                "--tracker",
                str(tracker),
                "--company",
                "Acme",
                "--role",
                "Analyst",
                "--fit-rating",
                "78",
                "--cv-file",
                "cv/main_acme_analyst.tex",
            )
            plan = json.loads(result.stdout)
            self.assertEqual(plan["action"], "append_new")
            self.assertFalse(plan["written"])
            self.assertFalse(tracker.exists())

    def test_upsert_writes_new_row_and_migrates_legacy_header(self):
        with tempfile.TemporaryDirectory() as directory:
            tracker = Path(directory) / "tracker.csv"
            legacy_header = HEADER[:13]
            write_rows(
                tracker,
                legacy_header,
                [
                    {
                        field: value
                        for field, value in zip(
                            legacy_header,
                            [
                                "2026-01-01",
                                "Old Co",
                                "",
                                "Old Role",
                                "",
                                "online",
                                "rejected",
                                "",
                                "55",
                                "closed",
                                "old.tex",
                                "",
                                "https://old.example",
                            ],
                        )
                    }
                ],
            )
            result = run_cli(
                "upsert-draft",
                "--tracker",
                str(tracker),
                "--company",
                "Acme",
                "--role",
                "Analyst",
                "--fit-rating",
                "78",
                "--cv-file",
                "cv/main_acme_analyst.tex",
                "--deadline",
                "2026-09-30",
                "--write",
            )
            plan = json.loads(result.stdout)
            self.assertTrue(plan["header_migrated"])
            fields, rows = read_rows(tracker)
            self.assertEqual(fields, HEADER)
            self.assertEqual(rows[0]["source"], "https://old.example")
            self.assertEqual(rows[0]["deadline"], "")
            self.assertEqual(rows[1]["deadline"], "2026-09-30")

    def test_submitted_row_cannot_be_overwritten_by_a_redraft(self):
        with tempfile.TemporaryDirectory() as directory:
            tracker = Path(directory) / "tracker.csv"
            fields = HEADER + ["custom"]
            row = {field: "" for field in fields}
            row.update(
                {
                    "date": "2026-08-01",
                    "company": "Acme",
                    "role": "Analyst",
                    "status": "interview",
                    "notes": "2026-08-10 phone screen",
                    "cover_letter_file": "cover_letters/old.tex",
                    "deadline": "2026-09-01",
                    "custom": "keep-me",
                }
            )
            write_rows(tracker, fields, [row])
            before = tracker.read_bytes()
            result = run_cli(
                "upsert-draft",
                "--tracker",
                str(tracker),
                "--company",
                "acme",
                "--role",
                "analyst",
                "--fit-rating",
                "81",
                "--cv-file",
                "cv/new.tex",
                "--write",
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("submitted application", result.stderr)
            self.assertEqual(tracker.read_bytes(), before)

    def test_drafted_row_can_be_refreshed_without_losing_extra_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            tracker = Path(directory) / "tracker.csv"
            fields = HEADER + ["custom"]
            row = {field: "" for field in fields}
            row.update(
                {
                    "date": "2026-08-01",
                    "company": "Acme",
                    "role": "Analyst",
                    "status": "drafted",
                    "cover_letter_file": "cover_letters/old.tex",
                    "custom": "keep-me",
                }
            )
            write_rows(tracker, fields, [row])
            run_cli(
                "upsert-draft",
                "--tracker",
                str(tracker),
                "--company",
                "Acme",
                "--role",
                "Analyst",
                "--fit-rating",
                "81",
                "--cv-file",
                "cv/new.tex",
                "--write",
            )
            _, rows = read_rows(tracker)
            self.assertEqual(rows[0]["fit_rating"], "81")
            self.assertEqual(rows[0]["cv_file"], "cv/new.tex")
            self.assertEqual(rows[0]["cover_letter_file"], "cover_letters/old.tex")
            self.assertEqual(rows[0]["custom"], "keep-me")

    def test_validation_error_never_changes_tracker(self):
        with tempfile.TemporaryDirectory() as directory:
            tracker = Path(directory) / "tracker.csv"
            row = {field: "" for field in HEADER}
            row.update({"company": "Existing", "role": "Role", "status": "applied"})
            write_rows(tracker, HEADER, [row])
            before = tracker.read_bytes()
            result = run_cli(
                "upsert-draft",
                "--tracker",
                str(tracker),
                "--company",
                "///",
                "--role",
                "...",
                "--fit-rating",
                "101",
                "--cv-file",
                "cv/new.tex",
                "--write",
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertEqual(tracker.read_bytes(), before)

    def test_malformed_tracker_is_rejected_without_rewrite(self):
        with tempfile.TemporaryDirectory() as directory:
            tracker = Path(directory) / "tracker.csv"
            tracker.write_text(
                ",".join(HEADER) + "\n" + ",".join([""] * len(HEADER) + ["extra"]) + "\n",
                encoding="utf-8",
            )
            before = tracker.read_bytes()
            result = run_cli("list-open", "--tracker", str(tracker), check=False)
            self.assertEqual(result.returncode, 2)
            self.assertIn("more cells", result.stderr)
            self.assertEqual(tracker.read_bytes(), before)

    def test_missing_optional_tail_cells_are_migrated_as_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            tracker = Path(directory) / "tracker.csv"
            tracker.write_text(
                ",".join(HEADER) + "\n"
                + ",".join(
                    [
                        "2026-08-30",
                        "Acme",
                        "",
                        "Analyst",
                        "",
                        "online",
                        "applied",
                        "",
                        "70",
                        "",
                        "cv/acme.pdf",
                        "",
                        "https://example.test/job",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            result = json.loads(run_cli("list-open", "--tracker", str(tracker)).stdout)
            self.assertEqual(result["open"][0]["deadline"], "")

    def test_status_regression_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            tracker = Path(directory) / "tracker.csv"
            row = {field: "" for field in HEADER}
            row.update({"company": "Acme", "role": "Analyst", "status": "offer"})
            write_rows(tracker, HEADER, [row])
            result = run_cli(
                "update-status",
                "--tracker",
                str(tracker),
                "--company",
                "Acme",
                "--role",
                "Analyst",
                "--status",
                "interview",
                "--write",
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("status regression", result.stderr)

    def test_legacy_rows_get_unique_application_ids_dry_run_first(self):
        with tempfile.TemporaryDirectory() as directory:
            tracker = Path(directory) / "tracker.csv"
            legacy = HEADER[:14]
            rows = []
            for _ in range(2):
                row = {field: "" for field in legacy}
                row.update(
                    {
                        "date": "2026-08-30",
                        "company": "Acme",
                        "role": "Analyst",
                        "status": "rejected",
                        "source": "https://careers.example/jobs/42",
                    }
                )
                rows.append(row)
            write_rows(tracker, legacy, rows)
            before = tracker.read_bytes()
            plan = json.loads(
                run_cli("migrate-identities", "--tracker", str(tracker)).stdout
            )
            self.assertEqual(tracker.read_bytes(), before)
            self.assertEqual(len(plan["changed"]), 2)
            self.assertNotEqual(
                plan["changed"][0]["application_id"],
                plan["changed"][1]["application_id"],
            )
            run_cli(
                "migrate-identities",
                "--tracker",
                str(tracker),
                "--write",
            )
            fields, written = read_rows(tracker)
            self.assertEqual(fields, HEADER)
            self.assertTrue(all(row["archive_path"] for row in written))

    def test_final_match_appends_instead_of_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            tracker = Path(directory) / "tracker.csv"
            row = {field: "" for field in HEADER}
            row.update({"company": "Acme", "role": "Analyst", "status": "no response"})
            write_rows(tracker, HEADER, [row])
            result = run_cli(
                "upsert-draft",
                "--tracker",
                str(tracker),
                "--company",
                "Acme",
                "--role",
                "Analyst",
                "--fit-rating",
                "70",
                "--cv-file",
                "cv/new.tex",
                "--write",
            )
            self.assertEqual(json.loads(result.stdout)["action"], "append_after_final")
            _, rows = read_rows(tracker)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["status"], "no response")
            self.assertEqual(rows[1]["status"], "drafted")

    def test_repeat_application_gets_a_distinct_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            tracker = Path(directory) / "tracker.csv"
            first = run_cli(
                "add-application",
                "--tracker",
                str(tracker),
                "--company",
                "Acme",
                "--role",
                "Analyst",
                "--date",
                "2026-08-30",
                "--status",
                "no_response",
                "--source",
                "https://jobs.example/acme-analyst",
                "--write",
            )
            second = run_cli(
                "upsert-draft",
                "--tracker",
                str(tracker),
                "--company",
                "Acme",
                "--role",
                "Analyst",
                "--date",
                "2026-08-30",
                "--fit-rating",
                "70",
                "--cv-file",
                "cv/main_acme_analyst.tex",
                "--source",
                "https://jobs.example/acme-analyst",
                "--write",
            )
            self.assertNotEqual(
                json.loads(first.stdout)["application_id"],
                json.loads(second.stdout)["application_id"],
            )
            _, rows = read_rows(tracker)
            self.assertEqual(len({row["archive_path"] for row in rows}), 2)

    def test_status_update_preserves_unrelated_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            tracker = Path(directory) / "tracker.csv"
            fields = HEADER + ["custom"]
            row = {field: "" for field in fields}
            row.update(
                {
                    "date": "2026-08-20",
                    "company": "Acme",
                    "role": "Analyst",
                    "status": "applied",
                    "deadline": "2026-09-01",
                    "custom": "keep-me",
                }
            )
            write_rows(tracker, fields, [row])
            result = run_cli(
                "update-status",
                "--tracker",
                str(tracker),
                "--company",
                "Acme",
                "--role",
                "Analyst",
                "--status",
                "interview",
                "--note",
                "2026-08-29 gmail-sync: interview invite",
                "--write",
            )
            plan = json.loads(result.stdout)
            self.assertEqual(plan["previous_status"], "applied")
            _, rows = read_rows(tracker)
            self.assertEqual(rows[0]["status"], "interview")
            self.assertEqual(rows[0]["deadline"], "2026-09-01")
            self.assertEqual(rows[0]["custom"], "keep-me")

    def test_list_open_excludes_legacy_final_spellings(self):
        with tempfile.TemporaryDirectory() as directory:
            tracker = Path(directory) / "tracker.csv"
            rows = []
            for company, status in (
                ("Open Co", "applied"),
                ("Closed One", "no response"),
                ("Closed Two", "offer declined"),
            ):
                row = {field: "" for field in HEADER}
                row.update({"company": company, "role": "Analyst", "status": status})
                rows.append(row)
            write_rows(tracker, HEADER, rows)
            result = run_cli("list-open", "--tracker", str(tracker))
            open_rows = json.loads(result.stdout)["open"]
            self.assertEqual([row["company"] for row in open_rows], ["Open Co"])


if __name__ == "__main__":
    unittest.main()
