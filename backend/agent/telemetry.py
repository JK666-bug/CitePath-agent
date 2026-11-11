"""Local model usage records. Never store prompts, answers, keys or error text."""
import json
import logging
import os
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.callbacks import BaseCallbackHandler

_write_lock = threading.Lock()
_logger = logging.getLogger(__name__)
_usage_context = ContextVar("citepath_usage_context", default={})
_context_keys = {"operation", "operation_id", "user_id", "course_id", "chapter_id", "session_id", "exam_id", "question_id", "evaluation_id", "system", "repeat"}


def _append(path, record):
    try:
        with _write_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        _logger.warning("Could not write an execution usage log")


@contextmanager
def usage_context(**fields):
    """Attach non-content business identifiers to model usage and operation spans."""
    safe = {key: value for key, value in fields.items()
            if key in _context_keys and type(value) in {str, int} and len(str(value)) <= 100}
    safe = {**_usage_context.get(), **safe, "operation_id": str(uuid.uuid4())}
    token = _usage_context.set(safe)
    start = time.perf_counter()
    status, error_type = "ok", None
    try:
        yield safe
    except BaseException as error:
        status, error_type = "error", type(error).__name__
        raise
    finally:
        _usage_context.reset(token)
        path = Path(os.environ.get("OPERATION_LOG") or Path(__file__).resolve().parents[1] / "logs" / "operations.jsonl")
        _append(path, {"at": datetime.now(timezone.utc).isoformat(), "context": safe,
                       "status": status, "error_type": error_type,
                       "latency_ms": round((time.perf_counter() - start) * 1000)})


def _rate(name):
    try:
        value = float(os.environ.get(name, ""))
        return value if 0 <= value < float("inf") else None
    except ValueError:
        return None


class UsageLog(BaseCallbackHandler):
    def __init__(self, model):
        self.model = model
        self.started = {}
        self.lock = threading.Lock()

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        with self.lock:
            self.started[str(run_id)] = (time.perf_counter(), dict(_usage_context.get()))

    def on_llm_end(self, response, *, run_id, **kwargs):
        usage = (response.llm_output or {}).get("token_usage") or {}
        # Providers may put normalized counts on the returned AIMessage.
        if not usage and response.generations and response.generations[0]:
            message = getattr(response.generations[0][0], "message", None)
            usage = getattr(message, "usage_metadata", None) or {}
        self._record(run_id, "ok", usage)

    def on_llm_error(self, error, *, run_id, **kwargs):
        self._record(run_id, "error", {}, type(error).__name__)

    def _record(self, run_id, status, usage, error_type=None):
        with self.lock:
            started = self.started.pop(str(run_id), None)
        start, context = started if started else (None, {})
        input_tokens = usage.get("prompt_tokens", usage.get("input_tokens"))
        output_tokens = usage.get("completion_tokens", usage.get("output_tokens"))
        input_rate = _rate("MODEL_INPUT_COST_PER_MILLION")
        output_rate = _rate("MODEL_OUTPUT_COST_PER_MILLION")
        cost = None
        if all(v is not None for v in (input_tokens, output_tokens, input_rate, output_rate)):
            cost = (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000
        record = {
            "at": datetime.now(timezone.utc).isoformat(), "run_id": str(run_id),
            "model": self.model, "model_calls": 1, "status": status,
            "latency_ms": round((time.perf_counter() - start) * 1000) if start is not None else None,
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "estimated_cost": cost, "cost_currency": os.environ.get("MODEL_COST_CURRENCY") or None,
            "error_type": error_type,
            "context": context,
        }
        path = Path(os.environ.get("MODEL_USAGE_LOG") or Path(__file__).resolve().parents[1] / "logs" / "model-usage.jsonl")
        _append(path, record)
