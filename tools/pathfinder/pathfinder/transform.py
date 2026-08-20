from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path
from typing import IO, Iterable
from urllib.parse import urlsplit

import pandas as pd

from .config import PAGE_EVENT_NAMES


RULE_COLUMNS = {
    "priority",
    "enabled",
    "journey",
    "route_name",
    "match_field",
    "pattern",
    "event_scope",
    "step_type",
    "outcome",
}

RAW_DEFAULTS = {
    "event_date": pd.NaT,
    "event_timestamp": pd.NA,
    "batch_page_id": 0,
    "batch_ordering_id": 0,
    "batch_event_index": 0,
    "platform": "unknown",
    "stream_id": pd.NA,
    "device_category": "unknown",
    "first_user_source": "(not set)",
    "first_user_medium": "(not set)",
    "first_user_campaign": "(not set)",
    "analytics_storage": "Unset",
    "identified_key": pd.NA,
    "ga_session_id": pd.NA,
    "ga_session_number": pd.NA,
    "ga_session_key": pd.NA,
    "route_path": pd.NA,
    "page_title": pd.NA,
    "form_id": pd.NA,
    "form_step_id": pd.NA,
    "component_id": pd.NA,
    "component_type": pd.NA,
    "component_validated": pd.NA,
    "instrument_code": pd.NA,
}

_UUID_SEGMENT = re.compile(
    r"/[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}(?=/|$)",
    re.IGNORECASE,
)
_LONG_NUMBER_SEGMENT = re.compile(r"/\d{6,}(?=/|$)")


def load_route_rules(source: str | Path | IO[str]) -> pd.DataFrame:
    rules = pd.read_csv(source, dtype=str).fillna("")
    missing = sorted(RULE_COLUMNS - set(rules.columns))
    if missing:
        raise ValueError(f"Route rules are missing columns: {', '.join(missing)}")

    rules = rules.copy()
    rules["priority"] = pd.to_numeric(rules["priority"], errors="raise").astype(int)
    rules["enabled"] = rules["enabled"].str.lower().isin({"true", "1", "yes", "y"})
    rules["outcome"] = rules["outcome"].str.lower().isin({"true", "1", "yes", "y"})
    rules["event_scope"] = rules["event_scope"].str.lower().str.strip()
    invalid_scopes = sorted(set(rules["event_scope"]) - {"page", "event", "any"})
    if invalid_scopes:
        raise ValueError(f"Invalid event_scope values: {', '.join(invalid_scopes)}")
    rules = rules.loc[rules["enabled"]].sort_values("priority", kind="stable")
    return rules.reset_index(drop=True)


def normalise_path(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None

    if text.startswith(("http://", "https://")):
        text = urlsplit(text).path
    else:
        text = text.split("?", 1)[0].split("#", 1)[0]

    text = re.sub(r"/{2,}", "/", text)
    text = _UUID_SEGMENT.sub("/:uuid", text)
    text = _LONG_NUMBER_SEGMENT.sub("/:id", text)
    if text.startswith("/") and len(text) > 1:
        text = text.rstrip("/")
    return text[:500] if text else None


def _scope_mask(event_names: pd.Series, scope: str) -> pd.Series:
    is_page = event_names.isin(PAGE_EVENT_NAMES)
    if scope == "page":
        return is_page
    if scope == "event":
        return ~is_page
    return pd.Series(True, index=event_names.index)


def _contains(values: pd.Series, pattern: str, priority: int) -> pd.Series:
    try:
        return values.fillna("").astype(str).str.contains(
            pattern, case=False, regex=True, na=False
        )
    except re.error as exc:
        raise ValueError(f"Invalid regex in route rule priority {priority}: {pattern}") from exc


def _form_label(row: pd.Series) -> str:
    parts = ["Form"]
    raw_form_id = row.get("form_id")
    raw_form_step_id = row.get("form_step_id")
    form_id = "" if pd.isna(raw_form_id) else str(raw_form_id).strip()
    form_step_id = "" if pd.isna(raw_form_step_id) else str(raw_form_step_id).strip()
    if form_id and form_id.lower() not in {"nan", "<na>"}:
        parts.append(form_id)
    if form_step_id and form_step_id.lower() not in {"nan", "<na>"}:
        parts.append(form_step_id)
    return " • ".join(parts)


def _interaction_label(row: pd.Series) -> str:
    raw_event_name = row.get("event_name")
    raw_component_id = row.get("component_id")
    event_name = "Interaction" if pd.isna(raw_event_name) else str(raw_event_name)
    component_id = "" if pd.isna(raw_component_id) else str(raw_component_id).strip()
    if component_id and component_id.lower() not in {"nan", "<na>"}:
        return f"{event_name} • {component_id}"
    return event_name


def apply_route_rules(events: pd.DataFrame, rules: pd.DataFrame) -> pd.DataFrame:
    work = events.copy()
    work["route_path"] = work["route_path"].map(normalise_path)
    work["route_name"] = pd.NA
    work["journey"] = pd.NA
    work["step_type"] = pd.NA
    work["outcome"] = False
    work["route_rule_priority"] = pd.NA
    work["rule_matched"] = False

    context_journey = pd.Series(pd.NA, index=work.index, dtype="object")
    for rule in rules.loc[rules["match_field"].eq("route_path")].itertuples(index=False):
        mask = context_journey.isna() & _contains(
            work["route_path"], rule.pattern, rule.priority
        )
        context_journey.loc[mask] = rule.journey

    for rule in rules.itertuples(index=False):
        if rule.match_field not in work.columns:
            continue
        mask = (
            work["route_name"].isna()
            & _scope_mask(work["event_name"], rule.event_scope)
            & _contains(work[rule.match_field], rule.pattern, rule.priority)
        )
        work.loc[mask, "route_name"] = rule.route_name
        work.loc[mask, "journey"] = rule.journey
        work.loc[mask, "step_type"] = rule.step_type
        work.loc[mask, "outcome"] = bool(rule.outcome)
        work.loc[mask, "route_rule_priority"] = int(rule.priority)
        work.loc[mask, "rule_matched"] = True

    page_mask = work["event_name"].isin(PAGE_EVENT_NAMES)
    form_mask = work["event_name"].eq("form_event_v2")
    interaction_mask = work["event_name"].isin(
        {"internal_click", "component_interaction"}
    )
    unmatched = work["route_name"].isna()

    page_fallback = work["route_path"].fillna(work["page_title"])
    page_fallback = page_fallback.fillna("[missing page/screen]")
    work.loc[unmatched & page_mask, "route_name"] = page_fallback
    work.loc[unmatched & page_mask, "step_type"] = "page"

    form_indices = work.index[unmatched & form_mask]
    if len(form_indices):
        work.loc[form_indices, "route_name"] = work.loc[form_indices].apply(
            _form_label, axis=1
        )
        work.loc[form_indices, "step_type"] = "form"

    interaction_indices = work.index[unmatched & interaction_mask]
    if len(interaction_indices):
        work.loc[interaction_indices, "route_name"] = work.loc[
            interaction_indices
        ].apply(_interaction_label, axis=1)
        work.loc[interaction_indices, "step_type"] = "interaction"

    remaining = work["route_name"].isna()
    work.loc[remaining, "route_name"] = work.loc[remaining, "event_name"].fillna(
        "[unknown event]"
    )
    work.loc[remaining, "step_type"] = "event"

    work["journey"] = work["journey"].fillna(context_journey).fillna("Unmapped")
    work["outcome"] = work["outcome"].fillna(False).astype(bool)
    work["rule_matched"] = work["rule_matched"].fillna(False).astype(bool)
    return work


def _add_session_keys(events: pd.DataFrame, inactivity_minutes: int) -> pd.DataFrame:
    work = events.sort_values(
        [
            "browser_key",
            "event_ts",
            "event_timestamp",
            "batch_page_id",
            "batch_ordering_id",
            "batch_event_index",
        ],
        kind="stable",
    ).copy()
    gaps = work.groupby("browser_key", sort=False)["event_ts"].diff()
    new_time_session = gaps.isna() | gaps.gt(timedelta(minutes=inactivity_minutes))
    work["_fallback_session_number"] = new_time_session.groupby(
        work["browser_key"], sort=False
    ).cumsum()
    fallback_key = (
        "fallback:"
        + work["browser_key"].astype(str)
        + ":"
        + work["_fallback_session_number"].astype(int).astype(str)
    )
    has_ga_session = work["ga_session_key"].notna() & work["ga_session_key"].ne("")
    work["session_key"] = work["ga_session_key"].where(has_ga_session, fallback_key)
    work["session_key_source"] = "30m_fallback"
    work.loc[has_ga_session, "session_key_source"] = "ga4"
    return work.drop(columns=["_fallback_session_number"])


def _add_identity_status(events: pd.DataFrame) -> pd.DataFrame:
    work = events.copy()
    id_counts = work.groupby("session_key", sort=False)["identified_key"].nunique(
        dropna=True
    )
    work["identified_id_count"] = work["session_key"].map(id_counts).fillna(0).astype(int)
    work["identity_status"] = "anonymous"
    work.loc[work["identified_id_count"].eq(1), "identity_status"] = (
        "single_identified_id"
    )
    work.loc[work["identified_id_count"].gt(1), "identity_status"] = (
        "multiple_identified_ids"
    )

    single_ids = (
        work.loc[work["identified_key"].notna()]
        .groupby("session_key", sort=False)["identified_key"]
        .agg(lambda values: values.iloc[0] if values.nunique() == 1 else pd.NA)
    )
    work["identified_key_session"] = work["session_key"].map(single_ids)

    browser_id_counts = work.groupby("browser_key", sort=False)["identified_key"].nunique(
        dropna=True
    )
    work["browser_identified_id_count"] = (
        work["browser_key"].map(browser_id_counts).fillna(0).astype(int)
    )
    work["browser_identity_status"] = "anonymous_in_range"
    work.loc[work["browser_identified_id_count"].eq(1), "browser_identity_status"] = (
        "single_identified_id_in_range"
    )
    work.loc[work["browser_identified_id_count"].gt(1), "browser_identity_status"] = (
        "multiple_identified_ids_in_range"
    )
    return work


def resequence_spine(spine: pd.DataFrame) -> pd.DataFrame:
    if spine.empty:
        return spine.copy()
    work = spine.sort_values(
        [
            "session_key",
            "event_ts",
            "event_timestamp",
            "batch_page_id",
            "batch_ordering_id",
            "batch_event_index",
        ],
        kind="stable",
    ).copy()
    work["step_index"] = work.groupby("session_key", sort=False).cumcount() + 1
    return work.reset_index(drop=True)


def build_event_spine(
    raw_events: pd.DataFrame,
    route_rules: pd.DataFrame,
    inactivity_minutes: int = 30,
    collapse_consecutive: bool = True,
) -> pd.DataFrame:
    required = {"event_ts", "event_name", "browser_key"}
    missing = sorted(required - set(raw_events.columns))
    if missing:
        raise ValueError(f"Raw event data is missing columns: {', '.join(missing)}")
    if raw_events.empty:
        return raw_events.copy()

    work = raw_events.copy()
    for column, default in RAW_DEFAULTS.items():
        if column not in work.columns:
            work[column] = default

    work["event_ts"] = pd.to_datetime(work["event_ts"], errors="coerce", utc=True)
    work = work.loc[work["event_ts"].notna() & work["browser_key"].notna()].copy()
    if work.empty:
        return work

    if work["event_timestamp"].isna().all():
        work["event_timestamp"] = work["event_ts"].astype("int64") // 1_000
    else:
        derived = work["event_ts"].astype("int64") // 1_000
        work["event_timestamp"] = pd.to_numeric(
            work["event_timestamp"], errors="coerce"
        ).fillna(derived)

    work = _add_session_keys(work, inactivity_minutes=inactivity_minutes)
    work = apply_route_rules(work, route_rules)
    # Calculate identity status before deduplication so conflicting IDs on otherwise
    # duplicate-looking events are still surfaced in QA.
    work = _add_identity_status(work)

    dedupe_columns = [
        "session_key",
        "event_timestamp",
        "batch_page_id",
        "batch_ordering_id",
        "batch_event_index",
        "event_name",
        "route_name",
        "form_step_id",
        "component_id",
    ]
    work = work.drop_duplicates(subset=dedupe_columns, keep="first")
    work = work.sort_values(
        [
            "session_key",
            "event_ts",
            "event_timestamp",
            "batch_page_id",
            "batch_ordering_id",
            "batch_event_index",
        ],
        kind="stable",
    )

    if collapse_consecutive:
        previous_route = work.groupby("session_key", sort=False)["route_name"].shift()
        work = work.loc[previous_route.isna() | work["route_name"].ne(previous_route)]

    return resequence_spine(work)


def transition_table(spine: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "from_route",
        "to_route",
        "from_journey",
        "to_journey",
        "transition_count",
        "sessions",
        "identified_sessions",
        "median_seconds",
        "share_from_pct",
    ]
    if spine.empty:
        return pd.DataFrame(columns=columns)

    work = resequence_spine(spine)
    grouped = work.groupby("session_key", sort=False)
    work["to_route"] = grouped["route_name"].shift(-1)
    work["to_journey"] = grouped["journey"].shift(-1)
    work["to_ts"] = grouped["event_ts"].shift(-1)
    work["seconds_to_next"] = (work["to_ts"] - work["event_ts"]).dt.total_seconds()
    work["is_identified"] = work["identity_status"].eq("single_identified_id")
    work["identified_session_key"] = work["session_key"].where(work["is_identified"])
    edges = work.loc[work["to_route"].notna()].rename(
        columns={"route_name": "from_route", "journey": "from_journey"}
    )
    if edges.empty:
        return pd.DataFrame(columns=columns)

    result = (
        edges.groupby(
            ["from_route", "to_route", "from_journey", "to_journey"],
            dropna=False,
            sort=False,
        )
        .agg(
            transition_count=("session_key", "size"),
            sessions=("session_key", "nunique"),
            identified_sessions=("identified_session_key", "nunique"),
            median_seconds=("seconds_to_next", "median"),
        )
        .reset_index()
    )
    totals = result.groupby("from_route")["transition_count"].transform("sum")
    result["share_from_pct"] = (result["transition_count"] / totals * 100).round(2)
    result["median_seconds"] = result["median_seconds"].round(1)
    return result.sort_values(
        ["transition_count", "sessions"], ascending=False, kind="stable"
    ).reset_index(drop=True)


def _mode_or_first(values: pd.Series) -> object:
    modes = values.dropna().mode()
    if not modes.empty:
        return modes.iloc[0]
    non_null = values.dropna()
    return non_null.iloc[0] if not non_null.empty else pd.NA


def session_table(spine: pd.DataFrame, max_steps: int = 25) -> pd.DataFrame:
    columns = [
        "session_key",
        "session_start",
        "session_end",
        "duration_seconds",
        "step_count",
        "start_route",
        "end_route",
        "path",
        "path_truncated",
        "platform",
        "device_category",
        "identity_status",
        "browser_identity_status",
        "identified_key_session",
        "converted",
        "session_key_source",
    ]
    if spine.empty:
        return pd.DataFrame(columns=columns)

    records: list[dict[str, object]] = []
    for session_key, group in resequence_spine(spine).groupby(
        "session_key", sort=False
    ):
        routes = group["route_name"].astype(str).tolist()
        shown_routes = routes[:max_steps]
        path_truncated = len(routes) > max_steps
        path = " > ".join(shown_routes)
        if path_truncated:
            path += " > …"
        session_start = group["event_ts"].iloc[0]
        session_end = group["event_ts"].iloc[-1]
        records.append(
            {
                "session_key": session_key,
                "session_start": session_start,
                "session_end": session_end,
                "duration_seconds": (session_end - session_start).total_seconds(),
                "step_count": len(routes),
                "start_route": routes[0],
                "end_route": routes[-1],
                "path": path,
                "path_truncated": path_truncated,
                "platform": _mode_or_first(group["platform"]),
                "device_category": _mode_or_first(group["device_category"]),
                "identity_status": group["identity_status"].iloc[0],
                "browser_identity_status": group["browser_identity_status"].iloc[0],
                "identified_key_session": group["identified_key_session"].iloc[0],
                "converted": bool(group["outcome"].any()),
                "session_key_source": (
                    "30m_fallback"
                    if group["session_key_source"].eq("30m_fallback").any()
                    else "ga4"
                ),
            }
        )
    return pd.DataFrame.from_records(records, columns=columns)


def path_table(spine: pd.DataFrame, max_steps: int = 25) -> pd.DataFrame:
    sessions = session_table(spine, max_steps=max_steps)
    columns = [
        "path",
        "sessions",
        "share_pct",
        "converted_sessions",
        "conversion_rate_pct",
        "median_steps",
        "median_duration_seconds",
    ]
    if sessions.empty:
        return pd.DataFrame(columns=columns)
    result = (
        sessions.groupby("path", sort=False)
        .agg(
            sessions=("session_key", "nunique"),
            converted_sessions=("converted", "sum"),
            median_steps=("step_count", "median"),
            median_duration_seconds=("duration_seconds", "median"),
        )
        .reset_index()
    )
    result["share_pct"] = (result["sessions"] / len(sessions) * 100).round(2)
    result["conversion_rate_pct"] = (
        result["converted_sessions"] / result["sessions"] * 100
    ).round(2)
    result["median_duration_seconds"] = result["median_duration_seconds"].round(1)
    return result[columns].sort_values(
        "sessions", ascending=False, kind="stable"
    ).reset_index(drop=True)


def dropoff_table(spine: pd.DataFrame) -> pd.DataFrame:
    columns = ["route_name", "sessions_reaching", "sessions_ending", "exit_rate_pct"]
    if spine.empty:
        return pd.DataFrame(columns=columns)
    sessions = session_table(spine)
    reaching = (
        spine.groupby("route_name")["session_key"]
        .nunique()
        .rename("sessions_reaching")
    )
    ending = sessions.groupby("end_route")["session_key"].nunique().rename(
        "sessions_ending"
    )
    result = reaching.to_frame().join(ending, how="left").fillna(0).reset_index()
    result["sessions_ending"] = result["sessions_ending"].astype(int)
    result["exit_rate_pct"] = (
        result["sessions_ending"] / result["sessions_reaching"] * 100
    ).round(2)
    return result.sort_values(
        ["sessions_ending", "exit_rate_pct"], ascending=False, kind="stable"
    ).reset_index(drop=True)


def loop_table(spine: pd.DataFrame) -> pd.DataFrame:
    columns = ["route_name", "sessions_revisiting", "total_revisits"]
    if spine.empty:
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, object]] = []
    for session_key, group in resequence_spine(spine).groupby(
        "session_key", sort=False
    ):
        counts = group["route_name"].value_counts()
        for route_name, count in counts.loc[counts.gt(1)].items():
            rows.append(
                {
                    "session_key": session_key,
                    "route_name": route_name,
                    "revisits": int(count - 1),
                }
            )
    if not rows:
        return pd.DataFrame(columns=columns)
    revisits = pd.DataFrame(rows)
    result = (
        revisits.groupby("route_name", sort=False)
        .agg(
            sessions_revisiting=("session_key", "nunique"),
            total_revisits=("revisits", "sum"),
        )
        .reset_index()
    )
    return result.sort_values(
        ["sessions_revisiting", "total_revisits"], ascending=False, kind="stable"
    ).reset_index(drop=True)


def filter_spine(
    spine: pd.DataFrame,
    platforms: Iterable[str] | None = None,
    identity_statuses: Iterable[str] | None = None,
    journeys: Iterable[str] | None = None,
    start_route: str | None = None,
) -> pd.DataFrame:
    work = spine.copy()
    platform_values = set(platforms or [])
    identity_values = set(identity_statuses or [])
    journey_values = set(journeys or [])

    if platform_values:
        work = work.loc[work["platform"].isin(platform_values)]
    if identity_values:
        work = work.loc[work["identity_status"].isin(identity_values)]
    if journey_values and not work.empty:
        selected_sessions = work.loc[
            work["journey"].isin(journey_values), "session_key"
        ].unique()
        work = work.loc[work["session_key"].isin(selected_sessions)]

    if start_route and not work.empty:
        starts = (
            work.loc[work["route_name"].eq(start_route)]
            .groupby("session_key")["step_index"]
            .min()
            .rename("start_index")
        )
        work = work.join(starts, on="session_key")
        work = work.loc[
            work["start_index"].notna() & work["step_index"].ge(work["start_index"])
        ].drop(columns="start_index")
    return resequence_spine(work)


def focus_event_spine(
    spine: pd.DataFrame,
    event_name: str | None = None,
    mode: str = "full_route",
    context_steps: int = 2,
) -> pd.DataFrame:
    """Keep and optionally trim sessions around a selected event.

    The selected event is always retained. ``full_route`` keeps the complete
    sessions that contain the event, ``leading_to`` keeps everything through
    the first occurrence, ``after`` starts at the first occurrence, and
    ``around`` keeps a small window on either side. This allows every downstream
    path, transition and friction chart to use the same event-centred cohort.
    """
    if spine.empty or not event_name:
        return resequence_spine(spine)
    if mode not in {"full_route", "leading_to", "after", "around"}:
        raise ValueError(f"Unsupported event focus mode: {mode}")
    if context_steps < 0:
        raise ValueError("context_steps must be zero or positive")

    work = resequence_spine(spine)
    first_matches = (
        work.loc[work["event_name"].eq(event_name)]
        .groupby("session_key", sort=False)["step_index"]
        .min()
        .rename("focus_index")
    )
    if first_matches.empty:
        return work.iloc[0:0].copy()

    work = work.join(first_matches, on="session_key", how="inner")
    if mode == "leading_to":
        work = work.loc[work["step_index"].le(work["focus_index"])]
    elif mode == "after":
        work = work.loc[work["step_index"].ge(work["focus_index"])]
    elif mode == "around":
        work = work.loc[
            work["step_index"].between(
                work["focus_index"] - context_steps,
                work["focus_index"] + context_steps,
            )
        ]
    return resequence_spine(work.drop(columns="focus_index"))


def data_quality_table(raw_events: pd.DataFrame, spine: pd.DataFrame) -> pd.DataFrame:
    page_raw = raw_events["event_name"].isin(PAGE_EVENT_NAMES)
    missing_route = raw_events.get("route_path", pd.Series(index=raw_events.index)).isna()
    ambiguous_sessions = (
        spine.loc[spine["identity_status"].eq("multiple_identified_ids"), "session_key"]
        .nunique()
        if not spine.empty
        else 0
    )
    ambiguous_browsers = (
        spine.loc[
            spine["browser_identity_status"].eq("multiple_identified_ids_in_range"),
            "browser_key",
        ].nunique()
        if not spine.empty
        else 0
    )
    fallback_sessions = (
        spine.loc[spine["session_key_source"].eq("30m_fallback"), "session_key"].nunique()
        if not spine.empty
        else 0
    )
    unmapped_pages = (
        spine.loc[
            spine["event_name"].isin(PAGE_EVENT_NAMES) & ~spine["rule_matched"]
        ].shape[0]
        if not spine.empty
        else 0
    )
    records = [
        ("Raw rows returned", len(raw_events), "Selected raw GA4 events"),
        ("Usable path steps", len(spine), "After validation, dedupe and path collapse"),
        (
            "Page/screen rows missing route",
            int((page_raw & missing_route).sum()),
            "Check web page_view and app screen naming coverage",
        ),
        (
            "Rows missing GA session key",
            int(raw_events.get("ga_session_key", pd.Series(index=raw_events.index)).isna().sum()),
            "These rows use the flagged 30-minute fallback",
        ),
        ("Fallback sessions", fallback_sessions, "Not native GA4 sessions"),
        (
            "Sessions with multiple identified IDs",
            ambiguous_sessions,
            "Retained for routes but not assigned to one identified person",
        ),
        (
            "Browser keys with multiple identified IDs",
            ambiguous_browsers,
            "Detects one user_pseudo_id mapping to several IDs across the selected range",
        ),
        (
            "Unmapped page/screen steps",
            unmapped_pages,
            "Still shown using their normalised path/screen name",
        ),
    ]
    return pd.DataFrame(records, columns=["metric", "value", "interpretation"])
