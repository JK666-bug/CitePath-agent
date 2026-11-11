# Reproducible evaluation

The tools separate assistant-authored question drafts, collected system outputs,
independent human judgments and adjudicated results. Blank judgments and missing
runs produce `pending` and `official_accepted: null`. Synthetic tests remain
development evidence. Acceptance needs the frozen final cohort and complete actual
observations plus two independent human annotation attestations.

## Materials and split

Use MIT OpenCourseWare **6.006 Introduction to Algorithms, Spring 2020**:

| Role | Lectures |
| --- | --- |
| Development | 2: Data Structures; 3: Sorting |
| Held-out final evaluation | 4: Hashing; 6: Binary Trees, Part 1; 8: Binary Heaps |

Original PDFs/checksums are in `data/mit-6.006-spring-2020/corpus.json`. They contain
29 original pages, including five attribution sheets; 24 pages are teaching text.
Preserve complete PDFs. Only teaching pages count as evidence, with the original
page numbers. Source: [MIT lecture notes](https://ocw.mit.edu/courses/6-006-introduction-to-algorithms-spring-2020/pages/lecture-notes/).

Only lecture text belongs in the retrieval index. Evaluation questions, candidate
answer keys, reference answers, student responses, human judgments and adjudications
stay outside it. The public notes split evaluates chapter transfer in this app;
it does not establish that a pretrained model has never seen the material.

The final cohort has **20 MCQ responses, 40 short-answer responses, 40 evidence
questions (30 supported, 10 unsupported), and 20 workflow scenarios**. Run each
workflow three times per system: 120 runs across baseline and full CitePath.
Two human members label independently, then jointly review disagreements.
Assistant-authored references remain candidate drafts until checked by them.

## Deterministic checks

From the repository root, in PowerShell:

```powershell
python -m venv backend/.venv
backend/.venv/Scripts/python -m pip install -r backend/requirements-test.txt
Push-Location backend
.venv/Scripts/python -m unittest discover -s tests -v
Pop-Location
cd frontend
npm ci
npm run build
npm run lint
```

The lightweight requirements support mocked-service regression tests. The full
runtime needs `backend/requirements.txt`, MySQL, Milvus, embedding models and valid
provider configuration. Browser smoke instructions are in `frontend/tests/`.

## Check real prerequisites

The following commands run from `backend`, using that checkout's Python environment:

```powershell
.venv/Scripts/python -m evaluation preflight --output logs/live-preflight.json
```

Preflight checks whether a key is configured, native modules can import, database
TCP listeners respond and `/api/health` responds. It invokes no model. A listener
does not prove authentication or persistence. `blocked` lists missing prerequisites
and keeps `formal_evaluation_run: false`.

The bounded live runner, its retained test data, safe process ownership and exit
codes are documented in [LIVE-INTEGRATION.md](LIVE-INTEGRATION.md). It uses only
development Lectures 2/3 and is not the 120-run final comparison collector.

For live integration, create a dedicated test account/course, upload development
lectures, and verify ingestion, generation, first-round success/failure, targeted
second round, final report, process-restart recovery, duplicate submissions across
API workers, independent Q&A, and explanation retry. Retain question IDs, original
sources, immutable grades and operation logs. Injected controller scores isolate
transition logic in separate runs. End-to-end expectations also need actual grader
scores; do not describe a controller simulation as real-model quality evidence.

## Freeze before final collection

Commit the application, then capture its configuration:

```powershell
.venv/Scripts/python freeze_evaluation.py --output logs/evaluation-manifest.json
.venv/Scripts/python -m pip freeze > logs/evaluation-packages.txt
```

The manifest records source hashes, settings and package versions without keys.
Record its SHA-256, commit, timezone-aware creation time and model deployment/version
in `dataset.freeze`, including `provider` and `base_url_sha256` from the manifest.
Retain the limitation when a provider exposes no immutable model
snapshot. Debug only on Lectures 2/3. Freeze questions, model, prompts, retrieval and
rules before final runs on 4/6/8. Any configuration change starts a new named cohort.

The upstream planner now splits each PDF into major teaching themes. The proposal's
evaluation chapter unit remains one lecture. Before formal runs, record the stable
application chapter IDs belonging to each lecture and the exact action sequence,
or prepare an explicitly reviewed one-lecture fixture. Never silently substitute
the dynamic theme count for the proposal's evaluation chapter count. The blank
preparation cohorts contain no observed runtime mapping and cannot certify that
protocol step. The old `evaluation_assets/final` preparation snapshot is retained
for provenance; later code/provider changes require a new named cohort. The updated
preparation batch is `evaluation_assets/cohorts/upstream-20261112`; its labels,
predictions, workflow observations and chapter mapping remain unfilled.

## Dataset schema

```json
{
  "schema": "citepath-evaluation-v1",
  "evaluation_id": "citepath-final-v1",
  "split": "final",
  "synthetic": false,
  "freeze": {
    "manifest_sha256": "64 lowercase hexadecimal characters",
    "created_at": "2026-11-11T10:00:00+08:00",
    "git_commit": "40 lowercase hexadecimal characters",
    "model": "the frozen deployment/version",
    "provider": "hku",
    "base_url_sha256": "64 lowercase hexadecimal characters"
  },
  "documents": [{
    "id": "mit6006-l04", "lecture": 4, "sha256": "original PDF SHA-256",
    "page_count": 5, "teaching_pages": [1, 2, 3, 4], "pdf_path": "lecture-04.pdf"
  }],
  "items": [{
    "id": "short-001", "kind": "short", "lecture": 4,
    "question": "A source-grounded question", "response": "The student's response",
    "rubric": ["One predefined point", "Another predefined point"],
    "sources": [{"document_id": "mit6006-l04", "page_number": 2}],
    "predictions": {"baseline": null, "full": null}
  }]
}
```

MCQ items have four distinct option texts, a selected `response`, and optionally a
candidate `answer_key` for actual grading collection. Short items contain the real
response and distinct equally weighted rubric points. Evidence items contain
`reference_points` for coverage review. Workflow items have `expected.baseline` and
`expected.full`, each with `transitions: [string]`, `final_state: string`, and an
ordered `actions: [string]` protocol for the concrete scenario. Actions record such
steps as duplicate submission, Q&A, process restart, or injected timeout and the
associated checks; a generic successful transition list does not establish them.

Predictions remain `null` until collected. Every prediction records `collected_at`,
`configuration_sha256` matching the manifest, and the frozen `model`. Collection
before freezing or with another identity is rejected.

| Kind | Actual recorded prediction |
| --- | --- |
| MCQ/short | `correct: boolean`; keep actual short-answer `rubric_hits` |
| Evidence | `answer`, `refused: boolean`, `claims: [{id, text, citations: [{document_id, page_number}]}]` |
| Workflow | `runs: [{repeat: 1..3, actions, transitions, final_state, round_count, third_round, duplicate_scoring, qa_score_changed, grading_feedback_latency_ms, model_calls, input_tokens, output_tokens, estimated_cost, cost_currency}]` |

When the frozen protocol specifies actions, a completed observation must contain
its actual ordered actions. Missing actions leave the observation pending; a
different action list fails it. Record the prohibited-error observations explicitly;
the evaluator never assumes absent flags are false. Distinguish injected controller
inputs from actual-grader end-to-end actions in the scenario and collection logs.

Unknown latency/usage fields stay `null`. Observed transitions determine workflow
success. A third round or other prohibited error defeats the workflow target even
when 19/20 scenarios otherwise succeed.

```powershell
.venv/Scripts/python -m evaluation validate path/to/dataset.json
```

## Collect real outputs

With the provider configured, run the application's MCQ/short grader on a fixed bank:

```powershell
.venv/Scripts/python -m evaluation collect-grading path/to/dataset.json --output logs/graded-dataset.json
```

This runs the actual shared first-round grader once and reuses its results for both
variants. It collects grading only; retrieval, feedback, persistence and workflow
observations require the live integration run. Candidate MCQ keys require human
audit. Actual rubric indexes and model usage are retained. Missing provider
configuration stops collection.

Import other actual collected outputs with a JSON object containing the current
`dataset_sha256` (printed by `validate`) and records:

```json
{
  "dataset_sha256": "the current dataset digest",
  "records": [{
    "item_id": "evidence-001", "variant": "full",
    "prediction": {
      "collected_at": "timezone-aware ISO timestamp",
      "configuration_sha256": "frozen manifest hash", "model": "frozen model",
      "answer": "The actual answer", "refused": false,
      "claims": [{"id": "claim-1", "text": "One factual claim", "citations": []}]
    }
  }]
}
```

```powershell
.venv/Scripts/python -m evaluation import-predictions logs/graded-dataset.json logs/recorded-outputs.json --output logs/collected-dataset.json
```

Saved predictions cannot be overwritten. The resulting snapshot has a new hash;
prepare labels after collection and complete factual-claim enumeration. Changes
afterwards require fresh sheets. Human reviewers verify `claims_complete`. Web
answers to unsupported lecture questions remain non-refusals. Outside sources do
not establish support in the frozen lecture corpus.

## Independent labels and adjudication

```powershell
.venv/Scripts/python -m evaluation labels logs/collected-dataset.json --output-dir logs/annotation
```

This creates `annotator-a.json`, `annotator-b.json` and `blind-workitems.json`.
Neither sheet is pre-filled with decisions or claims of independence. Model binary
grades and candidate MCQ keys are omitted from work items. Each member receives
their own sheet and original PDFs. The original question/key record remains
available for the separate generated-question audit.

Each member fills a distinct `annotator_id`, sets `label_origin: "human"`, and
attests `independent: true` after completing their own work:

- MCQ: correctness and supporting original pages; audit clarity, source support,
  candidate answer-key correctness and repetition.
- Short: exact **zero-based** rubric indexes hit, source pages and question audit.
  Four of five points passes; three of five fails.
- Evidence: question support, source pages, answer correctness, covered reference
  points, completeness of claims, support of each claim by valid cited teaching
  pages, and irrelevant citations.

Independence is an attestation the software cannot prove. Machine-assisted labels
retain their origin and cannot substitute for those human judgments.

```powershell
.venv/Scripts/python -m evaluation adjudication logs/collected-dataset.json --annotator logs/annotation/annotator-a.json --annotator logs/annotation/annotator-b.json --output-dir logs/review
```

The command lists disagreements and creates an empty resolution sheet. Resolve
each together, copy the agreed label into `adjudication.json.labels`, add a nonempty
`reason`, record the adjudicator and both original IDs in `reviewed_by`. A third
person is optional. Preserve the two original independent sheets.

## Score and report

```powershell
.venv/Scripts/python -m evaluation score logs/collected-dataset.json --annotator logs/annotation/annotator-a.json --annotator logs/annotation/annotator-b.json --adjudication logs/review/adjudication.json --usage-log logs/model-usage.jsonl --output logs/evaluation-report.json
```

Omit `--adjudication` when none is needed. `--require-complete` gives exit 2 for
pending evidence, exit 3 for completed final rejection, and exit 1 for invalid
inputs. A normal pending report exits 0 and explicitly records its status.

| Metric | Proposal target | Evidence |
| --- | --- | --- |
| MCQ agreement | 100% | Adjudicated binary human references |
| Short-answer agreement | At least 80% | Fixed 80% equal-weight rubric threshold; false passes/failures separately |
| Citation support | At least 85% | Fully supported factual claims; missing citations fail |
| Workflow scenarios | At least 18/20 scenarios | A scenario passes only when all three repeats match every expected transition and final state |
| Prohibited errors | None | No third rounds, duplicate scoring or Q&A grade changes |

Answer correctness, reference-point coverage, irrelevant citations, correct
unsupported refusals, generated-question audit issues and execution cost/latency
are descriptive metrics without additional passing thresholds. Refusing a
supported question is an answer failure. Each round keeps its own score.

The workflow aggregation rule is frozen before evaluation: a scenario passes if
all three repeats pass, fails as soon as any observed repeat fails, and otherwise
remains pending while repeats are missing. The official workflow target is assessed
after all repeats have observations. Per-repeat counts are descriptive; failures in
different scenarios across repeats cannot be hidden by averaging or aggregating
those counts. Prohibited errors in either baseline or full CitePath defeat official
acceptance, even when the full system's aggregate scenario count reaches 18/20.

Baseline and full runs use the same materials, model, first-round questions,
responses and first-round feedback. Only full CitePath adds targeted practice.
Retain first-round question/answer fingerprints in logs. The report compares the
matched item IDs in the same snapshot; missing variants remain pending.

## Usage and failure records

`backend/logs/model-usage.jsonl` records invocation time, scoped business IDs,
deployment, latency, tokens and configured estimated cost; override with
`MODEL_USAGE_LOG`. `backend/logs/operations.jsonl` links failures to sessions and
questions without answer text, API keys or provider error messages.

Provider-contract rate settings are `MODEL_INPUT_COST_PER_MILLION`,
`MODEL_OUTPUT_COST_PER_MILLION`, and `MODEL_COST_CURRENCY`. Missing counts/rates
produce unknown totals. Shared first-round use is reported separately from
per-system additional calls. SDK internal HTTP retries are not individually
enumerated by the model-invocation callback.

Reports include median and nearest-rank 95th-percentile grading/feedback latency,
completion/failure counts and usage grouped by one/two-round runs when recorded.
Retain unknown counts, manifests, original human sheets, adjudications and failure
cases. These measurements describe reliability and answer quality; they do not
establish improved student learning.
