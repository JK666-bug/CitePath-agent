"""Exclusive, atomic checkpoints for evaluation sessions; not application storage."""
import json
import os
from contextlib import contextmanager
from pathlib import Path
from evaluation.core import digest, require


class CheckpointStore:
    def __init__(self, directory, identity):
        self.directory = Path(directory).resolve()
        protected = Path(__file__).resolve().parents[2] / "evaluation_assets"
        require(self.directory != protected and protected not in self.directory.parents,
                "Workflow checkpoints must be outside distributed evaluation assets")
        self.identity = identity

    @contextmanager
    def exclusive(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        lock = self.directory / ".collector.lock"
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as error:
            raise RuntimeError("Workflow checkpoint directory is in use; inspect the owning process before removing its lock") from error
        try:
            os.write(descriptor, str(os.getpid()).encode("ascii"))
            os.close(descriptor)
            header = self.directory / "identity.json"
            if header.exists():
                if json.loads(header.read_text(encoding="utf-8")) != self.identity:
                    raise ValueError("Checkpoint belongs to a different dataset, configuration, bindings or answers")
            else:
                self._write(header, self.identity)
            yield self
        finally:
            lock.unlink(missing_ok=True)

    def load(self, key):
        path = self._path(key)
        if not path.exists():
            return {}
        stored = json.loads(path.read_text(encoding="utf-8"))
        require(stored.get("schema") == "citepath-workflow-checkpoint-v1"
                and stored.get("identity_sha256") == digest(self.identity)
                and stored.get("payload_sha256") == digest(stored.get("payload")),
                "Workflow checkpoint content or identity changed")
        return stored["payload"]

    def save(self, key, value):
        self._write(self._path(key), {"schema": "citepath-workflow-checkpoint-v1",
                    "identity_sha256": digest(self.identity), "payload_sha256": digest(value), "payload": value})

    def _path(self, key):
        if not key or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in key):
            raise ValueError("Invalid checkpoint key")
        return self.directory / f"{key}.json"

    @staticmethod
    def _write(path, value):
        temporary = path.with_suffix(path.suffix + ".tmp")
        descriptor = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
