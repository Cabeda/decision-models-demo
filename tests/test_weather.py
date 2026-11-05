"""Weather regressions: fresh live decisions, offline replay, useful failures."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import httpx
from typesafe_sdk import SystemOneResponse

from act2_weather import app as weather
from dm.client import FIXTURES


class WeatherTests(unittest.TestCase):
    def setUp(self):
        self.raw = weather.load_cache()["Porto"]
        summary = weather.summarise(self.raw["current"], self.raw["hourly"])
        recorded = weather.Decider("act2", replay=True).decide(
            summary, weather.QUESTIONS, model="laya:en"
        )
        self.response = SystemOneResponse.model_validate_json(json.dumps({
            "model": "laya:en",
            "answers": recorded.answers,
            "usage": {"input_tokens": 100, "output_tokens": 0},
        }))

    def test_repeated_live_location_calls_weather_and_model_without_recording(self):
        # A fixture with this exact state already exists. A fresh request must
        # still reach the model on BOTH calls and leave the recordings intact.
        paths = [FIXTURES / "act2.jsonl", weather.OPENMETEO_CACHE]
        before = [p.read_bytes() for p in paths]
        with patch.object(weather, "fetch_openmeteo", return_value=self.raw) as fetch:
            with patch.object(weather.Decider, "_sdk") as sdk:
                sdk.return_value.system_one.return_value = self.response
                client = TestClient(weather.build_app(replay=False), headers={"X-Demo-Request": "1"})
                for _ in range(2):
                    result = client.get("/api/weather", params={
                        "lat": 41.15, "lon": -8.61, "model": "laya:en",
                    })
                    self.assertEqual(result.status_code, 200, result.text)
                    self.assertFalse(result.json()["cached"])
                    self.assertEqual(result.headers["cache-control"], "no-store")
                self.assertEqual(fetch.call_count, 2)
                self.assertEqual(sdk.return_value.system_one.call_count, 2)
        self.assertEqual([p.read_bytes() for p in paths], before)

    def test_weather_provider_response_is_parsed_and_http_errors_are_checked(self):
        request = httpx.Request("GET", weather.OPENMETEO_URL)
        success = httpx.Response(200, json=self.raw, request=request)
        with patch.object(weather.httpx, "get", return_value=success):
            self.assertEqual(weather.fetch_openmeteo(41.15, -8.61), self.raw)
        failure = httpx.Response(503, request=request)
        with patch.object(weather.httpx, "get", return_value=failure):
            with self.assertRaises(httpx.HTTPStatusError):
                weather.fetch_openmeteo(41.15, -8.61)

    def test_live_sample_city_does_not_overwrite_replay_fixtures(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder) / "weather.json"
            cache.write_text(json.dumps({"Porto": self.raw}))
            before = cache.read_bytes()
            with patch.object(weather, "OPENMETEO_CACHE", cache):
                with patch.object(weather, "fetch_openmeteo", return_value=self.raw):
                    with patch.object(weather.Decider, "_sdk") as sdk:
                        sdk.return_value.system_one.return_value = self.response
                        result = TestClient(weather.build_app(False), headers={"X-Demo-Request": "1"}).get(
                            "/api/weather", params={
                                "lat": 41.15, "lon": -8.61,
                                "city": "Porto", "model": "laya:en",
                            },
                        )
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(cache.read_bytes(), before)

    def test_replay_cities_never_call_weather_or_model(self):
        with patch.object(weather, "fetch_openmeteo", side_effect=AssertionError("weather network")):
            with patch.object(weather.Decider, "_sdk", side_effect=AssertionError("model network")):
                client = TestClient(weather.build_app(True), headers={"X-Demo-Request": "1"})
                for city, (lat, lon) in weather.CITIES.items():
                    for model in weather.MODEL_FALLBACK:
                        with self.subTest(city=city, model=model):
                            result = client.get("/api/weather", params={
                                "lat": lat, "lon": lon, "city": city, "model": model,
                            })
                            self.assertEqual(result.status_code, 200, result.text)
                            self.assertTrue(result.json()["cached"])

    def test_location_in_replay_explains_how_to_run_live(self):
        with patch.object(weather, "fetch_openmeteo", side_effect=AssertionError("weather network")):
            result = TestClient(weather.build_app(True), headers={"X-Demo-Request": "1"}).get(
                "/api/weather", params={"lat": 41.15, "lon": -8.61},
            )
        self.assertEqual(result.status_code, 400)
        self.assertIn("without --replay", result.json()["error"])

    def test_weather_failure_is_json_and_not_cacheable(self):
        with patch.object(weather, "fetch_openmeteo", side_effect=httpx.ConnectError("offline")):
            result = TestClient(weather.build_app(False), headers={"X-Demo-Request": "1"}).get(
                "/api/weather", params={"lat": 41.15, "lon": -8.61},
            )
        self.assertEqual(result.status_code, 502)
        self.assertIn("weather", result.json()["error"].lower())
        self.assertEqual(result.headers["cache-control"], "no-store")

    def test_replay_page_marks_mode_and_defaults_to_recorded_city(self):
        result = TestClient(weather.build_app(True), headers={"X-Demo-Request": "1"}).get("/")
        self.assertEqual(result.status_code, 200)
        self.assertIn("const REPLAY=true", result.text)
        self.assertIn("<option selected>Lisbon</option>", result.text)
        self.assertIn('id=locate', result.text)

    @unittest.skipUnless(shutil.which("node"), "Node is optional for the client-script regression check")
    def test_location_refresh_timeout_and_replay_in_client_script(self):
        response = TestClient(weather.build_app(True), headers={"X-Demo-Request": "1"}).get("/api/weather", params={
            "lat": 41.15, "lon": -8.61, "city": "Porto", "model": "laya:en",
        }).json()
        result = subprocess.run(
            [shutil.which("node"), str(Path(__file__).with_name("weather_ui.cjs"))],
            input=json.dumps({"html": weather.PAGE, "response": response}),
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
