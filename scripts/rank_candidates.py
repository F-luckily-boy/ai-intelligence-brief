#!/usr/bin/env python3
"""Filter, rank, and safely deduplicate AI brief candidates."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
import json
import math
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_POLICY = SKILL_ROOT / "references" / "source-policy.json"
VALID_KINDS = {"news", "builder", "blog", "podcast", "community"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Candidate JSON array or JSONL")
    parser.add_argument("--output", "-o", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--as-of", required=True, help="Exclusive ISO reporting cutoff")
    parser.add_argument("--hours", type=float, default=24.0)
    parser.add_argument("--builder-hours", type=float, default=36.0)
    parser.add_argument("--community-hours", type=float, default=48.0)
    parser.add_argument("--longform-hours", type=float, default=72.0)
    parser.add_argument("--limit", type=int, default=45)
    parser.add_argument("--min-keyword-score", type=float, default=3.0)
    parser.add_argument(
        "--seen",
        type=Path,
        action="append",
        default=[],
        help="Previously published ranked JSON; matching events are excluded",
    )
    return parser.parse_args()


def load_payload(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}, []
    payload = json.loads(text) if text.startswith(("[", "{")) else None
    if isinstance(payload, dict):
        meta = dict(payload.get("meta") or {})
        payload = payload.get("items", [])
    else:
        meta = {}
    if isinstance(payload, list):
        return meta, [dict(item) for item in payload]
    if payload is not None:
        raise ValueError("JSON input must be an array or an object with an items array")
    return {}, [json.loads(line) for line in text.splitlines() if line.strip()]


def load_items(path: Path) -> list[dict[str, Any]]:
    return load_payload(path)[1]


def parse_datetime(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def normalize_source(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def source_metadata(source: str, policy: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    source_key = normalize_source(source)
    for spec in policy.get("sources", []):
        names = [spec.get("name", ""), *spec.get("aliases", [])]
        if source_key in {normalize_source(name) for name in names if name}:
            return dict(spec)
    default = dict(policy.get("default_source", {}))
    channels = set(map(str, item.get("channels") or []))
    if item.get("channel"):
        channels.add(str(item["channel"]))
    if item.get("kind") == "builder" or "builders" in channels:
        default.update({"tier": 2, "group": "builders", "weight": 32})
    default["name"] = source or "Unknown"
    return default


def canonicalize_url(url: str, tracking_params: set[str]) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        return ""
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.casefold() not in tracking_params and not key.casefold().startswith("utm_")
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def source_url_matches(url: str, source_spec: dict[str, Any]) -> bool:
    domains = [str(value).casefold().lstrip(".") for value in source_spec.get("domains", [])]
    if not domains:
        return True
    host = (urlsplit(url).hostname or "").casefold()
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def text_fields(item: dict[str, Any]) -> list[tuple[str, float]]:
    return [
        (str(item.get("title") or "").casefold(), 1.55),
        (str(item.get("summary") or item.get("chinese_summary") or "").casefold(), 1.0),
        (str(item.get("original_text") or item.get("content") or "").casefold(), 0.75),
        (str(item.get("translated_text") or "").casefold(), 0.75),
        (" ".join(map(str, item.get("tags") or [])).casefold(), 0.8),
    ]


def term_matches(term: str, text: str) -> bool:
    term = term.strip().casefold()
    if not term:
        return False
    if re.fullmatch(r"[a-z0-9][a-z0-9 ._+-]*", term):
        return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None
    return term in text


def keyword_score(item: dict[str, Any], keywords: list[dict[str, Any]]) -> tuple[float, list[str]]:
    score = 0.0
    matched: list[str] = []
    fields = text_fields(item)
    for spec in keywords:
        term = str(spec.get("term") or "").strip()
        multiplier = max(
            (field_weight for text, field_weight in fields if term_matches(term, text)),
            default=0.0,
        )
        if multiplier:
            matched.append(term)
            score += float(spec.get("weight", 1)) * multiplier
    return min(score, 24.0), matched


def recency_score(published_at: datetime, start: datetime, cutoff: datetime) -> float:
    window = max((cutoff - start).total_seconds(), 1.0)
    position = (published_at - start).total_seconds() / window
    return max(0.0, min(2.0, 2.0 * position))


def engagement_score(metrics: Any) -> float:
    if not isinstance(metrics, dict):
        return 0.0
    points = float(metrics.get("points") or metrics.get("likes") or 0)
    comments = float(metrics.get("comments") or metrics.get("replies") or 0)
    stars = float(metrics.get("stars") or 0)
    raw = math.log1p(max(points, 0)) + 0.7 * math.log1p(max(comments, 0))
    raw += 0.8 * math.log1p(max(stars, 0))
    return min(2.0, raw / 4.0)


def infer_section(item: dict[str, Any], policy: dict[str, Any]) -> str:
    if item.get("section") in {"core", "industry", "models", "research"}:
        return str(item["section"])
    text = " ".join(
        str(item.get(key) or "").casefold()
        for key in ("title", "summary", "chinese_summary", "translated_text")
    )
    scores = {
        section: sum(term_matches(str(cue), text) for cue in cues)
        for section, cues in policy.get("section_cues", {}).items()
    }
    return max(scores, key=scores.get, default="models") if any(scores.values()) else "models"


def normalized_title(value: Any) -> str:
    text = re.sub(r"https?://\S+", "", str(value or "").casefold())
    return re.sub(r"[\W_]+", "", text, flags=re.UNICODE)


def title_similarity(left: Any, right: Any) -> float:
    a = normalized_title(left)
    b = normalized_title(right)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def lane(item: dict[str, Any]) -> str:
    kind = str(item.get("kind") or "news")
    return "news" if kind == "news" else kind


def same_story(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if lane(left) != lane(right):
        return False
    if left.get("canonical_url") and left["canonical_url"] == right.get("canonical_url"):
        return True
    left_claim = str(left.get("claim_id") or "").strip()
    right_claim = str(right.get("claim_id") or "").strip()
    if left_claim and left_claim == right_claim:
        return True
    return title_similarity(left.get("title"), right.get("title")) >= 0.92


def prepare(
    item: dict[str, Any],
    policy: dict[str, Any],
    start: datetime,
    cutoff: datetime,
    min_keyword_score: float,
    extended_starts: dict[str, datetime] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    title = str(item.get("title") or "").strip()
    source = str(item.get("source") or "").strip()
    tracking = {str(value).casefold() for value in policy.get("tracking_params", [])}
    url = canonicalize_url(str(item.get("url") or ""), tracking)
    published_at = parse_datetime(item.get("published_at"))
    if not title or not source or not url:
        return None, "invalid_required_fields"
    if not published_at:
        return None, "missing_or_naive_timestamp"
    kind = str(item.get("kind") or "news")
    if kind not in VALID_KINDS:
        return None, "invalid_kind"
    allowed_start = (extended_starts or {}).get(kind, start)
    if published_at < allowed_start:
        return None, "before_window"
    if published_at >= cutoff:
        return None, "at_or_after_cutoff"

    source_spec = source_metadata(source, policy, item)
    if not source_url_matches(url, source_spec):
        return None, "source_url_mismatch"
    relevance, matched = keyword_score(item, policy.get("keywords", []))
    tier = int(source_spec.get("tier", 2))
    if relevance < min_keyword_score and tier != 0 and not item.get("manual_evidence"):
        return None, "below_relevance_threshold"

    result = dict(item)
    result.update(
        {
            "title": title,
            "url": url,
            "canonical_url": url,
            "source": source,
            "published_at": published_at.isoformat(),
            "kind": kind,
            "source_tier": tier,
            "source_group": source_spec.get("group", "broad_signal"),
            "source_weight": float(source_spec.get("weight", 24)),
            "matched_keywords": matched,
            "keyword_score": round(relevance, 2),
            "window_class": "primary" if published_at >= start else "extended",
        }
    )
    result["section"] = infer_section(result, policy)
    result["sources"] = list(dict.fromkeys([source, *map(str, item.get("sources") or [])]))
    source_urls = dict(item.get("source_urls") or {})
    source_urls.setdefault(source, url)
    result["source_urls"] = {
        str(name): canonicalize_url(str(link), tracking)
        for name, link in source_urls.items()
    }
    channels = [str(item.get("channel"))] if item.get("channel") else []
    channels.extend(map(str, item.get("channels") or []))
    if not channels:
        channels.append("builders" if kind == "builder" else "community" if kind == "community" else "radar")
    result["channels"] = list(dict.fromkeys(channels))
    result["base_score"] = round(
        result["source_weight"]
        + relevance
        + recency_score(published_at, allowed_start, cutoff)
        + engagement_score(item.get("metrics")),
        2,
    )
    result["internal_score"] = result["base_score"]
    return result, None


def merge(primary: dict[str, Any], duplicate: dict[str, Any]) -> dict[str, Any]:
    if duplicate["source_weight"] > primary["source_weight"]:
        primary, duplicate = duplicate, primary
    primary["sources"] = list(dict.fromkeys([*primary["sources"], *duplicate["sources"]]))
    primary["source_urls"] = {**duplicate["source_urls"], **primary["source_urls"]}
    primary["channels"] = list(
        dict.fromkeys([*primary["channels"], *duplicate["channels"]])
    )
    bonus = min(3.0, 1.5 * (len(primary["sources"]) - 1))
    primary["internal_score"] = round(max(primary["base_score"], duplicate["base_score"]) + bonus, 2)
    for field in ("summary", "chinese_summary"):
        if not str(primary.get(field) or "").strip() and str(
            duplicate.get(field) or ""
        ).strip():
            primary[field] = duplicate[field]
    return primary


def dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda row: row["internal_score"], reverse=True):
        match = next((index for index, current in enumerate(merged) if same_story(current, item)), None)
        if match is None:
            merged.append(item)
        else:
            merged[match] = merge(merged[match], item)
    return sorted(
        merged,
        key=lambda row: (row["internal_score"], row["published_at"]),
        reverse=True,
    )


def exclude_seen(
    items: list[dict[str, Any]], seen_items: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], int]:
    kept = [item for item in items if not any(same_story(item, seen) for seen in seen_items)]
    return kept, len(items) - len(kept)


def coverage_counts(items: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {
        "kind": {},
        "section": {},
        "source_group": {},
    }
    for item in items:
        kind = str(item.get("kind") or "news")
        values = {
            "kind": kind,
            "section": (
                str(item.get("section") or "unassigned")
                if kind == "news"
                else "not_applicable"
            ),
            "source_group": str(item.get("source_group") or "unknown"),
        }
        for dimension, value in values.items():
            result[dimension][value] = result[dimension].get(value, 0) + 1
    return result


def select_review_queue(
    items: list[dict[str, Any]], limit: int
) -> list[dict[str, Any]]:
    """Preserve official and matched parallel lanes before global-score fill."""
    if limit <= 0:
        return []
    protected_groups = {"official", "builders", "community", "selected_media"}
    protected = [
        item for item in items if str(item.get("source_group")) in protected_groups
    ]
    if len(protected) >= limit:
        return protected[:limit]
    selected_ids = {id(item) for item in protected}
    remainder = [item for item in items if id(item) not in selected_ids]
    selected = protected + remainder[: limit - len(protected)]
    return sorted(
        selected,
        key=lambda row: (row["internal_score"], row["published_at"]),
        reverse=True,
    )


def main() -> int:
    args = parse_args()
    if min(args.hours, args.builder_hours, args.community_hours, args.longform_hours) <= 0:
        raise ValueError("all lookback windows must be positive")
    cutoff = parse_datetime(args.as_of)
    if cutoff is None:
        raise ValueError("--as-of must include a valid timezone")
    start = cutoff - timedelta(hours=args.hours)
    extended_starts = {
        "builder": cutoff - timedelta(hours=args.builder_hours),
        "community": cutoff - timedelta(hours=args.community_hours),
        "blog": cutoff - timedelta(hours=args.longform_hours),
        "podcast": cutoff - timedelta(hours=args.longform_hours),
    }
    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    input_meta, candidates = load_payload(args.input)

    prepared: list[dict[str, Any]] = []
    rejected: dict[str, int] = {}
    for candidate in candidates:
        result, reason = prepare(
            candidate,
            policy,
            start,
            cutoff,
            args.min_keyword_score,
            extended_starts,
        )
        if result is not None:
            prepared.append(result)
        else:
            rejected[reason or "unknown"] = rejected.get(reason or "unknown", 0) + 1

    merged = dedupe(prepared)
    seen_items = [item for path in args.seen for item in load_items(path)]
    unseen, seen_excluded = exclude_seen(merged, seen_items)
    selected = select_review_queue(unseen, args.limit)
    output_meta = dict(input_meta)
    output_meta.update(
        {
            "window_start": start.isoformat(),
            "window_end": cutoff.isoformat(),
            "windows_hours": {
                "news": args.hours,
                "builders": args.builder_hours,
                "community": args.community_hours,
                "longform": args.longform_hours,
            },
            "input_count": len(candidates),
            "matched_count": len(prepared),
            "deduped_count": len(merged),
            "seen_excluded": seen_excluded,
            "selected_count": len(selected),
            "rejected": rejected,
            "review_coverage": {
                "matched": coverage_counts(prepared),
                "deduped": coverage_counts(merged),
                "selected": coverage_counts(selected),
            },
        }
    )
    payload = {
        "meta": output_meta,
        "items": selected,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["meta"], ensure_ascii=False), file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
