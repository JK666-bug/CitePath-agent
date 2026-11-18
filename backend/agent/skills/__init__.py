from pathlib import Path


def load_skill(name: str) -> str:
    path = Path(__file__).resolve().parent / name / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return text.strip()
    end = text.find("\n---", 3)
    if end < 0:
        raise ValueError(f"Skill {name} is missing its closing ---")
    body = text[end + 4 :].strip()
    if not body:
        raise ValueError(f"Skill {name} has no steps")
    return body
