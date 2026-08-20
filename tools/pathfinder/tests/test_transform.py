from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pathfinder.sample import make_sample_events  # noqa: E402
from pathfinder.transform import (  # noqa: E402
    build_event_spine,
    filter_spine,
    focus_event_spine,
    load_route_rules,
    normalise_path,
    path_table,
    session_table,
    transition_table,
)


RULES_PATH = PROJECT_ROOT / "config" / "route_rules.csv"


def make_event(
    minute: int,
    event_name: str,
    route_path: str,
    *,
    browser_key: str = "browser-a",
    ga_session_key: str | None = "session-a",
    identified_key: str | None = None,
    form_id: str | None = None,
    form_step_id: str | None = None,
) -> dict[str, object]:
    event_ts = datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc) + timedelta(
        minutes=minute
    )
    return {
        "event_date": event_ts.date(),
        "event_ts": event_ts,
        "event_timestamp": int(event_ts.timestamp() * 1_000_000),
        "event_name": event_name,
        "platform": "WEB",
        "device_category": "desktop",
        "browser_key": browser_key,
        "identified_key": identified_key,
        "ga_session_key": ga_session_key,
        "route_path": route_path,
        "page_title": route_path,
        "form_id": form_id,
        "form_step_id": form_step_id,
    }


class PathfinderTransformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = load_route_rules(RULES_PATH)

    def test_normalise_path_removes_query_and_dynamic_ids(self):
        self.assertEqual(
            normalise_path("https://www.ii.co.uk/secure/item/12345678?source=email"),
            "/secure/item/:id",
        )
        self.assertEqual(normalise_path("App home"), "App home")

    def test_route_mapping_and_consecutive_collapse(self):
        raw = pd.DataFrame(
            [
                make_event(0, "page_view", "/secure/research/uk-summary"),
                make_event(1, "page_view", "/secure/research/uk-summary"),
                make_event(
                    2,
                    "page_view",
                    "/secure/research/instrument-report/B1Y9TB3",
                ),
                make_event(3, "trade_preview", "/secure/trading/preview"),
                make_event(4, "trade_placed", "/secure/trading/confirmation"),
            ]
        )
        spine = build_event_spine(raw, self.rules, collapse_consecutive=True)
        self.assertEqual(
            spine["route_name"].tolist(),
            ["UK summary", "Instrument report", "Trade preview", "Trade placed"],
        )
        self.assertTrue(bool(spine.iloc[-1]["outcome"]))
        self.assertEqual(spine["session_key"].nunique(), 1)

    def test_identified_id_does_not_split_session(self):
        raw = pd.DataFrame(
            [
                make_event(0, "page_view", "/", identified_key=None),
                make_event(1, "login", "/login", identified_key="id-1"),
                make_event(2, "login_complete", "/secure", identified_key="id-1"),
            ]
        )
        spine = build_event_spine(raw, self.rules)
        self.assertEqual(spine["session_key"].nunique(), 1)
        self.assertEqual(set(spine["identity_status"]), {"single_identified_id"})

    def test_multiple_identified_ids_are_flagged(self):
        raw = pd.DataFrame(
            [
                make_event(0, "page_view", "/", identified_key="id-1"),
                make_event(1, "login", "/login", identified_key="id-2"),
            ]
        )
        spine = build_event_spine(raw, self.rules)
        self.assertEqual(set(spine["identity_status"]), {"multiple_identified_ids"})
        self.assertTrue(spine["identified_key_session"].isna().all())

    def test_multiple_ids_across_sessions_are_flagged_on_browser(self):
        raw = pd.DataFrame(
            [
                make_event(0, "page_view", "/", identified_key="id-1"),
                make_event(
                    60,
                    "page_view",
                    "/news",
                    ga_session_key="session-b",
                    identified_key="id-2",
                ),
            ]
        )
        spine = build_event_spine(raw, self.rules)
        self.assertEqual(spine["session_key"].nunique(), 2)
        self.assertEqual(set(spine["identity_status"]), {"single_identified_id"})
        self.assertEqual(
            set(spine["browser_identity_status"]),
            {"multiple_identified_ids_in_range"},
        )

    def test_missing_ga_session_uses_30_minute_fallback(self):
        raw = pd.DataFrame(
            [
                make_event(0, "page_view", "/", ga_session_key=None),
                make_event(10, "page_view", "/news", ga_session_key=None),
                make_event(50, "page_view", "/help", ga_session_key=None),
            ]
        )
        spine = build_event_spine(raw, self.rules, collapse_consecutive=False)
        self.assertEqual(spine["session_key"].nunique(), 2)
        self.assertEqual(set(spine["session_key_source"]), {"30m_fallback"})

    def test_transition_and_path_outputs(self):
        raw = pd.DataFrame(
            [
                make_event(0, "page_view", "/secure/research/uk-summary"),
                make_event(
                    1,
                    "page_view",
                    "/secure/research/instrument-report/B1Y9TB3",
                ),
                make_event(2, "trade_preview", "/secure/trading/preview"),
            ]
        )
        spine = build_event_spine(raw, self.rules)
        transitions = transition_table(spine)
        paths = path_table(spine)
        self.assertEqual(len(transitions), 2)
        self.assertEqual(transitions["transition_count"].sum(), 2)
        self.assertEqual(
            paths.iloc[0]["path"],
            "UK summary > Instrument report > Trade preview",
        )

    def test_start_route_trims_each_session(self):
        raw = pd.DataFrame(
            [
                make_event(0, "page_view", "/"),
                make_event(1, "page_view", "/secure/research/uk-summary"),
                make_event(
                    2,
                    "page_view",
                    "/secure/research/instrument-report/B1Y9TB3",
                ),
            ]
        )
        spine = build_event_spine(raw, self.rules)
        trimmed = filter_spine(spine, start_route="UK summary")
        self.assertEqual(trimmed["route_name"].tolist()[0], "UK summary")
        self.assertEqual(trimmed["step_index"].tolist(), [1, 2])

    def test_event_focus_controls_every_downstream_route(self):
        raw = pd.DataFrame(
            [
                make_event(0, "page_view", "/secure/research/uk-summary"),
                make_event(1, "trade_preview", "/secure/trading/preview"),
                make_event(2, "trade_placed", "/secure/trading/confirmation"),
                make_event(3, "page_view", "/secure"),
            ]
        )
        spine = build_event_spine(raw, self.rules)
        before = focus_event_spine(spine, "trade_placed", mode="leading_to")
        after = focus_event_spine(spine, "trade_placed", mode="after")
        self.assertEqual(
            before["route_name"].tolist(),
            ["UK summary", "Trade preview", "Trade placed"],
        )
        self.assertEqual(after["route_name"].tolist(), ["Trade placed", "/secure"])

    def test_event_focus_only_keeps_sessions_containing_event(self):
        raw = pd.DataFrame(
            [
                make_event(0, "page_view", "/", ga_session_key="session-a"),
                make_event(1, "login", "/login", ga_session_key="session-a"),
                make_event(
                    60,
                    "page_view",
                    "/news",
                    browser_key="browser-b",
                    ga_session_key="session-b",
                ),
            ]
        )
        spine = build_event_spine(raw, self.rules)
        focused = focus_event_spine(spine, "login", mode="full_route")
        self.assertEqual(focused["session_key"].nunique(), 1)
        self.assertEqual(focused["route_name"].tolist(), ["/", "Login"])

    def test_sample_builds_all_analysis_tables(self):
        raw = make_sample_events(session_count=40)
        spine = build_event_spine(raw, self.rules)
        self.assertGreater(len(spine), 0)
        self.assertGreater(len(transition_table(spine)), 0)
        self.assertEqual(len(session_table(spine)), spine["session_key"].nunique())


if __name__ == "__main__":
    unittest.main()
