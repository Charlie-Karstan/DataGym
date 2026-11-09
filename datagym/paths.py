from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKS = ROOT / 'exercise_packs'
WORKSPACE = ROOT / 'workspace'
SOLUTION = WORKSPACE / 'solution.py'
DATABASE = WORKSPACE / 'progress.sqlite3'


def ensure_dirs() -> None:
    WORKSPACE.mkdir(parents=True, exist_ok=True)
