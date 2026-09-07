"""Deterministic local state operations for the job-search workflow.

The Markdown commands decide *what* should change. This helper owns the repetitive,
error-prone mechanics: tracker schema migration, company/role matching, status
finality, archive slugs, posting-snapshot hashing, unrelated-column preservation,
and atomic CSV writes.

Every mutating command is a dry-run unless ``--write`` is supplied.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


STANDARD_FIELDS = [
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

REQUIRED_FIELDS = STANDARD_FIELDS[:13]
OPTIONAL_FIELDS = STANDARD_FIELDS[13:]

CANONICAL_STATUSES = {
    "drafted",
    "applied",
    "interview",
    "offer",
    "hired",
    "rejected",
    "no_response",
    "offer_declined",
    "withdrawn",
}

FINAL_STATUSES = {
    "hired",
    "rejected",
    "no_response",
    "offer_declined",
    "withdrawn",
}

LEGACY_STATUS_MAP = {
    "no response": "no_response",
    "offer declined": "offer_declined",
}

STATUS_ORDER = {
    "drafted": 0,
    "applied": 1,
    "interview": 2,
    "offer": 3,
    "hired": 4,
}

TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "source",
}

WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


class JobStateError(ValueError):
    """Raised when a requested state transition is ambiguous or unsafe."""


@dataclass
class Tracker:
    path: Path
    fieldnames: list[str]
    rows: list[dict[str, str]]
    header_migrated: bool = False


def normalize_status(value: str) -> str:
    normalized = value.strip().casefold()
    return LEGACY_STATUS_MAP.get(normalized, normalized)


def is_final(value: str) -> bool:
    return normalize_status(value) in FINAL_STATUSES


def match_text(value: str) -> str:
    return " ".join(value.casefold().split())


def archive_slug(company: str, role: str) -> str:
    """Implement documents/README.md's single-component naming rule."""

    raw = f"{company}_{role}".lower().replace(" ", "_")
    cleaned = "".join(ch for ch in raw if ch == "_" or ch.isalnum())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        raise JobStateError(
            "company and role do not produce a safe archive name; include a letter or digit"
        )
    if cleaned.casefold() in WINDOWS_RESERVED_NAMES:
        cleaned = f"job_{cleaned}"
    if len(cleaned) > 96:
        suffix = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:12]
        cleaned = f"{cleaned[:83].rstrip('_')}_{suffix}"
    return cleaned


def normalize_url(value: str) -> str:
    """Return a conservative canonical HTTP(S) URL for identity and hashing."""

    raw = value.strip()
    if not raw:
        raise JobStateError("URL cannot be empty")
    parts = urlsplit(raw)
    if parts.scheme.casefold() not in {"http", "https"} or not parts.hostname:
        raise JobStateError("URL must be an absolute http(s) URL")
    host = parts.hostname.casefold()
    if parts.port and not (
        (parts.scheme.casefold() == "http" and parts.port == 80)
        or (parts.scheme.casefold() == "https" and parts.port == 443)
    ):
        host = f"{host}:{parts.port}"
    query = [
        (key, item)
        for key, item in parse_qsl(parts.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_")
        and key.casefold() not in TRACKING_QUERY_KEYS
    ]
    query.sort(key=lambda pair: (pair[0].casefold(), pair[1]))
    path = parts.path or "/"
    return urlunsplit((parts.scheme.casefold(), host, path, urlencode(query), ""))


def _validate_iso_date(value: str, field: str, *, allow_empty: bool = True) -> None:
    candidate = value.strip()
    if not candidate and allow_empty:
        return
    try:
        date.fromisoformat(candidate)
    except ValueError as exc:
        raise JobStateError(f"{field} must be YYYY-MM-DD") from exc


def _validate_fit_rating(value: str, *, allow_empty: bool = False) -> None:
    candidate = value.strip()
    if not candidate and allow_empty:
        return
    try:
        score = float(candidate)
    except ValueError as exc:
        raise JobStateError("fit_rating must be a number from 0 to 100") from exc
    if not 0 <= score <= 100:
        raise JobStateError("fit_rating must be a number from 0 to 100")


def _validate_application_input(
    *, company: str, role: str, application_date: str, deadline: str, fit_rating: str,
    allow_empty_fit: bool = False,
) -> None:
    archive_slug(company.strip(), role.strip())
    _validate_iso_date(application_date, "date", allow_empty=False)
    _validate_iso_date(deadline, "deadline")
    _validate_fit_rating(fit_rating, allow_empty=allow_empty_fit)


def make_application_id(
    company: str, role: str, application_date: str, source: str = "",
    requisition_id: str = "",
) -> str:
    base = archive_slug(company, role)
    identity = requisition_id.strip() or source.strip() or "pasted-posting"
    if source.strip():
        try:
            identity = normalize_url(source)
        except JobStateError:
            identity = source.strip()
    digest = hashlib.sha256(
        f"{identity}|{application_date}".encode("utf-8")
    ).hexdigest()[:10]
    return archive_slug(base, digest)


def unique_application_id(rows: Iterable[dict[str, str]], candidate: str) -> str:
    """Return a stable unused ID without conflating repeat applications."""

    used = {
        match_text(row.get("application_id", ""))
        for row in rows
        if row.get("application_id", "").strip()
    }
    if match_text(candidate) not in used:
        return candidate
    sequence = 2
    while True:
        suffix = hashlib.sha256(
            f"{candidate}|repeat|{sequence}".encode("utf-8")
        ).hexdigest()[:6]
        alternate = archive_slug(candidate, suffix)
        if match_text(alternate) not in used:
            return alternate
        sequence += 1


def _empty_tracker(path: Path) -> Tracker:
    return Tracker(path=path, fieldnames=list(STANDARD_FIELDS), rows=[])


def load_tracker(path: Path) -> Tracker:
    if not path.exists() or path.stat().st_size == 0:
        return _empty_tracker(path)

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            return _empty_tracker(path)
        fieldnames = list(reader.fieldnames)
        if any(not field.strip() for field in fieldnames):
            raise JobStateError("tracker header contains a blank column name")
        normalized_headers = [field.casefold() for field in fieldnames]
        if len(set(normalized_headers)) != len(normalized_headers):
            raise JobStateError("tracker header contains duplicate column names")
        rows = []
        for line_number, row in enumerate(reader, start=2):
            if None in row:
                raise JobStateError(
                    f"tracker row {line_number} has more cells than the header"
                )
            missing_required_cells = [
                field for field in REQUIRED_FIELDS if field in row and row[field] is None
            ]
            if missing_required_cells:
                raise JobStateError(
                    f"tracker row {line_number} is missing required cells: "
                    + ", ".join(missing_required_cells)
                )
            rows.append(
                {
                    field: "" if row[field] is None and field in OPTIONAL_FIELDS else row[field]
                    for field in fieldnames
                }
            )

    missing_required = [field for field in REQUIRED_FIELDS if field not in fieldnames]
    if missing_required:
        raise JobStateError(
            "tracker is missing required columns: " + ", ".join(missing_required)
        )

    migrated = False
    for optional_field in OPTIONAL_FIELDS:
        if optional_field in fieldnames:
            continue
        fieldnames.append(optional_field)
        for row in rows:
            row[optional_field] = ""
        migrated = True

    return Tracker(
        path=path,
        fieldnames=fieldnames,
        rows=rows,
        header_migrated=migrated,
    )


def write_tracker(tracker: Tracker) -> None:
    tracker.path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="",
            dir=tracker.path.parent,
            prefix=f".{tracker.path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_name = handle.name
            writer = csv.DictWriter(
                handle,
                fieldnames=tracker.fieldnames,
                extrasaction="ignore",
                lineterminator="\n",
            )
            writer.writeheader()
            for row in tracker.rows:
                writer.writerow({field: row.get(field, "") for field in tracker.fieldnames})
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, tracker.path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def _matching_indices(rows: Iterable[dict[str, str]], company: str, role: str) -> list[int]:
    company_key = match_text(company)
    role_key = match_text(role)
    return [
        index
        for index, row in enumerate(rows)
        if match_text(row.get("company", "")) == company_key
        and match_text(row.get("role", "")) == role_key
    ]


def _append_note(existing: str, note: str) -> str:
    existing = existing.strip()
    note = note.strip()
    if not note:
        return existing
    if not existing:
        return note
    if note in [part.strip() for part in existing.split(";")]:
        return existing
    return f"{existing}; {note}"


def _json_plan(
    *, tracker: Tracker, action: str, index: int | None, row: dict[str, str], written: bool
) -> dict[str, Any]:
    return {
        "action": action,
        "tracker": str(tracker.path),
        "row_index": None if index is None else index + 1,
        "company": row.get("company", ""),
        "role": row.get("role", ""),
        "status": row.get("status", ""),
        "application_id": row.get("application_id", ""),
        "archive_path": row.get("archive_path", ""),
        "archive_slug": Path(row.get("archive_path", "")).name
        if row.get("archive_path", "")
        else archive_slug(row.get("company", ""), row.get("role", "")),
        "header_migrated": tracker.header_migrated,
        "written": written,
    }


def upsert_draft(args: argparse.Namespace) -> dict[str, Any]:
    _validate_application_input(
        company=args.company,
        role=args.role,
        application_date=args.date,
        deadline=args.deadline,
        fit_rating=args.fit_rating,
    )
    tracker = load_tracker(args.tracker)
    matches = _matching_indices(tracker.rows, args.company, args.role)
    open_matches = [index for index in matches if not is_final(tracker.rows[index]["status"])]

    if len(open_matches) > 1:
        raise JobStateError(
            "multiple open tracker rows match this company and role; resolve manually"
        )

    values = {
        "company": args.company.strip(),
        "role": args.role.strip(),
        "sector": args.sector.strip(),
        "role_type": args.role_type.strip(),
        "channel": args.channel.strip(),
        "contact_person": args.contact_person.strip(),
        "fit_rating": args.fit_rating.strip(),
        "cv_file": args.cv_file.strip(),
        "cover_letter_file": args.cover_letter_file.strip(),
        "source": args.source.strip(),
        "deadline": args.deadline.strip(),
    }
    app_id = make_application_id(
        values["company"], values["role"], args.date,
        args.authoritative_url or values["source"], args.requisition_id,
    )
    if not open_matches:
        app_id = unique_application_id(tracker.rows, app_id)
    values["application_id"] = app_id
    values["archive_path"] = f"documents/applications/{app_id}"

    if open_matches:
        index = open_matches[0]
        row = tracker.rows[index]
        if normalize_status(row.get("status", "")) != "drafted":
            raise JobStateError(
                "a submitted application already matches; preserve its score, source, "
                "and submitted artifacts instead of overwriting it with a redraft"
            )
        for field in ("fit_rating", "source", "cv_file", "cover_letter_file", "deadline"):
            if values[field]:
                row[field] = values[field]
        for field in ("sector", "role_type", "channel", "contact_person"):
            if values[field] and not row.get(field, "").strip():
                row[field] = values[field]
        if not row.get("application_id", "").strip():
            row["application_id"] = values["application_id"]
        if not row.get("archive_path", "").strip():
            row["archive_path"] = values["archive_path"]
        row["notes"] = _append_note(row.get("notes", ""), "redrafted")
        if normalize_status(row.get("status", "")) == "drafted":
            row["date"] = args.date
        action = "update_open"
    else:
        row = {field: "" for field in tracker.fieldnames}
        row.update(values)
        row["date"] = args.date
        row["status"] = "drafted"
        tracker.rows.append(row)
        index = len(tracker.rows) - 1
        action = "append_after_final" if matches else "append_new"

    if args.write:
        write_tracker(tracker)
    return _json_plan(
        tracker=tracker, action=action, index=index, row=row, written=args.write
    )


def add_application(args: argparse.Namespace) -> dict[str, Any]:
    """Append an application created outside /apply without a transient draft row."""

    _validate_application_input(
        company=args.company,
        role=args.role,
        application_date=args.date,
        deadline=args.deadline,
        fit_rating=args.fit_rating,
        allow_empty_fit=True,
    )
    tracker = load_tracker(args.tracker)
    matches = _matching_indices(tracker.rows, args.company, args.role)
    open_matches = [index for index in matches if not is_final(tracker.rows[index]["status"])]
    if open_matches:
        raise JobStateError(
            "an open tracker row already matches this company and role; update it instead"
        )
    requested_status = normalize_status(args.status)
    if requested_status not in CANONICAL_STATUSES:
        raise JobStateError(f"unknown canonical tracker status: {args.status}")

    row = {field: "" for field in tracker.fieldnames}
    row.update(
        {
            "date": args.date,
            "company": args.company.strip(),
            "sector": args.sector.strip(),
            "role": args.role.strip(),
            "role_type": args.role_type.strip(),
            "channel": args.channel.strip(),
            "status": requested_status,
            "contact_person": args.contact_person.strip(),
            "fit_rating": args.fit_rating.strip(),
            "notes": args.note.strip(),
            "cv_file": args.cv_file.strip(),
            "cover_letter_file": args.cover_letter_file.strip(),
            "source": args.source.strip(),
            "deadline": args.deadline.strip(),
        }
    )
    app_id = make_application_id(
        row["company"], row["role"], args.date,
        args.authoritative_url or row["source"], args.requisition_id,
    )
    app_id = unique_application_id(tracker.rows, app_id)
    row["application_id"] = app_id
    row["archive_path"] = f"documents/applications/{app_id}"
    tracker.rows.append(row)
    index = len(tracker.rows) - 1
    action = "append_after_final" if matches else "append_external"
    if args.write:
        write_tracker(tracker)
    return _json_plan(
        tracker=tracker, action=action, index=index, row=row, written=args.write
    )


def update_status(args: argparse.Namespace) -> dict[str, Any]:
    archive_slug(args.company.strip(), args.role.strip())
    if args.date:
        _validate_iso_date(args.date, "date", allow_empty=False)
    tracker = load_tracker(args.tracker)
    requested_status = normalize_status(args.status)
    if requested_status not in CANONICAL_STATUSES:
        raise JobStateError(f"unknown canonical tracker status: {args.status}")

    if args.application_id:
        matches = [
            index for index, row in enumerate(tracker.rows)
            if match_text(row.get("application_id", "")) == match_text(args.application_id)
        ]
    else:
        matches = _matching_indices(tracker.rows, args.company, args.role)
    if not matches:
        raise JobStateError("no tracker row matches this company and role")
    open_matches = [index for index in matches if not is_final(tracker.rows[index]["status"])]

    if len(open_matches) > 1:
        raise JobStateError(
            "multiple open tracker rows match this company and role; resolve manually"
        )
    if open_matches:
        index = open_matches[0]
    elif len(matches) == 1 and args.allow_final:
        index = matches[0]
    else:
        raise JobStateError(
            "only final tracker rows match; use --allow-final only for an explicit correction"
        )

    row = tracker.rows[index]
    previous_status = normalize_status(row.get("status", ""))
    if (
        previous_status in STATUS_ORDER
        and requested_status in STATUS_ORDER
        and STATUS_ORDER[requested_status] < STATUS_ORDER[previous_status]
        and not args.allow_final
    ):
        raise JobStateError(
            f"status regression {previous_status} -> {requested_status} requires an explicit correction"
        )
    row["status"] = requested_status
    if args.note:
        row["notes"] = _append_note(row.get("notes", ""), args.note)
    if args.date:
        row["date"] = args.date

    if args.write:
        write_tracker(tracker)
    result = _json_plan(
        tracker=tracker,
        action="update_status",
        index=index,
        row=row,
        written=args.write,
    )
    result["previous_status"] = previous_status
    return result


def list_open(args: argparse.Namespace) -> dict[str, Any]:
    tracker = load_tracker(args.tracker)
    rows = []
    for index, row in enumerate(tracker.rows):
        if is_final(row.get("status", "")):
            continue
        rows.append(
            {
                "row_index": index + 1,
                "company": row.get("company", ""),
                "role": row.get("role", ""),
                "date": row.get("date", ""),
                "status": normalize_status(row.get("status", "")),
                "deadline": row.get("deadline", ""),
                "archive_slug": archive_slug(
                    row.get("company", ""), row.get("role", "")
                ) if not row.get("archive_path", "") else Path(row["archive_path"]).name,
                "application_id": row.get("application_id", ""),
                "archive_path": row.get("archive_path", ""),
            }
        )
    return {
        "tracker": str(tracker.path),
        "header_migration_needed": tracker.header_migrated,
        "open": rows,
    }


def migrate_identities(args: argparse.Namespace) -> dict[str, Any]:
    """Add optional identity columns and deterministic IDs to legacy rows."""

    tracker = load_tracker(args.tracker)
    used = {
        match_text(row.get("application_id", ""))
        for row in tracker.rows
        if row.get("application_id", "").strip()
    }
    changed: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for index, row in enumerate(tracker.rows):
        if row.get("application_id", "").strip() and row.get("archive_path", "").strip():
            continue
        company = row.get("company", "").strip()
        role = row.get("role", "").strip()
        try:
            app_id = make_application_id(
                company,
                role,
                row.get("date", "").strip() or "unknown-date",
                row.get("source", ""),
            )
        except JobStateError as exc:
            issues.append({"row_index": index + 1, "error": str(exc)})
            continue
        candidate = app_id
        if match_text(candidate) in used:
            suffix = hashlib.sha256(f"{candidate}|{index + 1}".encode("utf-8")).hexdigest()[:8]
            candidate = archive_slug(candidate, suffix)
        used.add(match_text(candidate))
        row["application_id"] = candidate
        row["archive_path"] = f"documents/applications/{candidate}"
        changed.append(
            {
                "row_index": index + 1,
                "application_id": candidate,
                "archive_path": row["archive_path"],
            }
        )
    if args.write and (changed or tracker.header_migrated):
        write_tracker(tracker)
    return {
        "tracker": str(tracker.path),
        "header_migrated": tracker.header_migrated,
        "changed": changed,
        "issues": issues,
        "written": args.write,
    }


def slug_plan(args: argparse.Namespace) -> dict[str, Any]:
    return {"archive_slug": archive_slug(args.company, args.role)}


def snapshot_path_plan(args: argparse.Namespace) -> dict[str, Any]:
    canonical_url = normalize_url(args.url)
    digest = hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()
    return {
        "canonical_url": canonical_url,
        "posting_snapshot": f"job_scraper/postings/{digest}.md",
    }


def normalize_url_plan(args: argparse.Namespace) -> dict[str, Any]:
    return {"canonical_url": normalize_url(args.url)}


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_hash_plan(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "posting_snapshot": args.path.as_posix(),
        "snapshot_sha256": _file_sha256(args.path),
        "size_bytes": args.path.stat().st_size,
    }


def _parse_utc_timestamp(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise JobStateError("snapshot timestamp must be valid ISO-8601") from exc
    if parsed.tzinfo is None:
        raise JobStateError("snapshot timestamp must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def snapshot_verify_plan(args: argparse.Namespace) -> dict[str, Any]:
    exists = args.path.is_file()
    actual_sha = _file_sha256(args.path) if exists else None
    fetched_at = _parse_utc_timestamp(args.fetched_at)
    age_hours = (datetime.now(timezone.utc) - fetched_at).total_seconds() / 3600
    hash_matches = actual_sha == args.expected_sha.strip().casefold() if exists else False
    fresh = 0 <= age_hours <= args.max_age_hours
    return {
        "posting_snapshot": args.path.as_posix(),
        "exists": exists,
        "snapshot_sha256": actual_sha,
        "hash_matches": hash_matches,
        "age_hours": round(age_hours, 3),
        "fresh": fresh,
        "valid": bool(exists and hash_matches and fresh),
    }


def _add_tracker_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--tracker", type=Path, default=Path("job_search_tracker.csv")
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    slug = subparsers.add_parser("slug", help="derive the canonical archive slug")
    slug.add_argument("--company", required=True)
    slug.add_argument("--role", required=True)
    slug.set_defaults(handler=slug_plan)

    snapshot_path = subparsers.add_parser(
        "snapshot-path", help="derive the cache path for a canonical posting URL"
    )
    snapshot_path.add_argument("--url", required=True)
    snapshot_path.set_defaults(handler=snapshot_path_plan)

    url_parser = subparsers.add_parser(
        "normalize-url", help="canonicalize a posting URL for identity and hashing"
    )
    url_parser.add_argument("--url", required=True)
    url_parser.set_defaults(handler=normalize_url_plan)

    snapshot_hash = subparsers.add_parser(
        "snapshot-hash", help="hash a posting snapshot after writing it"
    )
    snapshot_hash.add_argument("--path", type=Path, required=True)
    snapshot_hash.set_defaults(handler=snapshot_hash_plan)

    snapshot_verify = subparsers.add_parser(
        "snapshot-verify", help="verify a snapshot's hash and freshness"
    )
    snapshot_verify.add_argument("--path", type=Path, required=True)
    snapshot_verify.add_argument("--expected-sha", required=True)
    snapshot_verify.add_argument("--fetched-at", required=True)
    snapshot_verify.add_argument("--max-age-hours", type=float, default=24.0)
    snapshot_verify.set_defaults(handler=snapshot_verify_plan)

    open_parser = subparsers.add_parser("list-open", help="list non-final tracker rows")
    _add_tracker_argument(open_parser)
    open_parser.set_defaults(handler=list_open)

    migrate = subparsers.add_parser(
        "migrate-identities",
        help="plan or add stable application IDs/archive paths to legacy rows",
    )
    _add_tracker_argument(migrate)
    migrate.add_argument("--write", action="store_true")
    migrate.set_defaults(handler=migrate_identities)

    draft = subparsers.add_parser(
        "upsert-draft", help="plan or write a drafted application row"
    )
    _add_tracker_argument(draft)
    draft.add_argument("--company", required=True)
    draft.add_argument("--role", required=True)
    draft.add_argument("--date", default=date.today().isoformat())
    draft.add_argument("--sector", default="")
    draft.add_argument("--role-type", default="")
    draft.add_argument("--channel", default="")
    draft.add_argument("--contact-person", default="")
    draft.add_argument("--fit-rating", required=True)
    draft.add_argument("--cv-file", required=True)
    draft.add_argument("--cover-letter-file", default="")
    draft.add_argument("--source", default="")
    draft.add_argument("--authoritative-url", default="")
    draft.add_argument("--requisition-id", default="")
    draft.add_argument("--deadline", default="")
    draft.add_argument("--write", action="store_true")
    draft.set_defaults(handler=upsert_draft)

    external = subparsers.add_parser(
        "add-application", help="plan or append an application made outside /apply"
    )
    _add_tracker_argument(external)
    external.add_argument("--company", required=True)
    external.add_argument("--role", required=True)
    external.add_argument("--date", default=date.today().isoformat())
    external.add_argument("--status", default="applied")
    external.add_argument("--sector", default="")
    external.add_argument("--role-type", default="")
    external.add_argument("--channel", default="")
    external.add_argument("--contact-person", default="")
    external.add_argument("--fit-rating", default="")
    external.add_argument("--note", default="")
    external.add_argument("--cv-file", default="")
    external.add_argument("--cover-letter-file", default="")
    external.add_argument("--source", default="")
    external.add_argument("--authoritative-url", default="")
    external.add_argument("--requisition-id", default="")
    external.add_argument("--deadline", default="")
    external.add_argument("--write", action="store_true")
    external.set_defaults(handler=add_application)

    status = subparsers.add_parser(
        "update-status", help="plan or write a tracker status transition"
    )
    _add_tracker_argument(status)
    status.add_argument("--company", required=True)
    status.add_argument("--role", required=True)
    status.add_argument("--application-id", default="")
    status.add_argument("--status", required=True)
    status.add_argument("--note", default="")
    status.add_argument("--date", default="")
    status.add_argument("--allow-final", action="store_true")
    status.add_argument("--write", action="store_true")
    status.set_defaults(handler=update_status)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.handler(args)
    except (JobStateError, OSError, csv.Error) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
