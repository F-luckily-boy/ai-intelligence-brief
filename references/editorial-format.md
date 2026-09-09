# Editorial and Format Guide

## Order

Render only non-empty sections:

1. `AI 情报简报 · YYYY-MM-DD（周X）`
2. Exact lane windows and collection counts
3. `过去 24 小时 · AI 圈信号`
4. Event/theme groups via `event_title`; fall back to the four editorial
   sections when no event title is assigned
5. `Builders · 他们在说什么`
6. `社区精选`
7. `播客精选`, `博客精选`

## Entries

News entries use a linked factual Chinese title followed by one compact
paragraph. Put the consequence or new fact first. Secondary source links may
follow when they independently corroborate or deepen the report.

Default to one sentence for ordinary news. Add a second sentence only for
material uncertainty, consequences, or source qualification. Do not give every
item a mini-analysis; use the saved space for additional verified signals.

Use one item per independently useful claim. Assign the same `claim_id` only
to duplicate coverage of that claim. Related but distinct claims may share an
`event_id` and `event_title`, which groups them under one heading without
discarding detail.

Builder entries include name, handle, optional current affiliation, direct
post link, original text, and faithful Chinese translation. Group multiple
posts by the same author.

Long-form entries may use several short paragraphs with short internal
subheads. Extract reusable decisions, architecture, governance, failures, and
operational lessons; do not reduce a strong implementation article to one
generic paragraph. Preserve an English précis and Chinese version only when
both add value; do not enforce arbitrary word counts or pad a thin source.

Community items are grouped by source and must add discussion value beyond the
main news item.

The metadata must disclose a missing or failed Builder lane. Do not print a
Builder lookback window in a way that implies the lane was successfully
collected when no reliable feed or direct evidence was available.

## Visual Quality

- A4 portrait, white background, restrained navy and blue accents.
- No cards, visible scores, raw URLs, or internal collection notes.
- Keep headings with following content where possible.
- Verify day-of-week, counts, links, glyphs, clipping, and page breaks.
- Visually inspect every PDF page before delivery.
