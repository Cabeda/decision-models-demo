"""typesafe-sdk pointed at Ollaya, with record/replay for offline demos.

The SDK is the Jev client. Ollaya implements the same wire API on open
models, so the only things that change are the base URL and the model name.

Live calls are recorded to data/recordings/<scope>.jsonl by default. Set cache=False
for fresh live calls that neither read nor write recordings. In replay mode
(--replay or DM_REPLAY=1) nothing touches the network: a call that was never
recorded raises, so a gap shows up in rehearsal and not on stage.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

# Keep requests to localhost off any system proxy (see the Ollaya docs).
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")

BASE_URL = os.environ.get("TYPESAFE_BASE_URL", "http://localhost:11435")
API_KEY = os.environ.get("TYPESAFE_API_KEY", "local")
DEFAULT_MODEL = os.environ.get("TYPESAFE_DEFAULT_MODEL", "laya:en")
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


class DecisionError(Exception):
    """The server refused the request (for example STATE_TRUNCATED)."""


@dataclass
class Decision:
    """One response: plain dicts, identical for live and replayed calls."""

    model: str
    answers: dict[str, dict[str, Any]]
    latency_ms: float
    input_tokens: int = 0
    cached: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def __getitem__(self, name: str) -> dict[str, Any]:
        return self.answers[name]


def certainty(answer: Mapping[str, Any]) -> float:
    """Confidence in 0..1 for any primitive.

    Choice and Score carry their own `confidence`. A Noul is a single
    probability, so its certainty is its distance from 0.5, rescaled.
    """
    if "confidence" in answer:
        return float(answer["confidence"])
    return abs(float(answer["noul"]) - 0.5) * 2


def _key(model: str, state: Any, questions: Mapping[str, Any]) -> str:
    payload = json.dumps(
        {"m": model, "s": state, "q": {k: v.model_dump(mode="json") for k, v in questions.items()}},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:20]


class Decider:
    """Ask typed questions about a state. `scope` names the fixtures file."""

    def __init__(self, scope: str, model: str | None = None, replay: bool | None = None,
                 *, cache: bool = True):
        self.scope = scope
        self.model = model or DEFAULT_MODEL
        self.replay = replay if replay is not None else os.environ.get("DM_REPLAY") == "1"
        if self.replay and not cache:
            raise ValueError("Replay requires the fixture cache")
        self.cache = cache
        self._path = FIXTURES / f"{scope}.jsonl"
        self._record_path = FIXTURES.parent / "data" / "recordings" / f"{scope}.jsonl"
        self._cache: dict[str, dict[str, Any]] = {}
        if self.cache:
            for path in (self._path, self._record_path):
                if path.exists():
                    for line in path.read_text().splitlines():
                        rec = json.loads(line)
                        self._cache[rec["key"]] = rec
        self._client = None

    def _sdk(self):
        if self._client is None:
            import typesafe_sdk as ts

            # Default timeout is 10 s; a cold model load can outlive it.
            self._client = ts.TypeSafeClient(base_url=BASE_URL, api_key=API_KEY, timeout=60.0)
        return self._client

    def decide(self, state: str, questions: Mapping[str, Any], model: str | None = None) -> Decision:
        model = model or self.model
        key = _key(model, state, questions)
        if self.cache and key in self._cache:
            rec = self._cache[key]
            if "error" in rec:
                raise DecisionError(rec["error"])
            return Decision(rec["model"], rec["answers"], rec["latency_ms"], rec["input_tokens"], cached=True)
        if self.replay:
            raise LookupError(
                f"replay miss in fixtures/{self.scope}.jsonl for model={model!r}, "
                f"state={state[:60]!r}. Run once without --replay to record it."
            )
        import typesafe_sdk as ts

        start = time.perf_counter()
        try:
            resp = self._sdk().system_one(state, questions, model=model)
        except ts.TypeSafeUnprocessableEntityError as exc:
            # A 422 is a real answer worth showing (e.g. STATE_TRUNCATED), so record it too.
            self._record({"key": key, "requested_model": model, "error": str(exc)})
            raise DecisionError(str(exc)) from exc
        latency = (time.perf_counter() - start) * 1000
        answers = {name: a.model_dump(mode="json") for name, a in resp.answers.items()}
        rec = {
            "key": key,
            "model": resp.model,
            "requested_model": model,
            "answers": answers,
            "latency_ms": round(latency, 1),
            "input_tokens": resp.usage.input_tokens,
        }
        self._record(rec)
        return Decision(resp.model, answers, rec["latency_ms"], rec["input_tokens"])

    def _record(self, rec: dict[str, Any]) -> None:
        if not self.cache:
            return
        self._cache[rec["key"]] = rec
        self._record_path.parent.mkdir(parents=True, exist_ok=True)
        with self._record_path.open("a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
