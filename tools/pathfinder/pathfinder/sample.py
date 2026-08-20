from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta, timezone

import pandas as pd


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest().upper()


PATH_TEMPLATES = [
    [
        ("page_view", "/", "Home"),
        ("page_view", "/news", "News"),
        ("page_view", "/secure/research/instrument-report/B1Y9TB3", "Instrument report"),
        ("login", "/login", "Login"),
        ("login_complete", "/secure", "Secure home"),
        ("trade_preview", "/secure/trading/preview", "Trade preview"),
        ("trade_placed", "/secure/trading/confirmation", "Trade confirmation"),
    ],
    [
        ("page_view", "/secure/research/uk-summary", "UK summary"),
        ("page_view", "/secure/research/instrument-report/B1Y9TB3", "Instrument report"),
        ("login", "/login", "Login"),
        ("login_complete", "/secure", "Secure home"),
        ("page_view", "/secure/research/instrument-report/B1Y9TB3", "Instrument report"),
        ("trade_preview", "/secure/trading/preview", "Trade preview"),
    ],
    [
        ("page_view", "/secure/direct-debit", "Direct debit"),
        ("form_event_v2", "/secure/direct-debit", "Direct debit"),
        ("form_event_v2", "/secure/direct-debit/amount", "Direct debit amount"),
        ("page_view", "/secure/direct-debit/confirmation", "Direct debit confirmation"),
    ],
    [
        ("screen_view", "App home", "App home"),
        ("screen_view", "Regular investments", "Regular investments"),
        ("screen_view", "Instrument search", "Instrument search"),
        ("screen_view", "Regular investment review", "Regular investment review"),
    ],
    [
        ("page_view", "/open-account", "Open account"),
        ("form_event_v2", "/open-account/personal-details", "Personal details"),
        ("form_event_v2", "/open-account/review", "Review"),
        ("account_opened", "/open-account/complete", "Account opened"),
    ],
]


def make_sample_events(session_count: int = 240, seed: int = 7) -> pd.DataFrame:
    randomizer = random.Random(seed)
    start = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=3)
    rows: list[dict[str, object]] = []

    weights = [0.31, 0.24, 0.18, 0.14, 0.13]
    for session_number in range(session_count):
        template = randomizer.choices(PATH_TEMPLATES, weights=weights, k=1)[0]
        browser_key = _hash(f"browser-{session_number // 2}")
        ga_session_key = _hash(f"session-{session_number}")
        platform = "APP" if template[0][0] == "screen_view" else "WEB"
        device = randomizer.choice(["desktop", "mobile", "tablet"])
        event_time = start + timedelta(
            minutes=randomizer.randint(0, 3 * 24 * 60), seconds=randomizer.randint(0, 59)
        )
        identified = session_number % 4 != 0
        identified_key = _hash(f"identified-{session_number // 3}") if identified else None

        # A small, deliberate sample demonstrates the multiple-ID QA flag.
        second_identified_key = (
            _hash(f"identified-conflict-{session_number}")
            if session_number > 0 and session_number % 71 == 0
            else None
        )
        missing_ga_session = session_number > 0 and session_number % 43 == 0

        # Some sessions exit early so drop-off views are meaningful.
        keep_steps = len(template)
        if randomizer.random() < 0.23 and len(template) > 2:
            keep_steps = randomizer.randint(2, len(template) - 1)

        for step_number, (event_name, route_path, page_title) in enumerate(
            template[:keep_steps], start=1
        ):
            event_time += timedelta(seconds=randomizer.randint(4, 75))
            current_identified = identified_key
            if second_identified_key and step_number == keep_steps:
                current_identified = second_identified_key
            form_id = None
            form_step_id = None
            component_id = None
            if event_name == "form_event_v2":
                form_id = "direct-debit" if "direct-debit" in route_path else "account-opening"
                form_step_id = route_path.rsplit("/", 1)[-1]
                component_id = "continue"
            rows.append(
                {
                    "event_date": event_time.date(),
                    "event_ts": event_time,
                    "event_timestamp": int(event_time.timestamp() * 1_000_000),
                    "batch_page_id": step_number,
                    "batch_ordering_id": step_number,
                    "batch_event_index": 0,
                    "event_name": event_name,
                    "platform": platform,
                    "stream_id": "sample-app" if platform == "APP" else "sample-web",
                    "device_category": device,
                    "first_user_source": randomizer.choice(["google", "direct", "email"]),
                    "first_user_medium": randomizer.choice(["organic", "none", "email"]),
                    "first_user_campaign": "sample",
                    "analytics_storage": "Yes",
                    "browser_key": browser_key,
                    "identified_key": current_identified,
                    "ga_session_id": session_number + 1000,
                    "ga_session_number": randomizer.randint(1, 15),
                    "ga_session_key": None if missing_ga_session else ga_session_key,
                    "route_path": route_path,
                    "page_title": page_title,
                    "form_id": form_id,
                    "form_step_id": form_step_id,
                    "component_id": component_id,
                    "component_type": "button" if component_id else None,
                    "component_validated": "true" if form_id else None,
                    "instrument_code": "B1Y9TB3" if "instrument-report" in route_path else None,
                }
            )
    return pd.DataFrame.from_records(rows)
