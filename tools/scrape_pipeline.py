"""Offline scrape mechanics. No network or model calls; JSON summaries by default.

Run --help for commands. Source records and full snapshots stay on disk; packet
reads are bounded and lossless. Fit judgments remain with the canonical /rank rubric.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

try:
    from . import job_state
except ImportError:
    import job_state

VERSION = "scrape-packet-v1"
PROFILE_FILES = (
    ".claude/skills/job-application-assistant/01-candidate-profile.md",
    ".claude/skills/job-application-assistant/02-behavioral-profile.md",
    ".claude/skills/job-application-assistant/04-job-evaluation.md",
    ".claude/commands/rank.md",
    ".claude/skills/job-scraper/search-queries.md",
)
CARD_FIELDS = ("id", "title", "company", "location", "date", "url", "portal",
               "source", "requisition_id", "work_mode", "deadline", "discovered_url",
               "authoritative_url", "canonical_url", "source_confidence", "country",
               "regions", "remote_regions", "seniority", "employment_type", "work_arrangement")
GATES = ("eligibility_gate", "target_scope_gate", "location_verdict", "language_gate")
DIMENSIONS = ("technical", "experience", "behavioral", "career")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic_bytes(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".scrape-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def save_json(path, obj):
    atomic_bytes(path, (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def inside(base, relative):
    path = (Path(base) / relative).resolve()
    if not path.is_relative_to(Path(base).resolve()):
        raise ValueError("path escapes the data directory")
    return path


def load_state(base):
    path = Path(base) / "job_scraper/seen_jobs.json"
    state = read_json(path) if path.exists() else {"seen": {}}
    if not isinstance(state.get("seen"), dict):
        raise ValueError("seen must be an object")
    return state


def tracker_rows(base):
    path = Path(base) / "job_search_tracker.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def role_identity(row):
    """Return the normalized company/title identity used only as a fallback."""
    title = row.get("title") or row.get("role") or ""
    return job_state.match_text(row.get("company", "")), job_state.match_text(title)


def tracker_matches(row, tracked):
    """Match a seen/discovery row to one tracker application without hiding new reqs."""
    if identities(row) & identities(tracked):
        return True
    role = role_identity(row)
    if role != role_identity(tracked) or not all(role):
        return False
    # An open application with no shared durable identifier is still unsafe to present
    # again. Final rows require a URL/requisition match so a genuinely new opening with
    # the same company and title can return to the queue.
    if job_state.is_final(tracked.get("status", "")):
        return False
    row_req = str(row.get("requisition_id") or "").strip().casefold()
    tracked_req = str(tracked.get("requisition_id") or "").strip().casefold()
    return not (row_req and tracked_req and row_req != tracked_req)


def identities(row):
    keys = set()
    for field in ("url", "canonical_url", "authoritative_url", "discovered_url"):
        value = row.get(field)
        if value:
            url = job_state.normalize_url(value)
            keys.add("url:" + url)
            # LinkedIn's slug URL and numeric detail URL identify the same job.
            match = re.search(r"https?://(?:[\w-]+\.)?linkedin\.com/jobs/view/(?:[^/?]*-)?(\d+)(?:[/?]|$)", url)
            if match:
                keys.add("linkedin:" + match[1])
    for value in row.get("discovered_urls", []):
        keys.add("url:" + job_state.normalize_url(value))
    if row.get("company") and row.get("requisition_id"):
        keys.add("req:" + job_state.match_text(row["company"]) + ":" + str(row["requisition_id"]).strip())
    if row.get("portal") and row.get("id"):
        keys.add("portal:" + row["portal"] + ":" + str(row["id"]))
    if isinstance(row.get("source"), str) and row["source"].startswith(("https://", "http://")):
        keys.add("url:" + job_state.normalize_url(row["source"]))
    return keys


def prepare(base, inputs, output):
    """Dedupe before detail; preserve ambiguous roles and all source aliases."""
    state = load_state(base)["seen"]
    tracked = tracker_rows(base)
    known = {}
    for key, row in state.items():
        for identity in identities(row):
            known[identity] = (key, row)
    rows = []
    for path in inputs:
        data = read_json(path)
        rows.extend(data if isinstance(data, list) else data["results"])
    # Interrupted new/unverified work must not be lost in the duplicate filter.
    rows.extend(dict(row, existing_key=key) for key, row in state.items()
                if row.get("status") in {"new", "unverified"} and row.get("skip_reason") != "user_not_interested")
    groups, index, duplicates = [], {}, 0
    for raw in rows:
        if not all(isinstance(raw.get(f), str) and raw[f].strip() for f in ("title", "company", "url")):
            raise ValueError("discovery needs nonempty title, company and URL; repair degraded source first")
        row = {k: raw[k] for k in CARD_FIELDS if k in raw}
        row["url"] = job_state.normalize_url(row["url"])
        row["discovered_urls"] = sorted(set(raw.get("discovered_urls", []) + [raw["url"]]))
        ids = identities(raw)
        matches = sorted({index[x] for x in ids if x in index})
        if matches:
            target = matches[0]
            groups[target]["discovered_urls"] = sorted(set(groups[target]["discovered_urls"] + row["discovered_urls"]))
            # Preserve explicit structured restrictions/provenance from richer aliases.
            for field in CARD_FIELDS:
                if groups[target].get(field) in (None, "") and row.get(field) not in (None, ""):
                    groups[target][field] = row[field]
                elif field in {"location", "country", "regions", "remote_regions", "work_mode", "work_arrangement"} and row.get(field) not in (None, "") and groups[target].get(field) != row[field]:
                    groups[target].setdefault("metadata_conflicts", {}).setdefault(field, [groups[target][field]]).append(row[field])
            if row.get("authoritative_url"):
                groups[target]["url"] = job_state.normalize_url(row["authoritative_url"])
            # Merge bridge records without dropping aliases from either source.
            for other in matches[1:]:
                if groups[other] is not None:
                    groups[target]["discovered_urls"] = sorted(set(groups[target]["discovered_urls"] + groups[other]["discovered_urls"]))
                    groups[other] = None
                    duplicates += 1
                    for identity, group in list(index.items()):
                        if group == other:
                            index[identity] = target
            duplicates += 1
        else:
            target = len(groups)
            old = next((known[x] for x in sorted(ids) if x in known), None)
            reason = "tracked" if any(tracker_matches(row, application) for application in tracked) else None
            if not reason and old and (old[1].get("status") not in {"new", "unverified"} or old[1].get("skip_reason") == "user_not_interested"):
                reason = "duplicate"
            row.update(key=old[0] if old else row["url"], decision="skip" if reason else "candidate", skip_reason=reason)
            groups.append(row)
        for identity in ids:
            index[identity] = target
    groups = [r for r in groups if r is not None]
    save_json(output, groups)
    return {"input_rows_including_recovery": len(rows), "unique": len(groups), "duplicates_consolidated": duplicates,
            "candidates": sum(r["decision"] == "candidate" for r in groups), "file": str(output)}


QUEUE_FIELDS = tuple(dict.fromkeys(CARD_FIELDS + (
    "rank_score", "rank_verdict", "rank_date", "geographic_priority", "strengths", "gaps",
    "evidence_confidence", "compensation", "first_seen", "posted_date", "availability_checked_at",
    "availability_status", "availability_checked_url", "location_note", "language_note",
)))


def active_queue(base, output):
    """Write ranked opportunities that are not already represented in the tracker."""
    state = load_state(base)["seen"]
    tracked = tracker_rows(base)
    rows, excluded = [], {}
    ranked_seen = 0
    for key, row in state.items():
        if row.get("status") != "ranked" or row.get("skip_reason") == "user_not_interested":
            continue
        ranked_seen += 1
        application = next((item for item in tracked if tracker_matches(row, item)), None)
        if application:
            status = job_state.normalize_status(application.get("status", "")) or "unknown"
            excluded[status] = excluded.get(status, 0) + 1
            continue
        card = {"key": key}
        card.update({field: row[field] for field in QUEUE_FIELDS if field in row})
        rows.append(card)
    save_json(output, rows)
    return {"ranked_seen": ranked_seen, "tracked_excluded": sum(excluded.values()),
            "tracked_excluded_by_status": excluded, "active": len(rows), "file": str(output)}


class PostingText(HTMLParser):
    """Keep text in document order. Do not use keyword filters on qualifications."""
    DROP = {"script", "style", "nav", "noscript", "svg", "template"}
    BLOCK = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "tr", "section"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden, self.parts = [], []

    def handle_starttag(self, tag, attrs):
        if tag in self.DROP:
            self.hidden.append(tag)
        if not self.hidden and tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if self.hidden:
            if tag == self.hidden[-1]:
                self.hidden.pop()
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def posting_text(text, format="text"):
    if format == "html":
        parser = PostingText()
        parser.feed(text)
        text = "".join(parser.parts)
        text = "\n".join(" ".join(line.split()) for line in text.splitlines())
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
    elif re.search(r"<(?:html|body|script|div|p)(?:\s|>)", text, re.I):
        raise ValueError("HTML supplied as text; extract the selected posting with --format html")
    if not text.strip():
        raise ValueError("empty posting text")
    return text


def chunks(text, budget=6000):
    if budget < 256 or budget > 12000:
        raise ValueError("chunk budget must be 256..12000 characters")
    result = []
    while text:
        end = min(budget, len(text))
        if end < len(text):
            boundary = text.rfind("\n", 0, end)
            if boundary > end // 2:
                end = boundary + 1
        result.append(text[:end])
        text = text[end:]
    return result


def verified_text(base, row):
    path = inside(base, row["posting_snapshot"])
    check = job_state.snapshot_verify_plan(SimpleNamespace(path=path, expected_sha=row["snapshot_sha256"],
                    fetched_at=row["snapshot_fetched_at"], max_age_hours=24))
    if not check["valid"]:
        raise ValueError("snapshot stale, missing, future-dated or hash-mismatched; verify/refetch before analysis")
    return posting_text(path.read_bytes().decode("utf-8"))


def packet(base, key, part=0, budget=6000):
    row = load_state(base)["seen"][key]
    text = verified_text(base, row)
    parts = chunks(text, budget)
    if part < 0 or part >= len(parts):
        raise ValueError("part out of range")
    return {"version": VERSION, "key": key, "snapshot_sha256": row["snapshot_sha256"],
            "job": {k: row[k] for k in CARD_FIELDS if k in row}, "part": part, "parts": len(parts),
            "next_part": part + 1 if part + 1 < len(parts) else None,
            "posting_text": parts[part], "complete_in_this_packet": len(parts) == 1,
            "estimated_text_tokens": math.ceil(len(parts[part]) / 4)}


def analysis_key(base, row):
    verified_text(base, row)
    fields = CARD_FIELDS + ("authoritative_url", "source_confidence", "work_arrangement", "compensation", "employment_type")
    material = [VERSION, row["snapshot_sha256"], {k: row.get(k) for k in fields}]
    # Include all extraction/scoring inputs; missing files fail closed.
    material.extend(digest((Path(base) / path).read_bytes()) for path in PROFILE_FILES)
    return digest(json.dumps(material).encode("utf-8"))


def validate_analysis(result):
    if result.get("status") != "scored":
        raise ValueError("cache accepts completed scored triage only; live closure stays outside analysis cache")
    for field in GATES:
        if result.get(field) not in {"PASS", "FLAG", "FAIL"}:
            raise ValueError("all four explicit gates are required")
    for field in DIMENSIONS:
        score = result.get("scores", {}).get(field)
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 100:
            raise ValueError("dimension scores must be finite numbers from 0 to 100")
        if not str(result.get("score_evidence", {}).get(field, "")).strip():
            raise ValueError("each score needs evidence")
    for field, allowed in [("evidence_confidence", {"HIGH", "MEDIUM", "LOW"}),
                           ("source_confidence", {"EMPLOYER", "ATS", "AGGREGATOR"}),
                           ("geographic_priority", {"PREFERRED_REMOTE", "PREFERRED_REGION", "OUTSIDE_PREFERENCE", "UNKNOWN"})]:
        if result.get(field) not in allowed:
            raise ValueError("invalid or missing " + field)
    for field in ("strengths", "gaps"):
        if not isinstance(result.get(field), list):
            raise ValueError(field + " must be a list")


def score_totals(result):
    validate_analysis(result)
    if any(result[g] == "FAIL" for g in GATES):
        return {"rank_score": None, "rank_verdict": "Excluded"}
    score = round(sum(result["scores"][d] * weight for d, weight in zip(DIMENSIONS, (.30, .25, .15, .30))))
    verdict = next(label for floor, label in [(75, "Strong Fit"), (60, "Good Fit"),
                   (45, "Moderate Fit"), (30, "Weak Fit"), (0, "Poor Fit")] if score >= floor)
    return {"rank_score": score, "rank_verdict": verdict}


def cache(base, key, result=None, budget=6000, force=False, write=True):
    row = load_state(base)["seen"][key]
    blocked = row.get("status") not in {"new", "ranked", "unverified"} or row.get("skip_reason") == "user_not_interested"
    blocked = blocked or any(tracker_matches(row, application) for application in tracker_rows(base))
    if blocked:
        if result is not None:
            raise ValueError("excluded/tracked state cannot receive a cached analysis")
        return {"hit": False, "key": key, "reason": "excluded/tracked state"}
    token = analysis_key(base, row)
    path = Path(base) / "job_scraper/analysis_cache" / (token + ".json")
    if result is None:
        if force or not path.exists():
            return {"hit": False, "key": key}
        entry = read_json(path)
        if entry.get("fingerprint") != token:
            return {"hit": False, "key": key}
        validate_analysis(entry["result"])
        return {"hit": True, "key": key, "result": dict(entry["result"], key=key)}
    validate_analysis(result)
    parts = chunks(verified_text(base, row), budget)
    if result.get("snapshot_sha256") != row["snapshot_sha256"] or result.get("reviewed_parts") != list(range(len(parts))):
        raise ValueError("analysis must attest every part of this exact snapshot")
    if result.get("key") != key:
        raise ValueError("analysis key mismatch")
    result = dict(result, **score_totals(result))
    if write:
        save_json(path, {"fingerprint": token, "result": result})
    return {"stored": write, "key": key}


def store_analyses(base, results, budget=6000):
    if len({r["key"] for r in results}) != len(results):
        raise ValueError("duplicate analysis keys")
    for result in results:
        cache(base, result["key"], result, budget, write=False)
    for result in results:
        cache(base, result["key"], result, budget)
    return {"stored": len(results)}


def plan(base, keys, output, budget=6000, force=False):
    """One cache/packet preparation call per batch; never print the whole bundle."""
    cached, packets, held = [], [], []
    for key in dict.fromkeys(keys):
        try:
            hit = cache(base, key, force=force)
            if hit.get("reason"):
                held.append({"key": key, "reason": hit["reason"]})
                continue
            if hit["hit"]:
                cached.append(hit["result"])
                continue
            first = packet(base, key, 0, budget)
            packets.append(first)
            for part in range(1, first["parts"]):
                packets.append(packet(base, key, part, budget))
        except (KeyError, ValueError, OSError) as exc:
            held.append({"key": key, "reason": str(exc)})
    directory = Path(output)
    save_json(directory / "cached.json", cached)
    save_json(directory / "packets.json", packets)
    save_json(directory / "held.json", held)
    summary = {"cached": len(cached), "packets": len(packets), "held": len(held),
               "posting_characters": sum(len(p["posting_text"]) for p in packets),
               "directory": str(directory), "budget": budget}
    save_json(directory / "manifest.json", summary)
    return summary


def persist(base, payload, write=False):
    """Additive updates; validate whole batch before writing. Owner-only mutation."""
    state = load_state(base)
    before = digest(json.dumps(state, sort_keys=True).encode())
    snapshots, changed = {}, []
    tracked = tracker_rows(base)
    for update in payload:
        row = dict(update)
        source = row.pop("snapshot_source", None)
        format = row.pop("snapshot_format", "text")
        key = row.pop("key", None) or job_state.normalize_url(row["url"])
        old = state["seen"].get(key, {})
        if row.get("status") not in {"new", "ranked", "skipped", "unverified", "expired"}:
            raise ValueError("invalid scrape status")
        if old.get("skip_reason") == "user_not_interested" or old.get("status") in {"applied", "drafted", "interview", "offer", "hired", "rejected"}:
            raise ValueError("cannot overwrite dismissed or application state")
        if old and row.get("skip_reason") == "duplicate":
            raise ValueError("duplicate discovery must not replace an existing rich record")
        if old.get("status") == "expired" and row.get("status") in {"new", "ranked"} and not (source and row.get("live_open_verified") is True):
            raise ValueError("reviving expired state requires a fresh source and live-open proof")
        merged = dict(old, **row)
        for field in ("company", "title", "url"):
            if not isinstance(merged.get(field), str) or not merged[field].strip():
                raise ValueError("missing " + field)
        merged["url"] = job_state.normalize_url(merged["url"])
        if merged["status"] in {"new", "ranked"} and any(tracker_matches(merged, application) for application in tracked):
            raise ValueError("tracked job cannot enter scoring")
        if old.get("first_seen"):
            merged["first_seen"] = old["first_seen"]
        else:
            merged.setdefault("first_seen", datetime.now(timezone.utc).date().isoformat())
        if source:
            if format not in {"html", "text"}:
                raise ValueError("snapshot_format must be text or html")
            data = posting_text(Path(source).read_bytes().decode("utf-8"), format).encode("utf-8")
            sha = digest(data)
            # Immutable content-qualified name keeps previous state valid if interrupted.
            relative = "job_scraper/postings/" + digest(merged["url"].encode()) + "-" + sha + ".md"
            snapshots[relative] = data
            merged.update(posting_snapshot=relative, snapshot_sha256=sha,
                          snapshot_fetched_at=datetime.now(timezone.utc).isoformat())
        if merged["status"] in {"new", "ranked"}:
            if not source:
                verified_text(base, merged)
            if merged["status"] == "ranked" and any(merged.get(g) == "FAIL" for g in GATES):
                raise ValueError("hard gate FAIL cannot be ranked")
            if merged["status"] == "ranked":
                merged.update(score_totals(dict(merged, status="scored")))
        state["seen"][key] = merged
        changed.append(key)
    if write:
        if digest(json.dumps(load_state(base), sort_keys=True).encode()) != before:
            raise ValueError("state changed during planning; repeat dry run")
        for relative, data in snapshots.items():
            path = inside(base, relative)
            atomic_bytes(path, data)
            if job_state._file_sha256(path) != digest(data):
                raise ValueError("snapshot byte verification failed")
        save_json(Path(base) / "job_scraper/seen_jobs.json", state)
    return {"write": write, "updated": len(changed), "keys": changed, "snapshots": len(snapshots), "total_seen": len(state["seen"])}


def page(path, offset=0, limit=5, budget=12000):
    if offset < 0 or not 1 <= limit <= 10 or not 256 <= budget <= 12000:
        raise ValueError("invalid page bounds")
    rows = read_json(path)
    selected = []
    for row in rows[offset:offset + limit]:
        if len(json.dumps(selected + [row], ensure_ascii=False)) > budget:
            break
        selected.append(row)
    if not selected and offset < len(rows):
        raise ValueError("one record exceeds page budget; inspect its source without dumping the pool")
    end = offset + len(selected)
    return {"rows": selected, "next_offset": end if end < len(rows) else None, "total": len(rows)}


def usage_report(trace, turn, stages=None):
    """Use response ledger, not legacy counters which can omit compaction."""
    calls, models, totals, seen = [], {}, {}, set()
    stage_map = stages or {}
    model, malformed = "unknown", 0
    with Path(trace).open(encoding="utf-8") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            data = event.get("payload", {})
            if event.get("type") == "turn_context":
                model = data.get("model", "unknown")
            if event.get("type") != "token_usage_record" or data.get("root_turn_id", data.get("turn_id")) != turn:
                continue
            identity = data.get("response_id")
            if not identity or identity in seen:
                continue
            seen.add(identity)
            usage = dict(data["usage"])
            stage = stage_map.get(identity, "unassigned")
            calls.append({"response_id": identity, "model": model, "stage": stage, "usage": usage})
            for target in (totals, models.setdefault(model, {})):
                for field, value in usage.items():
                    target[field] = target.get(field, 0) + value
    by_stage = {}
    for call in calls:
        total = by_stage.setdefault(call["stage"], {})
        for field, value in call["usage"].items():
            total[field] = total.get(field, 0) + value
    return {"turn_id": turn, "response_count": len(calls), "available": bool(calls),
            "totals": totals if calls else None, "by_model": models, "by_stage": by_stage,
            "malformed_lines": malformed, "calls": calls,
            "note": "Reasoning is included in output; cached input is included in input. Pass child traces separately if used."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--base", type=Path, required=True)
    p.add_argument("--input", type=Path, nargs="+", required=True)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("page")
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--budget", type=int, default=12000)
    p = sub.add_parser("queue")
    p.add_argument("--base", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("plan")
    p.add_argument("--base", type=Path, required=True)
    p.add_argument("--keys", nargs="+", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--budget", type=int, default=6000)
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("packet")
    p.add_argument("--base", type=Path, required=True)
    p.add_argument("--key", required=True)
    p.add_argument("--part", type=int, default=0)
    p.add_argument("--budget", type=int, default=6000)
    p = sub.add_parser("cache")
    p.add_argument("--base", type=Path, required=True)
    p.add_argument("--key")
    p.add_argument("--result", type=Path)
    p.add_argument("--budget", type=int, default=6000)
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("persist")
    p.add_argument("--base", type=Path, required=True)
    p.add_argument("--payload", type=Path, required=True)
    p.add_argument("--write", action="store_true")
    p = sub.add_parser("usage")
    p.add_argument("--trace", type=Path, required=True)
    p.add_argument("--turn", required=True)
    p.add_argument("--stages", type=Path)
    p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare(args.base, args.input, args.output)
        elif args.command == "page":
            result = page(args.input, args.offset, args.limit, args.budget)
        elif args.command == "queue":
            result = active_queue(args.base, args.output)
        elif args.command == "plan":
            result = plan(args.base, args.keys, args.output, args.budget, args.force)
        elif args.command == "packet":
            result = packet(args.base, args.key, args.part, args.budget)
        elif args.command == "cache":
            data = read_json(args.result) if args.result else None
            if isinstance(data, list):
                result = store_analyses(args.base, data, args.budget)
            else:
                if not args.key:
                    raise ValueError("--key is required except with an analysis array")
                result = cache(args.base, args.key, data, args.budget, args.force)
        elif args.command == "persist":
            result = persist(args.base, read_json(args.payload), args.write)
        else:
            result = usage_report(args.trace, args.turn, read_json(args.stages) if args.stages else None)
            save_json(args.output, result)
            result = {k: v for k, v in result.items() if k != "calls"}
            result["file"] = str(args.output)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ValueError, KeyError, OSError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
