#!/usr/bin/env python3
"""Import `mavi_vision` submodules without dragging in the runtime stack.

`mavi_vision/runtime/__init__.py` re-exports the whole runtime surface, so
`from mavi_vision.runtime.requirements_projection import ...` executes
`interfaces` and `mmdetection` and therefore imports NumPy and Torch. For the
C2/C3 tools that is circular: `write_requirements_projection.py` derives *what
to download*, and it cannot require the download to have already happened.

The offline-closure modules themselves are clean -- `requirements_projection`,
`offline_lock` and `component_identity` need `packaging` and the standard
library and nothing else. Only the package's eager `__init__` stands in the
way.

So register lightweight stand-ins for the package nodes, each carrying only a
`__path__`. The normal import machinery then resolves
`mavi_vision.runtime.<module>` straight to the file, transitively and with no
change to any import statement, and the heavy `__init__` never runs. This is
the same shape as the boundary-gate workflow, which loads these modules by file
path for the same reason -- which is also why CI never caught this: it never
imported the package at all.

An already-imported `mavi_vision` is left alone, so a full environment (the
test suite, the application) behaves exactly as before.

Stdlib only.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

#: Package nodes the offline-closure tools reach through. Each is a directory
#: with an `__init__.py` that is deliberately not executed.
_PACKAGE_NODES = (
    ("mavi_vision", ()),
    ("mavi_vision.common", ("common",)),
    ("mavi_vision.runtime", ("runtime",)),
)


def vision_source_root() -> Path:
    """`src/vision`, the directory that holds the `mavi_vision` package."""
    return Path(__file__).resolve().parents[2] / "src" / "vision"


def install_lightweight_vision_package(root: Path | None = None) -> bool:
    """Make `mavi_vision.*` submodules importable without the eager re-exports.

    Returns True when stand-ins were installed, False when `mavi_vision` was
    already imported and was therefore left untouched.
    """
    if "mavi_vision" in sys.modules:
        return False

    source_root = vision_source_root() if root is None else root
    package_root = source_root / "mavi_vision"
    if not (package_root / "__init__.py").is_file():
        # Refuse rather than install stand-ins for a package that is not there;
        # a silent no-op would surface later as a confusing ImportError.
        raise ModuleNotFoundError(
            f"mavi_vision package not found under {source_root}"
        )

    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

    for name, parts in _PACKAGE_NODES:
        directory = package_root.joinpath(*parts)
        if not directory.is_dir():
            continue
        module = types.ModuleType(name)
        module.__path__ = [str(directory)]  # type: ignore[attr-defined]
        module.__package__ = name
        sys.modules[name] = module
    return True


__all__ = ["install_lightweight_vision_package", "vision_source_root"]
