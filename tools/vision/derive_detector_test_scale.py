#!/usr/bin/env python3
"""Derive a detector resolved config whose only change is the test-time input scale.

The Stage-3 Development candidate ``phase1-rtmdet-m-scale1280-a2`` is the H3 E1
intervention packaged as a Model Pack: the base resolved config with the test
``Resize`` ``scale`` and ``Pad`` ``size`` changed from (640, 640) to
(``scale``, ``scale``) in ``test_dataloader.dataset.pipeline`` and
``test_pipeline``, and nothing else. ``keep_ratio`` and ``pad_val`` stay as they
are; the validation and training pipelines are untouched.

The derivation is byte-minimal and deterministic: the base config (an mmengine
dump) is parsed with ``ast`` and exactly the eight integer literals of those
four nodes are rewritten in place, so the derived bytes equal the base bytes
everywhere else. ``check_test_scale_derivation`` proves the result structurally:
both configs are evaluated as literal trees (no code is executed) and they must
differ at exactly the four frozen paths, each holding the E1 override values.

Usage::

    derive_detector_test_scale.py --base <rtmdet_m_resolved.py> --base-sha256 <hex>
        --scale 1280 --output <derived.py>
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

# The two test pipelines the E1 override targeted (H3-E1 override spec 69386445…).
TEST_PIPELINE_PATHS: tuple[tuple[str, ...], ...] = (("test_dataloader", "dataset", "pipeline"), ("test_pipeline",))
BASE_SCALE = 640
PAD_VALUE = {"img": (114, 114, 114)}


class DerivationError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


# --------------------------------------------------------------------------- literal evaluation


def _literal(node: ast.AST) -> Any:
    """Evaluate one node of an mmengine config dump; anything but a literal is refused."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Tuple):
        return tuple(_literal(item) for item in node.elts)
    if isinstance(node, ast.List):
        return [_literal(item) for item in node.elts]
    if isinstance(node, ast.Dict):
        if any(key is None for key in node.keys):
            raise DerivationError("config_not_literal:dict_unpacking")
        return {_literal(key): _literal(value) for key, value in zip(node.keys, node.values)}
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        value = _literal(node.operand)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise DerivationError("config_not_literal:unary")
        return -value
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "dict" and not node.args:
        if any(keyword.arg is None for keyword in node.keywords):
            raise DerivationError("config_not_literal:dict_unpacking")
        return {keyword.arg: _literal(keyword.value) for keyword in node.keywords}
    raise DerivationError(f"config_not_literal:{type(node).__name__}")


def _assignments(text: str) -> dict[str, ast.AST]:
    try:
        module = ast.parse(text)
    except SyntaxError as exc:
        raise DerivationError("config_unparseable") from exc
    nodes: dict[str, ast.AST] = {}
    for statement in module.body:
        if not (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        ):
            raise DerivationError("config_not_literal:statement")
        name = statement.targets[0].id
        if name in nodes:
            raise DerivationError(f"config_duplicate_assignment:{name}")
        nodes[name] = statement.value
    return nodes


def config_tree(data: bytes) -> dict[str, Any]:
    """The config as plain values: every top-level name to its literal value."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DerivationError("config_not_utf8") from exc
    return {name: _literal(node) for name, node in _assignments(text).items()}


# --------------------------------------------------------------------------- structural difference


def structural_differences(left: Any, right: Any, path: tuple[Any, ...] = ()) -> list[tuple[tuple[Any, ...], Any, Any]]:
    """Every leaf path at which two literal trees differ (type changes count as differences)."""
    if isinstance(left, dict) and isinstance(right, dict):
        out: list[tuple[tuple[Any, ...], Any, Any]] = []
        for key in sorted(set(left) | set(right), key=repr):
            if key not in left or key not in right:
                out.append((path + (key,), left.get(key, "<absent>"), right.get(key, "<absent>")))
            else:
                out.extend(structural_differences(left[key], right[key], path + (key,)))
        return out
    if isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
        out = []
        for index, (a, b) in enumerate(zip(left, right)):
            out.extend(structural_differences(a, b, path + (index,)))
        return out
    if type(left) is type(right) and left == right:
        return []
    return [(path, left, right)]


def _pipeline(tree: dict[str, Any], path: tuple[str, ...]) -> list[Any]:
    node: Any = tree
    for key in path:
        if not isinstance(node, dict) or key not in node:
            raise DerivationError(f"config_pipeline_missing:{'.'.join(path)}")
        node = node[key]
    if not isinstance(node, list):
        raise DerivationError(f"config_pipeline_missing:{'.'.join(path)}")
    return node


def _single_index(pipeline: list[Any], transform: str, path: tuple[str, ...]) -> int:
    indices = [i for i, step in enumerate(pipeline) if isinstance(step, dict) and step.get("type") == transform]
    if len(indices) != 1:
        raise DerivationError(f"config_transform_not_unique:{'.'.join(path)}:{transform}")
    return indices[0]


def expected_differences(base_tree: dict[str, Any], *, scale: int) -> dict[tuple[Any, ...], tuple[Any, Any]]:
    """The four frozen leaf changes, located in the base tree (and checked to be the 640 base)."""
    out: dict[tuple[Any, ...], tuple[Any, Any]] = {}
    for path in TEST_PIPELINE_PATHS:
        pipeline = _pipeline(base_tree, path)
        resize = _single_index(pipeline, "Resize", path)
        pad = _single_index(pipeline, "Pad", path)
        if pipeline[resize].get("keep_ratio") is not True:
            raise DerivationError(f"config_base_unexpected:{'.'.join(path)}:keep_ratio")
        if pipeline[pad].get("pad_val") != PAD_VALUE:
            raise DerivationError(f"config_base_unexpected:{'.'.join(path)}:pad_val")
        for index, key in ((resize, "scale"), (pad, "size")):
            if pipeline[index].get(key) != (BASE_SCALE, BASE_SCALE):
                raise DerivationError(f"config_base_unexpected:{'.'.join(path)}:{key}")
            out[path + (index, key)] = ((BASE_SCALE, BASE_SCALE), (scale, scale))
    return out


def check_test_scale_derivation(base: bytes, derived: bytes, *, scale: int) -> list[dict[str, Any]]:
    """Refuse unless ``derived`` differs from ``base`` exactly by the frozen test-scale change.

    Returns the differences as JSON-ready rows (path, from, to) for the provenance record.
    """
    base_tree, derived_tree = config_tree(base), config_tree(derived)
    expected = expected_differences(base_tree, scale=scale)
    actual = {path: (left, right) for path, left, right in structural_differences(base_tree, derived_tree)}
    if actual != expected:
        unexpected = sorted(set(actual) ^ set(expected), key=repr) or sorted(actual, key=repr)
        raise DerivationError(f"config_derivation_not_test_scale_only:{unexpected[:3]!r}")
    for path in TEST_PIPELINE_PATHS:
        pipeline = _pipeline(derived_tree, path)
        resize = pipeline[_single_index(pipeline, "Resize", path)]
        pad = pipeline[_single_index(pipeline, "Pad", path)]
        if resize != {"keep_ratio": True, "scale": (scale, scale), "type": "Resize"}:
            raise DerivationError(f"config_derivation_resize_not_e1:{'.'.join(path)}")
        if pad != {"pad_val": PAD_VALUE, "size": (scale, scale), "type": "Pad"}:
            raise DerivationError(f"config_derivation_pad_not_e1:{'.'.join(path)}")
    return [
        {"path": ".".join(str(part) for part in path), "from": list(change[0]), "to": list(change[1])}
        for path, change in sorted(expected.items(), key=lambda item: repr(item[0]))
    ]


# --------------------------------------------------------------------------- derivation


def _node_at(nodes: dict[str, ast.AST], path: tuple[str, ...]) -> ast.AST:
    node = nodes[path[0]] if path[0] in nodes else None
    for key in path[1:]:
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "dict"):
            raise DerivationError(f"config_pipeline_missing:{'.'.join(path)}")
        node = next((keyword.value for keyword in node.keywords if keyword.arg == key), None)
    if not isinstance(node, ast.List):
        raise DerivationError(f"config_pipeline_missing:{'.'.join(path)}")
    return node


def _keyword(call: ast.AST, name: str) -> ast.Tuple:
    assert isinstance(call, ast.Call)
    value = next((keyword.value for keyword in call.keywords if keyword.arg == name), None)
    if not (isinstance(value, ast.Tuple) and len(value.elts) == 2 and all(isinstance(item, ast.Constant) for item in value.elts)):
        raise DerivationError(f"config_transform_value_invalid:{name}")
    return value


def derive(base: bytes, *, scale: int) -> bytes:
    """The base bytes with exactly the eight frozen integer literals set to ``scale``."""
    if isinstance(scale, bool) or not isinstance(scale, int) or not BASE_SCALE < scale <= 4096:
        raise DerivationError("scale_invalid")
    text = base.decode("utf-8")
    if "\r" in text:
        raise DerivationError("config_not_lf")
    tree = config_tree(base)
    nodes = _assignments(text)
    edits: list[tuple[int, int, int]] = []  # (line, start column, end column), 1-based lines
    for path in TEST_PIPELINE_PATHS:
        pipeline = _pipeline(tree, path)
        list_node = _node_at(nodes, path)
        for transform, key in (("Resize", "scale"), ("Pad", "size")):
            index = _single_index(pipeline, transform, path)
            for item in _keyword(list_node.elts[index], key).elts:
                if item.value != BASE_SCALE or item.lineno != item.end_lineno:
                    raise DerivationError(f"config_base_unexpected:{'.'.join(path)}:{key}")
                edits.append((item.lineno, item.col_offset, item.end_col_offset))
    if len(edits) != 8 or len(set(edits)) != 8:
        raise DerivationError("config_derivation_edit_count")
    lines = text.split("\n")
    replacement = str(scale)
    # Right to left within a line, bottom to top across lines, so offsets stay valid.
    # ast columns are UTF-8 byte offsets; these lines are ASCII, which is checked.
    for line, start, end in sorted(edits, reverse=True):
        source = lines[line - 1]
        if not source.isascii() or source[start:end] != str(BASE_SCALE):
            raise DerivationError("config_derivation_offset_invalid")
        lines[line - 1] = source[:start] + replacement + source[end:]
    derived = "\n".join(lines).encode("utf-8")
    check_test_scale_derivation(base, derived, scale=scale)
    return derived


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--base-sha256", required=True)
    parser.add_argument("--scale", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    base = args.base.read_bytes()
    if _sha256(base) != args.base_sha256:
        print("base_sha256_mismatch", file=sys.stderr)
        return 2
    if args.output.exists():
        print("output_exists", file=sys.stderr)
        return 2
    derived = derive(base, scale=args.scale)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(derived)
    print(json.dumps({
        "baseSha256": args.base_sha256,
        "derivedSha256": _sha256(derived),
        "scale": args.scale,
        "differences": check_test_scale_derivation(base, derived, scale=args.scale),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
