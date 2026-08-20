from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from .transform import resequence_spine, session_table


def _focus_rows(spine: pd.DataFrame, event_name: str) -> pd.DataFrame:
    """Return complete matching sessions with the first focus position attached."""
    if spine.empty or not event_name:
        return spine.iloc[0:0].copy()
    work = resequence_spine(spine)
    focus_indices = (
        work.loc[work["event_name"].eq(event_name)]
        .groupby("session_key", sort=False)["step_index"]
        .min()
        .rename("focus_index")
    )
    if focus_indices.empty:
        return work.iloc[0:0].copy()
    return work.join(focus_indices, on="session_key", how="inner")


def event_neighbourhood(
    spine: pd.DataFrame,
    event_name: str,
    *,
    before_steps: int = 3,
    after_steps: int = 3,
    max_routes_per_step: int = 5,
) -> pd.DataFrame:
    """Aggregate the routes at each position around a selected event.

    Percentages use every session containing the selected event as the
    denominator. That makes the result directly interpretable on a phone: a
    route at ``-1`` with 42% means 42% of focused sessions recorded that route
    immediately before the event.
    """
    if before_steps < 0 or after_steps < 0:
        raise ValueError("before_steps and after_steps must be zero or positive")
    if max_routes_per_step <= 0:
        raise ValueError("max_routes_per_step must be positive")

    work = _focus_rows(spine, event_name)
    columns = [
        "offset",
        "route_name",
        "sessions",
        "share_focus_pct",
        "share_position_pct",
        "position_coverage_sessions",
        "position_coverage_pct",
    ]
    if work.empty:
        return pd.DataFrame(columns=columns)

    focus_sessions = work["session_key"].nunique()
    work["offset"] = work["step_index"] - work["focus_index"]
    work = work.loc[work["offset"].between(-before_steps, after_steps)].copy()

    # One route per session/offset is expected after path sequencing. Keep first
    # defensively so duplicate events cannot inflate the mobile percentages.
    work = work.drop_duplicates(["session_key", "offset"], keep="first")
    counts = (
        work.groupby(["offset", "route_name"], sort=False, dropna=False)[
            "session_key"
        ]
        .nunique()
        .rename("sessions")
        .reset_index()
    )
    coverage = (
        work.groupby("offset", sort=False)["session_key"]
        .nunique()
        .rename("position_coverage_sessions")
    )
    counts = counts.join(coverage, on="offset")
    counts["share_focus_pct"] = (counts["sessions"] / focus_sessions * 100).round(1)
    counts["share_position_pct"] = (
        counts["sessions"] / counts["position_coverage_sessions"] * 100
    ).round(1)
    counts["position_coverage_pct"] = (
        counts["position_coverage_sessions"] / focus_sessions * 100
    ).round(1)
    counts = counts.sort_values(
        ["offset", "sessions", "route_name"],
        ascending=[True, False, True],
        kind="stable",
    )
    counts = counts.groupby("offset", sort=False).head(max_routes_per_step)
    return counts[columns].reset_index(drop=True)


def event_window_paths(
    spine: pd.DataFrame,
    event_name: str,
    *,
    before_steps: int = 3,
    after_steps: int = 3,
    limit: int = 8,
) -> pd.DataFrame:
    """Return common route windows surrounding the first selected event."""
    if before_steps < 0 or after_steps < 0:
        raise ValueError("before_steps and after_steps must be zero or positive")
    if limit <= 0:
        raise ValueError("limit must be positive")
    work = _focus_rows(spine, event_name)
    columns = ["routes", "sessions", "share_pct", "outcome_rate_pct"]
    if work.empty:
        return pd.DataFrame(columns=columns)

    work["offset"] = work["step_index"] - work["focus_index"]
    window = work.loc[work["offset"].between(-before_steps, after_steps)].copy()
    routes = (
        window.sort_values(["session_key", "step_index"], kind="stable")
        .groupby("session_key", sort=False)["route_name"]
        .agg(lambda values: tuple(values.astype(str)))
        .rename("routes_key")
    )
    outcome_after = (
        work.assign(
            _outcome_after=work["outcome"] & work["step_index"].ge(work["focus_index"])
        )
        .groupby("session_key", sort=False)["_outcome_after"]
        .any()
        .rename("outcome_after")
    )
    paths = pd.concat([routes, outcome_after], axis=1).reset_index()
    total_sessions = len(paths)
    result = (
        paths.groupby("routes_key", sort=False)
        .agg(
            sessions=("session_key", "nunique"),
            outcome_sessions=("outcome_after", "sum"),
        )
        .reset_index()
    )
    result["share_pct"] = (result["sessions"] / total_sessions * 100).round(1)
    result["outcome_rate_pct"] = (
        result["outcome_sessions"] / result["sessions"] * 100
    ).round(1)
    result["routes"] = result["routes_key"].map(list)
    return (
        result.sort_values("sessions", ascending=False, kind="stable")
        .head(limit)[columns]
        .reset_index(drop=True)
    )


def event_focus_summary(spine: pd.DataFrame, event_name: str) -> dict[str, object]:
    """Return concise, decision-ready metrics for a selected event."""
    work = _focus_rows(spine, event_name)
    if work.empty:
        return {
            "sessions": 0,
            "has_previous_sessions": 0,
            "has_previous_pct": 0.0,
            "continued_sessions": 0,
            "continued_pct": 0.0,
            "stopped_sessions": 0,
            "stopped_pct": 0.0,
            "outcome_after_sessions": 0,
            "outcome_after_pct": 0.0,
        }

    flags = work.assign(
        has_previous=work["step_index"].lt(work["focus_index"]),
        continued=work["step_index"].gt(work["focus_index"]),
        outcome_after=work["outcome"] & work["step_index"].ge(work["focus_index"]),
    )
    sessions = flags.groupby("session_key", sort=False).agg(
        has_previous=("has_previous", "any"),
        continued=("continued", "any"),
        outcome_after=("outcome_after", "any"),
    )
    total = len(sessions)
    previous = int(sessions["has_previous"].sum())
    continued = int(sessions["continued"].sum())
    stopped = total - continued
    outcome_after = int(sessions["outcome_after"].sum())
    return {
        "sessions": total,
        "has_previous_sessions": previous,
        "has_previous_pct": round(previous / total * 100, 1),
        "continued_sessions": continued,
        "continued_pct": round(continued / total * 100, 1),
        "stopped_sessions": stopped,
        "stopped_pct": round(stopped / total * 100, 1),
        "outcome_after_sessions": outcome_after,
        "outcome_after_pct": round(outcome_after / total * 100, 1),
    }


def event_catalog(spine: pd.DataFrame) -> list[dict[str, object]]:
    """Return available focus events ordered by distinct session reach."""
    if spine.empty:
        return []
    counts = (
        spine.groupby("event_name", dropna=False)["session_key"]
        .nunique()
        .rename("sessions")
        .reset_index()
        .sort_values(["sessions", "event_name"], ascending=[False, True])
    )
    return [
        {"name": str(row.event_name), "sessions": int(row.sessions)}
        for row in counts.itertuples(index=False)
    ]


def recommended_event(
    events: Iterable[dict[str, object]],
    priorities: Iterable[str] = (
        "trade_preview",
        "form_event_v2",
        "login_complete",
        "trade_placed",
        "account_opened",
        "component_interaction",
        "internal_click",
    ),
) -> str | None:
    available = {str(item["name"]) for item in events}
    for event_name in priorities:
        if event_name in available:
            return event_name
    for item in events:
        name = str(item["name"])
        if name not in {"page_view", "screen_view", "pageView"}:
            return name
    return str(next(iter(events))["name"]) if events else None
