from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PDF_ROOT = ROOT / "data" / "pdfs"


def pdf_path(course_id: int, document_id: int) -> Path:
    return PDF_ROOT / str(int(course_id)) / f"{int(document_id)}.pdf"


def has_pdf(course_id: int, document_id: int) -> bool:
    path = pdf_path(course_id, document_id)
    return path.is_file() and path.stat().st_size > 0


def save_pdf(course_id: int, document_id: int, data: bytes) -> None:
    if not data:
        raise ValueError("The PDF is empty")
    path = pdf_path(course_id, document_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def read_pdf_bytes(course_id: int, document_id: int) -> bytes | None:
    path = pdf_path(course_id, document_id)
    if not path.is_file():
        return None
    data = path.read_bytes()
    return data or None


def delete_pdf(course_id: int, document_id: int) -> None:
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
