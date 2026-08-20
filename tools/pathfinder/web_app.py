from __future__ import annotations

import argparse
import copy
import json
import threading
from datetime import date, datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pandas as pd

from pathfinder.config import AppConfig, DEFAULT_EVENT_NAMES
from pathfinder.event_focus import (
    event_catalog,
    event_focus_summary,
    event_neighbourhood,
    event_window_paths,
    recommended_event,
)
from pathfinder.query import estimate_query_bytes, query_raw_events
from pathfinder.sample import make_sample_events
from pathfinder.transform import build_event_spine, filter_spine, load_route_rules


ROOT = Path(__file__).resolve().parent
STATIC_ROOT = ROOT / "static"
RULES_PATH = ROOT / "config" / "route_rules.csv"
MAX_REQUEST_BYTES = 1_000_000


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _format_bytes(value: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(max(0, value))
    for unit in units:
        if size < 1000 or unit == units[-1]:
            return f"{size:,.1f} {unit}" if unit != "B" else f"{int(size):,} B"
        size /= 1000
    return f"{size:,.1f} TB"


def _brief_error(error: Exception, limit: int = 420) -> str:
    message = " ".join(str(error).split()) or error.__class__.__name__
    return message if len(message) <= limit else message[: limit - 1] + "…"


def _clean_choice(value: Any, allowed: set[str]) -> str | None:
    if value is None or value == "" or value == "all":
        return None
    text = str(value)
    if text not in allowed:
        raise ValueError(f"Unsupported filter value: {text}")
    return text


def _parse_date(value: Any, label: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must use YYYY-MM-DD") from exc


def _parse_event_names(value: Any) -> list[str]:
    if isinstance(value, str):
        values = value.replace(",", "\n").splitlines()
    elif isinstance(value, list):
        values = value
    else:
        values = []
    names = list(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))
    if not names:
        raise ValueError("Select at least one event name")
    if len(names) > 100:
        raise ValueError("A maximum of 100 event names is supported")
    return names


def _insights(
    neighbourhood: pd.DataFrame,
    summary: dict[str, object],
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    immediately_before = neighbourhood.loc[neighbourhood["offset"].eq(-1)]
    if not immediately_before.empty:
        top = immediately_before.iloc[0]
        items.append(
            {
                "label": "Most common previous route",
                "value": str(top["route_name"]),
                "detail": f"{float(top['share_focus_pct']):.1f}% of focused sessions",
            }
        )
    immediately_after = neighbourhood.loc[neighbourhood["offset"].eq(1)]
    if not immediately_after.empty:
        top = immediately_after.iloc[0]
        items.append(
            {
                "label": "Most common next route",
                "value": str(top["route_name"]),
                "detail": f"{float(top['share_focus_pct']):.1f}% of focused sessions",
            }
        )
    items.append(
        {
            "label": "Stops at the event",
            "value": f"{float(summary['stopped_pct']):.1f}%",
            "detail": f"{int(summary['stopped_sessions']):,} sessions have no later recorded step",
        }
    )
    return items


class PathFinderStore:
    """In-memory analysis store shared by the lightweight HTTP handlers."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._raw = pd.DataFrame()
        self._spine = pd.DataFrame()
        self._source = ""
        self._loaded_at = ""
        self._query_stats: dict[str, object] | None = None
        self._analysis_cache: dict[tuple[object, ...], dict[str, object]] = {}
        self.load_demo()

    def _replace(
        self,
        raw: pd.DataFrame,
        *,
        source: str,
        inactivity_minutes: int = 30,
        collapse_consecutive: bool = True,
        query_stats: dict[str, object] | None = None,
    ) -> None:
        rules = load_route_rules(RULES_PATH)
        spine = build_event_spine(
            raw,
            rules,
            inactivity_minutes=inactivity_minutes,
            collapse_consecutive=collapse_consecutive,
        )
        if spine.empty:
            raise ValueError("No usable route steps were produced")
        with self._lock:
            self._raw = raw
            self._spine = spine
            self._source = source
            self._loaded_at = _utc_now()
            self._query_stats = query_stats
            self._analysis_cache.clear()

    def load_demo(self) -> dict[str, object]:
        raw = make_sample_events(session_count=300)
        self._replace(raw, source="Synthetic demo")
        return self.meta()

    def meta(self) -> dict[str, object]:
        with self._lock:
            spine = self._spine
            catalog = event_catalog(spine)
            return {
                "version": "3.0",
                "source": self._source,
                "loaded_at": self._loaded_at,
                "raw_events": int(len(self._raw)),
                "route_steps": int(len(spine)),
                "sessions": int(spine["session_key"].nunique()),
                "events": catalog,
                "recommended_event": recommended_event(catalog),
                "platforms": sorted(spine["platform"].dropna().astype(str).unique()),
                "journeys": sorted(spine["journey"].dropna().astype(str).unique()),
                "identity_states": sorted(
                    spine["identity_status"].dropna().astype(str).unique()
                ),
                "query_stats": self._query_stats,
                "default_event_names": list(DEFAULT_EVENT_NAMES),
            }

    def analyse(self, payload: dict[str, Any]) -> dict[str, object]:
        with self._lock:
            spine = self._spine
            events = event_catalog(spine)
            event_names = {str(item["name"]) for item in events}
            event_name = str(payload.get("event") or recommended_event(events) or "")
            if event_name not in event_names:
                raise ValueError(f"Event is not available in this dataset: {event_name}")

            platforms = set(spine["platform"].dropna().astype(str))
            journeys = set(spine["journey"].dropna().astype(str))
            identities = set(spine["identity_status"].dropna().astype(str))
            platform = _clean_choice(payload.get("platform"), platforms)
            journey = _clean_choice(payload.get("journey"), journeys)
            identity = _clean_choice(payload.get("identity"), identities)

            try:
                context_steps = int(payload.get("context_steps", 3))
            except (TypeError, ValueError) as exc:
                raise ValueError("Context steps must be a whole number") from exc
            if not 1 <= context_steps <= 5:
                raise ValueError("Context steps must be between 1 and 5")

            filtered = filter_spine(
                spine,
                platforms=[platform] if platform else None,
                journeys=[journey] if journey else None,
                identity_statuses=[identity] if identity else None,
            )

            cache_key = (
                self._loaded_at,
                event_name,
                platform,
                journey,
                identity,
                context_steps,
            )
            cached = self._analysis_cache.get(cache_key)
            if cached is not None:
                return copy.deepcopy(cached)

        neighbourhood = event_neighbourhood(
            filtered,
            event_name,
            before_steps=context_steps,
            after_steps=context_steps,
        )
        summary = event_focus_summary(filtered, event_name)
        if not summary["sessions"]:
            result = {
                "selection": {
                    "event": event_name,
                    "platform": platform,
                    "journey": journey,
                    "identity": identity,
                    "context_steps": context_steps,
                },
                "summary": summary,
                "steps": [],
                "paths": [],
                "insights": [],
                "empty_message": "No sessions contain this event after applying the filters.",
            }
            with self._lock:
                self._analysis_cache[cache_key] = result
            return copy.deepcopy(result)

        step_records: list[dict[str, object]] = []
        for offset in range(-context_steps, context_steps + 1):
            rows = neighbourhood.loc[neighbourhood["offset"].eq(offset)]
            if rows.empty:
                continue
            routes = [
                {
                    "route": str(row.route_name),
                    "sessions": int(row.sessions),
                    "share_focus_pct": float(row.share_focus_pct),
                    "share_position_pct": float(row.share_position_pct),
                }
                for row in rows.itertuples(index=False)
            ]
            step_records.append(
                {
                    "offset": offset,
                    "coverage_sessions": int(rows.iloc[0]["position_coverage_sessions"]),
                    "coverage_pct": float(rows.iloc[0]["position_coverage_pct"]),
                    "routes": routes,
                }
            )

        paths_frame = event_window_paths(
            filtered,
            event_name,
            before_steps=context_steps,
            after_steps=context_steps,
        )
        paths = [
            {
                "routes": list(row.routes),
                "sessions": int(row.sessions),
                "share_pct": float(row.share_pct),
                "outcome_rate_pct": float(row.outcome_rate_pct),
            }
            for row in paths_frame.itertuples(index=False)
        ]
        result = {
            "selection": {
                "event": event_name,
                "platform": platform,
                "journey": journey,
                "identity": identity,
                "context_steps": context_steps,
            },
            "summary": summary,
            "steps": step_records,
            "paths": paths,
            "insights": _insights(neighbourhood, summary),
            "empty_message": None,
        }
        with self._lock:
            if len(self._analysis_cache) >= 64:
                self._analysis_cache.pop(next(iter(self._analysis_cache)))
            self._analysis_cache[cache_key] = result
        return copy.deepcopy(result)

    @staticmethod
    def _config_from_payload(payload: dict[str, Any]) -> AppConfig:
        defaults = AppConfig.from_env()
        try:
            max_gb = float(payload.get("max_gb", defaults.maximum_bytes_billed / 1e9))
        except (TypeError, ValueError) as exc:
            raise ValueError("Maximum GB must be a number") from exc
        if not 0.1 <= max_gb <= 500:
            raise ValueError("Maximum GB must be between 0.1 and 500")
        return AppConfig(
            project_id=str(payload.get("project_id", defaults.project_id)).strip(),
            dataset_id=str(payload.get("dataset_id", defaults.dataset_id)).strip(),
            table_pattern=str(payload.get("table_pattern", defaults.table_pattern)).strip(),
            location=str(payload.get("location", defaults.location)).strip(),
            maximum_bytes_billed=int(max_gb * 1_000_000_000),
        ).validated()

    @classmethod
    def _query_args(cls, payload: dict[str, Any]):
        config = cls._config_from_payload(payload)
        start_date = _parse_date(payload.get("start_date"), "Start date")
        end_date = _parse_date(payload.get("end_date"), "End date")
        if start_date > end_date:
            raise ValueError("Start date must be on or before end date")
        event_names = _parse_event_names(payload.get("event_names"))
        consent_values = payload.get("consent_values", ["Yes"])
        if not isinstance(consent_values, list):
            raise ValueError("Consent values must be a list")
        consent_values = [str(value) for value in consent_values if value]
        if not consent_values:
            raise ValueError("Select at least one consent value")
        return config, start_date, end_date, event_names, consent_values

    def estimate(self, payload: dict[str, Any]) -> dict[str, object]:
        config, start_date, end_date, event_names, consent_values = self._query_args(
            payload
        )
        try:
            estimated = estimate_query_bytes(
                config, start_date, end_date, event_names, consent_values
            )
        except Exception as exc:
            raise RuntimeError(f"BigQuery estimate failed: {_brief_error(exc)}") from exc
        return {
            "estimated_bytes": estimated,
            "estimated_display": _format_bytes(estimated),
            "within_guard": estimated <= config.maximum_bytes_billed,
            "guard_display": _format_bytes(config.maximum_bytes_billed),
        }

    def load_bigquery(self, payload: dict[str, Any]) -> dict[str, object]:
        config, start_date, end_date, event_names, consent_values = self._query_args(
            payload
        )
        try:
            raw, stats = query_raw_events(
                config, start_date, end_date, event_names, consent_values
            )
        except Exception as exc:
            raise RuntimeError(f"BigQuery load failed: {_brief_error(exc)}") from exc
        if raw.empty:
            raise ValueError("The selected BigQuery tables returned no events")
        self._replace(
            raw,
            source="Raw BigQuery",
            inactivity_minutes=int(payload.get("inactivity_minutes", 30)),
            collapse_consecutive=bool(payload.get("collapse_consecutive", True)),
            query_stats={
                "rows": stats.rows,
                "processed": _format_bytes(stats.total_bytes_processed),
                "billed": _format_bytes(stats.total_bytes_billed),
                "cache_hit": stats.cache_hit,
            },
        )
        return self.meta()


STORE = PathFinderStore()


class PathFinderHandler(BaseHTTPRequestHandler):
    server_version = "PathFinder/3.0"

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def _send_bytes(
        self,
        body: bytes,
        content_type: str,
        status: int = HTTPStatus.OK,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: object, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        self._send_bytes(body, "application/json; charset=utf-8", status)

    def _request_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Invalid request length") from exc
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise ValueError("Request body is missing or too large")
        try:
            payload = json.loads(self.rfile.read(length))
        except json.JSONDecodeError as exc:
            raise ValueError("Request body must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object")
        return payload

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlsplit(self.path).path
        if path == "/api/meta":
            self._json(STORE.meta())
            return
        if path == "/healthz":
            self._json({"status": "ok", "version": "3.0"})
            return
        static_files = {
            "/": (STATIC_ROOT / "index.html", "text/html; charset=utf-8"),
            "/app.css": (STATIC_ROOT / "app.css", "text/css; charset=utf-8"),
            "/app.js": (STATIC_ROOT / "app.js", "text/javascript; charset=utf-8"),
            "/favicon.svg": (STATIC_ROOT / "favicon.svg", "image/svg+xml"),
        }
        selected = static_files.get(path)
        if not selected or not selected[0].is_file():
            self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        self._send_bytes(selected[0].read_bytes(), selected[1])

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlsplit(self.path).path
        try:
            payload = self._request_json()
            if path == "/api/analyse":
                result = STORE.analyse(payload)
            elif path == "/api/load-demo":
                result = STORE.load_demo()
            elif path == "/api/estimate":
                result = STORE.estimate(payload)
            elif path == "/api/load-bigquery":
                result = STORE.load_bigquery(payload)
            else:
                self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
                return
            self._json(result)
        except ValueError as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except RuntimeError as exc:
            self._json({"error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE)
        except Exception:
            self._json(
                {"error": "PathFinder could not complete this request. Check the server log."},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the GA4 PathFinder mobile app")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8501)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), PathFinderHandler)
    print(f"GA4 PathFinder is running on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
