from __future__ import annotations

import os
import re
from dataclasses import dataclass


DEFAULT_EVENT_NAMES = (
    "page_view",
    "screen_view",
    "pageView",
    "form_event_v2",
    "internal_click",
    "component_interaction",
    "trade_preview",
    "trade_placed",
    "account_opened",
    "add_account",
    "site_search",
    "login",
    "login_complete",
)

PAGE_EVENT_NAMES = frozenset({"page_view", "screen_view", "pageView"})

_PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{3,62}$")
_DATASET_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,1023}$")
_TABLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_*]{0,1023}$")


@dataclass(frozen=True)
class AppConfig:
    project_id: str = "ii-bigquery-local"
    dataset_id: str = "analytics_225781377"
    table_pattern: str = "events_*"
    location: str = "US"
    maximum_bytes_billed: int = 20_000_000_000

    @classmethod
    def from_env(cls) -> "AppConfig":
        return cls(
            project_id=os.getenv("BQ_PROJECT_ID", cls.project_id),
            dataset_id=os.getenv("BQ_DATASET_ID", cls.dataset_id),
            table_pattern=os.getenv("BQ_TABLE_PATTERN", cls.table_pattern),
            location=os.getenv("BQ_LOCATION", cls.location),
            maximum_bytes_billed=int(
                os.getenv("MAX_BYTES_BILLED", str(cls.maximum_bytes_billed))
            ),
        ).validated()

    def validated(self) -> "AppConfig":
        if not _PROJECT_RE.fullmatch(self.project_id):
            raise ValueError(f"Invalid BigQuery project id: {self.project_id!r}")
        if not _DATASET_RE.fullmatch(self.dataset_id):
            raise ValueError(f"Invalid BigQuery dataset id: {self.dataset_id!r}")
        if not _TABLE_RE.fullmatch(self.table_pattern) or "*" not in self.table_pattern:
            raise ValueError(
                "The table pattern must be a valid wildcard table name, for example events_*"
            )
        if self.maximum_bytes_billed <= 0:
            raise ValueError("maximum_bytes_billed must be positive")
        return self

    @property
    def source_table(self) -> str:
        self.validated()
        return f"{self.project_id}.{self.dataset_id}.{self.table_pattern}"

