from __future__ import annotations

from pathlib import Path


def test_runtime_requirements_projection_is_forced_to_lf_on_checkout() -> None:
    repository_root = Path(__file__).parents[3]
    attributes = (repository_root / ".gitattributes").read_text(encoding="utf-8")

    assert "*.requirements.txt text eol=lf" in attributes.splitlines()
