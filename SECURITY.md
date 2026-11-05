# Security and data handling

This is a local educational demo, not a production service or a vehicle-safety system.

## Publication boundary

Publish only the files selected by `scripts/export_public.py`. This excludes Git
history, the real NHTSA complaint sample, Act 3 recordings, virtual environments,
downloaded datasets, databases, credentials and workstation configuration.
`git add .` respects the corresponding ignore rules, but `git add -f` bypasses them.

The support tickets are hand-written fictional examples. Published fixtures for
Acts 1, 2 and 4 contain model answers, model names, input-token counts, timings
and hashed request keys. They do not contain customer records. Weather fixtures
use the four public sample cities; they are historical forecasts, not live data.

New live model responses are written under ignored `data/recordings/`, rather
than to published fixtures. These recordings are loaded locally on subsequent live or replay runs, but are
excluded from the public export. Errors returned by a remote model service may contain request details:
treat local recordings as private. Review any deliberately promoted fixture.
Never enter real customer, employee, vehicle or company-confidential data.

Act 3 downloads public complaints that may contain contact details, vehicle
identifiers, incident descriptions and health information. Public availability
does not make those records anonymous. Keep the CSV, database and model answers
local. Existing public Act 3 results in the documentation are historical, not
reproducible from the public package alone.

## Runtime boundary

The weather launcher binds to `127.0.0.1`, disables request access logs, rejects
untrusted hostnames and cross-origin requests, requires a custom header for inference, restricts model selection and
escapes response labels before rendering HTML. It has no authentication or
per-user quotas. Do not expose it through a tunnel, public bind or reverse proxy.
Inline scripts and styles are allowed by its content security policy because
the demo is a single HTML file. Do not insert unescaped dynamic HTML.

Live weather sends rounded coordinates to Open-Meteo. Only a weather summary
goes to the model. The application does not save live weather or coordinates.
Selecting “Get my location” requests browser permission; use sample cities for a
presentation if you do not want to disclose your location to the weather provider.

Model requests go to `TYPESAFE_BASE_URL` (localhost by default). An override can
send demo input and `TYPESAFE_API_KEY` to that endpoint. Keep keys in environment
variables, use HTTPS for remote services, and verify the destination yourself.

## Known demonstration limitations

- Confidence is not calibrated accuracy; thresholds were tuned on 40 examples.
- The recorded safety ticket `t24` bypasses the safety detector. Do not claim
  that the policy guarantees safety review or use it to operate real support.
- Fixture keys ignore Choice option order. The evaluation skips the invalid
  shuffle comparison rather than claiming order invariance.
- The forecast summary takes the first 12 hourly entries, not necessarily the
  next 12 hours. It is not a reliable current forecast recommendation.
- “Human review” prints a decision; it does not assign a real ticket.

## Repeat checks

```bash
uv sync --locked
uv run python -m unittest discover -s tests -v
uv export --locked --no-dev --no-emit-project --format requirements-txt -o /tmp/demo-requirements.txt
uv tool run pip-audit --no-deps --disable-pip -r /tmp/demo-requirements.txt
python3 scripts/export_public.py /tmp/decision-models-public
gitleaks dir /tmp/decision-models-public --redact --no-banner
gitleaks git --redact --no-banner
```

Secret scanners do not detect all personal data. Inspect new datasets and
documents manually. A dependency audit reports known advisories at the time it
runs, not proof that software has no vulnerabilities.

The original Git history contains a personal author name and email. A source
export excludes it. Publishing the existing history preserves that metadata;
choose the intended public author identity before creating or pushing commits.
