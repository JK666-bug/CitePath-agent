import random


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


def review_set(concepts: list[dict], progress: dict[int, dict], limit: int = 3) -> list[dict]:
    mastered = []
    for index, concept in enumerate(concepts):
        state = progress.get(concept["id"], {})
        if int(state.get("level") or 0) >= 2:
            mastered.append((str(state.get("updated_at") or ""), index, concept))
    mastered.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in mastered[:limit]]


def build_review_queue(concept_ids: list[int], shuffle=None) -> list[dict]:
    items = []
    for concept_id in concept_ids:
        items.append({"concept_id": int(concept_id), "kind": "mcq"})
        items.append({"concept_id": int(concept_id), "kind": "short"})
    if shuffle is None:
        random.shuffle(items)
    else:
        shuffle(items)
    return items


def record_review(correct_count: int) -> tuple[int, int]:
    if correct_count <= 0:
        return 0, 0
    return 2, 2
