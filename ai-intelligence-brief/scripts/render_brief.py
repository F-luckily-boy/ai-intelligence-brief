#!/usr/bin/env python3
"""Render a ranked AI brief to Markdown, self-contained HTML, and optional PDF."""

from __future__ import annotations

import argparse
from datetime import date as date_type, datetime
from html import escape
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any
from zoneinfo import ZoneInfo


SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSS = SKILL_ROOT / "assets" / "brief.css"
WEEKDAYS = "一二三四五六日"
NEWS_SECTIONS = (
    ("core", "核心头条"),
    ("industry", "产业与商业"),
    ("models", "模型与工具"),
    ("research", "研究与深度"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--css", type=Path, default=DEFAULT_CSS)
    parser.add_argument("--note", default="")
    parser.add_argument("--pdf", action="store_true")
    parser.add_argument("--chrome", default="")
    return parser.parse_args()


def load_payload(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return {}, [dict(item) for item in payload]
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ValueError("input must be an array or an object with an items array")
    return dict(payload.get("meta") or {}), [dict(item) for item in payload["items"]]


def title_of(item: dict[str, Any]) -> str:
    return str(item.get("chinese_title") or item.get("title") or "未命名").strip()


def summary_of(item: dict[str, Any]) -> str:
    return str(item.get("chinese_summary") or item.get("summary") or "").strip()


def sources_of(item: dict[str, Any]) -> list[str]:
    values = item.get("sources") or [item.get("source")]
    return list(dict.fromkeys(str(value) for value in values if value))


def source_url(item: dict[str, Any], source: str) -> str:
    return str((item.get("source_urls") or {}).get(source) or item.get("url") or "")


def secondary_sources_markdown(item: dict[str, Any]) -> str:
    links = []
    for source in sources_of(item)[1:]:
        url = source_url(item, source)
        links.append(f"[{source}]({url})" if url else source)
    return f" · {' · '.join(links)}" if links else ""


def secondary_sources_html(item: dict[str, Any]) -> str:
    links = []
    for source in sources_of(item)[1:]:
        url = source_url(item, source)
        links.append(
            f'<a href="{escape(url, quote=True)}">{escape(source)}</a>'
            if url
            else escape(source)
        )
    return f' · <span class="source-links">{" · ".join(links)}</span>' if links else ""


def corroboration_text(item: dict[str, Any]) -> str:
    count = len(sources_of(item))
    return f"（{count} 源报道）" if count >= 2 else ""


def news_markdown(item: dict[str, Any]) -> str:
    title = title_of(item)
    url = str(item.get("url") or "")
    linked = f"[{title}]({url})" if url else title
    summary = summary_of(item)
    corroboration = corroboration_text(item)
    return (
        f"**{linked}**{f' {corroboration}' if corroboration else ''}"
        f"{f' {summary}' if summary else ''}{secondary_sources_markdown(item)}"
    )


def news_html(item: dict[str, Any]) -> str:
    title = title_of(item)
    url = str(item.get("url") or "")
    linked = (
        f'<a href="{escape(url, quote=True)}">{escape(title)}</a>'
        if url
        else escape(title)
    )
    summary = summary_of(item)
    corroboration = corroboration_text(item)
    return (
        '<p class="entry"><span class="entry-title">'
        f"{linked}</span>{f' {escape(corroboration)}' if corroboration else ''}"
        f"{f' {escape(summary)}' if summary else ''}"
        f"{secondary_sources_html(item)}</p>"
    )


def builder_identity(item: dict[str, Any]) -> str:
    name = str(item.get("author") or title_of(item))
    handle = str(item.get("handle") or "").strip()
    identity = f"{name} ({handle if handle.startswith('@') else '@' + handle})" if handle else name
    detail = " / ".join(
        value
        for value in (
            str(item.get("affiliation") or "").strip(),
            str(item.get("role") or "").strip(),
        )
        if value
    )
    return f"{identity} · {detail}" if detail else identity


def builder_markdown(item: dict[str, Any]) -> str:
    identity = builder_identity(item)
    url = str(item.get("url") or "")
    linked = f"[{identity}]({url})" if url else identity
    original = str(item.get("original_text") or "").strip()
    translated = str(item.get("translated_text") or "").strip()
    marker = " · 双源信号" if item.get("cross_signal") else ""
    return f"**{linked}** — “{original}” / “{translated}”{marker}"


def builder_html(item: dict[str, Any]) -> str:
    identity = builder_identity(item)
    url = str(item.get("url") or "")
    linked = (
        f'<a href="{escape(url, quote=True)}">{escape(identity)}</a>'
        if url
        else escape(identity)
    )
    original = escape(str(item.get("original_text") or "").strip())
    translated = escape(str(item.get("translated_text") or "").strip())
    marker = ' <span class="signal-marker">· 双源信号</span>' if item.get("cross_signal") else ""
    return (
        '<p class="entry"><span class="builder-name">'
        f"{linked}</span> — “{original}” / “{translated}”{marker}</p>"
    )


def builder_groups(items: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    index: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        key = str(item.get("handle") or item.get("author") or title_of(item)).casefold()
        if key not in index:
            index[key] = []
            groups.append(index[key])
        index[key].append(item)
    return groups


def longform_markdown(item: dict[str, Any]) -> str:
    title = title_of(item)
    url = str(item.get("url") or "")
    linked = f"[{title}]({url})" if url else title
    body = str(item.get("translated_text") or summary_of(item)).strip()
    original = str(item.get("original_text") or "").strip()
    byline = str(item.get("byline") or "").strip()
    parts = [f"**{linked}**"]
    if byline:
        parts.extend(["", f"*{byline}*"])
    if original:
        parts.extend(["", f"[English] {original}"])
    if body:
        parts.extend(["", body])
    return "\n".join(parts)


def rich_text_html(value: str) -> str:
    paragraphs = [
        paragraph.strip()
        for paragraph in value.split("\n")
        if paragraph.strip()
    ]
    parts: list[str] = []
    index = 0
    while index < len(paragraphs):
        paragraph = paragraphs[index]
        if paragraph.startswith("**") and paragraph.endswith("**") and len(paragraph) > 4:
            heading = f"<h4>{escape(paragraph[2:-2])}</h4>"
            if index + 1 < len(paragraphs):
                following = paragraphs[index + 1]
                if not (following.startswith("**") and following.endswith("**")):
                    parts.append(
                        '<div class="longform-lead">'
                        f"{heading}<p>{escape(following)}</p></div>"
                    )
                    index += 2
                    continue
            parts.append(heading)
        else:
            parts.append(f"<p>{escape(paragraph)}</p>")
        index += 1
    return "".join(parts)


def longform_html(item: dict[str, Any]) -> str:
    title = title_of(item)
    url = str(item.get("url") or "")
    linked = (
        f'<a href="{escape(url, quote=True)}">{escape(title)}</a>'
        if url
        else escape(title)
    )
    parts = [
        '<article class="longform">',
        f'<p class="entry"><span class="entry-title">{linked}</span></p>',
    ]
    byline = str(item.get("byline") or "").strip()
    if byline:
        parts.append(f'<p class="byline">{escape(byline)}</p>')
    original = str(item.get("original_text") or "").strip()
    translated = str(item.get("translated_text") or summary_of(item)).strip()
    if original:
        parts.append(f'<p><span class="lang-label">English</span>{escape(original)}</p>')
    if translated:
        parts.append(rich_text_html(translated))
    parts.append("</article>")
    return "".join(parts)


def split_sections(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result = {key: [] for key, _ in NEWS_SECTIONS}
    result.update({"news": [], "builder": [], "podcast": [], "blog": [], "community": []})
    for item in items:
        kind = str(item.get("kind") or "news")
        if kind == "news":
            result["news"].append(item)
            result.get(str(item.get("section") or "models"), result["models"]).append(item)
        elif kind in result:
            result[kind].append(item)
    return result


def news_groups(news: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    section_names = dict(NEWS_SECTIONS)
    groups: list[tuple[str, list[dict[str, Any]]]] = []
    index: dict[str, list[dict[str, Any]]] = {}
    for item in news:
        label = str(
            item.get("event_title")
            or item.get("theme")
            or section_names.get(str(item.get("section") or "models"), "其他")
        ).strip()
        if label not in index:
            index[label] = []
            groups.append((label, index[label]))
        index[label].append(item)
    return groups


def local_time(value: Any) -> str:
    raw = str(value or "").strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return raw
    if parsed.tzinfo is None:
        return raw
    return parsed.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M")


def metadata_text(meta: dict[str, Any], items: list[dict[str, Any]], note: str) -> str:
    parts: list[str] = []
    windows = dict(meta.get("windows_hours") or {})
    news_hours = float(windows.get("news") or 24)
    if meta.get("window_start") and meta.get("window_end"):
        parts.append(
            f"新闻窗口: {local_time(meta['window_start'])} 至 "
            f"{local_time(meta['window_end'])}（{news_hours:g}h，Asia/Shanghai）"
        )
    extended = []
    for key, label in (
        ("builders", "Builders"),
        ("community", "社区"),
        ("longform", "播客/长文"),
    ):
        hours = float(windows.get(key) or news_hours)
        if hours != news_hours:
            extended.append(f"{label} {hours:g}h")
    if extended:
        parts.append("扩展观察: " + " · ".join(extended))

    collection = dict(meta.get("collection") or {})
    raw_count = collection.get("raw_count")
    accepted_count = collection.get("accepted_count")
    manual_evidence_count = collection.get("manual_evidence_count")
    if raw_count is not None:
        counts = f"自动采集原始信号 {raw_count}"
        if accepted_count is not None:
            counts += f" · 自动窗内 {accepted_count}"
        if manual_evidence_count:
            counts += f" · 人工核验直链 {manual_evidence_count}"
        if meta.get("deduped_count") is not None:
            counts += f" · 自动候选去重后 {meta['deduped_count']}"
        parts.append(counts)
    elif meta.get("input_count") is not None:
        parts.append(
            f"采集 {meta['input_count']} · 匹配 {meta.get('matched_count', 0)} · "
            f"去重后 {meta.get('deduped_count', 0)}"
        )

    selected: dict[str, int] = {}
    builder_authors: set[str] = set()
    for item in items:
        kind = str(item.get("kind") or "news")
        selected[kind] = selected.get(kind, 0) + 1
        if kind == "builder":
            builder_authors.add(
                str(item.get("handle") or item.get("author") or title_of(item)).casefold()
            )

    lane_status = dict(collection.get("lane_status") or {})
    builder_status = dict(lane_status.get("builders") or {})
    if not selected.get("builder") and builder_status:
        configured = int(builder_status.get("configured") or 0)
        successful = int(builder_status.get("ok") or 0)
        manual_count = int(collection.get("manual_evidence_count") or 0)
        if configured == 0 and manual_count == 0:
            parts.append("Builders: 未配置可靠 Feed")
        elif configured > 0 and successful == 0:
            parts.append("Builders: 采集失败")
        elif successful > 0:
            parts.append("Builders: 已采集，未入选")

    kind_status = dict(collection.get("kind_status") or {})
    podcast_status = dict(kind_status.get("podcast") or {})
    if not selected.get("podcast") and podcast_status:
        configured = int(podcast_status.get("configured") or 0)
        successful = int(podcast_status.get("ok") or 0)
        captured = int(dict(collection.get("kind_counts") or {}).get("podcast") or 0)
        if configured == 0:
            parts.append("播客: 未配置源")
        elif successful == 0:
            parts.append("播客: 采集失败")
        elif captured == 0:
            parts.append("播客: 窗口内无新内容")
        else:
            parts.append("播客: 已采集，未入选")

    breakdown = [f"新闻 {selected.get('news', 0)}"]
    if selected.get("builder"):
        breakdown.append(
            f"Builders {len(builder_authors)} 人/{selected['builder']} 条"
        )
    if selected.get("community"):
        breakdown.append(f"社区 {selected['community']}")
    longform_count = selected.get("podcast", 0) + selected.get("blog", 0)
    if longform_count:
        breakdown.append(f"播客/长文 {longform_count}")
    parts.append(f"入选 {len(items)}（{' · '.join(breakdown)}）")
    if meta.get("seen_excluded"):
        parts.append(f"跨日去重: {meta['seen_excluded']} 条")
    if note:
        parts.append(f"注: {note}")
    return " | ".join(parts)


def credit_markdown(meta: dict[str, Any]) -> str:
    text = str(meta.get("credit_text") or "").strip()
    url = str(meta.get("credit_url") or "").strip()
    if not text:
        return ""
    return f"[{text}]({url})" if url else text


def credit_html(meta: dict[str, Any]) -> str:
    text = str(meta.get("credit_text") or "").strip()
    url = str(meta.get("credit_url") or "").strip()
    if not text:
        return ""
    content = (
        f'<a href="{escape(url, quote=True)}">{escape(text)}</a>'
        if url
        else escape(text)
    )
    return f'<footer class="credit">{content}</footer>'


def render_markdown(
    date: str,
    meta: dict[str, Any],
    sections: dict[str, list[dict[str, Any]]],
    items: list[dict[str, Any]],
    note: str,
) -> str:
    day = date_type.fromisoformat(date)
    lines = [
        f"# AI 情报简报 · {date}（周{WEEKDAYS[day.weekday()]}）",
        "",
        f"> {metadata_text(meta, items, note)}",
        "",
        "## 过去 24 小时 · AI 圈信号",
    ]
    for heading, group in news_groups(sections["news"]):
        lines.extend(["", f"### {heading}", ""])
        lines.extend(
            f"{index}. {news_markdown(item)}"
            for index, item in enumerate(group, 1)
        )
    if sections["builder"]:
        lines.extend(["", "## Builders · 他们在说什么", ""])
        for group in builder_groups(sections["builder"]):
            lines.append(builder_markdown(group[0]))
            lines.extend(f"  - {builder_markdown(item)}" for item in group[1:])
    if sections["community"]:
        lines.extend(["", "## 社区精选"])
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in sections["community"]:
            grouped.setdefault(str(item.get("community_group") or item.get("source") or "社区"), []).append(item)
        for label, group in grouped.items():
            lines.extend(["", f"### {label}", ""])
            lines.extend(f"- {news_markdown(item)}" for item in group)
    for key, heading in (("podcast", "播客精选"), ("blog", "博客精选")):
        if sections[key]:
            lines.extend(["", f"## {heading}", ""])
            lines.extend(longform_markdown(item) for item in sections[key])
    credit = credit_markdown(meta)
    if credit:
        lines.extend(["", "---", "", credit])
    return "\n".join(lines) + "\n"


def render_html(
    date: str,
    meta: dict[str, Any],
    sections: dict[str, list[dict[str, Any]]],
    items: list[dict[str, Any]],
    note: str,
    css: str,
) -> str:
    day = date_type.fromisoformat(date)
    body = [
        "<!doctype html>",
        '<html lang="zh-CN"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>AI情报简报-{escape(date)}</title>",
        f"<style>{css}</style></head><body><main>",
        f"<h1>AI 情报简报 · {escape(date)}（周{WEEKDAYS[day.weekday()]}）</h1>",
        f'<div class="meta">{escape(metadata_text(meta, items, note))}</div>',
        '<section class="major-section"><h2>过去 24 小时 · AI 圈信号</h2>',
    ]
    for heading, group in news_groups(sections["news"]):
        body.append(f'<h3>{escape(heading)}</h3><ol class="news-list">')
        body.extend(f"<li>{news_html(item)}</li>" for item in group)
        body.append("</ol>")
    body.append("</section>")
    if sections["builder"]:
        body.append('<section class="major-section"><h2>Builders · 他们在说什么</h2>')
        for group in builder_groups(sections["builder"]):
            body.append(f'<div class="builder-group">{builder_html(group[0])}')
            body.extend(
                f'<div class="builder-followup">{builder_html(item)}</div>'
                for item in group[1:]
            )
            body.append("</div>")
        body.append("</section>")
    if sections["community"]:
        body.append('<section class="major-section community-section"><h2>社区精选</h2>')
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in sections["community"]:
            grouped.setdefault(str(item.get("community_group") or item.get("source") or "社区"), []).append(item)
        for label, group in grouped.items():
            body.append(f'<h3>{escape(label)}</h3><ul class="community-list">')
            body.extend(f"<li>{news_html(item)}</li>" for item in group)
            body.append("</ul>")
        body.append("</section>")
    for key, heading in (("podcast", "播客精选"), ("blog", "博客精选")):
        if sections[key]:
            body.append(f'<section class="major-section {key}-section"><h2>{heading}</h2>')
            body.extend(longform_html(item) for item in sections[key])
            body.append("</section>")
    credit = credit_html(meta)
    if credit:
        body.append(credit)
    body.append("</main></body></html>")
    return "\n".join(body)


def find_chrome(explicit: str) -> str | None:
    candidates = [
        explicit,
        shutil.which("google-chrome") or "",
        shutil.which("chromium") or "",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]
    return next((value for value in candidates if value and Path(value).exists()), None)


def print_pdf(html_path: Path, pdf_path: Path, chrome: str) -> None:
    completed = subprocess.run(
        [
            chrome,
            "--headless",
            "--no-sandbox",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path}",
            html_path.resolve().as_uri(),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if completed.returncode != 0 or not pdf_path.exists():
        message = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"Chrome PDF generation failed: {message}")


def main() -> int:
    args = parse_args()
    date_type.fromisoformat(args.date)
    meta, items = load_payload(args.input)
    sections = split_sections(items)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"AI情报简报-{args.date}"
    markdown_path = args.output_dir / f"{stem}.md"
    html_path = args.output_dir / f"{stem}.html"
    markdown_path.write_text(
        render_markdown(args.date, meta, sections, items, args.note),
        encoding="utf-8",
    )
    html_path.write_text(
        render_html(
            args.date,
            meta,
            sections,
            items,
            args.note,
            args.css.read_text(encoding="utf-8"),
        ),
        encoding="utf-8",
    )
    outputs = [markdown_path, html_path]
    if args.pdf:
        chrome = find_chrome(args.chrome)
        if not chrome:
            raise RuntimeError("Chrome/Chromium not found; omit --pdf or pass --chrome")
        pdf_path = args.output_dir / f"{stem}.pdf"
        print_pdf(html_path, pdf_path, chrome)
        outputs.append(pdf_path)
    print("\n".join(map(str, outputs)))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
