#!/usr/bin/env python3
"""Validate a ranked AI brief without imposing content quotas."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


VALID_KINDS = {"news", "builder", "blog", "podcast", "community"}
VALID_SECTIONS = {"core", "industry", "models", "research"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--strict-builder-links", action="store_true")
    parser.add_argument("--require-collection", action="store_true")
    parser.add_argument(
        "--require-lane",
        action="append",
        default=[],
        choices=["radar", "builders", "community"],
        help="Require a successful collection pass for this lane",
    )
    parser.add_argument("--require-selected-when-captured", action="store_true")
    return parser.parse_args()


def load_payload(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return {}, [dict(item) for item in payload]
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ValueError("input must be an array or an object with an items array")
    return dict(payload.get("meta") or {}), [dict(item) for item in payload["items"]]


def parse_datetime(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def valid_url(value: Any) -> bool:
    parts = urlsplit(str(value or "").strip())
    return parts.scheme in {"http", "https"} and bool(parts.netloc)


def main() -> int:
    args = parse_args()
    meta, items = load_payload(args.input)
    start = parse_datetime(meta.get("window_start")) if meta.get("window_start") else None
    end = parse_datetime(meta.get("window_end")) if meta.get("window_end") else None
    windows = dict(meta.get("windows_hours") or {})
    collection = dict(meta.get("collection") or {})
    errors: list[str] = []
    warnings: list[str] = []
    seen_urls: dict[tuple[str, str], int] = {}
    seen_events: dict[tuple[str, str], int] = {}

    if (start is None) != (end is None):
        errors.append("metadata must contain both window_start and window_end")
    if start and end and start >= end:
        errors.append("window_start must be earlier than window_end")
    if args.require_collection and not collection:
        errors.append("collection metadata is required for a full brief")
    lane_status = dict(collection.get("lane_status") or {})
    selected_builder_count = sum(
        1 for item in items if str(item.get("kind") or "news") == "builder"
    )
    manual_builder_evidence = (
        int(collection.get("manual_evidence_count") or 0) > 0
        and selected_builder_count > 0
    )
    for lane in args.require_lane:
        status = dict(lane_status.get(lane) or {})
        if int(status.get("configured") or 0) == 0:
            if lane != "builders" or not manual_builder_evidence:
                errors.append(f"{lane} collection lane was not configured")
        elif int(status.get("ok") or 0) == 0:
            errors.append(f"{lane} collection lane had no successful source")

    for index, item in enumerate(items, 1):
        label = str(item.get("chinese_title") or item.get("title") or f"item {index}")
        kind = str(item.get("kind") or "news")
        missing = [
            field
            for field in ("title", "url", "source", "published_at")
            if not str(item.get(field) or "").strip()
        ]
        if missing:
            errors.append(f"{label}: missing {', '.join(missing)}")
            continue
        if kind not in VALID_KINDS:
            errors.append(f"{label}: invalid kind {kind}")
        if kind == "news" and item.get("section") not in VALID_SECTIONS:
            errors.append(f"{label}: news item needs a valid section")
        if not valid_url(item["url"]):
            errors.append(f"{label}: invalid URL")
        published = parse_datetime(item["published_at"])
        if published is None:
            errors.append(f"{label}: published_at must include a timezone")
        elif start and end:
            hours = float(windows.get(
                "builders" if kind == "builder"
                else "community" if kind == "community"
                else "longform" if kind in {"blog", "podcast"}
                else "news",
                (end - start).total_seconds() / 3600,
            ))
            allowed_start = end - timedelta(hours=hours)
            if not (allowed_start <= published < end):
                errors.append(f"{label}: published_at is outside the {kind} window")

        if kind in {"news", "community"} and not str(
            item.get("chinese_summary") or item.get("summary") or ""
        ).strip():
            errors.append(f"{label}: missing publishable summary")
        if kind == "builder":
            if not str(item.get("original_text") or "").strip():
                errors.append(f"{label}: Builder item lacks original_text")
            if not str(item.get("translated_text") or "").strip():
                errors.append(f"{label}: Builder item lacks translated_text")
            url = str(item.get("url") or "")
            if "x.com/" in url and "/status/" not in url:
                message = f"{label}: X profile link is a fallback, not a direct post"
                (errors if args.strict_builder_links else warnings).append(message)

        lane = "news" if kind == "news" else kind
        canonical = str(item.get("canonical_url") or item.get("url") or "")
        url_key = (lane, canonical)
        if canonical and url_key in seen_urls:
            errors.append(f"{label}: duplicate URL in {lane} lane")
        seen_urls[url_key] = index
        claim_id = str(item.get("claim_id") or "").strip()
        claim_key = (lane, claim_id)
        if claim_id and claim_key in seen_events:
            errors.append(f"{label}: duplicate claim_id in {lane} lane")
        if claim_id:
            seen_events[claim_key] = index

    if args.require_selected_when_captured:
        captured = dict(collection.get("kind_counts") or {})
        selected_kinds: dict[str, int] = {}
        for item in items:
            kind = str(item.get("kind") or "news")
            selected_kinds[kind] = selected_kinds.get(kind, 0) + 1
        for kind in ("builder", "community", "podcast"):
            if int(captured.get(kind) or 0) > 0 and selected_kinds.get(kind, 0) == 0:
                errors.append(f"{kind} candidates were captured but none were selected")

    if meta.get("selected_count") is not None and int(meta["selected_count"]) != len(items):
        errors.append("selected_count does not match items length")

    report = {
        "items": len(items),
        "errors": errors,
        "warnings": warnings,
        "status": "failed" if errors else "passed",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
