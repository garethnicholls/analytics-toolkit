from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pathfinder.config import AppConfig  # noqa: E402
from pathfinder.query import build_sql  # noqa: E402


class ConfigAndQueryTests(unittest.TestCase):
    def test_default_source_is_raw_ii_ga4_export(self):
        config = AppConfig().validated()
        self.assertEqual(
            config.source_table,
            "ii-bigquery-local.analytics_225781377.events_*",
        )
        sql = build_sql(config)
        self.assertIn(
            "`ii-bigquery-local.analytics_225781377.events_*`",
            sql,
        )
        self.assertNotIn("{{SOURCE_TABLE}}", sql)

    def test_invalid_table_identifier_is_rejected(self):
        with self.assertRaises(ValueError):
            AppConfig(table_pattern="events_*`; DROP TABLE x; --").validated()

    def test_query_has_partition_pruning_and_no_component_value(self):
        sql = build_sql(AppConfig())
        self.assertIn("_TABLE_SUFFIX BETWEEN", sql)
        self.assertIn("@start_date", sql)
        self.assertIn("@end_date", sql)
        executable_sql = "\n".join(
            line for line in sql.splitlines() if not line.lstrip().startswith("--")
        )
        self.assertNotIn("component_value", executable_sql)
        self.assertIn("SHA256(user_pseudo_id)", executable_sql)


if __name__ == "__main__":
    unittest.main()

