from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "inspect_production_logs.py"
SPEC = importlib.util.spec_from_file_location("inspect_logs", MODULE_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def test_external_url_is_rejected_from_clean_offline_log():
    external, suspicious = mod.inspect_text(
        "POST https://example.com/telemetry",
        allowed_hosts={"localhost", "127.0.0.1", "::1"},
    )
    assert external == ["https://example.com/telemetry"]
    assert suspicious


def test_internal_and_loopback_urls_are_allowed():
    external, suspicious = mod.inspect_text(
        "GET http://127.0.0.1/api/health\n"
        "GET https://mavi-api.local/api/tracks",
        allowed_hosts={
            "localhost",
            "127.0.0.1",
            "::1",
            "mavi-api.local",
        },
    )
    assert external == []
    assert suspicious == []


def test_licence_or_telemetry_indicator_is_rejected_even_without_url():
    external, suspicious = mod.inspect_text(
        "attempting license activation",
        allowed_hosts={"localhost", "127.0.0.1", "::1"},
    )
    assert external == []
    assert suspicious == ["attempting license activation"]


def test_external_dns_name_cannot_be_allowlisted():
    import pytest

    with pytest.raises(
        mod.LogInspectionError,
        match="production_allowed_host_not_internal",
    ):
        mod.validate_allowed_host("example.com")


def test_private_or_internal_hosts_can_be_allowlisted():
    assert mod.validate_allowed_host("10.10.0.5") == "10.10.0.5"
    assert mod.validate_allowed_host("mavi-api.internal") == "mavi-api.internal"
    assert mod.validate_allowed_host("mavi-db") == "mavi-db"


def test_non_http_external_locator_is_rejected():
    external, suspicious = mod.inspect_text(
        "loading s3://bucket/model",
        allowed_hosts={"localhost", "127.0.0.1", "::1"},
    )
    assert external == ["s3://bucket/model"]
    assert suspicious == []
