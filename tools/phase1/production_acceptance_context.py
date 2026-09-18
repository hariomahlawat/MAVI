#!/usr/bin/env python3
"""Shared validation for the immutable Task-17 production acceptance context."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


class AcceptanceContextError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_context(
    path: Path,
    *,
    schema_path: Path,
    expected_source_commit: str,
    expected_mavi_build: str,
) -> tuple[dict[str, Any], str]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AcceptanceContextError("production_acceptance_context_invalid") from exc
    if not isinstance(value, dict) or not isinstance(schema, dict):
        raise AcceptanceContextError("production_acceptance_context_invalid")
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        raise AcceptanceContextError("production_acceptance_context_schema_invalid")
    if (
        value.get("sourceCommit") != expected_source_commit
        or value.get("maviBuild") != expected_mavi_build
    ):
        raise AcceptanceContextError("production_acceptance_context_identity_mismatch")
    return value, sha256_file(path)
