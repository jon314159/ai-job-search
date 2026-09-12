"""Offline behavioral tests for bounded scrape mechanics; never fetch a job."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tools import scrape_pipeline as pipe


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.key = "https://example.com/jobs/42"
        self.source = self.base / "source.txt"
        self.source.write_bytes(b"Operations Analyst\r\nExcel and SQL required.\r\nRemote in NJ.\r\n")
        self.job = {"key": self.key, "url": self.key, "title": "Operations Analyst", "company": "Example", "status": "new",
                    "snapshot_source": str(self.source), "portal": "example-search"}
        for name in pipe.PROFILE_FILES:
            path = self.base / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture rubric/profile " + name, encoding="utf-8")

    def state(self):
        return pipe.load_state(self.base)

    def write_state(self, state):
        pipe.save_json(self.base / "job_scraper/seen_jobs.json", state)

    def persist(self):
        pipe.persist(self.base, [self.job], True)

    def result(self, budget=6000):
        row = self.state()["seen"][self.key]
        return {"key": self.key, "status": "scored", "scores": dict(zip(pipe.DIMENSIONS, [74, 66, 90, 92])),
                "score_evidence": {d: "specific posting and candidate evidence" for d in pipe.DIMENSIONS},
                **{g: "PASS" for g in pipe.GATES}, "evidence_confidence": "HIGH", "source_confidence": "EMPLOYER",
                "geographic_priority": "PREFERRED_REMOTE", "strengths": ["Excel"], "gaps": ["PMO"],
                "snapshot_sha256": row["snapshot_sha256"],
                "reviewed_parts": list(range(len(pipe.chunks(pipe.verified_text(self.base, row), budget))))}

    def test_html_removes_navigation_scripts_but_keeps_late_restrictions(self):
        text = pipe.posting_text('<html><nav>Search 500 other jobs</nav><script>bad()</script><style>css</style>'
                                 '<h1>Analyst</h1><p>Excel &amp; SQL</p><p>Must reside in NJ.</p>'
                                 '<footer>Travel 25%; no sponsorship.</footer></html>', "html")
        for fragment in ["Analyst", "Excel & SQL", "Must reside in NJ", "Travel 25%", "no sponsorship"]:
            self.assertIn(fragment, text)
        for fragment in ["Search 500", "bad()", "css", "<p>"]:
            self.assertNotIn(fragment, text)
        with self.assertRaises(ValueError):
            pipe.posting_text("<html><p>Raw</p></html>")

    def test_long_document_packets_are_lossless_and_require_every_part(self):
        text = "Responsibilities and qualifications.\n" * 600 + "FINAL REQUIREMENT: active clearance required."
        self.source.write_bytes(text.encode())
        self.persist()
        parts, index = [], 0
        while True:
            packet = pipe.packet(self.base, self.key, index, 1000)
            self.assertLessEqual(len(packet["posting_text"]), 1000)
            parts.append(packet["posting_text"])
            if packet["next_part"] is None:
                break
            index = packet["next_part"]
        self.assertEqual("".join(parts), text)
        result = self.result(1000)
        result["reviewed_parts"] = [0]
        with self.assertRaisesRegex(ValueError, "every part"):
            pipe.cache(self.base, self.key, result, 1000)
        pipe.cache(self.base, self.key, self.result(1000), 1000)
        self.assertTrue(pipe.cache(self.base, self.key)["hit"])

    def test_discovery_dedupes_slug_tracking_and_req_but_preserves_distinct_roles(self):
        common = {"title": "Analyst", "company": "Example", "description": "x" * 100000}
        rows = [dict(common, url="https://www.linkedin.com/jobs/view/analyst-at-example-123?utm_source=x"),
                dict(common, url="https://www.linkedin.com/jobs/view/123"),
                dict(common, url="https://example.com/jobs/a", requisition_id="a", country="US"),
                dict(common, url="https://other.example/jobs/a", requisition_id="a", country="CA", authoritative_url="https://employer.example/jobs/a"),
                dict(common, url="https://example.com/jobs/b", requisition_id="b")]
        source, output = self.base / "search.json", self.base / "cards.json"
        pipe.save_json(source, {"results": rows})
        report = pipe.prepare(self.base, [source], output)
        cards = pipe.read_json(output)
        self.assertEqual(report["candidates"], 3)
        self.assertEqual(report["duplicates_consolidated"], 2)
        self.assertNotIn("description", json.dumps(cards))
        self.assertEqual(len(cards[0]["discovered_urls"]), 2)
        self.assertEqual(cards[1]["url"], "https://employer.example/jobs/a")
        self.assertEqual(cards[1]["metadata_conflicts"]["country"], ["US", "CA"])
        self.assertLess(output.stat().st_size, 4000)

    def test_recovery_and_tracker_exclusions(self):
        self.persist()
        source, output = self.base / "empty.json", self.base / "cards.json"
        pipe.save_json(source, [])
        self.assertEqual(pipe.prepare(self.base, [source], output)["candidates"], 1)
        (self.base / "job_search_tracker.csv").write_text("company,role,status\nExample,Operations Analyst,applied\n")
        self.assertEqual(pipe.prepare(self.base, [source], output)["candidates"], 0)
        self.assertEqual(pipe.read_json(output)[0]["skip_reason"], "tracked")
        self.assertFalse(pipe.cache(self.base, self.key)["hit"])

    def test_active_queue_excludes_applied_jobs_and_preserves_distinct_final_openings(self):
        self.persist()
        result = self.result()
        pipe.cache(self.base, self.key, result)
        pipe.persist(self.base, [dict(pipe.cache(self.base, self.key)["result"], status="ranked")], True)
        output = self.base / "active.json"

        (self.base / "job_search_tracker.csv").write_text(
            "company,role,status,source\nExample,Operations Analyst,rejected,https://example.com/jobs/other\n",
            encoding="utf-8",
        )
        self.assertEqual(pipe.active_queue(self.base, output)["active"], 1)

        state = self.state()
        state["seen"][self.key]["requisition_id"] = "REQ-A"
        self.write_state(state)
        (self.base / "job_search_tracker.csv").write_text(
            "company,role,status,source,requisition_id\nExample,Operations Analyst,applied,,REQ-B\n",
            encoding="utf-8",
        )
        self.assertEqual(pipe.active_queue(self.base, output)["active"], 1)

        (self.base / "job_search_tracker.csv").write_text(
            "company,role,status,source\nExample,Operations Analyst,applied,\n",
            encoding="utf-8",
        )
        report = pipe.active_queue(self.base, output)
        self.assertEqual(report["active"], 0)
        self.assertEqual(report["tracked_excluded_by_status"], {"applied": 1})
        self.assertEqual(pipe.read_json(output), [])

        (self.base / "job_search_tracker.csv").write_text(
            "company,role,status,source\nOther,Other,rejected,https://example.com/jobs/42\n",
            encoding="utf-8",
        )
        self.assertEqual(pipe.active_queue(self.base, output)["tracked_excluded"], 1)

    def test_persistence_dry_run_exact_bytes_and_unrelated_state_preservation(self):
        self.assertFalse(pipe.persist(self.base, [self.job])["write"])
        self.assertFalse((self.base / "job_scraper").exists())
        self.persist()
        state = self.state()
        row = state["seen"][self.key]
        path = self.base / row["posting_snapshot"]
        self.assertEqual(path.read_bytes(), self.source.read_bytes())
        self.assertEqual(row["snapshot_sha256"], pipe.digest(path.read_bytes()))
        state["custom"] = "keep"
        row["private_note"] = "keep"
        row["first_seen"] = "2020-01-01"
        self.write_state(state)
        pipe.persist(self.base, [dict(self.job, location="NJ")], True)
        updated = self.state()
        self.assertEqual(updated["custom"], "keep")
        self.assertEqual(updated["seen"][self.key]["private_note"], "keep")
        self.assertEqual(updated["seen"][self.key]["first_seen"], "2020-01-01")

    def test_invalid_batch_has_no_partial_state_or_snapshot_writes(self):
        with self.assertRaises(ValueError):
            pipe.persist(self.base, [self.job, dict(self.job, status="invalid")], True)
        self.assertFalse((self.base / "job_scraper").exists())

    def test_stale_tampered_and_traversal_snapshots_fail_closed(self):
        self.persist()
        state = self.state()
        row = state["seen"][self.key]
        original = row["snapshot_fetched_at"]
        row["snapshot_fetched_at"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        self.write_state(state)
        with self.assertRaises(ValueError):
            pipe.packet(self.base, self.key)
        row["snapshot_fetched_at"] = original
        row["snapshot_sha256"] = "wrong"
        self.write_state(state)
        with self.assertRaises(ValueError):
            pipe.cache(self.base, self.key)
        row["posting_snapshot"] = "../outside.md"
        self.write_state(state)
        with self.assertRaisesRegex(ValueError, "escapes"):
            pipe.packet(self.base, self.key)

    def test_cache_invalidates_for_every_profile_rubric_query_and_snapshot_change(self):
        self.persist()
        for name in pipe.PROFILE_FILES:
            pipe.cache(self.base, self.key, self.result())
            self.assertTrue(pipe.cache(self.base, self.key)["hit"])
            path = self.base / name
            path.write_bytes(path.read_bytes() + b" changed")
            self.assertFalse(pipe.cache(self.base, self.key)["hit"])
        pipe.cache(self.base, self.key, self.result())
        self.assertFalse(pipe.cache(self.base, self.key, force=True)["hit"])
        self.source.write_bytes(b"Different role requirements")
        self.persist()
        self.assertFalse(pipe.cache(self.base, self.key)["hit"])

    def test_fit_weights_gates_and_metadata_survive_cache_and_persistence(self):
        self.persist()
        result = self.result()
        result["location_verdict"] = "FLAG"
        result["location_note"] = "Hybrid schedule needs confirmation"
        pipe.cache(self.base, self.key, result)
        cached = pipe.cache(self.base, self.key)["result"]
        self.assertEqual(cached["rank_score"], 80)
        self.assertEqual(cached["rank_verdict"], "Strong Fit")
        self.assertEqual(cached["location_note"], result["location_note"])
        pipe.persist(self.base, [dict(cached, status="ranked")], True)
        self.assertEqual(self.state()["seen"][self.key]["score_evidence"], result["score_evidence"])
        result["language_gate"] = "FAIL"
        self.assertIsNone(pipe.score_totals(result)["rank_score"])
        with self.assertRaises(ValueError):
            pipe.persist(self.base, [dict(result, status="ranked")], True)
        result["scores"]["technical"] = float("nan")
        with self.assertRaises(ValueError):
            pipe.cache(self.base, self.key, result)

    def test_rich_dismissed_and_expired_records_are_not_overwritten(self):
        self.persist()
        with self.assertRaises(ValueError):
            pipe.persist(self.base, [dict(self.job, status="skipped", skip_reason="duplicate")], True)
        state = self.state()
        state["seen"][self.key]["status"] = "expired"
        self.write_state(state)
        with self.assertRaises(ValueError):
            pipe.persist(self.base, [self.job], True)
        pipe.persist(self.base, [dict(self.job, live_open_verified=True)], True)
        state = self.state()
        state["seen"][self.key]["skip_reason"] = "user_not_interested"
        self.write_state(state)
        self.assertFalse(pipe.cache(self.base, self.key)["hit"])

    def test_page_is_bounded_without_losing_rows(self):
        path = self.base / "rows.json"
        rows = [{"title": str(i), "url": "x" * 100} for i in range(17)]
        pipe.save_json(path, rows)
        collected, offset = [], 0
        while offset is not None:
            result = pipe.page(path, offset, 5, 500)
            self.assertLessEqual(len(json.dumps(result["rows"])), 500)
            collected += result["rows"]
            offset = result["next_offset"]
        self.assertEqual(collected, rows)

    def test_batch_plan_reuses_cache_and_keeps_other_jobs_independent(self):
        self.persist()
        out = self.base / "run_test"
        first = pipe.plan(self.base, [self.key, self.key, "missing"], out)
        self.assertEqual(first["packets"], 1)
        self.assertEqual(first["held"], 1)
        self.assertNotIn("posting_text", json.dumps(first))
        self.assertEqual(pipe.read_json(out / "packets.json")[0]["key"], self.key)
        pipe.store_analyses(self.base, [self.result()])
        again = pipe.plan(self.base, [self.key], out)
        self.assertEqual(again["cached"], 1)
        self.assertEqual(again["packets"], 0)
        self.assertEqual(pipe.plan(self.base, [self.key], out, force=True)["packets"], 1)

    def test_batch_cache_rejects_malformed_result_before_any_writes(self):
        self.persist()
        bad = self.result()
        bad.update(key="missing", scores={})
        with self.assertRaises((ValueError, KeyError)):
            pipe.store_analyses(self.base, [self.result(), bad])
        self.assertFalse(pipe.cache(self.base, self.key)["hit"])

    def test_metadata_change_invalidates_analysis_and_final_tracker_identity_excludes(self):
        self.persist()
        pipe.cache(self.base, self.key, self.result())
        state = self.state()
        state["seen"][self.key]["location"] = "Changed state restriction"
        self.write_state(state)
        self.assertFalse(pipe.cache(self.base, self.key)["hit"])
        (self.base / "job_search_tracker.csv").write_text("company,role,status,source\nOther,Other,rejected," + self.key + "\n")
        source, output = self.base / "search.json", self.base / "cards.json"
        pipe.save_json(source, [self.job])
        self.assertEqual(pipe.prepare(self.base, [source], output)["candidates"], 0)

    def test_usage_counts_unique_responses_and_compaction_not_legacy_counters(self):
        trace = self.base / "trace.jsonl"
        usage = {"input_tokens": 100, "cached_input_tokens": 80, "output_tokens": 10,
                 "reasoning_output_tokens": 3, "total_tokens": 110}
        event = {"type": "token_usage_record", "payload": {"root_turn_id": "t", "response_id": "a", "usage": usage}}
        compact = copy.deepcopy(event)
        compact["payload"]["response_id"] = "compact"
        other = copy.deepcopy(event)
        other["payload"].update(root_turn_id="other", response_id="other")
        rows = [{"type": "turn_context", "payload": {"model": "fixture-model"}}, event, event, compact, other,
                {"type": "event_msg", "payload": {"type": "token_count", "info": {"total_tokens": 999999}}}]
        trace.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
        report = pipe.usage_report(trace, "t", {"a": "discovery", "compact": "compaction"})
        self.assertEqual(report["totals"]["total_tokens"], 220)
        self.assertEqual(report["response_count"], 2)
        self.assertEqual(report["by_stage"]["compaction"]["total_tokens"], 110)
        self.assertEqual(report["by_model"]["fixture-model"]["total_tokens"], 220)
        self.assertIsNone(pipe.usage_report(trace, "missing")["totals"])

    def test_cli_pipeline_round_trip(self):
        path = self.base / "payload.json"
        pipe.save_json(path, [self.job])
        script = Path(pipe.__file__)
        def run(*args):
            result = subprocess.run([sys.executable, "-B", str(script), *map(str, args)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        self.assertTrue(run("persist", "--base", self.base, "--payload", path, "--write")["write"])
        self.assertIn("Excel and SQL", run("packet", "--base", self.base, "--key", self.key)["posting_text"])
        queue = self.base / "queue.json"
        self.assertEqual(run("queue", "--base", self.base, "--output", queue)["active"], 0)
        self.assertEqual(pipe.read_json(queue), [])


if __name__ == "__main__":
    unittest.main()
