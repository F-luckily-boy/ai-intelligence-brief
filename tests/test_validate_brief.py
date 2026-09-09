from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate_brief.py"


def payload(include_builder: bool) -> dict:
    items = [
        {
            "title": "News",
            "url": "https://example.com/news",
            "source": "Example",
            "published_at": "2026-09-07T12:00:00+00:00",
            "summary": "News summary",
            "kind": "news",
            "section": "core",
            "claim_id": "news",
        },
        {
            "title": "Community",
            "url": "https://example.com/community",
            "source": "Example",
            "published_at": "2026-09-07T12:00:00+00:00",
            "summary": "Community summary",
            "kind": "community",
            "claim_id": "community",
        },
    ]
    if include_builder:
        items.append(
            {
                "title": "Builder",
                "url": "https://x.com/example/status/2096815819997204639",
                "source": "Builders/X",
                "published_at": "2026-09-07T04:20:23+00:00",
                "kind": "builder",
                "claim_id": "builder",
                "original_text": "Original",
                "translated_text": "Translation",
            }
        )
    return {
        "meta": {
            "window_start": "2026-09-07T00:00:00+00:00",
            "window_end": "2026-09-08T00:00:00+00:00",
            "windows_hours": {
                "news": 24,
                "builders": 36,
                "community": 48,
                "longform": 72,
            },
            "selected_count": len(items),
            "collection": {
                "manual_evidence_count": 1,
                "lane_status": {
                    "radar": {"configured": 1, "ok": 1},
                    "community": {"configured": 1, "ok": 1},
                    "builders": {"configured": 0, "ok": 0},
                },
            },
        },
        "items": items,
    }


class ValidateBriefTest(unittest.TestCase):
    def run_validator(self, data: dict) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "brief.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            return subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR),
                    str(path),
                    "--require-collection",
                    "--require-lane",
                    "radar",
                    "--require-lane",
                    "builders",
                    "--require-lane",
                    "community",
                    "--strict-builder-links",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

    def test_manual_direct_builder_evidence_satisfies_builder_lane(self) -> None:
        result = self.run_validator(payload(include_builder=True))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_manual_count_without_builder_item_does_not_satisfy_lane(self) -> None:
        result = self.run_validator(payload(include_builder=False))
        self.assertEqual(result.returncode, 1)
        self.assertIn("builders collection lane was not configured", result.stdout)


if __name__ == "__main__":
    unittest.main()
