from __future__ import annotations

import json
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from web_app import PathFinderHandler, STORE  # noqa: E402


class StoreTests(unittest.TestCase):
    def test_default_analysis_is_event_centred(self):
        meta = STORE.meta()
        result = STORE.analyse(
            {"event": meta["recommended_event"], "context_steps": 3}
        )
        self.assertGreater(result["summary"]["sessions"], 0)
        offsets = [step["offset"] for step in result["steps"]]
        self.assertIn(0, offsets)
        self.assertEqual(offsets, sorted(offsets))
        focus = next(step for step in result["steps"] if step["offset"] == 0)
        self.assertAlmostEqual(focus["routes"][0]["share_focus_pct"], 100.0)

    def test_filters_are_validated_and_can_return_empty_safely(self):
        meta = STORE.meta()
        with self.assertRaises(ValueError):
            STORE.analyse(
                {"event": meta["recommended_event"], "platform": "INVALID"}
            )

    def test_static_interface_has_mobile_viewport_and_no_chart_library(self):
        html = (PROJECT_ROOT / "static" / "index.html").read_text(encoding="utf-8")
        javascript = (PROJECT_ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("viewport-fit=cover", html)
        combined = (html + javascript).lower()
        self.assertNotIn("plotly", combined)
        self.assertNotIn("streamlit", combined)
        self.assertNotIn("https://", combined)


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), PathFinderHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def read_json(self, path: str):
        with urlopen(self.base + path, timeout=5) as response:
            return response.status, json.loads(response.read())

    def post_json(self, path: str, payload: dict):
        request = Request(
            self.base + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())

    def test_health_and_meta(self):
        status, health = self.read_json("/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(health["status"], "ok")
        status, meta = self.read_json("/api/meta")
        self.assertEqual(status, 200)
        self.assertGreater(meta["sessions"], 0)

    def test_analysis_endpoint_returns_compact_mobile_model(self):
        _, meta = self.read_json("/api/meta")
        status, result = self.post_json(
            "/api/analyse",
            {"event": meta["recommended_event"], "context_steps": 2},
        )
        self.assertEqual(status, 200)
        self.assertIn("steps", result)
        self.assertIn("paths", result)
        self.assertLess(len(json.dumps(result)), 100_000)

    def test_invalid_event_returns_explained_400(self):
        with self.assertRaises(HTTPError) as caught:
            self.post_json("/api/analyse", {"event": "not_a_real_event"})
        self.assertEqual(caught.exception.code, 400)
        body = json.loads(caught.exception.read())
        self.assertIn("not available", body["error"])


if __name__ == "__main__":
    unittest.main()
