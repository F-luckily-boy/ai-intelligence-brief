---
name: ai-intelligence-brief
description: Collect, verify, edit, and render a multi-lane Chinese AI daily brief from official, vertical-media, Builder, community, and long-form feeds. Use for AI 日报、AI 情报简报、过去 24 小时 AI 动态、Builder/X 动态，或需要 Markdown、HTML、PDF 版本的可核验 AI 新闻摘要。
---

# AI Intelligence Brief

Produce an edited brief, not a visible ranking. Source authority and keyword
relevance create a review queue; final inclusion still requires opening the
source and verifying the claim.

## Workflow

1. Define an exact cutoff in `Asia/Shanghai`. For a morning brief, default to
   08:00. Use news 24h, Builders 36h, community 48h, and podcast/blog 72h;
   disclose every window instead of presenting all lanes as 24 hours.
2. Read [source-strategy.md](references/source-strategy.md), then run the
   collection layer:

   ```bash
   python3 scripts/collect_sources.py \
     --output candidates.json \
     --as-of 2026-09-09T08:00:00+08:00
   ```

   The bundled registry includes the official, vertical, selected-media, broad
   signal, community, and public WeChat relay sources documented in
   `source-feeds.json`. It also includes Zara Zhang's public Follow Builders
   central JSON feed, generated upstream with the official X API without
   requiring a local X token. Use `--builder-feed URL` only to add another
   Builder RSS/JSON source.

   When a user supplies direct X post links in a reference PDF or file,
   extract the links and run
   `scripts/hydrate_builder_evidence.py links.json --output evidence.json`;
   then pass `--builder-evidence evidence.json`. The collector derives
   timestamps from X status IDs, so this path does not require an X API token.
   Pass `--podcast-feed URL` to add podcast sources beyond the bundled feed.
3. Inspect `meta.collection.lane_status`, `kind_status`, and the ranker's
   `meta.review_coverage`. A sample-complete brief needs
   successful `radar`, `builders`, and `community` collection lanes. Report a
   missing Builder feed as missing coverage; do not manufacture posts from the
   roster or search snippets. When the user supplies direct post links in a
   reference document, treat them as manually verified evidence rather than a
   successful feed collection, verify the post timestamps from their status
   IDs, and record the count as `meta.collection.manual_evidence_count`.
4. Prefer original sources. Keep an independent secondary source only when it
   adds verification or material context.
5. Save candidates as JSON or JSONL. Every candidate must have a verifiable
   publication timestamp. Do not invent a time for date-only pages.
6. Rank and safely deduplicate:

   ```bash
   python3 scripts/rank_candidates.py candidates.jsonl \
     --output ranked.json \
     --as-of 2026-09-09T08:00:00+08:00 \
     --hours 24 \
     --builder-hours 36 \
     --community-hours 48 \
     --longform-hours 72 \
     --limit 100 \
     --seen output/2026-09-08/ranked.json
   ```

   Always pass `--seen <previous-ranked.json>` so cross-day deduplication
   actually runs. **Keep the previous day's `ranked.json`** (with the
   editor-assigned `claim_id` values) for this purpose; do not delete it after
   rendering. When no prior `ranked.json` exists, skip `--seen` and rely on
   the editorial pass to drop repeats against the previous day's published
   brief, and note any repeated-event judgments explicitly.

7. Open the shortlisted links. Remove unsupported, promotional, stale, thin,
   or off-topic items. Assign the same `claim_id` only to duplicate coverage
   of one factual claim. Related claims may share `event_id` and
   `event_title`, which groups them without collapsing useful detail. Retain
   the strongest primary URL and independent sources. For a major event,
   separately review the official claim, dispute or limitation, named
   responses, measurable cost or capability implications, and useful Builder
   reactions. Keep only independently informative claims.
8. Write factual Chinese titles and compact summaries. Preserve uncertainty,
   figures, model names, and attribution. Builder posts require the original
   text, a faithful Chinese translation, and a direct post URL when available.
   For enterprise-Agent or engineering-heavy editions, actively review the
   previous 72 hours for one substantial implementation or governance article;
   include it only when it adds reusable operational detail.
   Use one compact sentence for an ordinary signal. Use a second sentence only
   for material uncertainty, consequence, or verification context. Reserve
   multi-paragraph treatment for the lead event and selected long-form item.
   Select for information value; on a dense day, 18-30 news claims plus useful
   Builder, community, and long-form signals is a reasonable editorial range,
   not a quota.
9. Validate full-lane execution and render:

   ```bash
   python3 scripts/validate_brief.py ranked.json \
     --require-collection \
     --require-lane radar \
     --require-lane community \
     --require-selected-when-captured \
     --strict-builder-links
   python3 scripts/render_brief.py ranked.json \
     --output-dir output/2026-09-09 \
     --date 2026-09-09 \
     --pdf
   ```

   Add `--require-lane builders` only when a Builder feed was configured or
   manually verified direct Builder evidence was selected.
10. Inspect all links and visually inspect every PDF page.

## Runtime

- Python 3.10 or newer; collection and ranking use only the standard library.
- Network access is required for collection.
- Chrome or Chromium is required only for `--pdf`; Markdown and HTML rendering
  work without it. Pass a non-standard browser location with `--chrome`.

## Candidate Contract

```json
{
  "title": "Original or working title",
  "chinese_title": "准确的中文标题",
  "url": "https://example.com/story",
  "source": "OpenAI News",
  "published_at": "2026-09-08T18:40:00+08:00",
  "summary": "Source-grounded notes",
  "chinese_summary": "可发布的中文摘要",
  "kind": "news",
  "section": "core",
  "claim_id": "openai-astra-access-rollout-enterprise",
  "event_id": "openai-astra-rollout",
  "event_title": "OpenAI Astra 发布与生态",
  "channels": ["radar"],
  "author": "",
  "handle": "",
  "original_text": "",
  "translated_text": "",
  "metrics": {"points": 0, "comments": 0},
  "tags": []
}
```

Required: `title`, `url`, `source`, `published_at`.

- `kind`: `news`, `builder`, `blog`, `podcast`, or `community`.
- `section` for news: `core`, `industry`, `models`, or `research`.
- `channels`: any of `radar`, `builders`, `community`.
- `claim_id`: stable identifier for duplicate reports of the same factual
  claim. This is the semantic deduplication key.
- `event_id`: stable identifier linking related claims across one broader
  event. It does not trigger merging.
- `event_title`: human-readable heading used to group related news claims.
- `sources` and `source_urls`: populated by the ranker when reports merge.
- A Builder item remains in the Builder lane even when it shares an
  `event_id` with a news item. No escape flag is needed.

## Editorial Rules

- Treat source counts as observations, never quotas.
- Keep one claim once in the news lane. Preserve distinct developments inside
  the same event. Secondary links must independently corroborate or deepen it.
- Lead with the consequence or new fact, not announcement boilerplate.
- Use fewer items when signal quality is weak. Do not fill empty sections.
- Do not require a Builder, podcast, blog, or community item when no reliable
  in-window candidate exists.
- Do not show scores, tiers, collection failures, or internal review notes in
  the published brief.
- Do not use profile or aggregator links as evidence for a Builder post.
- Never fabricate an X status URL, timestamp, quote, metric, or source.
- A price cut / pricing-change signal is usually the tail of a larger event.
  Before publishing it as a standalone item, check whether the same vendor
  announced a new model release, launch, or version in the window (e.g. a
  "降价/调价" report alongside a "V4.1 Flash 发布" announcement). Surface the
  release/launch as the main claim and fold the pricing change into it, so the
  primary fact (a new model shipping) is never reduced to a pricing footnote.
- A prior brief is optional context for cross-day deduplication, not an input
  requirement. When none is available, label repeated-event judgments as an
  editorial note only when the evidence supports them.
- Coverage diagnostics are review prompts, not quotas. Before publishing,
  inspect whether official releases, model/product updates, developer tools,
  research, financing, named responses, and practitioner reactions were
  considered; do not add weak items merely to fill a category.

## Resources

- [source-strategy.md](references/source-strategy.md): source tiers,
  selection, collection, and deduplication policy.
- [source-policy.json](references/source-policy.json): machine-readable source
  weights, aliases, keywords, and section cues.
- [source-feeds.json](references/source-feeds.json): executable feed registry
  for the collection layer.
- [builder-roster.json](references/builder-roster.json): intended account
  coverage reference only; never evidence that an account posted.
- [editorial-format.md](references/editorial-format.md): writing and layout.
- `scripts/collect_sources.py`: RSS/Atom, JSON, AIbase, Hacker News, optional
  article-index, sitemap, GitHub Trending, Follow Builders, and podcast
  collection with lane diagnostics.
- `scripts/rank_candidates.py`: lane-window filtering, ranking, and safe
  deduplication.
- `scripts/validate_brief.py`: publication contract checks.
- `scripts/render_brief.py`: Markdown, HTML, and optional PDF output.
