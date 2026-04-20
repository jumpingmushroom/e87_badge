"""Sanity check: RE captures exist in the shape later phases will consume."""

from pathlib import Path

import pytest

CAPTURES = Path(__file__).parent.parent / "docs" / "captures"


def test_captures_dir_exists():
    assert CAPTURES.is_dir(), f"{CAPTURES} must exist"


@pytest.mark.skipif(
    not any(CAPTURES.glob("*.log")),
    reason="No btsnoop captures yet — phase 1 task 4 not complete",
)
def test_every_capture_has_matching_png_and_notes():
    missing = []
    for log in CAPTURES.glob("*.log"):
        stem = log.stem
        png = CAPTURES / f"{stem}.png"
        notes = CAPTURES / f"{stem}.md"
        if not png.is_file():
            missing.append(str(png))
        if not notes.is_file():
            missing.append(str(notes))
    assert not missing, f"Missing companion files: {missing}"
