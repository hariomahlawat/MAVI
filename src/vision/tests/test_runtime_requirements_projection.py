from __future__ import annotations

import importlib.util


def test_runtime_requirements_projection_module_exists() -> None:
    assert importlib.util.find_spec(
        "mavi_vision.runtime.requirements_projection"
    ) is not None
