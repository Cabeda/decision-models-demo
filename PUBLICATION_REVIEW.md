# Public source review — 5 November 2026

## Scope and outcome

Reviewed current source, documents, fixtures, dependency lock and the one-commit
Git history. Prepared a source export without Git history. No remote publication
or history rewrite was performed. This review does not certify the absence of
all vulnerabilities or identify company approval requirements.

## Changes

- Excluded the raw 300-row NHTSA complaint sample and its derived model recordings.
  The sample contains real narratives, contact information and injury details.
  Existing local copies were preserved. Optional Act 3 requires local data.
- Removed personal workstation paths from the presenter guide.
- Moved new model recordings to ignored local storage, still usable for local replay.
- Updated FastAPI from 0.115.6 to 0.162.0 and Starlette from 0.41.3 to 1.10.0.
  The original audit reported 14 advisory entries against Starlette, including
  duplicate advisory IDs. The installed and locked dependency audits now report
  no known vulnerabilities.
- Added weather request-origin, fetch-metadata and host checks, an inference
  request marker, coordinate bounds, model restrictions, response-label escaping
  and security headers. Corrected direct CLI model-filter SQL interpolation.
- Corrected support replay activation and misleading shuffle, injection and
  safety reporting. The routing policy and recorded model answers are unchanged.
- Added repeatable source export and security regression checks.

## Validation

- Eleven automated checks pass, including weather UI script execution with Node,
  all sixteen city/model replay combinations, private recording persistence,
  coordinate validation and cross-site browser-request rejection.
- Act 1 primitive and failure demonstrations and all forty Act 4 routes/evaluation
  replay successfully. The cascade still reports 26 automatic routes, 22 correct,
  and 14 human handoffs.
- Gitleaks finds no secrets in the original history or filtered source export.
  The source scan initially flagged 61 request hashes as generic API keys. The
  committed scanner configuration recognises only the exact JSON assignment of
  these twenty-character hexadecimal cache identities; other fields remain scanned.
- Targeted publication scans find no email addresses, personal home-directory
  paths, private-network IP addresses, private-key headers or known internal
  company hostnames. Dataset and document inspection supplemented the scanners.
- The public dependency lock installs into a separate temporary environment.
  The exported code passes its tests and offline demonstrations there.

## Remaining limits

The existing Git commit contains a personal author name and email. The source
export excludes this metadata; publishing the original history retains it.
Select the intended public author identity before creating or pushing commits.

The demo remains educational. Its model-based safety detector misses escalation
for recorded ticket `t24`, its weather forecast window is imperfect, and its
cache cannot establish option-order invariance. These limits are disclosed in
the README, presenter guide, evaluation and SECURITY.md. Live model/provider
integration and actual device geolocation were not revalidated in this review.
