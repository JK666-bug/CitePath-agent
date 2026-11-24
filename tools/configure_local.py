"""Generate the environment files for a new CitePath installation."""
import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write_new(path: Path, content: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(content)


def main() -> None:
    compose = ROOT / ".env"
    backend = ROOT / "backend" / ".env"
    if compose.exists() or backend.exists():
        raise SystemExit("A local configuration file already exists. Review the README before starting the application.")
    app_password, root_password, object_password = [secrets.token_hex(24) for _ in range(3)]
    write_new(compose, f"CITEPATH_MYSQL_PASSWORD={app_password}\n"
                        f"CITEPATH_MYSQL_ROOT_PASSWORD={root_password}\n"
                        "CITEPATH_MINIO_USER=citepath-local\n"
                        f"CITEPATH_MINIO_PASSWORD={object_password}\n")
    template = (ROOT / "backend" / ".env.example").read_text(encoding="utf-8")
    write_new(backend, template.replace("MYSQL_PASSWORD=\n", f"MYSQL_PASSWORD={app_password}\n", 1))
    print("Local configuration created. Set the model provider and API key in backend/.env.")


if __name__ == "__main__":
    main()
