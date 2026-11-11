# Live development integration

This runner observes the actual HTTP application with development Lectures 2 and 3.
It is separate from the held-out baseline/full evaluation and never supplies human
labels. Missing services or credentials produce a blocked report and exit code 2.

From `backend`, using the full runtime environment:

```powershell
python -m evaluation preflight --output logs/live-preflight.json
python -m evaluation live-integration --output logs/live-integration.json
```

The second command performs prerequisite checks only until test-data creation is
explicitly enabled. To run against an already started local API:

```powershell
python -m evaluation live-integration --allow-create-test-data --include-new-materials --output logs/live-integration.json
```

To include API-process restart recovery, choose a free local port. The runner starts
and stops only the Uvicorn process it creates; MySQL and Milvus must already run:

```powershell
python -m evaluation live-integration --api-url http://127.0.0.1:8011 --allow-create-test-data --manage-api-process --include-new-materials --output logs/live-integration-restart.json
```

It creates a new `citepath_it_...` account and course, verifies development PDF
checksums, uploads Lecture 2, generates a plan and saved practice questions, saves
and reopens a draft, tests duplicate submission and Q&A isolation, completes at
most two rounds, and checks explanation retry and final-result persistence. The
optional Lecture 3 update checks old chapter IDs, completed tasks and reports.
No existing account/course is selected or deleted; created data remains for review.

Default responses are deterministic development inputs (`A` for MCQ and an explicit
uncertain answer for short questions). Actual grader results determine pass/fail.
A first-round pass ends immediately and marks second-round execution as unobserved.
The runner does not force model grades or claim all branches were covered. Limit
answer submissions with `--max-answers` (1–80, default 64).

Optional `--answers answers.json` accepts `mcq`, `short` and `by_prompt_sha256`
response overrides. Hashes use SHA-256 of the UTF-8 canonical JSON string for the
prompt, as implemented by `evaluation.integration.fingerprint`. Keep fixtures out
of the lecture index. For subsequent manual login, set both
`CITEPATH_INTEGRATION_USERNAME` (beginning `citepath_it_`) and
`CITEPATH_INTEGRATION_PASSWORD` locally before the run; registration still creates
a new account, and an already-used username fails. Without them, a random password
is not retained in the report.

Reports contain resource IDs, check outcomes, request paths/status/latency and
snapshot hashes, without passwords, cookies, answer text or provider exception
bodies. Only loopback origins are accepted, proxies and redirects are disabled.
`synthetic: true` identifies a dependency-injected test client. A completed live
development run still has `formal_evaluation_run: false` and
`official_accepted: null`. Formal collection needs frozen configuration, actual
baseline/full observations and independent human review as described in
[EVALUATION.md](EVALUATION.md).
