from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Sequence

import pandas as pd

from .config import AppConfig


SQL_PATH = Path(__file__).resolve().parents[1] / "sql" / "pathfinder_raw_ga4.sql"


@dataclass(frozen=True)
class QueryStats:
    rows: int
    total_bytes_processed: int
    total_bytes_billed: int
    cache_hit: bool


def _bigquery_module():
    try:
        from google.cloud import bigquery
    except ImportError as exc:  # pragma: no cover - depends on local environment
        raise RuntimeError(
            "BigQuery support is not installed. Run: pip install -r requirements.txt"
        ) from exc
    return bigquery


def build_sql(config: AppConfig) -> str:
    template = SQL_PATH.read_text(encoding="utf-8")
    return template.replace("{{SOURCE_TABLE}}", config.source_table)


def _query_parameters(
    start_date: date,
    end_date: date,
    event_names: Sequence[str],
    analytics_storage_values: Sequence[str],
):
    bigquery = _bigquery_module()
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")
    clean_events = sorted({name.strip() for name in event_names if name.strip()})
    if not clean_events:
        raise ValueError("At least one event name is required")
    clean_consent = sorted({value.strip() for value in analytics_storage_values if value.strip()})
    if not clean_consent:
        raise ValueError("At least one analytics_storage value is required")
    return [
        bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
        bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        bigquery.ArrayQueryParameter("event_names", "STRING", clean_events),
        bigquery.ArrayQueryParameter(
            "analytics_storage_values", "STRING", clean_consent
        ),
    ]


def _client(config: AppConfig):
    bigquery = _bigquery_module()
    return bigquery.Client(project=config.project_id, location=config.location)


def estimate_query_bytes(
    config: AppConfig,
    start_date: date,
    end_date: date,
    event_names: Sequence[str],
    analytics_storage_values: Sequence[str],
) -> int:
    bigquery = _bigquery_module()
    job_config = bigquery.QueryJobConfig(
        query_parameters=_query_parameters(
            start_date, end_date, event_names, analytics_storage_values
        ),
        dry_run=True,
        use_query_cache=False,
    )
    job = _client(config).query(
        build_sql(config), job_config=job_config, location=config.location
    )
    return int(job.total_bytes_processed or 0)


def query_raw_events(
    config: AppConfig,
    start_date: date,
    end_date: date,
    event_names: Sequence[str],
    analytics_storage_values: Sequence[str] = ("Yes",),
) -> tuple[pd.DataFrame, QueryStats]:
    bigquery = _bigquery_module()
    job_config = bigquery.QueryJobConfig(
        query_parameters=_query_parameters(
            start_date, end_date, event_names, analytics_storage_values
        ),
        use_query_cache=True,
        maximum_bytes_billed=config.maximum_bytes_billed,
    )
    job = _client(config).query(
        build_sql(config), job_config=job_config, location=config.location
    )
    frame = job.result().to_dataframe(create_bqstorage_client=False)
    stats = QueryStats(
        rows=len(frame),
        total_bytes_processed=int(job.total_bytes_processed or 0),
        total_bytes_billed=int(job.total_bytes_billed or 0),
        cache_hit=bool(job.cache_hit),
    )
    return frame, stats

