from __future__ import annotations

from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_IMPORT = "peetsfea.legacy.type1"
SCAN_ROOTS = (
    REPO_ROOT / "src",
    REPO_ROOT / "entry",
    REPO_ROOT / "tests",
)
SKIP_PARTS = {
    "legacy",
    "__pycache__",
    ".venv",
    ".git",
}


def _should_scan(path: Path) -> bool:
    return not any(part in SKIP_PARTS for part in path.parts)


def test_active_tree_does_not_import_legacy_type1_modules() -> None:
    offenders: list[str] = []
    pattern = re.compile(r"^\s*(from|import)\s+peetsfea\.legacy\.type1\b", re.MULTILINE)
    for scan_root in SCAN_ROOTS:
        for path in scan_root.rglob("*.py"):
            if not _should_scan(path):
                continue
            text = path.read_text(encoding="utf-8")
            if pattern.search(text):
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []
