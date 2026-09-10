from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "render_brief", ROOT / "scripts" / "render_brief.py"
)
assert SPEC and SPEC.loader
render_brief = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(render_brief)


class RenderBriefTest(unittest.TestCase):
    def test_event_title_groups_distinct_claims(self) -> None:
        items = [
            {
                "title": "Claim one",
                "event_title": "Astra 发布",
                "kind": "news",
            },
            {
                "title": "Claim two",
                "event_title": "Astra 发布",
                "kind": "news",
            },
            {
                "title": "Research item",
                "section": "research",
                "kind": "news",
            },
        ]
        groups = render_brief.news_groups(items)
        self.assertEqual([name for name, _ in groups], ["Astra 发布", "研究与深度"])
        self.assertEqual(len(groups[0][1]), 2)

    def test_metadata_discloses_lane_windows_and_builder_counts(self) -> None:
        meta = {
            "window_start": "2026-09-04T00:00:00+00:00",
            "window_end": "2026-09-05T00:00:00+00:00",
            "windows_hours": {
                "news": 24,
                "builders": 36,
                "community": 48,
                "longform": 72,
            },
            "collection": {
                "raw_count": 270,
                "accepted_count": 259,
                "manual_evidence_count": 2,
            },
            "deduped_count": 100,
        }
        items = [
            {"kind": "news", "title": "News"},
            {"kind": "builder", "title": "Post one", "handle": "@alice"},
            {"kind": "builder", "title": "Post two", "handle": "@alice"},
            {"kind": "community", "title": "Community"},
            {"kind": "podcast", "title": "Podcast"},
        ]
        text = render_brief.metadata_text(meta, items, "")
        self.assertIn("Builders 36h", text)
        self.assertIn("自动采集原始信号 270", text)
        self.assertIn("人工核验直链 2", text)
        self.assertIn("自动候选去重后 100", text)
        self.assertIn("Builders 1 人/2 条", text)

    def test_metadata_discloses_missing_builder_and_unused_podcast(self) -> None:
        meta = {
            "windows_hours": {
                "news": 24,
                "builders": 36,
                "community": 48,
                "longform": 72,
            },
            "collection": {
                "lane_status": {
                    "builders": {
                        "configured": 0,
                        "ok": 0,
                        "empty": 0,
                        "failed": 0,
                        "raw": 0,
                    }
                },
                "kind_status": {
                    "podcast": {
                        "configured": 1,
                        "ok": 1,
                        "empty": 0,
                        "failed": 0,
                        "raw": 10,
                    }
                },
                "kind_counts": {"podcast": 2},
            },
        }
        text = render_brief.metadata_text(
            meta, [{"kind": "news", "title": "News"}], ""
        )
        self.assertIn("Builders: 未配置可靠 Feed", text)
        self.assertIn("播客: 已采集，未入选", text)

    def test_longform_heading_stays_with_first_paragraph(self) -> None:
        html = render_brief.rich_text_html("**安全与可用性**\n正文内容。")
        self.assertEqual(
            html,
            '<div class="longform-lead"><h4>安全与可用性</h4>'
            "<p>正文内容。</p></div>",
        )


if __name__ == "__main__":
    unittest.main()
