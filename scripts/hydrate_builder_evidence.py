#!/usr/bin/env python3
"""Hydrate known public X status URLs through the unauthenticated oEmbed API."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


X_EPOCH_MS = 1288834974657
STATUS_RE = re.compile(
    r"https?://(?:www\.)?(?:x|twitter)\.com/[^/\s]+/status/\d+",
    re.I,
)


class TweetText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.in_paragraph = False

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag == "p":
            self.in_paragraph = True
        elif tag == "br" and self.in_paragraph:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "p":
            self.in_paragraph = False

    def handle_data(self, data: str) -> None:
        if self.in_paragraph:
            self.parts.append(data)


def load_rows(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return [{"url": match.group(0)} for match in STATUS_RE.finditer(text)]
    rows = data.get("items", [data]) if isinstance(data, dict) else data
    return [dict(row) for row in rows]


def hydrate(row: dict, timeout: float) -> dict:
    url = str(row.get("url") or "").strip()
    if not STATUS_RE.fullmatch(url):
        raise ValueError(f"not a direct X status URL: {url}")
    endpoint = "https://publish.twitter.com/oembed?" + urlencode(
        {"url": url, "omit_script": "1", "dnt": "1"}
    )
    request = Request(
        endpoint,
        headers={"User-Agent": "ai-intelligence-brief/1.0"},
    )
    with urlopen(request, timeout=timeout) as response:
        data = json.load(response)

    parser = TweetText()
    parser.feed(str(data.get("html") or ""))
    original = re.sub(
        r"\n{3,}",
        "\n\n",
        unescape("".join(parser.parts)),
    ).strip()
    path = urlsplit(url).path.strip("/").split("/")
    status_id = int(path[-1])
    timestamp_ms = (status_id >> 22) + X_EPOCH_MS
    return {
        **row,
        "title": str(row.get("title") or original[:120] or data.get("author_name")),
        "url": url,
        "source": "X oEmbed",
        "published_at": datetime.fromtimestamp(
            timestamp_ms / 1000,
            timezone.utc,
        ).isoformat(),
        "author": str(row.get("author") or data.get("author_name") or path[0]),
        "handle": str(row.get("handle") or "@" + path[0]),
        "original_text": original,
        "summary": original,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", "-o", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=15)
    args = parser.parse_args()

    seen: set[str] = set()
    items: list[dict] = []
    for row in load_rows(args.input):
        url = str(row.get("url") or "")
        if url and url not in seen:
            items.append(hydrate(row, args.timeout))
            seen.add(url)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"items": items}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {"hydrated": len(items), "output": str(args.output)},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
