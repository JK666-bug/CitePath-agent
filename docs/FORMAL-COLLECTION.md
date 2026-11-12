# Actual evaluation collection

The CLI now prepares runtime bindings, collects production QA outputs and paired
workflow sessions, and merges complementary observations from one original input.
Every command uses the same immutable source dataset. Collection is not official
acceptance; human labels, protocol review and complete actual observations are
separate requirements.

## Prepare and review the runtime protocol

From `backend`, in the configured environment:

```powershell
python -m evaluation prepare-collection path/to/original-dataset.json --manifest path/to/frozen-configuration.json --output-dir logs/runtime-bindings
```

This makes empty evidence-course/document mappings, workflow fixture bindings,
an authored response policy, and a pending status file. It creates no accounts,
courses, model requests or human attestations. IDs remain `null` until observed.
Credentials are environment-variable names, never literal passwords in the files.

Use isolated `citepath_eval_...` accounts and courses. Each workflow item/repeat
has separate `shared`, `baseline` and `full` fixtures. No fixture may be reused
across scenarios or repeats. The default adapter rejects pre-existing practice
history when creating a session; a resumed collector reuses its saved session IDs.
Plan/material fixtures must be prepared and reviewed first. Each workflow chapter
must cover exactly one frozen lecture's teaching pages, with matching original
PDF checksum and page count, identical concepts and text in all three fixtures.
Dynamic application themes are not silently treated as whole proposal chapters.

The original `evaluation_assets/final` and upstream preparation cohorts retain
injected-count controller examples, including 159/200 and odd question counts.
They cannot be passed off as the application's naturally generated question sets.
The execution preparation cohort keeps those cases separately for controller
regression and uses `actual_grade_v1` for real-grader workflow observations.
That frozen policy computes expected termination from actual integer counts and
the saved threshold. It checks separate round scores, one-round baseline stopping,
at most two full-system rounds, probe actions and prohibited mutations. It does
not force an actual model to produce a desired accuracy or claim an unobserved
first-pass branch was exercised.

Before final collection, two humans must review this protocol and the completed
fixture map. The new dataset's `evaluation_protocol` must explicitly record
`reviewed: true`, `review_origin: "human"`, two distinct `reviewed_by` IDs, and
`chapter_mapping_sha256`, calculated with `evaluation.core.digest` over the
completed bindings' `cases` object. Do not put the full bindings digest there:
bindings also contain the dataset digest, which would create a circular reference.
Create a new named frozen input, regenerate its binding digest and annotation
templates, and retain the unreviewed preparation snapshot. Assistant-generated
files deliberately leave these human fields pending.

The same review must record `response_policy_sha256` over the complete authored
response-policy JSON. Positive branch probes can explicitly use `policy: reference`
(saved MCQ candidate option or joined rubric text); negative probes can use
`policy: wrong_reference` (a different MCQ option and an uncertain short response).
These are programmed test inputs, not real student data or independent model-quality
labels. They still go through the actual grader; no correct-count result is forced.
The policy is frozen before runs. A required first-pass/follow-up branch that is not
reached is recorded as a mismatch instead of being credited as exercised.

## Evidence outputs

Fill the generated evidence configuration with two distinct dedicated courses,
both containing the exact frozen corpus. Each runtime document ID maps to the
frozen PDF ID/checksum/page count. The selected QA policy is explicitly
`production_qa_shared_v1`; this comparison does not invent a retrieval ablation.

```powershell
python -m evaluation collect-evidence path/to/original-dataset.json --config logs/evidence-runtime.json --checkpoint-dir logs/evidence-checkpoints --output logs/evidence-collected.json --run
```

Omitting `--run` makes no service calls. Before a question, the collector logs in
using environment-only credentials and verifies the authenticated course runtime
endpoint's provider, model/API version, endpoint fingerprint, source hashes,
Python/packages and exact active document corpus against the frozen manifest.
The API captures its runtime identity at startup and rejects source/configuration
drift until restarted. It exports no keys or raw endpoint credentials.

Answers and the API's refusal flag are preserved. Verbatim paragraphs become
candidate claim boundaries; actual answer-level lecture citations are mapped to
frozen IDs. Humans must verify claim completeness, per-claim support and relevance.
Web references never become lecture citations. A refusal flag alone does not
establish that refusing was correct. The separate report and journal contain safe
IDs/status/hashes, while the collected dataset retains actual answer content.

Checkpoints bind the original dataset/configuration. Completed observations are
reused without another request. An intent without a completed output is uncertain
and stops automatic replay; reconcile the retained QA record before proceeding.

## Paired workflow observations

```powershell
python -m evaluation collect-workflows path/to/original-dataset.json --bindings logs/workflow-bindings.json --answers logs/response-policy.json --checkpoint-dir logs/workflow-checkpoints --output logs/workflows-collected.json --run
```

Without `--run`, no evaluation session is created. With it, the adapter checks
the frozen local runtime and explicit fixture bindings before writes. It generates,
grades and explains a shared first round once, saves exact question/answer/grade/
feedback fingerprints, and replays them into independent baseline/full sessions.
The one-round baseline is internal to evaluation; production practice retains
its two-round rule. The full system uses production controller functions. Results
record actual traces rather than copying expected transitions.

The shared first round is measured and scoped `shared_first_round`; follow-up
generation/grading and Q&A are scoped to their actual system/item/repeat. Configure
the existing usage logs and contracted price settings for cost calculations.
Unknown usage/prices remain unknown. SDK-internal HTTP retries are not individually
counted by the model callback.

For restart/draft scenarios, set `owned_api_url` to a free local IPv4 HTTP port
and supply each fixture's username/password environment-variable names. The
collector starts only its own Uvicorn process, saves a draft via HTTP, restarts
that process, and verifies persisted question content/ID, draft and grades. It
never stops an unrelated listener. Missing process bindings yield `not_run`.

The timeout scenario deliberately raises one `TimeoutError` at the production
short-answer grader boundary in the shared phase, verifies the saved draft and
absence of an official grade, restores the real grader, and retries. The actual
successful first-round result is then reused by both systems. Output explicitly
marks this controlled fault and its shared scope; it is not an observed provider
outage or a model-quality measurement. No desired correct-count result is injected.

Checkpoints use exclusive locks, atomic replacement and content/identity hashes.
Uncertain session creation or probe requests require reconciliation. Source/model
drift aborts further execution. Test adapters are marked synthetic and return
`controller_records`, separate from importable real `records`.

## Merge, annotate and score

Run all collectors against the original input, then merge their complementary
outputs once. Sequentially editing an already observed dataset would change its
digest and break the other collectors' bindings.

```powershell
python -m evaluation collect-grading path/to/original-dataset.json --output logs/grading-collected.json
python -m evaluation merge-collections path/to/original-dataset.json --collection logs/grading-collected.json --collection logs/evidence-collected.json --collection logs/workflows-collected.json --output logs/observed-dataset.json
python -m evaluation labels logs/observed-dataset.json --output-dir logs/human-review
```

The merger rejects changed inputs/configuration, conflicting observations,
synthetic results in a real cohort and controller-only records. Two humans fill
their own new observation-bound sheets independently, then use the adjudication
and score commands in [EVALUATION.md](EVALUATION.md). Missing runs or labels remain
pending; a third round, duplicate scoring or Q&A score mutation cannot be averaged
away. Exit 0 from collection means collection completed, not official acceptance.
