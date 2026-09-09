# AI 情报简报 Skill

自动采集过去 24 小时的 AI 圈信号，按「官方一手源 → AI 垂直媒体 → Builders/X → 社区 → 播客/长文」分层，
经关键词相关性与信源权重筛选、跨源合并与跨天去重后，生成**可核验的中文 AI 日报**（Markdown / HTML / PDF）。

产出的是**编辑后的简报**，不是排行榜：内部分数只用于排定复核队列，最终入选仍需打开原始链接核对。

## 特性

- **内置 20+ 信源**：OpenAI News、Google DeepMind、Hugging Face、GitHub（Changelog / AI Blog）、
  AIbase、The Decoder、TechCrunch AI、The Verge AI、Artificial Intelligence News、MarkTechPost、
  Simon Willison、Techmeme、MacRumors、Product Hunt、Hacker News 等。
- **Builder 通道开箱可用**：内置公开的 Follow Builders 中央 feed（上游由官方 X API 生成），
  **无需本地 X token** 即可采集 Builder 推文（中英双语呈现）。
- **事件导向分组**：用 `event_id` / `event_title` 把同一事件的多源报道聚合，
  而不是按「模型 / 产业」这类类别堆砌。
- **多窗口并如实披露**：新闻 24h、Builders 36h、社区 48h、播客与长文 72h，
  窗口会写进简报元数据，不会把各通道都伪装成 24 小时。
- **发布前校验**：`validate_brief.py` 检查采集通道、链接质量与入选完整性；
  通道缺失时**明确报告缺失，绝不伪造内容**。
- **不泄露内部信息**：分数、权重、采集失败等内部状态不会出现在成品里。

## 安装

### 通用 Agent（Codex / Claude Code 等）

把 `ai-intelligence-brief/` 整个目录放到以下任一位置：

```text
个人使用：  ~/.agents/skills/ai-intelligence-brief
项目共享：  <项目根>/.agents/skills/ai-intelligence-brief
```

Agent 通常会自动发现；若未生效，重启即可。

### WorkBuddy

```bash
cp -R ai-intelligence-brief ~/.workbuddy/skills/
```

然后在「技能管理」刷新或重启 WorkBuddy。

## 使用方法

### 方式一：交给 Agent（推荐）

```text
用 ai-intelligence-brief 生成今天的 AI 情报简报，覆盖官方源、AI 媒体和 Builders，输出 Markdown、HTML 和 PDF。
```

也可以直接说「生成 AI 日报」「整理过去 24 小时 AI 动态」，由 Agent 按描述自动匹配。

### 方式二：手动跑脚本

```bash
cd ai-intelligence-brief

# 1. 采集（--as-of 用带时区的 ISO 时间）
python3 scripts/collect_sources.py \
  --output candidates.json \
  --as-of 2026-09-09T08:00:00+08:00

# 2. 排序去重（多窗口）
python3 scripts/rank_candidates.py candidates.json \
  --output ranked.json \
  --as-of 2026-09-09T08:00:00+08:00 \
  --hours 24 --builder-hours 36 --community-hours 48 --longform-hours 72 \
  --limit 100

# 3. 编辑（人工/AI）：补中文标题与摘要、给 event_title、剔除低质项

# 4. 校验 + 渲染
python3 scripts/validate_brief.py ranked.json \
  --require-collection --require-lane radar --require-lane community
python3 scripts/render_brief.py ranked.json \
  --output-dir output/2026-09-09 --date 2026-09-09 --pdf
```

脚本需从 **Skill 根目录**（含 `SKILL.md` 的目录）运行。

## 可选配置

| 环境变量 / 参数 | 用途 |
|---|---|
| `FOLLOW_BUILDERS_FEED_URL` / `--builder-feed URL` | 额外接入你自己的 Follow Builders RSS/JSON 源 |
| `AI_PODCAST_FEED_URL` / `--podcast-feed URL` | 补充播客源（内置仅 Latent.Space） |
| `--note "…"` | 写进元数据末尾的编辑说明（今日新事件 / 增量 / 已剔除） |
| `--chrome /path` | 指定非标准位置的 Chrome/Chromium |

## 运行环境

- Python 3.10 或更高（采集与排序仅用标准库）
- 采集阶段需要联网
- 仅 `--pdf` 需要 Chrome 或 Chromium

## 目录结构

```text
ai-intelligence-brief/
├── SKILL.md                          # Skill 入口与完整工作流
├── README.md                         # 本文件
├── skill.yml                         # WorkBuddy 平台元数据（其他平台可忽略）
├── agents/openai.yaml                # UI 元数据
├── assets/brief.css                  # A4 打印样式
├── references/
│   ├── source-strategy.md            # 信源分层、选择、采集与去重策略
│   ├── source-policy.json            # 信源权重、别名、关键词、分区提示词
│   ├── source-feeds.json             # 采集层用的 feed 注册表
│   ├── builder-roster.json           # Builder 账号覆盖参考（非发推证据）
│   └── editorial-format.md           # 写作与排版规范
├── scripts/
│   ├── collect_sources.py            # 采集：RSS/Atom/JSON/AIbase/HN/Follow Builders/播客
│   ├── hydrate_builder_evidence.py   # 从公开 X 直链解析证据（oEmbed，无需 token）
│   ├── rank_candidates.py            # 多窗口过滤、排序、安全去重
│   ├── validate_brief.py             # 发布契约校验
│   └── render_brief.py               # Markdown / HTML / PDF 渲染
└── tests/                            # 自动化测试
```

## 已知限制

- **播客区经常为空**：内置播客源只有 Latent.Space，更新较慢。
  这是「如实报告窗口内无新内容」，不是故障；可用 `AI_PODCAST_FEED_URL` 补源。
- **Builder 依赖公开 feed**：未配置且内置源不可达时，该通道会显示缺失而非编造内容。
- **不内置任何密钥**：所有可选源都通过环境变量接入。

## License

MIT — 见 [LICENSE](LICENSE)。
