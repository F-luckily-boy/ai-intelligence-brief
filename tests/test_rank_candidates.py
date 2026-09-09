from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "rank_candidates", ROOT / "scripts" / "rank_candidates.py"
)
ranker = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(ranker)
POLICY = json.loads((ROOT / "references" / "source-policy.json").read_text())
START = datetime(2026, 9, 4, 0, 0, tzinfo=timezone.utc)
CUTOFF = datetime(2026, 9, 5, 0, 0, tzinfo=timezone.utc)


def candidate(**overrides):
    value = {
        "title": "OpenAI launches an agent API",
        "url": "https://openai.com/story?utm_source=test",
        "source": "OpenAI News",
        "published_at": "2026-09-04T12:00:00+00:00",
        "summary": "A new agent API release.",
        "kind": "news",
    }
    value.update(overrides)
    return value


class RankCandidatesTest(unittest.TestCase):
    def prepare(self, value):
        return ranker.prepare(value, POLICY, START, CUTOFF, 3.0)

    def test_rejects_item_at_cutoff(self):
        result, reason = self.prepare(
            candidate(published_at="2026-09-05T00:00:00+00:00")
        )
        self.assertIsNone(result)
        self.assertEqual(reason, "at_or_after_cutoff")

    def test_rejects_naive_timestamp(self):
        result, reason = self.prepare(
            candidate(published_at="2026-09-04T12:00:00")
        )
        self.assertIsNone(result)
        self.assertEqual(reason, "missing_or_naive_timestamp")

    def test_accepts_start_boundary_and_strips_tracking(self):
        result, reason = self.prepare(
            candidate(published_at="2026-09-04T00:00:00+00:00")
        )
        self.assertIsNone(reason)
        self.assertEqual(result["url"], "https://openai.com/story")

    def test_source_aliases_are_exact(self):
        result, _ = self.prepare(candidate(source="OpenAI Newswire"))
        self.assertEqual(result["source_weight"], 24)

    def test_rejects_configured_source_domain_mismatch(self):
        result, reason = self.prepare(candidate(url="https://example.com/not-openai"))
        self.assertIsNone(result)
        self.assertEqual(reason, "source_url_mismatch")

    def test_claim_id_merges_sources_within_news_lane(self):
        first, _ = self.prepare(candidate(claim_id="claim-1", event_id="event-1"))
        second, _ = self.prepare(
            candidate(
                claim_id="claim-1",
                event_id="event-1",
                source="TechCrunch AI",
                url="https://techcrunch.com/event-1",
            )
        )
        merged = ranker.dedupe([first, second])
        self.assertEqual(len(merged), 1)
        self.assertEqual(set(merged[0]["sources"]), {"OpenAI News", "TechCrunch AI"})

    def test_official_summary_is_not_replaced_by_longer_secondary_summary(self):
        official, _ = self.prepare(
            candidate(
                claim_id="claim-1",
                summary="Official release details.",
                chinese_summary="官方发布摘要。",
            )
        )
        secondary, _ = self.prepare(
            candidate(
                claim_id="claim-1",
                source="TechCrunch AI",
                url="https://techcrunch.com/event-1",
                summary="A much longer secondary interpretation of the same release.",
                chinese_summary="这是一段明显更长的二手媒体解释，不应覆盖官方摘要。",
            )
        )
        merged = ranker.dedupe([official, secondary])
        self.assertEqual(merged[0]["summary"], "Official release details.")
        self.assertEqual(merged[0]["chinese_summary"], "官方发布摘要。")

    def test_missing_primary_summary_can_be_filled_from_duplicate(self):
        official, _ = self.prepare(
            candidate(claim_id="claim-1", summary="", chinese_summary="")
        )
        secondary, _ = self.prepare(
            candidate(
                claim_id="claim-1",
                source="TechCrunch AI",
                url="https://techcrunch.com/event-1",
                summary="Secondary context.",
                chinese_summary="二手补充。",
            )
        )
        merged = ranker.dedupe([official, secondary])
        self.assertEqual(merged[0]["summary"], "Secondary context.")
        self.assertEqual(merged[0]["chinese_summary"], "二手补充。")

    def test_event_id_groups_but_does_not_merge_distinct_claims(self):
        first, _ = self.prepare(candidate(claim_id="claim-1", event_id="event-1"))
        second, _ = self.prepare(
            candidate(
                title="OpenAI publishes a separate benchmark result",
                claim_id="claim-2",
                event_id="event-1",
                url="https://openai.com/benchmark",
            )
        )
        self.assertEqual(len(ranker.dedupe([first, second])), 2)

    def test_builder_and_news_stay_in_separate_lanes(self):
        news, _ = self.prepare(candidate(event_id="event-1"))
        builder, _ = self.prepare(
            candidate(
                event_id="event-1",
                kind="builder",
                source="Builders/X",
                url="https://x.com/example/status/1",
                original_text="OpenAI agent launch.",
                translated_text="OpenAI 智能体发布。",
            )
        )
        self.assertEqual(len(ranker.dedupe([news, builder])), 2)

    def test_manual_builder_evidence_bypasses_keyword_threshold(self):
        result, reason = self.prepare(
            candidate(
                title="A practical observation",
                summary="No configured keyword appears here.",
                kind="builder",
                source="X oEmbed",
                url="https://x.com/example/status/1",
                manual_evidence=True,
            )
        )
        self.assertIsNone(reason)
        self.assertIsNotNone(result)

    def test_short_latin_keyword_uses_word_boundaries(self):
        score, matched = ranker.keyword_score(
            {"title": "Capital spending update"}, [{"term": "api", "weight": 3}]
        )
        self.assertEqual(score, 0)
        self.assertEqual(matched, [])

    def test_coverage_counts_do_not_impose_quotas(self):
        coverage = ranker.coverage_counts(
            [
                {"kind": "news", "section": "models", "source_group": "official"},
                {"kind": "news", "section": "models", "source_group": "vertical"},
                {"kind": "builder", "source_group": "builders"},
            ]
        )
        self.assertEqual(coverage["kind"], {"news": 2, "builder": 1})
        self.assertEqual(coverage["section"], {"models": 2, "not_applicable": 1})
        self.assertEqual(
            coverage["source_group"],
            {"official": 1, "vertical": 1, "builders": 1},
        )


if __name__ == "__main__":
    unittest.main()
