"""The ``plates`` role's import boundary (Stage 4 plan §2.4; ADR-013 item 10).

The role runs from its own Runtime Pack family, so nothing in ``mavi_vision.plates`` may import the
vision role's deep-learning stack — directly, or through any ``mavi_vision`` module it imports. Two
checks: a static closure over the source (independent of what this environment has installed) and a
fresh interpreter that imports every plates module and inspects ``sys.modules``.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

VISION_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = VISION_ROOT / "mavi_vision" / "plates"
FORBIDDEN = frozenset({"torch", "torchvision", "mmcv", "mmdet", "mmengine"})


def _module_path(module: str) -> Path | None:
    parts = module.split(".")
    candidate = VISION_ROOT.joinpath(*parts)
    if (candidate / "__init__.py").is_file():
        return candidate / "__init__.py"
    if candidate.with_suffix(".py").is_file():
        return candidate.with_suffix(".py")
    return None


def _imports(path: Path, module: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package = module if path.name == "__init__.py" else module.rsplit(".", 1)[0]
    found: set[str] = set()
    for node in ast.walk(tree):  # every import, including function-local ones
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.rsplit(".", node.level - 1)[0] if node.level > 1 else package
                name = f"{base}.{node.module}" if node.module else base
            else:
                name = node.module or ""
            found.add(name)
            found.update(f"{name}.{alias.name}" for alias in node.names)
    return found


def _plates_modules() -> list[str]:
    modules = []
    for path in sorted(PACKAGE.rglob("*.py")):
        relative = path.relative_to(VISION_ROOT).with_suffix("")
        parts = list(relative.parts)
        if parts[-1] == "__init__":
            parts.pop()
        modules.append(".".join(parts))
    return modules


def test_no_plates_module_reaches_the_vision_deep_learning_stack_statically() -> None:
    pending = list(_plates_modules())
    seen: set[str] = set()
    offenders: list[tuple[str, str]] = []
    while pending:
        module = pending.pop()
        if module in seen:
            continue
        seen.add(module)
        path = _module_path(module)
        if path is None:
            continue
        for imported in _imports(path, module):
            root = imported.split(".", 1)[0]
            if root in FORBIDDEN:
                offenders.append((module, imported))
            elif root == "mavi_vision":
                pending.append(imported)
    assert offenders == []
    assert "mavi_vision.plates.pipeline" in seen


def test_importing_every_plates_module_loads_no_forbidden_package() -> None:
    script = (
        "import importlib, sys\n"
        f"for name in {_plates_modules()!r}:\n"
        "    importlib.import_module(name)\n"
        f"loaded = sorted(name for name in sys.modules if name.split('.', 1)[0] in {sorted(FORBIDDEN)!r})\n"
        "print(','.join(loaded))\n"
    )
    result = subprocess.run([sys.executable, "-c", script], cwd=VISION_ROOT, capture_output=True, text=True, check=True)
    assert result.stdout.strip() == ""
