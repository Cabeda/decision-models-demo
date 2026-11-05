# Decision models, live

A developer talk with a **30-minute hard limit**: 25 minutes of content and five minutes for questions and delays. The terminal is the stage. Use the [presenter guide](PRESENTER_GUIDE.md#5-the-30-minute-stage-plan) for the timed script; this README also includes the optional examples.

A decision model evaluates a state against typed questions and returns choices, scores, or yes/no probabilities. Application code uses those values to route work or request review. The local models used here do not generate text in this decision path; their inference mechanisms differ. Jev from TypeSafe defined the API. [Ollaya](https://ollaya.dev) serves the same wire API on open models (`laya`, `kev`), so every script here uses the official `typesafe-sdk` and points it at a local server. Ollaya is independent and not affiliated with TypeSafe, and its models are not Jev. Typed answers and confidence do not establish correctness or calibration on your task: measure them on your own data.

Vocabulary is in [GLOSSARY.md](GLOSSARY.md).

## Public demo scope

The support tickets are fictional. The published replay files for Acts 1, 2 and 4 contain model answers for demo inputs. Real NHTSA complaint narratives, Act 3 recordings, downloaded data, local databases and new live recordings are excluded from publication. See [SECURITY.md](SECURITY.md) for data handling and remaining limitations.

For an offline rehearsal, install [uv](https://docs.astral.sh/uv/) and Python 3.12, then run:

```bash
uv sync --locked
uv run act1_primitives/02_primitives.py --replay
uv run act4_support/route.py --all --replay
uv run act4_support/eval.py --replay
```

These commands need no model server or model downloads. Replay timings are historical measurements.

## Setup

Live inference additionally requires [Ollaya](https://ollaya.dev) installed separately.


```bash
scripts/setup.sh      # uv sync + pull the five models (~13 GB)
ollaya serve          # listens on :11435
scripts/warmup.sh     # 5 min before the talk; kev:4b needs ~20 s to load
```

The Python demos support recorded answers from `fixtures/`. The raw HTTP shell script always calls the server. Outside replay, the wrapper normally returns cached answers before making new calls and writes new responses to ignored `data/recordings/`; live weather explicitly bypasses both reading and writing this cache. Displayed replay timings belong to the original recordings. Use the presenter guide's recorded command sequence for the main talk.

Ollaya needs `NO_PROXY=localhost,127.0.0.1` on a Mac with a system proxy. `dm/client.py` sets it.

## Run of show

| Time | Main path | What the audience sees |
|---|---|---|
| 0–3 min | The developer question | Why use a decision model when an LLM supports structured output? |
| 3–8 min | Act 1: primitives | One SDK example: queue, urgency, and refund probability. |
| 8–11 min | How the pieces fit | Input → model → scores → application policy. |
| 11–18 min | Act 4: support routing | A clear route, an escalation, and a confident mistake. |
| 18–22 min | Evidence | 26/40 automatic routes, 22/26 correct; limitations of the 40-ticket evaluation. |
| 22–25 min | Takeaways | Define the answer space, keep policy in code, and measure the trade-offs. |
| 25–30 min | Reserved | Questions and recovery time. |

Weather, NHTSA/DuckDB, raw HTTP, and the full failure/evaluation tables are backup material. The complete four-act version originally totalled 45 minutes. Do not try to fit it all into this slot. The presenter guide documents the remaining cache, weather, and safety-policy limitations and gives a recorded command sequence to use on stage.

### Act 1: primitives (`act1_primitives/`)

```bash
bash act1_primitives/01_raw_http.sh                      # the whole API in one request
uv run act1_primitives/02_primitives.py                  # same ticket, three question types
uv run act1_primitives/03_where_it_breaks.py             # then break it
```

Say: answers are probabilities, and confidence is a number you can gate on. Then show the failures in `03`:
- Checkpoints disagree on the same Portuguese ticket. `laya:multilingual` says technical at confidence 0.25, the others say billing. The low confidence is the usable signal.
- `laya:en` has a 512-token window and refuses a long state with a 422 instead of guessing. `kev` has 8,192.
- Asked "12 is less than 10", the model is right about as often as a coin. Bucket numbers in code first.

Try `--model kev:0.8b` on `02`.

### Act 2: weather app (`act2_weather/app.py`, backup)

```bash
uv run act2_weather/app.py            # live, foreground; Ctrl+C stops the server
uv run act2_weather/app.py --replay   # offline, sample cities from fixtures
```

Open http://127.0.0.1:8000 and keep the command running in your terminal. The startup message shows the URL and mode; Ctrl+C in that terminal releases the port. Live mode needs Ollaya running (`ollaya serve` in a separate terminal).

The page starts with Lisbon. **Get my location** requests a new browser position each time; **Refresh** requests it again when “my location” is selected. Live weather and model decisions are always fetched fresh and are not saved to the replay files. The browser has 30 seconds to acquire a position. Where the Permissions API is available, the page distinguishes pending permission from position lookup and allows up to 60 seconds for permission. Permission denial, unavailable location providers, and lookup timeouts have separate messages. A browser that never calls either callback is stopped by a fallback timer.

Replay mode is labelled on the page, starts with a recorded city, and disables location. Restart without `--replay` to use your current location. If an embedded browser cannot provide a position, open the same URL in a browser with location support or choose a sample city.

After editing the app, restart its foreground command with Ctrl+C followed by `uv run act2_weather/app.py`, then reload the page. The server does not automatically reload source changes.

Code fetches Open-Meteo and turns numbers into words ("cold", "a stiff breeze", "heavy rain"). Only that sentence goes to the model, never coordinates. The model answers a Noul (umbrella), a Choice (walk, bike or bus) and a Score (how pleasant). Switch the dropdown between `laya` and `kev`: same code, only the model string changes, and the confidence is visibly different.

Weather regression checks: `uv run python -m unittest discover -s tests -v`. The browser-script check also runs when Node is installed; the weather server itself requires only Python.

### Act 3: NHTSA complaints into DuckDB (`act3_nhtsa/`, backup)

```bash
uv run act3_nhtsa/label.py --model kev:0.8b --limit 20 --workers 1   # live, a few rows on stage
uv run act3_nhtsa/label.py --model kev:4b              # local data only
uv run act3_nhtsa/report.py                              # SQL: agreement with ground truth
```

The recorded latencies come from a run with four parallel workers on a CPU and include contention. Do not divide them by the worker count to infer single-request latency. Historical wall-clock throughput was roughly 0.4 s per row for `laya`, 0.8 s for `kev:0.8b` and 3 s for `kev:4b`. Use `--workers 1` to measure sequential per-call latency.

Public data: US vehicle complaints for VW Group brands. Each row gets a component (Choice), a safety-critical flag (Noul) and a severity (Score), written to a DuckDB `labels` table. The SQL in `report.sql` compares labels to the dataset's own fields.

Component agreement over 300 rows: `kev:4b` 52.7%, `kev:0.8b` 46.3%, `laya:typed-decisions` 38.0%. That is mediocre, and the slide says so: ten classes, noisy consumer-entered ground truth. What matters is that agreement rises with confidence, so a Gate gives a cleaner slice and a "needs human review" bucket. The safety-flag comparison is weak because the truth is only CRASH, FIRE and INJURED.

Act 3 is an optional local-data exercise. Run `uv run act3_nhtsa/fetch_data.py` (100+ MB) before labelling. Raw public complaints may contain personal data; the CSV and derived recordings are deliberately excluded from this public repository. A new download may differ from the historical 300-row sample, so the recorded agreement figures above are historical and must be remeasured. Act 3 replay requires matching recordings retained locally.

### Act 4: support routing (`act4_support/`)

```bash
uv run act4_support/route.py "my car won't charge and the app says error 42"   # type one live
DM_REPLAY=1 uv run act4_support/route.py --all --replay
DM_REPLAY=1 uv run act4_support/eval.py --replay                               # the evidence and disclosed limitations
```

A fictional connected-car company, 40 hand-written tickets in English and Portuguese: clear, ambiguous, multi-intent, safety and prompt-injection cases. `laya` answers first and is fast. A middle-confidence ticket goes to `kev:4b`. If that is still unsure it goes to a human. Tickets identified by the model as safety-related use stricter gates. This detector can miss real safety cases: the recorded `t24` bypasses escalation. This is an educational prototype, unsuitable for operating a real safety workflow.

`eval.py` prints the gate sweep, a shuffle-test skip notice (existing cache keys ignore option order), the injection results and every safety ticket. Read the real numbers off the screen, not this README.

Findings worth telling:
- `kev:4b` is much more accurate than `laya` (92.5% against 60% with no gate), but its confidence scale is lower, so each model needs its own gate.
- The wrong auto-routes all come from `laya`, which is confidently wrong on ambiguous and multi-intent tickets. Its docs say the raw checkpoints are over-confident and should be recalibrated on your own labelled data.
- The "needs a human" yes/no question was nearly useless on `kev` (about 0.5 for everything). A gate is only as good as the question it reads.
- The thresholds were tuned on the same 40 tickets, so the headline accuracy is optimistic. Say so.
- Renaming the fictional brand changed a few answers. Small input changes move decisions.

## Wrap-up: where else

First pilots: IT service-desk triage, and CI or merge-request gating (a cheap yes/no on "does this diff touch IAM" before the expensive review). Then warranty-complaint triage (Act 3 on internal data) and citation checks for internal knowledge assistants. Any use for consequential decisions needs a separate domain and legal review.

## Layout

```
dm/                shared code: Decider (SDK + record/replay), terminal output
act1_primitives/   curl, SDK primitives, failure cases
act2_weather/      single-file FastAPI app
act3_nhtsa/        fetch, label into DuckDB, SQL report, local-only 300-row sample
act4_support/      tickets, cascade, evaluation
fixtures/          reviewed model answers for Acts 1, 2 and 4
scripts/           setup.sh, warmup.sh
```

## Troubleshooting

- `502 status code (no body)` or hanging calls: a system proxy is catching localhost. Set `NO_PROXY=localhost,127.0.0.1`.
- `replay miss`: that exact state and question set was never recorded. Run it once live, or avoid typing new text in replay.
- `ollaya` prints a client/server version warning: run `ollaya update`.
- There is no GPU path on this Mac (`ollaya ps` shows `cpu`). Measured on a quiet machine: `laya` about 70 ms, `kev:0.8b` about 0.4 s, `kev:4b` about 2 s for a few questions. Under load these multiply, which is why warm-up matters.
