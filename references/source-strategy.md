# Source and Selection Strategy

## Selection Model

Use source authority plus keyword relevance to create an editorial review
queue. Recency, corroboration, and engagement are small tie-breakers. The
published brief is not a score leaderboard.

Observed source counts from a prior run, such as five official items or 53
vertical-media items, are diagnostics rather than quotas.

## Source Tiers

### Tier 0: official first-party

- GitHub Changelog
- Hugging Face Blog
- Google AI Blog / Google DeepMind
- OpenAI News

Use these for releases, system cards, platform changes, safety disclosures,
research, and engineering announcements.

### Tier 1: AI vertical

- AIbase
- The Decoder
- Anthropic / Claude official and engineering blogs
- IT之家
- Cursor Blog
- SemiAnalysis
- Emad Mostaque, OpenClaw, 小红书技术、数字生命卡兹克
- Other explicitly configured AI-specialist feeds

Verify consequential claims against a first-party source whenever one exists.

### Tier 2: parallel signal groups

- Builders/X: connected Follow Builders feeds and relevant first-hand posts.
- Community: WaytoAGI, Hacker News, V2EX, and similar practitioner forums.
- Selected AI media: TechCrunch AI, The Decoder AI News, Artificial
  Intelligence News, MarkTechPost Research, The Verge AI, Claude Code
  Releases.
- Broad signals: Readhub AI, GitHub Trending, Techmeme, Google News, 36氪,
  Yahoo Finance, Bloomberg, TechRadar, 虎嗅, and comparable aggregators.

Tier 2 groups are peers. Source-specific weights express quality differences.

## Collection

- Run `scripts/collect_sources.py` before ranking. Query each lane independently
  so one prolific feed cannot crowd out the others before ranking.
- Prefer the original URL. Aggregators are discovery surfaces, not automatic
  primary sources.
- After shortlisting a secondary report, search for the announcing company's
  release, documentation, changelog, research post, or named executive
  response. Replace the primary URL with the first-party page when it supports
  the same claim; retain the media link only when it corroborates or adds
  material context.
- Use the bundled Follow Builders JSON feed or an explicitly supplied Builder
  RSS/JSON feed for Builder posts. The bundled roster is only a discovery seed;
  it cannot prove that someone posted inside the reporting window.
- Direct X status links supplied in a user reference may be used as manual
  evidence after verifying the Snowflake timestamp and preserving the original
  post text. Normalize them to JSON/JSONL and use `--builder-evidence`. They do
  not turn an unconfigured feed into a successful feed.
- Treat an unconfigured Builder lane as missing coverage. Do not synthesize
  posts from profile pages, search snippets, or the roster.
- Continue when a source fails. Keep failures in collection logs, outside the
  published brief.
- Record exact timestamps and timezones. Date-only pages stay out of a strict
  24-hour run until their time can be verified.
- Use lane-specific lookbacks when the requested format includes them:
  news 24 hours, Builders 36 hours, community 48 hours, and podcast/blog
  72 hours. Disclose these windows in the published metadata.
- On enterprise-Agent and engineering-heavy days, search the long-form window
  for implementation details about architecture, governance, evaluation,
  security, or production operations. A substantive article is a first-class
  lane, not decorative filler.

## Relevance

Match keywords across title, summary, body notes, and tags, with title matches
weighted more strongly. Prioritize models, agents, developer tools,
infrastructure, research, safety, policy, funding, and material product or
business events.

Reject or demote:

- decorative mentions of AI;
- stock-price chatter without an underlying AI event;
- SEO roundups, coupons, repost farms, and thin rewrites;
- job posts and unrelated hardware or crypto;
- stale explainers in a daily brief.

These quality judgments require source inspection. Keyword scoring alone is
not evidence.

## Deduplication

1. Remove URL fragments and tracking parameters.
2. Merge exact canonical URLs.
3. Merge records sharing an editor-assigned `claim_id`.
4. Auto-merge highly similar titles only within the same content lane.
5. Select the highest-authority representative and retain independent source
   names and URLs.
6. Use `event_id` and `event_title` to group distinct claims about one broader
   event without collapsing them into one item.
7. Keep Builder commentary in the Builder lane even when it discusses a news
   event; a shared `event_id` records the relationship.
8. For cross-day deduplication, compare against prior ranked output. A new
   development should use a new `claim_id`; retain the broader `event_id` when
   it belongs to the same continuing event. Do not use a bypass flag.

## Editorial Pass

Review roughly 80-100 ranked candidates on a dense day, then open every
potentially selected source. A typical edited result may contain 18-30 news
claims plus useful Builder, community, and long-form signals, but these are
editorial ranges rather than quotas. A weak day should be shorter.

Prefer breadth through concise, independently useful claims rather than long
explanations repeated for every item. Ordinary signals usually need one
sentence; expand the lead event, consequential uncertainty, and the selected
long-form item.
