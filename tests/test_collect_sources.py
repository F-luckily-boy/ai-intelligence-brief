from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "collect_sources", ROOT / "scripts" / "collect_sources.py"
)
assert SPEC and SPEC.loader
collect_sources = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collect_sources)


class CollectSourcesTest(unittest.TestCase):
    def test_parses_follow_builders_nested_feed(self):
        payload = {
            "generatedAt": "2026-09-09T02:00:00.000Z",
            "x": [
                        {
                            "handle": "builder",
                            "name": "Builder Name",
                            "tweets": [
                                {
                                    "text": "Shipping an agent tool",
                                    "createdAt": "2026-09-09T01:00:00.000Z",
                                    "url": "https://x.com/builder/status/1",
                                }
                            ],
                        }
            ]
        }
        items = collect_sources.parse_follow_builders_feed(
            json.dumps(payload).encode(),
            {"name": "Follow Builders", "max_items": 10},
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["handle"], "@builder")
        self.assertEqual(items[0]["original_text"], "Shipping an agent tool")
        self.assertEqual(
            items[0]["feed_generated_at"],
            "2026-09-09T02:00:00+00:00",
        )

    def test_parses_legacy_follow_builders_feed(self):
        payload = {
            "generated_at": "2026-09-09T02:00:00Z",
            "days": [
                {
                    "accounts": [
                        {
                            "username": "legacy",
                            "tweets": [
                                {
                                    "text": "Legacy feed update",
                                    "created_at": "2026-09-09T01:00:00Z",
                                    "url": "https://x.com/legacy/status/2",
                                }
                            ],
                        }
                    ]
                }
            ],
        }
        items = collect_sources.parse_follow_builders_feed(
            json.dumps(payload).encode(),
            {"name": "Follow Builders", "max_items": 10},
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["handle"], "@legacy")

    def test_rejects_unknown_follow_builders_schema(self):
        payload = {
            "generatedAt": "2026-09-09T02:00:00Z",
            "builders": [],
        }
        with self.assertRaisesRegex(ValueError, "must contain 'x' or legacy 'days'"):
            collect_sources.parse_follow_builders_feed(
                json.dumps(payload).encode(),
                {"name": "Follow Builders", "max_items": 10},
            )

    def test_rejects_follow_builders_feed_without_generation_time(self):
        payload = {"x": []}
        with self.assertRaisesRegex(ValueError, "valid generatedAt timestamp"):
            collect_sources.parse_follow_builders_feed(
                json.dumps(payload).encode(),
                {"name": "Follow Builders", "max_items": 10},
            )

    def test_rejects_declared_follow_builders_data_when_parsing_is_empty(self):
        payload = {
            "generatedAt": "2026-09-09T02:00:00Z",
            "stats": {"totalTweets": 3},
            "x": [{"username": "builder", "tweets": []}],
        }
        with self.assertRaisesRegex(ValueError, "declares 3 tweets but parsed 0"):
            collect_sources.parse_follow_builders_feed(
                json.dumps(payload).encode(),
                {"name": "Follow Builders", "max_items": 10},
            )

    def test_rejects_stale_follow_builders_feed(self):
        cutoff = datetime(2026, 9, 9, 0, 0, tzinfo=timezone.utc)
        status = {
            "generated_at": (
                cutoff
                - timedelta(hours=collect_sources.BUILDER_FEED_MAX_AGE_HOURS + 1)
            ).isoformat()
        }
        with self.assertRaisesRegex(ValueError, "feed is stale"):
            collect_sources.validate_follow_builders_freshness(
                {"format": "follow_builders_json"},
                status,
                cutoff,
            )

    def test_builder_auto_format_uses_follow_builders_parser(self):
        payload = {
            "generatedAt": "2026-09-09T02:00:00Z",
            "x": [],
            "stats": {"totalTweets": 0},
        }
        spec = {
            "name": "Follow Builders",
            "url": "https://example.com/builders.json",
            "format": "auto",
            "kind": "builder",
            "channel": "builders",
        }
        with patch.object(
            collect_sources,
            "fetch",
            return_value=json.dumps(payload).encode(),
        ):
            items, status = collect_sources.collect_feed(spec, 1, 1)
        self.assertEqual(items, [])
        self.assertEqual(status["generated_at"], "2026-09-09T02:00:00+00:00")

    def test_parses_rss_and_keeps_source_lane(self) -> None:
        data = b"""<?xml version="1.0"?>
        <rss><channel><item>
          <title>OpenAI ships a coding agent</title>
          <link>https://example.com/release</link>
          <pubDate>Fri, 04 Sep 2026 12:00:00 GMT</pubDate>
          <description><![CDATA[<p>Release details.</p>]]></description>
        </item></channel></rss>"""
        items = collect_sources.parse_xml_feed(
            data,
            {
                "name": "Example",
                "kind": "news",
                "channel": "radar",
                "max_items": 10,
            },
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["summary"], "Release details.")
        self.assertEqual(items[0]["channel"], "radar")

    def test_parses_atom_builder_post(self) -> None:
        data = b"""<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom"><entry>
          <title>New model notes</title>
          <link rel="alternate" href="https://x.com/alice/status/123"/>
          <published>2026-09-04T12:00:00Z</published>
          <summary>We shipped a new model.</summary>
          <author><name>Alice</name></author>
        </entry></feed>"""
        items = collect_sources.parse_xml_feed(
            data,
            {
                "name": "Follow Builders RSS",
                "kind": "builder",
                "channel": "builders",
                "max_items": 10,
            },
        )
        self.assertEqual(items[0]["handle"], "@alice")
        self.assertEqual(items[0]["original_text"], "We shipped a new model.")

    def test_derives_timestamp_for_manual_builder_evidence(self) -> None:
        published = datetime(2026, 9, 8, 12, 34, 56, tzinfo=timezone.utc)
        status_id = (
            int(published.timestamp() * 1000)
            - collect_sources.X_SNOWFLAKE_EPOCH_MS
        ) << 22
        row = {
            "url": f"https://x.com/alice/status/{status_id}",
            "author": "Alice",
            "text": "A direct Builder update.",
            "translated_text": "一条 Builder 动态。",
        }
        with TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            path.write_text(json.dumps(row), encoding="utf-8")
            items = collect_sources.load_builder_evidence(path)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["published_at"], published.isoformat())
        self.assertEqual(items[0]["handle"], "@alice")
        self.assertTrue(items[0]["manual_evidence"])

    def test_rejects_profile_link_as_manual_builder_evidence(self) -> None:
        row = {
            "url": "https://x.com/alice",
            "published_at": "2026-09-08T12:00:00+00:00",
            "text": "Not a direct post.",
        }
        with TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            path.write_text(json.dumps([row]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not a direct X status URL"):
                collect_sources.load_builder_evidence(path)

    def test_article_metadata_tolerates_unnamed_meta_and_reads_addtime(self) -> None:
        data = b"""<html><head>
        <meta charset="utf-8"/>
        <meta property="og:title" content="AI release"/>
        <meta property="og:description" content="Release details"/>
        </head><body>
        <script>{"addtime":"2026-09-08T09:26:28+08:00"}</script>
        </body></html>"""
        item = collect_sources.parse_article_metadata(
            data, "https://example.com/news/1", "Example"
        )
        assert item
        self.assertEqual(item["title"], "AI release")
        self.assertEqual(item["published_at"], "2026-09-08T09:26:28+08:00")

    def test_aibase_uses_listing_ids_and_ignores_old_recommendations(self) -> None:
        index = """
        <a href="/news/30908">latest</a>
        <a href="/news/30907">second</a>
        <a href="https://news.aibase.com/news/30780">old recommendation</a>
        """
        self.assertEqual(
            collect_sources.extract_aibase_article_ids(index, 5),
            ["30908", "30907", "30906", "30905", "30904"],
        )

    def test_aibase_fallback_ids_are_sorted_before_limiting(self) -> None:
        index = r"""
        {\"Id\":30851}
        <a href="https://news.aibase.com/news/30908">new</a>
        <a href="https://news.aibase.com/news/30780">old</a>
        """
        self.assertEqual(
            collect_sources.extract_aibase_article_ids(index, 2),
            ["30908", "30851"],
        )


if __name__ == "__main__":
    unittest.main()
