"""Load the PDF parser and embedding model before the first upload."""
from pathlib import Path
import sys

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
load_dotenv(ROOT / "backend" / ".env", override=False)

from ingest.pdf_reader import read_pdf
from vector.segments import _embed


def main() -> None:
    sample = ROOT / "data" / "py4e-chapter-07-files.pdf"
    pages = read_pdf(sample.read_bytes())
    text = next(page["body"] for page in pages if page["usable"])
    vectors = _embed([text])
    if len(vectors) != 1 or not vectors[0]:
        raise RuntimeError("The sample text did not produce a valid embedding.")
    print("The PDF parser and embedding model are ready.")


if __name__ == "__main__":
    main()
