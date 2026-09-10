#!/usr/bin/env python3
"""Collect AI brief candidates from configured feeds and public endpoints."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import time
from typing import Any
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = SKILL_ROOT / "references" / "source-feeds.json"
USER_AGENT = "AIIntelligenceBrief/3.0 (+feed collector)"
X_SNOWFLAKE_EPOCH_MS = 1288834974657
BUILDER_FEED_MAX_AGE_HOURS = 36.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", "-o", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--as-of", required=True, help="Exclusive ISO cutoff with timezone")
    parser.add_argument("--hours", type=float, default=24.0, help="News window")
    parser.add_argument("--builder-hours", type=float, default=36.0)
    parser.add_argument("--community-hours", type=float, default=48.0)
    parser.add_argument("--longform-hours", type=float, default=72.0)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--builder-feed", action="append", default=[])
    parser.add_argument(
        "--builder-evidence",
        type=Path,
        action="append",
        default=[],
        help="JSON/JSONL direct Builder posts; X timestamps may be derived from status IDs",
    )
    parser.add_argument("--podcast-feed", action="append", default=[])
    return parser.parse_args()


def parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(raw)
            # RFC 822 "-0000" parses to a naive datetime but means UTC.
            if parsed is not None and parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def fetch(url: str, timeout: float, attempts: int = 2) -> bytes:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/rss+xml, application/atom+xml, application/json, text/html;q=0.8, */*;q=0.5",
                },
            )
            with urlopen(request, timeout=timeout) as response:
                return response.read()
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.4 * (attempt + 1))
    raise RuntimeError(f"fetch failed for {url}: {last_error}")


def strip_html(value: Any) -> str:
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", str(value or ""), flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def first_text(element: ET.Element, names: set[str]) -> str:
    for child in element.iter():
        if local_name(child.tag) in names and child.text:
            return child.text.strip()
    return ""


def entry_link(element: ET.Element) -> str:
    for child in element.iter():
        if local_name(child.tag) != "link":
            continue
        href = str(child.attrib.get("href") or "").strip()
        rel = str(child.attrib.get("rel") or "alternate")
        if href and rel in {"alternate", ""}:
            return href
        if child.text and child.text.strip():
            return child.text.strip()
    # Fallback: some podcast feeds (e.g. megaphone.fm) omit <link> and only
    # expose the audio <enclosure>; use its URL so the item is still captured.
    for child in element.iter():
        if local_name(child.tag) == "enclosure":
            href = str(child.attrib.get("url") or "").strip()
            if href:
                return href
    for child in element.iter():
        if local_name(child.tag) == "guid" and child.text:
            return child.text.strip()
    return ""


def builder_fields(item: dict[str, Any]) -> None:
    path = urlsplit(str(item.get("url") or "")).path.strip("/").split("/")
    if len(path) >= 3 and path[1] == "status":
        item.setdefault("handle", "@" + path[0])
    author = str(item.get("author") or "").strip()
    if author.startswith("@"):
        item.setdefault("handle", author)
    original = strip_html(
        item.get("original_text") or item.get("summary") or item.get("content") or item.get("title")
    )
    item["original_text"] = original
    item["title"] = str(item.get("title") or original[:120] or author or "Builder post")


def x_status_datetime(url: str) -> datetime | None:
    match = re.search(
        r"https?://(?:www\.)?(?:x|twitter)\.com/[^/]+/status/(\d+)",
        url,
        flags=re.I,
    )
    if not match:
        return None
    status_id = int(match.group(1))
    timestamp_ms = (status_id >> 22) + X_SNOWFLAKE_EPOCH_MS
    try:
        return datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def load_rows(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith(("[", "{")):
        payload = json.loads(text)
        rows = (
            payload.get("items", [payload])
            if isinstance(payload, dict)
            else payload
        )
    else:
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"{path}: expected a JSON array, JSONL, or an object with items")
    return [dict(row) for row in rows]


def load_builder_evidence(path: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(load_rows(path), 1):
        url = str(raw.get("url") or raw.get("link") or "").strip()
        published = parse_datetime(raw.get("published_at"))
        if published is None:
            published = x_status_datetime(url)
        if published is None:
            raise ValueError(
                f"{path}: item {index} needs a timezone timestamp or direct X status URL"
            )
        if not re.search(
            r"https?://(?:www\.)?(?:x|twitter)\.com/[^/]+/status/\d+",
            url,
            flags=re.I,
        ):
            raise ValueError(f"{path}: item {index} is not a direct X status URL")
        item = {
            **raw,
            "title": str(
                raw.get("title")
                or raw.get("original_text")
                or raw.get("text")
                or raw.get("author")
                or "Builder post"
            ),
            "url": url,
            "source": str(raw.get("source") or "Manual Builder Evidence"),
            "published_at": published.isoformat(),
            "summary": strip_html(
                raw.get("summary")
                or raw.get("original_text")
                or raw.get("text")
                or raw.get("title")
            ),
            "kind": "builder",
            "channel": "builders",
            "manual_evidence": True,
        }
        builder_fields(item)
        result.append(item)
    return result


def parse_xml_feed(data: bytes, spec: dict[str, Any]) -> list[dict[str, Any]]:
    root = ET.fromstring(data)
    exclude_title_pattern = str(spec.get("exclude_title_pattern") or "")
    max_summary_chars = int(spec.get("max_summary_chars") or 0)
    entries = [
        element
        for element in root.iter()
        if local_name(element.tag) in {"item", "entry"}
    ]
    result: list[dict[str, Any]] = []
    for entry in entries[: int(spec.get("max_items", 100))]:
        title = strip_html(first_text(entry, {"title"}))
        url = entry_link(entry)
        published = first_text(entry, {"pubdate", "published", "updated", "date"})
        summary = strip_html(first_text(entry, {"description", "summary", "content", "encoded"}))
        author = strip_html(first_text(entry, {"creator", "author", "name"}))
        if not title or not url or not published:
            continue
        if exclude_title_pattern and re.search(
            exclude_title_pattern, title, flags=re.I
        ):
            continue
        if max_summary_chars and len(summary) > max_summary_chars:
            summary = summary[:max_summary_chars].rstrip()
        item = {
            "title": title,
            "url": url,
            "source": spec["name"],
            "published_at": published,
            "summary": summary,
            "kind": spec.get("kind", "news"),
            "channel": spec.get("channel", "radar"),
            "author": author,
            "tags": list(spec.get("tags") or []),
        }
        if spec.get("community_group"):
            item["community_group"] = spec["community_group"]
        if item["kind"] == "builder":
            builder_fields(item)
        result.append(item)
    return result


def parse_json_feed(data: bytes, spec: dict[str, Any]) -> list[dict[str, Any]]:
    payload = json.loads(data.decode("utf-8"))
    rows = payload.get("items", []) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("JSON feed must be an array or contain an items array")
    result: list[dict[str, Any]] = []
    for raw in rows[: int(spec.get("max_items", 100))]:
        if not isinstance(raw, dict):
            continue
        url = raw.get("url") or raw.get("external_url") or raw.get("link")
        title = raw.get("title") or raw.get("name") or raw.get("text")
        published = (
            raw.get("published_at")
            or raw.get("date_published")
            or raw.get("published")
            or raw.get("created_at")
            or raw.get("date")
        )
        if not url or not title or not published:
            continue
        item = {
            **raw,
            "title": strip_html(title),
            "url": str(url),
            "source": str(raw.get("source") or spec["name"]),
            "published_at": published,
            "summary": strip_html(
                raw.get("summary") or raw.get("content_text") or raw.get("content_html") or raw.get("text")
            ),
            "kind": str(raw.get("kind") or spec.get("kind") or "news"),
            "channel": str(raw.get("channel") or spec.get("channel") or "radar"),
        }
        if item["kind"] == "builder":
            builder_fields(item)
        result.append(item)
    return result


def parse_follow_builders_feed(
    data: bytes,
    spec: dict[str, Any],
    status: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    payload = json.loads(data.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Follow Builders feed must be a JSON object")

    generated = parse_datetime(payload.get("generatedAt") or payload.get("generated_at"))
    if generated is None:
        raise ValueError("Follow Builders feed needs a valid generatedAt timestamp")
    generated_at = generated.isoformat()
    if status is not None:
        status["generated_at"] = generated_at

    if "x" in payload:
        accounts = payload["x"]
        if not isinstance(accounts, list):
            raise ValueError("Follow Builders feed field 'x' must be an array")
    elif "days" in payload:
        days = payload["days"]
        if not isinstance(days, list):
            raise ValueError("Follow Builders feed field 'days' must be an array")
        accounts = []
        for day in days:
            if not isinstance(day, dict) or not isinstance(day.get("accounts", []), list):
                raise ValueError(
                    "Follow Builders legacy feed days must contain account arrays"
                )
            accounts.extend(day.get("accounts", []))
    else:
        raise ValueError("Follow Builders feed must contain 'x' or legacy 'days'")

    result: list[dict[str, Any]] = []
    for account in accounts:
        if not isinstance(account, dict):
            raise ValueError("Follow Builders accounts must be JSON objects")
        tweets = account.get("tweets", [])
        if not isinstance(tweets, list):
            raise ValueError("Follow Builders account tweets must be an array")
        username = str(account.get("username") or account.get("handle") or "").strip()
        author = str(account.get("name") or username).strip()
        for tweet in tweets:
            if not isinstance(tweet, dict):
                continue
            url = str(tweet.get("url") or "").strip()
            text = strip_html(tweet.get("text") or "")
            published = tweet.get("created_at") or tweet.get("createdAt")
            if not url or not text or not published:
                continue
            item = {
                **tweet,
                "title": text[:120],
                "url": url,
                "source": spec["name"],
                "published_at": published,
                "summary": text,
                "original_text": text,
                "kind": "builder",
                "channel": "builders",
                "author": author,
                "handle": f"@{username}" if username else "",
                "feed_generated_at": generated_at,
            }
            builder_fields(item)
            result.append(item)
            if len(result) >= int(spec.get("max_items", 500)):
                break
        if len(result) >= int(spec.get("max_items", 500)):
            break

    stats = payload.get("stats") or {}
    if not isinstance(stats, dict):
        raise ValueError("Follow Builders feed stats must be a JSON object")
    declared_count = stats.get("totalTweets", stats.get("total_tweets", 0))
    try:
        declared_count = int(declared_count or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Follow Builders stats totalTweets must be an integer") from exc
    if declared_count > 0 and not result:
        raise ValueError(
            f"Follow Builders feed declares {declared_count} tweets but parsed 0"
        )

    published_times = [
        parsed
        for item in result
        if (parsed := parse_datetime(item.get("published_at"))) is not None
    ]
    if status is not None and published_times:
        status["latest_published_at"] = max(published_times).isoformat()
    return result


class MetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, str] = {}
        self.title_parts: list[str] = []
        self.in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.casefold(): value or "" for key, value in attrs}
        if tag.casefold() == "meta":
            key = str(values.get("property") or values.get("name") or "").casefold()
            if key and values.get("content"):
                self.meta.setdefault(key, values["content"])
        elif tag.casefold() == "title":
            self.in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)


def parse_article_metadata(data: bytes, url: str, source: str) -> dict[str, Any] | None:
    text = data.decode("utf-8", errors="replace")
    parser = MetaParser()
    parser.feed(text)
    title = strip_html(
        parser.meta.get("og:title")
        or parser.meta.get("twitter:title")
        or " ".join(parser.title_parts)
    )
    summary = strip_html(
        parser.meta.get("og:description")
        or parser.meta.get("description")
        or parser.meta.get("twitter:description")
    )
    patterns = (
        r'<meta[^>]+(?:property|name)=["\'](?:article:published_time|date|pubdate)["\'][^>]+content=["\']([^"\']+)',
        r'"datePublished"\s*:\s*"([^"]+)"',
        r'\\"datePublished\\"\s*:\s*\\"([^"\\]+)',
        r'\\"publishedAt\\"\s*:\s*\\"([^"\\]+)',
        r'\\"addtime\\"\s*:\s*\\"([^"\\]+)',
        r'"addtime"\s*:\s*"([^"]+)"',
        r"(20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?[+-]\d\d:\d\d)",
        r">\s*([A-Z][a-z]+ \d{1,2}, 20\d\d)\s*<",
    )
    published = ""
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            published = match.group(1)
            break
    if not title or not published:
        return None
    return {
        "title": title,
        "url": url,
        "source": source,
        "published_at": published,
        "summary": summary,
        "kind": "news",
        "channel": "radar",
    }


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "a":
            return
        values = {key.casefold(): value or "" for key, value in attrs}
        href = values.get("href", "").strip()
        if href:
            self.links.append(href)


def extract_index_links(data: bytes, spec: dict[str, Any]) -> list[str]:
    parser = LinkParser()
    parser.feed(data.decode("utf-8", errors="replace"))
    pattern = re.compile(str(spec["link_pattern"]))
    base_url = str(spec.get("base_url") or spec["url"])
    links: list[str] = []
    for href in parser.links:
        absolute = urljoin(base_url, href)
        if not pattern.search(urlsplit(absolute).path):
            continue
        if absolute not in links:
            links.append(absolute)
        if len(links) >= int(spec.get("max_items", 80)):
            break
    return links


def collect_article_pages(
    links: list[str],
    spec: dict[str, Any],
    timeout: float,
    workers: int,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=min(max(workers, 1), 12)) as pool:
        futures = {pool.submit(fetch, url, timeout): url for url in links}
        for future in as_completed(futures):
            url = futures[future]
            try:
                item = parse_article_metadata(future.result(), url, spec["name"])
            except Exception as exc:
                errors.append(f"{url}: {exc}")
                continue
            if not item:
                continue
            item["kind"] = spec.get("kind", "news")
            item["channel"] = spec.get("channel", "radar")
            if spec.get("community_group"):
                item["community_group"] = spec["community_group"]
            result.append(item)
    if links and not result and errors:
        raise RuntimeError(
            f"article parsing failed for {len(errors)} items; first: {errors[0]}"
        )
    return result


def collect_article_index(
    spec: dict[str, Any], timeout: float, workers: int
) -> list[dict[str, Any]]:
    links = extract_index_links(fetch(spec["url"], timeout), spec)
    return collect_article_pages(links, spec, timeout, workers)


def collect_sitemap_articles(
    spec: dict[str, Any], timeout: float, workers: int
) -> list[dict[str, Any]]:
    root = ET.fromstring(fetch(spec["url"], timeout))
    prefixes = tuple(str(value) for value in spec.get("path_prefixes", []))
    links: list[str] = []
    for element in root.iter():
        if local_name(element.tag) != "loc" or not element.text:
            continue
        url = element.text.strip()
        path = urlsplit(url).path
        if prefixes and not path.startswith(prefixes):
            continue
        links.append(url)
        if len(links) >= int(spec.get("max_items", 80)):
            break
    return collect_article_pages(links, spec, timeout, workers)


class GitHubTrendingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.items: list[dict[str, Any]] = []
        self.depth = 0
        self.in_heading = False
        self.in_description = False
        self.in_language = False
        self.current: dict[str, Any] | None = None
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.casefold(): value or "" for key, value in attrs}
        classes = set(values.get("class", "").split())
        if tag.casefold() == "article" and "Box-row" in classes:
            self.depth = 1
            self.current = {"description": "", "language": ""}
            self.text = []
            return
        if not self.current:
            return
        self.depth += 1
        if tag.casefold() == "h2":
            self.in_heading = True
        elif tag.casefold() == "p" and "color-fg-muted" in classes:
            self.in_description = True
        elif tag.casefold() == "span" and values.get("itemprop") == "programmingLanguage":
            self.in_language = True
        elif tag.casefold() == "a" and self.in_heading and values.get("href"):
            self.current["path"] = values["href"]

    def handle_endtag(self, tag: str) -> None:
        if not self.current:
            return
        if tag.casefold() == "h2":
            self.in_heading = False
        elif tag.casefold() == "p":
            self.in_description = False
        elif tag.casefold() == "span":
            self.in_language = False
        self.depth -= 1
        if self.depth != 0:
            return
        combined = re.sub(r"\s+", " ", " ".join(self.text))
        match = re.search(r"([\d,]+)\s+stars today", combined, flags=re.I)
        self.current["stars_today"] = int(match.group(1).replace(",", "")) if match else 0
        if self.current.get("path"):
            self.items.append(self.current)
        self.current = None

    def handle_data(self, data: str) -> None:
        if not self.current:
            return
        value = re.sub(r"\s+", " ", data).strip()
        if not value:
            return
        self.text.append(value)
        if self.in_description:
            self.current["description"] = (
                f"{self.current.get('description', '')} {value}".strip()
            )
        if self.in_language:
            self.current["language"] = value


def collect_github_trending(
    spec: dict[str, Any], timeout: float, cutoff: datetime
) -> list[dict[str, Any]]:
    observed_at = datetime.now(timezone.utc)
    if abs((observed_at - cutoff).total_seconds()) > 3600:
        raise ValueError(
            "GitHub Trending is a live snapshot and cannot represent a historical cutoff"
        )
    effective_at = min(observed_at, cutoff - timedelta(microseconds=1))
    parser = GitHubTrendingParser()
    parser.feed(fetch(spec["url"], timeout).decode("utf-8", errors="replace"))
    result: list[dict[str, Any]] = []
    for raw in parser.items[: int(spec.get("max_items", 50))]:
        path = str(raw["path"])
        repository = re.sub(r"\s+", "", path.strip("/"))
        tags = [str(raw.get("language") or "")] if raw.get("language") else []
        result.append(
            {
                "title": repository,
                "url": urljoin("https://github.com", path),
                "source": spec["name"],
                "published_at": effective_at.isoformat(),
                "observed_at": observed_at.isoformat(),
                "timestamp_type": "observed_at",
                "summary": str(raw.get("description") or ""),
                "kind": spec.get("kind", "community"),
                "channel": spec.get("channel", "community"),
                "community_group": spec.get("community_group", "GitHub Trending"),
                "metrics": {"points": int(raw.get("stars_today") or 0), "comments": 0},
                "tags": tags,
            }
        )
    return result


def extract_aibase_article_ids(index: str, max_items: int) -> list[str]:
    """Return recent AIbase article IDs without mixing in sidebar recommendations."""
    listing_ids = list(
        dict.fromkeys(re.findall(r'href="/(?:zh/)?news/(\d+)"', index))
    )
    if listing_ids:
        newest = max(int(article_id) for article_id in listing_ids)
        return [str(article_id) for article_id in range(newest, newest - max_items, -1)]

    fallback_ids: list[str] = []
    fallback_ids.extend(re.findall(r'\\"Id\\":(\d+)', index))
    fallback_ids.extend(re.findall(r'/(?:zh/)?news/(\d{4,})', index))
    return sorted(set(fallback_ids), key=int, reverse=True)[:max_items]


def collect_aibase(spec: dict[str, Any], timeout: float, workers: int) -> list[dict[str, Any]]:
    index_urls = [str(spec["url"])]
    index_template = str(spec.get("index_template") or "")
    if index_template:
        index_urls = [
            index_template.format(page=page)
            for page in range(1, int(spec.get("index_pages", 1)) + 1)
        ]
    max_items = int(spec.get("max_items", 40))
    ids: list[str] = []
    for index_url in index_urls:
        index = fetch(index_url, timeout).decode("utf-8", errors="replace")
        ids.extend(extract_aibase_article_ids(index, max_items))
    ids = sorted(set(ids), key=int, reverse=True)[:max_items]
    template = str(spec["article_template"])
    result: list[dict[str, Any]] = []
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=min(max(workers, 1), 10)) as pool:
        futures = {
            pool.submit(fetch, template.format(id=article_id), timeout): template.format(id=article_id)
            for article_id in ids
        }
        for future in as_completed(futures):
            url = futures[future]
            try:
                item = parse_article_metadata(future.result(), url, spec["name"])
            except Exception as exc:
                errors.append(f"{url}: {exc}")
                continue
            if item:
                result.append(item)
    if ids and not result and errors:
        raise RuntimeError(
            f"AIbase article parsing failed for {len(errors)} items; first: {errors[0]}"
        )
    return result


def collect_hacker_news(
    spec: dict[str, Any],
    timeout: float,
    workers: int,
    cutoff: datetime,
) -> list[dict[str, Any]]:
    ids = json.loads(fetch(spec["url"], timeout).decode("utf-8"))
    ids = ids[: int(spec.get("scan_items", 500))]
    start = cutoff - timedelta(hours=24)

    def load_item(item_id: int) -> dict[str, Any] | None:
        data = fetch(f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json", timeout)
        raw = json.loads(data.decode("utf-8"))
        if not raw or raw.get("type") != "story" or not raw.get("title") or not raw.get("time"):
            return None
        published = parse_datetime(raw["time"])
        if published is None or not (start <= published < cutoff):
            return None
        hn_url = f"https://news.ycombinator.com/item?id={item_id}"
        source_urls = {"Hacker News": hn_url}
        if raw.get("url"):
            source_urls["Original"] = raw["url"]
        return {
            "title": raw["title"],
            "url": hn_url,
            "source": "Hacker News",
            "published_at": raw["time"],
            "summary": "",
            "kind": "community",
            "channel": "community",
            "community_group": "Hacker News",
            "metrics": {
                "points": raw.get("score", 0),
                "comments": raw.get("descendants", 0),
            },
            "source_urls": source_urls,
        }

    result: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(workers, 1)) as pool:
        futures = [pool.submit(load_item, item_id) for item_id in ids]
        for future in as_completed(futures):
            try:
                item = future.result()
            except Exception:
                continue
            if item:
                result.append(item)
    result.sort(
        key=lambda item: (
            int(item.get("metrics", {}).get("points", 0)),
            int(item.get("metrics", {}).get("comments", 0)),
            str(item.get("published_at") or ""),
        ),
        reverse=True,
    )
    return result[: int(spec.get("max_items", 100))]


def collect_feed(
    spec: dict[str, Any],
    timeout: float,
    workers: int,
    cutoff: datetime | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    fmt = str(spec.get("format") or "auto")
    if fmt == "aibase_index":
        return collect_aibase(spec, timeout, workers), {}
    if fmt == "hacker_news":
        if cutoff is None:
            raise ValueError("Hacker News collection requires a cutoff")
        return collect_hacker_news(spec, timeout, workers, cutoff), {}
    if fmt == "article_index":
        return collect_article_index(spec, timeout, workers), {}
    if fmt == "sitemap_articles":
        return collect_sitemap_articles(spec, timeout, workers), {}
    if fmt == "github_trending":
        if cutoff is None:
            raise ValueError("GitHub Trending collection requires a cutoff")
        return collect_github_trending(spec, timeout, cutoff), {}
    data = fetch(spec["url"], timeout)
    if fmt == "auto":
        stripped = data.lstrip()
        if stripped.startswith((b"{", b"[")):
            fmt = (
                "follow_builders_json"
                if spec.get("kind") == "builder"
                else "json"
            )
        else:
            fmt = "rss"
    if fmt in {"rss", "atom"}:
        return parse_xml_feed(data, spec), {}
    if fmt == "json":
        return parse_json_feed(data, spec), {}
    if fmt == "follow_builders_json":
        status: dict[str, Any] = {}
        return parse_follow_builders_feed(data, spec, status), status
    raise ValueError(f"unsupported feed format: {fmt}")


def validate_follow_builders_freshness(
    spec: dict[str, Any],
    status: dict[str, Any],
    cutoff: datetime,
) -> None:
    if (
        spec.get("format") != "follow_builders_json"
        and "generated_at" not in status
    ):
        return
    generated = parse_datetime(status.get("generated_at"))
    if generated is None:
        raise ValueError("Follow Builders feed did not report generated_at")
    oldest_allowed = cutoff - timedelta(hours=BUILDER_FEED_MAX_AGE_HOURS)
    if generated < oldest_allowed:
        raise ValueError(
            "Follow Builders feed is stale: "
            f"generated_at {generated.isoformat()} is more than "
            f"{BUILDER_FEED_MAX_AGE_HOURS:g}h before cutoff {cutoff.isoformat()}"
        )


def kind_window_hours(kind: str, args: argparse.Namespace) -> float:
    if kind == "builder":
        return args.builder_hours
    if kind == "community":
        return args.community_hours
    if kind in {"blog", "podcast"}:
        return args.longform_hours
    return args.hours


def resolve_specs(config: dict[str, Any], args: argparse.Namespace) -> list[dict[str, Any]]:
    specs = [dict(spec) for spec in config.get("feeds", []) if spec.get("enabled", True)]
    for spec in config.get("optional_feeds", []):
        url = os.environ.get(str(spec.get("env") or ""))
        if url:
            resolved = dict(spec)
            resolved["url"] = url
            specs.append(resolved)
    for url in args.builder_feed:
        specs.append(
            {
                "name": "Follow Builders RSS",
                "url": url,
                "format": "auto",
                "kind": "builder",
                "channel": "builders",
                "max_items": 200,
            }
        )
    for url in args.podcast_feed:
        specs.append(
            {
                "name": "AI Podcast Feed",
                "url": url,
                "format": "auto",
                "kind": "podcast",
                "channel": "radar",
                "max_items": 30,
            }
        )
    return specs


def main() -> int:
    args = parse_args()
    cutoff = parse_datetime(args.as_of)
    if cutoff is None:
        raise ValueError("--as-of must include a valid timezone")
    if min(args.hours, args.builder_hours, args.community_hours, args.longform_hours) <= 0:
        raise ValueError("all lookback windows must be positive")
    config = json.loads(args.config.read_text(encoding="utf-8"))
    specs = resolve_specs(config, args)

    items: list[dict[str, Any]] = []
    statuses: dict[str, list[dict[str, Any]]] = {}
    for unavailable in config.get("unavailable_sources", []):
        statuses.setdefault(str(unavailable["name"]), []).append(
            {
                "url": str(unavailable.get("url") or ""),
                "status": "unavailable",
                "reason": str(unavailable.get("reason") or "No reliable public feed"),
            }
        )
    empty_status = {"configured": 0, "ok": 0, "empty": 0, "failed": 0, "raw": 0}
    lane_status: dict[str, dict[str, int]] = {
        lane: dict(empty_status) for lane in ("radar", "builders", "community")
    }
    kind_status: dict[str, dict[str, int]] = {
        kind: dict(empty_status)
        for kind in ("news", "builder", "community", "podcast", "blog")
    }
    for spec in specs:
        lane = str(spec.get("channel") or "radar")
        kind = str(spec.get("kind") or "news")
        lane_status.setdefault(
            lane,
            {"configured": 0, "ok": 0, "empty": 0, "failed": 0, "raw": 0},
        )
        kind_status.setdefault(
            kind,
            {"configured": 0, "ok": 0, "empty": 0, "failed": 0, "raw": 0},
        )
        lane_status[lane]["configured"] += 1
        kind_status[kind]["configured"] += 1
    with ThreadPoolExecutor(max_workers=max(args.workers, 1)) as pool:
        futures = {
            pool.submit(collect_feed, spec, args.timeout, args.workers, cutoff): spec
            for spec in specs
        }
        for future in as_completed(futures):
            spec = futures[future]
            name = str(spec["name"])
            status_details: dict[str, Any] = {}
            try:
                collected, status_details = future.result()
                validate_follow_builders_freshness(spec, status_details, cutoff)
                status = "ok" if collected else "empty"
                statuses.setdefault(name, []).append(
                    {
                        "url": spec["url"],
                        "status": status,
                        "raw": len(collected),
                        **status_details,
                    }
                )
                lane = str(spec.get("channel") or "radar")
                kind = str(spec.get("kind") or "news")
                lane_status[lane][status] += 1
                lane_status[lane]["raw"] += len(collected)
                kind_status[kind][status] += 1
                kind_status[kind]["raw"] += len(collected)
                items.extend(collected)
            except Exception as exc:
                statuses.setdefault(name, []).append(
                    {
                        "url": spec.get("url", ""),
                        "status": "failed",
                        "error": str(exc),
                        **status_details,
                    }
                )
                lane = str(spec.get("channel") or "radar")
                kind = str(spec.get("kind") or "news")
                lane_status[lane]["failed"] += 1
                kind_status[kind]["failed"] += 1

    for path in args.builder_evidence:
        evidence = load_builder_evidence(path)
        statuses.setdefault("Manual Builder Evidence", []).append(
            {"url": str(path), "status": "ok" if evidence else "empty", "raw": len(evidence)}
        )
        items.extend(evidence)

    accepted: list[dict[str, Any]] = []
    skipped_missing_time = 0
    skipped_outside = 0
    seen_urls: set[str] = set()
    primary_start = cutoff - timedelta(hours=args.hours)
    for item in items:
        published = parse_datetime(item.get("published_at"))
        if published is None:
            skipped_missing_time += 1
            continue
        lookback = kind_window_hours(str(item.get("kind") or "news"), args)
        start = cutoff - timedelta(hours=lookback)
        if not (start <= published < cutoff):
            skipped_outside += 1
            continue
        url = str(item.get("url") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        item["published_at"] = published.isoformat()
        item["window_class"] = "primary" if published >= primary_start else "extended"
        accepted.append(item)

    source_counts: dict[str, int] = {}
    kind_counts: dict[str, int] = {}
    for item in accepted:
        source = str(item.get("source") or "Unknown")
        source_counts[source] = source_counts.get(source, 0) + 1
        kind = str(item.get("kind") or "news")
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
    accepted.sort(key=lambda item: str(item.get("published_at") or ""), reverse=True)
    payload = {
        "meta": {
            "collection": {
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "cutoff": cutoff.isoformat(),
                "windows_hours": {
                    "news": args.hours,
                    "builders": args.builder_hours,
                    "community": args.community_hours,
                    "longform": args.longform_hours,
                },
                "raw_count": len(items),
                "accepted_count": len(accepted),
                "skipped_missing_time": skipped_missing_time,
                "skipped_outside_window": skipped_outside,
                "source_counts": source_counts,
                "kind_counts": kind_counts,
                "manual_evidence_count": sum(
                    1 for item in accepted if item.get("manual_evidence")
                ),
                "lane_status": lane_status,
                "kind_status": kind_status,
                "source_status": statuses,
            }
        },
        "items": accepted,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["meta"]["collection"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
