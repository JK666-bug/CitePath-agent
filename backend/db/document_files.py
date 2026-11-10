"""Original PDF storage; filenames come only from database document IDs."""
import os
import tempfile
from pathlib import Path


def _path(document_id: int) -> Path:
    if type(document_id) is not int or document_id <= 0:
        raise ValueError("A positive document ID is required")
    directory = Path(os.environ.get("PDF_STORAGE_DIR") or Path(__file__).resolve().parents[1] / "storage" / "uploads").resolve()
    path = directory / f"{document_id}.pdf"
    if path.resolve().parent != directory:
        raise ValueError("The document path is outside PDF storage")
    return path


def save_original_pdf(document_id: int, data: bytes) -> Path:
    if not isinstance(data, bytes) or not data:
        raise ValueError("Original PDF data is required")
    destination = _path(document_id)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=destination.parent, prefix=f".{document_id}-", suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination


def original_pdf_path(document_id: int) -> Path | None:
    path = _path(document_id)
    return path if path.is_file() else None


def delete_original_pdf(document_id: int) -> None:
    _path(document_id).unlink(missing_ok=True)
