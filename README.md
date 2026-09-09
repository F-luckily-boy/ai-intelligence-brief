# AI 情报简报

这是一个可导入腾讯 WorkBuddy 的 AI 情报简报 Skill。

## 安装

### 方式一：WorkBuddy 本地导入

在 WorkBuddy 的 Skills / 技能管理中选择“添加本地 Skill”，选择这个目录：

`ai-intelligence-brief/`

目录中应同时看到 `SKILL.md`、`skill.yml`、`references/`、`scripts/` 和 `assets/`。

### 方式二：手动复制

将整个 `ai-intelligence-brief` 文件夹复制到：

`~/.workbuddy/skills/ai-intelligence-brief/`

然后重启 WorkBuddy，或在技能管理中刷新。

## 使用

直接输入：

`用 AI 情报简报 Skill 获取今天的 AI 简报，覆盖官方源、AI 媒体和 Builders，并输出 PDF。`

也可以手动调用：

`@skill:ai-intelligence-brief 获取过去 24 小时 AI 资讯`

## 输出

- 默认按 Asia/Shanghai 的过去 24 小时采集
- 检查核心 Builder 名单及已连接的 Follow Builders 信源
- 自动进行关键词匹配、信源权重排序和跨来源/跨日期去重
- 所有 Builder 内容统一展示在“Builder 精选动态”；双源证据仅用于内部加权和去重
- 播客使用中英双语详细精读，并在输出前执行最低内容深度校验
- 支持 Markdown、HTML；环境有 Chrome/Chromium 时支持 PDF

## 运行环境

- WorkBuddy 的浏览器/联网能力，用于抓取实时资讯
- Python 3.10 或更高版本，用于运行排序、校验和渲染脚本
- Chrome 或 Chromium 仅在需要打印 PDF 时使用

脚本必须从 Skill 根目录（包含 `SKILL.md` 的目录）运行。
