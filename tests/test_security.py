"""Verify the local-server and private-recording publication boundaries."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from act2_weather.app import build_app
from dm.client import Decider


class SecurityTests(unittest.TestCase):
    def test_untrusted_host_and_cross_origin_are_rejected(self):
        client = TestClient(build_app(True), headers={"X-Demo-Request": "1"})
        self.assertEqual(client.get("/", headers={"host": "attacker.example"}).status_code, 400)
        self.assertEqual(client.get("/api/models", headers={"origin": "https://attacker.example"}).status_code, 403)
        self.assertEqual(client.get("/api/models", headers={"origin": "http://testserver"}).status_code, 200)
        self.assertEqual(client.get("/", headers={"origin": "null"}).status_code, 403)
        self.assertEqual(client.get("/api/weather?lat=0&lon=0&city=Porto", headers={"sec-fetch-site": "cross-site"}).status_code, 403)
        self.assertEqual(TestClient(build_app(True)).get("/api/weather?lat=0&lon=0&city=Porto").status_code, 403)

    def test_validation_and_security_headers(self):
        client = TestClient(build_app(True), headers={"X-Demo-Request": "1"})
        self.assertEqual(client.get("/api/weather?lat=91&lon=0&city=Porto").status_code, 422)
        self.assertEqual(client.get("/api/weather?lat=0&lon=181&city=Porto").status_code, 422)
        self.assertEqual(client.get("/api/weather?lat=0&lon=0&city=Porto&model=unexpected").status_code, 400)
        response = client.get("/")
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])

    def test_recordings_do_not_modify_published_fixtures(self):
        with tempfile.TemporaryDirectory() as folder:
            fixtures = Path(folder) / "fixtures"
            fixtures.mkdir()
            published = fixtures / "reviewed.jsonl"
            published.write_text("")
            with patch("dm.client.FIXTURES", fixtures):
                decider = Decider("reviewed")
                decider._record({"key": "test", "error": "private provider error"})
                self.assertIn("test", Decider("reviewed", replay=True)._cache)
            self.assertEqual(published.read_text(), "")
            local = Path(folder) / "data/recordings/reviewed.jsonl"
            self.assertEqual(json.loads(local.read_text())["key"], "test")


if __name__ == "__main__":
    unittest.main()
