#!/usr/bin/env python3
"""Resolve an inherited MMDetection config into one self-contained local artifact.

This is qualification/release tooling. It accepts only filesystem paths, uses
MMEngine's supported Config load/dump path to materialize inherited settings,
normalizes the emitted Python file to UTF-8/LF bytes, rejects residual external
resolution syntax, reloads the artifact, and verifies deployment-relevant
configuration equivalence before reporting success.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import uuid
from collections.abc import Mapping
from pathlib import Path, PureWindowsPath
from typing import Any
from urllib.parse import urlsplit


class ConfigResolutionError(RuntimeError):
    pass


_RELEVANT_KEYS = (
    "default_scope",
    "model",
    "test_cfg",
    "test_dataloader",
    "test_evaluator",
    "tta_model",
    "tta_pipeline",
)

_FORBIDDEN_RESOLVED_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b_base_\b"), "resolved_config_contains_base_reference"),
    (re.compile(r"https?://", re.IGNORECASE), "resolved_config_contains_remote_url"),
    (re.compile(r"\{\{"), "resolved_config_contains_template_reference"),
    (re.compile(r"\$\{"), "resolved_config_contains_environment_reference"),
)


def parse_local_path(value: str) -> Path:
    """Accept a local path and reject URL/model-hub style inputs."""
    if PureWindowsPath(value).is_absolute():
        return Path(value)

    parts = urlsplit(value)
    if parts.scheme or parts.netloc:
        raise ConfigResolutionError("config_url_forbidden")
    return Path(value)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_python_bytes(text: str) -> bytes:
    """Return deterministic UTF-8/LF Python source bytes with one final newline."""
    if text.startswith("\ufeff"):
        text = text.removeprefix("\ufeff")
    text = text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n") + "\n"
    return text.encode("utf-8")


def validate_resolved_text(text: str) -> None:
    if text.startswith("\ufeff"):
        raise ConfigResolutionError("resolved_config_contains_bom")

    for pattern, error in _FORBIDDEN_RESOLVED_PATTERNS:
        if pattern.search(text):
            raise ConfigResolutionError(error)

    try:
        compile(text, "<resolved-mmdet-config>", "exec")
    except SyntaxError as exc:
        raise ConfigResolutionError("resolved_config_python_invalid") from exc


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_plain(item) for item in value)
    return value


def relevant_effective_config(config: Any) -> dict[str, Any]:
    raw = config.to_dict()
    return {key: _plain(raw[key]) for key in _RELEVANT_KEYS if key in raw}


def assert_relevant_equivalence(source: Any, resolved: Any) -> None:
    source_view = relevant_effective_config(source)
    resolved_view = relevant_effective_config(resolved)
    if source_view != resolved_view:
        raise ConfigResolutionError("resolved_config_semantics_mismatch")


def resolve_config(source_path: Path, output_path: Path) -> dict[str, Any]:
    if not source_path.is_file():
        raise ConfigResolutionError("source_config_missing")
    if output_path == source_path:
        raise ConfigResolutionError("resolved_config_must_not_overwrite_source")

    try:
        from mmengine import Config
    except ImportError as exc:
        raise ConfigResolutionError("mmengine_unavailable") from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    source = Config.fromfile(str(source_path))

    temp_path = output_path.with_name(
        f".{output_path.name}.{uuid.uuid4().hex}.mmengine.tmp.py"
    )
    try:
        source.dump(str(temp_path))
        emitted = temp_path.read_text(encoding="utf-8")
        normalized = normalized_python_bytes(emitted)
        normalized_text = normalized.decode("utf-8")
        validate_resolved_text(normalized_text)
        output_path.write_bytes(normalized)

        resolved = Config.fromfile(str(output_path))
        assert_relevant_equivalence(source, resolved)
    except ConfigResolutionError:
        output_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        output_path.unlink(missing_ok=True)
        raise ConfigResolutionError("resolved_config_generation_failed") from exc
    finally:
        temp_path.unlink(missing_ok=True)

    return {
        "status": "passed",
        "sourceConfig": {
            "path": str(source_path.resolve()),
            "sha256": sha256_file(source_path),
        },
        "resolvedConfig": {
            "path": str(output_path.resolve()),
            "sha256": sha256_file(output_path),
        },
        "relevantKeys": sorted(relevant_effective_config(resolved)),
        "format": "python",
        "encoding": "utf-8",
        "lineEndings": "lf",
        "selfContained": True,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=parse_local_path)
    parser.add_argument("--output", required=True, type=parse_local_path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
        result = resolve_config(args.input, args.output)
    except ConfigResolutionError as exc:
        print(str(exc), file=sys.stderr)
        print(json.dumps({"error": str(exc), "status": "failed"}, sort_keys=True))
        return 1

    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
