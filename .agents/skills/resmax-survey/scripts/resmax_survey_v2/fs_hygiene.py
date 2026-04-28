from __future__ import annotations

from pathlib import Path


KNOWN_OS_METADATA_FILENAMES = frozenset({".DS_Store"})


def remove_known_os_metadata(root_dir: Path) -> list[Path]:
    if not root_dir.exists():
        return []
    removed: list[Path] = []
    candidates: set[Path] = set()
    for filename in KNOWN_OS_METADATA_FILENAMES:
        candidates.add(root_dir / filename)
        candidates.update(root_dir.rglob(filename))
    for path in sorted(candidates):
        if path.is_file():
            path.unlink()
            removed.append(path)
    return removed
