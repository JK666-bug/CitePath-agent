import re

# A line that is only a page number or a page-number footer. Table rows are kept,
# because a cell can legitimately be a number. Theorem and figure numbers stay
# because they share the line with other words.
_PAGE_NUMBER = re.compile(
    r"^(?:"
    r"\d{1,4}"
    r"|[-–—]\s*\d{1,4}\s*[-–—]"
    r"|page\s+\d{1,4}(?:\s+of\s+\d{1,4})?"
    r"|\d{1,4}\s*/\s*\d{1,4}"
    r"|第\s*\d{1,4}\s*页"
    r")$",
    re.IGNORECASE,
)
_HEADING_MARK = re.compile(r"^#{1,6}\s+")
_IMAGE_LINE = re.compile(r"^<!--\s*image\s*-->$", re.IGNORECASE)


def strip_page_furniture(text: str) -> str:
    kept = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if _drop_line(line):
            continue
        kept.append(line.rstrip())
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(kept))
    return cleaned.strip()


def is_attribution_page(text: str) -> bool:
    """Recognize the standalone MIT OCW credit sheet, retaining original PDF pages."""
    compact = re.sub(r"\s+", " ", text).strip().casefold()
    if not ("mit opencourseware" in compact and "ocw.mit.edu" in compact
            and "terms" in compact and "6.006" in compact):
        return False
    # The credit sheet has these few lines, without teaching material. A page
    # merely mentioning MIT/its license must not be removed.
    without_links = re.sub(r"https?://\S+", "", compact)
    for expected in ("mit opencourseware", "6.006 introduction to algorithms", "spring 2020",
                     "for information about citing these materials or our terms of use, visit:"):
        without_links = without_links.replace(expected, "")
    return not re.sub(r"[\s#*<>\[\]().,:/\\-]+", "", without_links)


def _drop_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped or "|" in stripped:
        return False
    if _IMAGE_LINE.match(stripped):
        return True
    return _PAGE_NUMBER.match(_HEADING_MARK.sub("", stripped)) is not None
