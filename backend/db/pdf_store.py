from pathlib import Path
import os
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PDF_ROOT = ROOT / "data" / "pdfs"


def pdf_path(course_id: int, document_id: int) -> Path:
    if type(course_id) is not int or course_id <= 0 or type(document_id) is not int or document_id <= 0:
        raise ValueError("Positive course and document IDs are required")
    return PDF_ROOT / str(course_id) / f"{document_id}.pdf"


def available_pdf_path(course_id: int, document_id: int) -> Path | None:
    """Read both layouts without moving or deleting immutable originals."""
    path = pdf_path(course_id, document_id)
    from db.document_files import original_pdf_path
    legacy = original_pdf_path(document_id)
    for candidate in (legacy, path):
        if candidate is not None and candidate.is_file() and candidate.stat().st_size:
            return candidate
    return None


def has_pdf(course_id: int, document_id: int) -> bool:
    return available_pdf_path(course_id, document_id) is not None


def save_pdf(course_id: int, document_id: int, data: bytes) -> None:
    if not data:
        raise ValueError("The PDF is empty")
    path = pdf_path(course_id, document_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=f".{document_id}-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_pdf_bytes(course_id: int, document_id: int) -> bytes | None:
    path = available_pdf_path(course_id, document_id)
    if path is None:
        return None
    data = path.read_bytes()
    return data or None


def delete_pdf(course_id: int, document_id: int) -> None:
    """Explicit permanent cleanup only; archiving must never call this."""
    path = pdf_path(course_id, document_id)
    try:
        path.unlink(missing_ok=True)
    except TypeError:
        if path.exists():
            path.unlink()
    parent = path.parent
    try:
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
    except OSError:
        pass


def delete_course_pdfs(course_id: int) -> None:
    folder = PDF_ROOT / str(int(course_id))
    if not folder.exists():
        return
    for path in folder.glob("*.pdf"):
        try:
            path.unlink()
        except OSError:
            pass
    try:
        folder.rmdir()
    except OSError:
        pass
