from pathlib import Path

import pytest
from pydantic import ValidationError

from mavi_vision.common.settings import WorkerSettings


# Test helpers
def seed_required(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MAVI_API_BASE_URL", "https://mavi-api.local:62152/")
    monkeypatch.setenv("MAVI_WORKER_ID", "dev-worker-01")
    monkeypatch.setenv("MAVI_MEDIA_ROOT", str(tmp_path))


# Settings behavior
def test_settings_load_and_normalize(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seed_required(monkeypatch, tmp_path)
    settings = WorkerSettings()
    assert settings.api_base_url == "https://mavi-api.local:62152"
    assert settings.worker_id == "dev-worker-01"
    assert settings.media_root == tmp_path
    assert settings.poll_interval_seconds == 2.0
    assert settings.heartbeat_interval_seconds == 30.0
    assert settings.model_root == Path("models")
    assert settings.component_binding_path == Path(
        "src/vision/config/components/phase1-bindings-v2.json"
    )
    assert settings.role_id == "vision"
    assert settings.overlay_root == Path(".")
    assert settings.runtime_pack_manifest_path is None
    assert settings.completion_schema_override is None
    assert settings.pipeline_profile_path == Path(
        "src/vision/config/pipelines/phase1-detection-tracking-v1.json"
    )
    assert settings.deployment_profile_policy_path == Path(
        "config/acceptance/phase1-deployment-profiles-v1.json"
    )
    assert settings.deployment_profile is None
    assert settings.device_policy == "auto"
    assert settings.device_index == 0
    assert settings.device_resolution_reason is None
    assert settings.production_mode is False
    assert settings.inference_watchdog_seconds == 120.0
    assert settings.watchdog_grace_seconds == 15.0


def test_settings_reject_unsafe_worker_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seed_required(monkeypatch, tmp_path)
    monkeypatch.setenv("MAVI_WORKER_ID", "bad/worker")
    with pytest.raises(ValidationError):
        WorkerSettings()


@pytest.mark.parametrize(
    "url",
    [
        "mavi-api.local",
        "ftp://mavi-api.local",
        "https:///missing-host",
        "https://mavi-api.local?tenant=a",
        "https://mavi-api.local/#worker",
        "https://mavi-api.local?",
        "https://mavi-api.local#",
    ],
)
def test_settings_reject_invalid_api_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, url: str
) -> None:
    seed_required(monkeypatch, tmp_path)
    monkeypatch.setenv("MAVI_API_BASE_URL", url)
    with pytest.raises(ValidationError):
        WorkerSettings()

def test_settings_load_runtime_operational_selection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seed_required(monkeypatch, tmp_path)
    monkeypatch.setenv("MAVI_MODEL_ROOT", str(tmp_path / "models"))
    monkeypatch.setenv(
        "MAVI_COMPONENT_BINDING_PATH",
        str(tmp_path / "release" / "bindings.json"),
    )
    monkeypatch.setenv(
        "MAVI_PIPELINE_PROFILE_PATH",
        str(tmp_path / "release" / "profile.json"),
    )
    monkeypatch.setenv("MAVI_OVERLAY_ROOT", str(tmp_path / "overlay"))
    monkeypatch.setenv(
        "MAVI_RUNTIME_PACK_MANIFEST_PATH",
        str(tmp_path / "pack" / "runtime-pack-manifest.json"),
    )
    monkeypatch.setenv("MAVI_DEVICE_POLICY", "cuda")
    monkeypatch.setenv("MAVI_DEVICE_INDEX", "2")
    monkeypatch.setenv("MAVI_DEPLOYMENT_PROFILE", "P1")
    monkeypatch.setenv("MAVI_PRODUCTION_MODE", "true")
    monkeypatch.setenv("MAVI_INFERENCE_WATCHDOG_SECONDS", "180")
    monkeypatch.setenv("MAVI_WATCHDOG_GRACE_SECONDS", "20")

    settings = WorkerSettings()

    assert settings.model_root == tmp_path / "models"
    assert settings.component_binding_path == tmp_path / "release" / "bindings.json"
    assert settings.pipeline_profile_path == tmp_path / "release" / "profile.json"
    assert settings.overlay_root == tmp_path / "overlay"
    assert settings.runtime_pack_manifest_path == tmp_path / "pack" / "runtime-pack-manifest.json"
    assert settings.device_policy == "cuda"
    assert settings.device_index == 2
    assert settings.deployment_profile == "P1"
    assert settings.production_mode is True
    assert settings.inference_watchdog_seconds == 180.0
    assert settings.watchdog_grace_seconds == 20.0


def test_production_settings_reject_auto_device_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seed_required(monkeypatch, tmp_path)
    monkeypatch.setenv("MAVI_PRODUCTION_MODE", "true")
    monkeypatch.setenv("MAVI_DEVICE_POLICY", "auto")

    with pytest.raises(ValidationError, match="development-only"):
        WorkerSettings()


@pytest.mark.parametrize("device_policy", ["gpu", "CUDA", ""])
def test_settings_reject_invalid_device_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    device_policy: str,
) -> None:
    seed_required(monkeypatch, tmp_path)
    monkeypatch.setenv("MAVI_DEVICE_POLICY", device_policy)

    with pytest.raises(ValidationError):
        WorkerSettings()


def test_settings_reject_negative_device_index(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seed_required(monkeypatch, tmp_path)
    monkeypatch.setenv("MAVI_DEVICE_INDEX", "-1")

    with pytest.raises(ValidationError):
        WorkerSettings()


@pytest.mark.parametrize(
    ("watchdog", "grace"),
    [
        ("10", "10"),
        ("10", "11"),
        ("4", "1"),
        ("120", "0"),
    ],
)
def test_settings_reject_invalid_watchdog_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    watchdog: str,
    grace: str,
) -> None:
    seed_required(monkeypatch, tmp_path)
    monkeypatch.setenv("MAVI_INFERENCE_WATCHDOG_SECONDS", watchdog)
    monkeypatch.setenv("MAVI_WATCHDOG_GRACE_SECONDS", grace)

    with pytest.raises(ValidationError):
        WorkerSettings()


def test_the_completion_override_is_development_only_and_names_a_pre_cut_over_version(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # S2a.3 (plan P-16): the completion version is the role's provenanceContract
    # (3.2); the settings hold no version, only the explicit Development override.
    seed_required(monkeypatch, tmp_path)
    assert WorkerSettings().completion_schema_override is None
    assert "completion_schema_version" not in WorkerSettings.model_fields

    for version in ("3.0", "3.1"):
        monkeypatch.setenv("MAVI_COMPLETION_SCHEMA_OVERRIDE", version)
        assert WorkerSettings().completion_schema_override == version

    for unsupported in ("2.0", "3.2", "3.3", ""):
        monkeypatch.setenv("MAVI_COMPLETION_SCHEMA_OVERRIDE", unsupported)
        with pytest.raises(ValidationError):
            WorkerSettings()


def test_the_completion_override_is_refused_in_production(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seed_required(monkeypatch, tmp_path)
    monkeypatch.setenv("MAVI_PRODUCTION_MODE", "true")
    monkeypatch.setenv("MAVI_DEVICE_POLICY", "cpu")
    monkeypatch.setenv("MAVI_DEPLOYMENT_PROFILE", "P3")
    WorkerSettings()
    monkeypatch.setenv("MAVI_COMPLETION_SCHEMA_OVERRIDE", "3.1")
    with pytest.raises(ValidationError, match="completion_override_forbidden_in_production"):
        WorkerSettings()


@pytest.mark.parametrize(
    "name",
    [
        "MAVI_MODEL_MANIFEST_PATH",
        "MAVI_QUALIFICATION_RECORD_PATH",
        "MAVI_RUNTIME_PROFILE_PATH",
        "MAVI_COMPLETION_SCHEMA_VERSION",
    ],
)
def test_every_retired_v1_composition_variable_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str
) -> None:
    # No dual reader (plan P-9): a v1 selection is refused, never ignored, even
    # when empty, and whatever its case.
    seed_required(monkeypatch, tmp_path)
    for value in ("x", ""):
        monkeypatch.setenv(name, value)
        with pytest.raises(ValidationError, match=f"settings_v1_composition_rejected:{name}"):
            WorkerSettings()
    monkeypatch.delenv(name)
    monkeypatch.setenv(name.lower(), "x")
    with pytest.raises(ValidationError, match="settings_v1_composition_rejected"):
        WorkerSettings()


def test_every_retired_variable_is_named_in_one_refusal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seed_required(monkeypatch, tmp_path)
    monkeypatch.setenv("MAVI_RUNTIME_PROFILE_PATH", "x")
    monkeypatch.setenv("MAVI_MODEL_MANIFEST_PATH", "x")
    with pytest.raises(
        ValidationError,
        match="settings_v1_composition_rejected:MAVI_MODEL_MANIFEST_PATH,MAVI_RUNTIME_PROFILE_PATH",
    ):
        WorkerSettings()


@pytest.mark.parametrize(
    "field", ["model_manifest_path", "qualification_record_path", "runtime_profile_path", "completion_schema_version"]
)
def test_the_retired_fields_are_refused_as_constructor_arguments(tmp_path: Path, field: str) -> None:
    with pytest.raises(ValidationError, match="settings_v1_composition_rejected"):
        WorkerSettings(api_base_url="https://mavi-api.local", worker_id="w", media_root=tmp_path, **{field: "x"})


def test_the_pipeline_profile_variable_is_not_retired(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seed_required(monkeypatch, tmp_path)
    monkeypatch.setenv("MAVI_PIPELINE_PROFILE_PATH", str(tmp_path / "p.json"))
    assert WorkerSettings().pipeline_profile_path == tmp_path / "p.json"


def test_worker_settings_do_not_expose_analytical_tuning_knobs() -> None:
    forbidden = {
        "detector_inference_floor",
        "track_activation_threshold",
        "high_confidence_threshold",
        "reference_frame_rate",
        "minimum_iou_threshold",
        "minimum_matching_threshold",
        "minimum_consecutive_frames",
        "lost_track_buffer_seconds",
        "max_detections",
    }

    assert forbidden.isdisjoint(WorkerSettings.model_fields)



def test_settings_expose_explicit_release_evidence_and_build_identity_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seed_required(monkeypatch, tmp_path)

    settings = WorkerSettings()

    assert "qualification_record_path" not in WorkerSettings.model_fields
    assert settings.build_id is None
    assert settings.commit_sha is None


def test_settings_load_release_evidence_and_build_identity_from_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seed_required(monkeypatch, tmp_path)
    monkeypatch.setenv("MAVI_BUILD_ID", "mavi-2026.09.12")
    monkeypatch.setenv("MAVI_COMMIT_SHA", "a" * 40)

    settings = WorkerSettings()

    assert settings.build_id == "mavi-2026.09.12"
    assert settings.commit_sha == "a" * 40


def test_production_settings_require_deployment_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seed_required(monkeypatch, tmp_path)
    monkeypatch.setenv("MAVI_PRODUCTION_MODE", "true")
    monkeypatch.setenv("MAVI_DEVICE_POLICY", "cpu")

    with pytest.raises(
        ValidationError,
        match="MAVI_DEPLOYMENT_PROFILE is required",
    ):
        WorkerSettings()


@pytest.mark.parametrize("profile", ["P0", "p1", "P4", ""])
def test_settings_reject_invalid_deployment_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    profile: str,
) -> None:
    seed_required(monkeypatch, tmp_path)
    monkeypatch.setenv("MAVI_DEPLOYMENT_PROFILE", profile)

    with pytest.raises(ValidationError):
        WorkerSettings()


def test_settings_load_device_resolution_reason(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seed_required(monkeypatch, tmp_path)
    monkeypatch.setenv(
        "MAVI_DEVICE_RESOLUTION_REASON",
        "cuda_pack_not_declared",
    )

    settings = WorkerSettings()

    assert (
        settings.device_resolution_reason
        == "cuda_pack_not_declared"
    )


@pytest.mark.parametrize(
    "value",
    ["CUDA FALLBACK", "bad-reason", "", "x" * 65],
)
def test_settings_reject_invalid_device_resolution_reason(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    value: str,
) -> None:
    seed_required(monkeypatch, tmp_path)
    monkeypatch.setenv(
        "MAVI_DEVICE_RESOLUTION_REASON",
        value,
    )
    with pytest.raises(ValidationError):
        WorkerSettings()
