from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pathfinder.event_focus import (  # noqa: E402
    event_catalog,
    event_focus_summary,
    event_neighbourhood,
    event_window_paths,
    recommended_event,
)
from pathfinder.sample import make_sample_events  # noqa: E402
from pathfinder.transform import build_event_spine, load_route_rules  # noqa: E402


class EventFocusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = make_sample_events(session_count=120)
        rules = load_route_rules(PROJECT_ROOT / "config" / "route_rules.csv")
        cls.spine = build_event_spine(raw, rules)

    def test_neighbourhood_is_centred_on_selected_event(self):
        result = event_neighbourhood(
            self.spine,
            "trade_placed",
            before_steps=3,
            after_steps=3,
        )
        self.assertFalse(result.empty)
        self.assertIn(0, result["offset"].tolist())
        self.assertEqual(
            set(result.loc[result["offset"].eq(0), "route_name"]),
            {"Trade placed"},
        )
        self.assertTrue(result["share_focus_pct"].between(0, 100).all())

    def test_summary_continuation_and_stop_are_complete(self):
        summary = event_focus_summary(self.spine, "trade_preview")
        self.assertGreater(summary["sessions"], 0)
        self.assertEqual(
            summary["continued_sessions"] + summary["stopped_sessions"],
            summary["sessions"],
        )

    def test_window_paths_return_route_arrays(self):
        paths = event_window_paths(self.spine, "trade_preview")
        self.assertGreater(len(paths), 0)
        self.assertIsInstance(paths.iloc[0]["routes"], list)
        self.assertLessEqual(paths["share_pct"].sum(), 100.1)

    def test_catalog_and_recommendation_prioritise_meaningful_event(self):
        catalog = event_catalog(self.spine)
        self.assertIn("trade_placed", {item["name"] for item in catalog})
        self.assertEqual(recommended_event(catalog), "trade_preview")

    def test_missing_event_returns_empty_safe_outputs(self):
        self.assertTrue(event_neighbourhood(self.spine, "missing").empty)
        self.assertEqual(event_focus_summary(self.spine, "missing")["sessions"], 0)
        self.assertTrue(event_window_paths(self.spine, "missing").empty)


if __name__ == "__main__":
    unittest.main()
