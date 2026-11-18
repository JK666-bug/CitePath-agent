def all_mastered(concepts: list[dict], progress: dict[int, dict]) -> bool:
    if not concepts:
        return False
    return all(int(progress.get(concept["id"], {}).get("level") or 0) >= 2 for concept in concepts)


def next_unmastered(concepts: list[dict], progress: dict[int, dict]) -> dict | None:
    for concept in concepts:
        level = int(progress.get(concept["id"], {}).get("level") or 0)
        if level < 2:
            return concept
    return None


def learn_kind(streak: int) -> str:
    return "mcq" if streak < 1 else "short"


def record_learn(correct: bool, streak: int) -> tuple[int, int]:
    if not correct:
        return 0, 0
    streak += 1
    if streak >= 2:
        return 2, streak
    return 0, streak
