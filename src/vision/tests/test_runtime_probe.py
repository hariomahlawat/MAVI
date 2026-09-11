from __future__ import annotations

import importlib.util
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
        probe.validate_local_artifacts(config, tmp_path / "missing.pth")


def test_rejects_non_file_config(tmp_path: Path) -> None:
    probe = _load_probe()
    checkpoint = tmp_path / "model.pth"
    checkpoint.write_bytes(b"model")

    with pytest.raises(probe.ProbeConfigurationError, match="config_missing"):
        probe.validate_local_artifacts(tmp_path / "missing.py", checkpoint)


def test_rejects_remote_artifact_syntax() -> None:
    probe = _load_probe()

    with pytest.raises(probe.ProbeConfigurationError, match="artifact_url_forbidden"):
        probe.parse_local_path("https://example.invalid/model.pth")


def test_parse_local_path_accepts_relative_or_absolute_filesystem_paths() -> None:
    probe = _load_probe()

    assert probe.parse_local_path("models/rtmdet.pth") == Path("models/rtmdet.pth")


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
            "--device",
            "cpu",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "runtime_probe_failed:RuntimeError:synthetic_inference_failure" in captured.err
    assert "Traceback (most recent call last)" in captured.err
    assert "RuntimeError: synthetic_inference_failure" in captured.err
