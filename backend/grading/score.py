PASS_MARK = 0.8


def choice_correct(response: str, answer: str) -> bool:
    given = (response or "").strip().upper()[:1]
    expected = (answer or "").strip().upper()[:1]
    return bool(given) and given == expected


def points_pass(hits: int, total: int) -> bool:
    if total <= 0:
        return False
    return hits / total >= PASS_MARK


def exam_pass(correct: int, total: int) -> bool:
    if total <= 0:
        return False
    return correct / total >= PASS_MARK


def percent(correct: int, total: int) -> int:
    if total <= 0:
        return 0
    return round(100 * correct / total)
