from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest
import numpy as np


PROBE_PATH = Path(__file__).parents[3] / "tools" / "vision" / "probe_runtime.py"


class UnapprovedCheckpointMetadata:
    pass


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


def test_reviewed_checkpoint_globals_cover_legacy_and_numpy2_numpy_aliases() -> None:
    pytest.importorskip("mmengine")
    probe = _load_probe()

    aliases = {
        entry[1]
        for entry in probe.reviewed_checkpoint_globals()
        if isinstance(entry, tuple)
    }

    assert {
        "numpy.core.multiarray._reconstruct",
        "numpy._core.multiarray._reconstruct",
        "numpy.core.multiarray.scalar",
        "numpy._core.multiarray.scalar",
    }.issubset(aliases)


def test_real_torch_scope_allows_reviewed_numpy_metadata_and_restores_globals(
    tmp_path: Path,
) -> None:
    torch = pytest.importorskip("torch")
    pytest.importorskip("mmengine")
    probe = _load_probe()
    checkpoint = tmp_path / "reviewed-metadata.pth"
    torch.save({"metadata": np.array([1.5], dtype=np.float64)}, checkpoint)
    before = tuple(torch.serialization.get_safe_globals())

    with pytest.raises(Exception, match="Weights only load failed"):
        torch.load(checkpoint)

    with probe.restricted_checkpoint_loading_scope():
        loaded = torch.load(checkpoint)
        assert loaded["metadata"].tolist() == [1.5]

    assert tuple(torch.serialization.get_safe_globals()) == before


def test_real_torch_scope_rejects_unapproved_type_and_restores_globals(
    tmp_path: Path,
) -> None:
    torch = pytest.importorskip("torch")
    pytest.importorskip("mmengine")
    probe = _load_probe()
    checkpoint = tmp_path / "unapproved-metadata.pth"
    torch.save(UnapprovedCheckpointMetadata(), checkpoint)
    before = tuple(torch.serialization.get_safe_globals())

    with pytest.raises(Exception, match="Weights only load failed"):
        with probe.restricted_checkpoint_loading_scope():
            torch.load(checkpoint)

    assert tuple(torch.serialization.get_safe_globals()) == before


@pytest.mark.parametrize(
    ("labels", "class_count", "error"),
    [
        (np.array([np.nan]), 2, "prediction_labels_type_invalid"),
        (np.array([1.5]), 2, "prediction_labels_type_invalid"),
        (np.array([-1], dtype=np.int64), 2, "prediction_label_range_invalid"),
        (np.array([2], dtype=np.int64), 2, "prediction_label_range_invalid"),
    ],
)
def test_prediction_validation_rejects_invalid_labels(
    labels: np.ndarray,
    class_count: int,
    error: str,
) -> None:
    probe = _load_probe()

    with pytest.raises(RuntimeError, match=error):
        probe.validate_prediction_arrays(
            np.array([[0.0, 0.0, 1.0, 1.0]]),
            np.array([0.9]),
            labels,
            class_count=class_count,
        )


def test_prediction_validation_accepts_valid_empty_result() -> None:
    probe = _load_probe()

    probe.validate_prediction_arrays(
        np.empty((0, 4), dtype=np.float32),
        np.empty((0,), dtype=np.float32),
        np.empty((0,), dtype=np.int64),
        class_count=80,
    )


@pytest.mark.parametrize(
    ("boxes", "scores", "labels", "error"),
    [
        (
            np.array([0.0, 0.0, 1.0, 1.0]),
            np.array([0.9]),
            np.array([1], dtype=np.int64),
            "prediction_boxes_shape_invalid",
        ),
        (
            np.array([[0.0, 0.0, 1.0, 1.0]]),
            np.array([[0.9]]),
            np.array([1], dtype=np.int64),
            "prediction_vector_shape_invalid",
        ),
        (
            np.array([[0.0, 0.0, 1.0, 1.0]]),
            np.array([]),
            np.array([1], dtype=np.int64),
            "prediction_length_mismatch",
        ),
        (
            np.array([[0.0, 0.0, np.inf, 1.0]]),
            np.array([0.9]),
            np.array([1], dtype=np.int64),
            "prediction_numeric_value_invalid",
        ),
        (
            np.array([[0.0, 0.0, 1.0, 1.0]]),
            np.array([np.nan]),
            np.array([1], dtype=np.int64),
            "prediction_numeric_value_invalid",
        ),
    ],
)
def test_prediction_validation_rejects_malformed_outputs(
    boxes: np.ndarray,
    scores: np.ndarray,
    labels: np.ndarray,
    error: str,
) -> None:
    probe = _load_probe()

    with pytest.raises(RuntimeError, match=error):
        probe.validate_prediction_arrays(
            boxes,
            scores,
            labels,
            class_count=80,
        )


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
