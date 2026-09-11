from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest


PROBE_PATH = Path(__file__).parents[3] / "tools" / "vision" / "probe_runtime.py"


def _load_probe():
    spec = importlib.util.spec_from_file_location("probe_runtime", PROBE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("probe_module_unloadable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rejects_missing_checkpoint_before_heavy_imports(tmp_path: Path) -> None:
    probe = _load_probe()
    config = tmp_path / "resolved.py"
    config.write_text("model = {}\n", encoding="utf-8")

    with pytest.raises(probe.ProbeConfigurationError, match="checkpoint_missing"):
        probe.validate_local_artifacts(
            config,
            tmp_path / "missing.pth",
            expected_checkpoint_sha256="0" * 64,
        )


def test_rejects_digest_mismatch_before_heavy_imports(tmp_path: Path) -> None:
    probe = _load_probe()
    config = tmp_path / "resolved.py"
    checkpoint = tmp_path / "model.pth"
    config.write_text("model = {}\n", encoding="utf-8")
    checkpoint.write_bytes(b"model")

    with pytest.raises(probe.ProbeConfigurationError, match="checkpoint_digest_mismatch"):
        probe.validate_local_artifacts(
            config,
            checkpoint,
            expected_checkpoint_sha256="0" * 64,
        )


def test_rejects_non_file_config(tmp_path: Path) -> None:
    probe = _load_probe()
    checkpoint = tmp_path / "model.pth"
    checkpoint.write_bytes(b"model")

    with pytest.raises(probe.ProbeConfigurationError, match="config_missing"):
        probe.validate_local_artifacts(
            tmp_path / "missing.py",
            checkpoint,
            expected_checkpoint_sha256="0" * 64,
        )


def test_checkpoint_permissions_are_explicit_and_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = _load_probe()
    active: list[object] = []
    observed: list[list[object]] = []

    class FakeSafeGlobals:
        def __init__(self, approved: list[object]) -> None:
            self.approved = approved

        def __enter__(self) -> None:
            active.extend(self.approved)
            observed.append(list(self.approved))

        def __exit__(self, *_args: object) -> None:
            active.clear()

    fake_torch = types.SimpleNamespace(
        serialization=types.SimpleNamespace(safe_globals=FakeSafeGlobals)
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setattr(probe, "reviewed_checkpoint_globals", lambda: ["reviewed"])

    with probe.restricted_checkpoint_loading_scope():
        assert active == ["reviewed"]

    assert observed == [["reviewed"]]
    assert active == []


def test_checkpoint_permissions_are_removed_after_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = _load_probe()
    active: list[object] = []

    class FakeSafeGlobals:
        def __init__(self, approved: list[object]) -> None:
            self.approved = approved

        def __enter__(self) -> None:
            active.extend(self.approved)

        def __exit__(self, *_args: object) -> None:
            active.clear()

    def restricted_load(required_type: object) -> None:
        if required_type not in active:
            raise RuntimeError("unapproved_checkpoint_type")

    monkeypatch.setitem(
        sys.modules,
        "torch",
        types.SimpleNamespace(
            serialization=types.SimpleNamespace(
                safe_globals=FakeSafeGlobals,
                load=restricted_load,
            )
        ),
    )
    monkeypatch.setattr(probe, "reviewed_checkpoint_globals", lambda: ["reviewed"])

    with pytest.raises(RuntimeError, match="unapproved_checkpoint_type"):
        with probe.restricted_checkpoint_loading_scope():
            fake_torch = sys.modules["torch"]
            fake_torch.serialization.load("unapproved")

    assert active == []


def test_rejects_remote_artifact_syntax() -> None:
    probe = _load_probe()

    with pytest.raises(probe.ProbeConfigurationError, match="artifact_url_forbidden"):
        probe.parse_local_path("https://example.invalid/model.pth")


def test_parse_local_path_accepts_relative_and_windows_absolute_filesystem_paths() -> None:
    probe = _load_probe()

    assert probe.parse_local_path("models/rtmdet.pth") == Path("models/rtmdet.pth")
    windows_absolute = r"C:\models\rtmdet.pth"
    assert probe.parse_local_path(windows_absolute) == Path(windows_absolute)


def test_unexpected_runtime_failure_emits_marker_and_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    probe = _load_probe()
    config = tmp_path / "resolved.py"
    checkpoint = tmp_path / "model.pth"
    config.write_text("model = {}\n", encoding="utf-8")
    checkpoint.write_bytes(b"model")

    def fail_probe(*_args, **_kwargs):
        raise RuntimeError("synthetic_inference_failure")

    monkeypatch.setattr(probe, "run_probe", fail_probe)

    exit_code = probe.main(
        [
            "--config",
            str(config),
            "--checkpoint",
            str(checkpoint),
            "--checkpoint-sha256",
            probe.sha256_file(checkpoint),
            "--device",
            "cpu",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "runtime_probe_failed:RuntimeError:synthetic_inference_failure" in captured.err
    assert "Traceback (most recent call last)" in captured.err
    assert "RuntimeError: synthetic_inference_failure" in captured.err
    assert json.loads(captured.out) == {
        "error": "synthetic_inference_failure",
        "errorType": "RuntimeError",
        "status": "failed",
    }
