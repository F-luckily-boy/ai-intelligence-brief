# AI Intelligence Brief

A self-contained skill that collects, verifies, and renders a daily Chinese-language AI intelligence brief across official, vertical-media, Builder/X, community, and podcast feeds.

## What it does

Each run gathers the last 24 hours of AI signals (with longer look-back windows for builders, community, and long-form content), scores them by keyword relevance and source authority, deduplicates across sources and days, then renders an edited Chinese brief to Markdown, HTML, and optional PDF.

## Coverage

### Tier 0 — Official first-party
OpenAI News · Google AI Blog · Google DeepMind · Hugging Face Blog · GitHub Blog / Changelog

### Tier 1 — AI vertical media
AIbase · The Decoder · IT之家 · Claude / Anthropic Blog · Cursor Blog · SemiAnalysis · OpenClaw Releases · Simon Willison · 小红书技术 · 数字生命卡兹克

### Selected international AI media
TechCrunch AI · The Verge AI · Artificial Intelligence News · MarkTechPost · Claude Code Releases

### Builders / X
Follow Builders — a public feed of first-hand posts from AI-product builders and core developers.

### Community
Hacker News · WaytoAGI · V2EX · Readhub AI · 虎嗅 · 36氪 · GitHub Trending · Techmeme · Google News · TechRadar · MacRumors · Product Hunt · Slashdot · 掘金 · MakeUseOf

### Podcasts
Lenny's Podcast · Dwarkesh · No Priors · TWIML · Machine Learning Street Talk · AI Daily Brief · Hard Fork · Latent.Space

## Output sections

- **过去 24 小时 · AI 圈信号** — news grouped into 核心头条 / 产业与商业 / 模型与工具 / 研究与深度
- **Builders · 他们在说什么** — first-hand posts with original text and Chinese translation
- **社区精选** — practitioner discussions from HN, V2EX, 掘金, Slashdot, and more
- **播客精选** — long-form podcast highlights

## Directory layout

```
.
├── ai-intelligence-brief/   ← the skill (drop-in)
│   ├── SKILL.md             ← full workflow + editorial rules
│   ├── skill.yml
│   ├── agents/
│   ├── assets/
│   ├── references/          ← feed registry, source policy, editorial format
│   ├── scripts/             ← collect → rank → validate → render pipeline
│   └── tests/
├── README.md
├── .gitignore
└── LICENSE
```

## Requirements

- Python 3.10+ (collection and ranking use only the standard library)
- Network access for collection
- Chrome/Chromium only if you want PDF output (Markdown and HTML work without it)

## Pipeline

```
scripts/collect_sources.py   # gather + window-filter candidates from all feeds
scripts/rank_candidates.py   # keyword/authority scoring + safe dedup
  (editorial pass)           # human-in-the-loop review, grouping, Chinese titles
scripts/validate_brief.py    # publication contract checks
scripts/render_brief.py      # Markdown / HTML / optional PDF
```

See `ai-intelligence-brief/SKILL.md` for the full workflow, candidate contract, and editorial rules.
