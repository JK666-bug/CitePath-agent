# Evaluation and reproducibility

The automated tests verify deterministic grading and workflow behavior using fake
model results and in-memory/mocked persistence. They do not establish model answer
quality, real retrieval quality, or the final project acceptance targets.

## Reproduce deterministic checks

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

The lightweight test requirements deliberately avoid downloading Docling,
embedding weights and the vector/PDF native runtimes. Install the full
`backend/requirements.txt` and start Docker for a real end-to-end run, using the
startup instructions in README. Native libraries load when their feature runs.

`tests/test_practice_rounds.py` includes twenty scripted development sessions
covering thresholds 70/80/90%, immediate passing, targeted second rounds, passing
in round 2 and final failure. Additional tests cover saved question identity,
saved drafts, incomplete model output, duplicate requests and concurrent requests.
These synthetic sessions are development tests, not held-out evaluation results.

## Freeze before held-out evaluation

1. Use Lectures 2 and 3 for development. Keep Lectures 4, 6 and 8 and their final
   labels out of debugging.
2. Commit the evaluated code and record the model deployment/version. Where the
   provider does not expose an immutable model snapshot, record that limitation.
3. Run the following from `backend` in the full runtime. The manifest records
   prompt/retrieval/grading source hashes, settings and installed package versions;
   it never writes API keys and never invokes the model.

```powershell
.venv/Scripts/python freeze_evaluation.py --output logs/evaluation-manifest.json
.venv/Scripts/python -m pip freeze > logs/evaluation-packages.txt
```

4. Save the evaluation document identifiers and SHA-256 checksums, the frozen
   prompts, question sets, raw rubric-hit output, independently produced human
   labels and adjudicated disagreements. Do not tune against these labels.
5. Run the real API/UI workflow with MySQL, Milvus and the configured provider.
   Include process restart, vector outage/retry and multiple API workers. In-memory
   concurrency tests do not replace this database integration verification.

## Report the proposal targets separately

| Metric | Target | Required evidence |
| --- | --- | --- |
| MCQ grading agreement | 100% | Predicted and human reference option labels |
| Short-answer binary agreement | At least 80% | Human labels and predicted pass/fail; false passes and false failures separately |
| Citation support coverage | At least 85% | Human check of factual claims against the original cited PDF pages; missing citations fail |
| Scripted workflows | At least 18 of 20 | Every expected transition and final state recorded for each held-out scripted session |
| Prohibited errors | None | No third round, duplicate scoring, or independent Q&A changing practice scores |

Do not substitute citation presence for factual support. Do not combine or average
the round scores. Pass/fail uses the unrounded accuracy and the threshold saved
when that chapter session started.

## Usage records

The model callback appends one JSONL record per LangChain model invocation to
`backend/logs/model-usage.jsonl` (override with `MODEL_USAGE_LOG`). It records time,
deployment, success/error type, invocation latency, token counts when reported by
the provider, and estimated cost when rates are configured. It never stores prompt
text, student answers, API keys or raw error messages. Invocation counts do not
separately enumerate provider SDK retries; token data missing on failures remains
unknown. These limitations must appear in a cost report.

Optional `.env` settings:

```dotenv
MODEL_INPUT_COST_PER_MILLION=
MODEL_OUTPUT_COST_PER_MILLION=
MODEL_COST_CURRENCY=
```

Use rates from the actual provider contract. Missing rates or token usage produce
`null` cost. Record latency, calls, tokens and cost without inventing extra passing
thresholds. Keep the logs, failure cases and environment manifest with the final
evaluation report.
