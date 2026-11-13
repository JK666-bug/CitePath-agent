from decimal import Decimal, InvalidOperation

PASS_MARK = 0.8


def validate_threshold(threshold: float = PASS_MARK) -> Decimal:
    if isinstance(threshold, bool):
        raise ValueError("The chapter passing threshold must be between 0 and 1")
    try:
        value = Decimal(str(threshold))
    except (InvalidOperation, ValueError):
        raise ValueError("The chapter passing threshold must be between 0 and 1") from None
    if not value.is_finite() or not 0 < value <= 1:
        raise ValueError("The chapter passing threshold must be between 0 and 1")
    return value


def _counts(correct: int, total: int) -> None:
    if (type(correct) is not int or type(total) is not int
            or total <= 0 or not 0 <= correct <= total):
        raise ValueError("A score requires a nonempty, completely graded question set")


def choice_correct(response: str, answer: str) -> bool:
    given = (response or "").strip().upper()
    expected = (answer or "").strip().upper()
    if expected not in {"A", "B", "C", "D"}:
        raise ValueError("The multiple-choice answer key is invalid")
    return given in {"A", "B", "C", "D"} and given == expected


def points_pass(hits: int, total: int) -> bool:
    _counts(hits, total)
    return hits * 5 >= total * 4


def exam_pass(correct: int, total: int, threshold: float = PASS_MARK) -> bool:
    _counts(correct, total)
    return Decimal(correct) >= Decimal(total) * validate_threshold(threshold)


def percent(correct: int, total: int) -> int:
    _counts(correct, total)
    return round(100 * correct / total)
