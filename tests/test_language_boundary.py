from pathlib import Path


def test_repository_language_keeps_fresh_project_boundary():
    root = Path(__file__).resolve().parents[1]
    banned = {
        "rezn" + "-" + "live",
        "redo" + "ing",
    }
    checked_suffixes = {".md", ".py", ".toml"}
    offenders = []

    for path in root.rglob("*"):
        if any(part in {".git", ".venv", "__pycache__", ".pytest_cache"} for part in path.parts):
            continue
        if path.suffix not in checked_suffixes:
            continue
        text = path.read_text(encoding="utf-8").lower()
        for phrase in banned:
            if phrase in text:
                offenders.append((path.relative_to(root), phrase))

    assert offenders == []

