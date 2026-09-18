"""The Windows CUDA build contract must fail closed until the toolchain is frozen."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
VERIFY_REPO_PATH = ROOT / "tools" / "verify_repo.py"
CONTRACT_RELATIVE = "config/vision/windows-cuda-development-build-v1.json"
CATALOG_RELATIVE = "config/dependencies/offline-binary-catalog-v1.json"
LOCK_RELATIVE = (
    "src/vision/runtime/mmdetection-phase1-v1/windows-x86_64-cuda.lock"
)


def CONTRACT_RELATIVE_TEXT() -> str:
    return (ROOT / CONTRACT_RELATIVE).read_text(encoding="utf-8")


def _load_verify_repo():
    spec = importlib.util.spec_from_file_location(
        "verify_repo_cuda_contract",
        VERIFY_REPO_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("verify_repo_module_unloadable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


# The staged toolchain blocks are built from a fixed base rather than from the
# repository's live contract. Merging onto the live contract would make these
# guardrail cases stop testing anything the moment R1 freezes a real toolchain.
_BASE_CONTRACT_TOOLCHAIN = {
    "cudaToolkitVersion": "12.4",
    "rule": "No Windows CUDA lock or Runtime Pack may be frozen until nvcc "
    "successfully compiles a trivial .cu file with the selected MSVC toolset "
    "and Windows SDK.",
}
_BASE_CATALOG_TOOLCHAIN = {
    "policyId": "msvc-cuda-build-toolchain-win-x64",
}


def _stage(
    tmp_path: Path,
    *,
    contract_toolchain: dict,
    catalog_toolchain: dict,
    with_lock: bool,
) -> Path:
    contract = json.loads(
        (ROOT / CONTRACT_RELATIVE).read_text(encoding="utf-8")
    )
    contract["toolchain"] = {
        **_BASE_CONTRACT_TOOLCHAIN,
        **contract_toolchain,
    }
    _write(tmp_path / CONTRACT_RELATIVE, contract)

    catalog = json.loads((ROOT / CATALOG_RELATIVE).read_text(encoding="utf-8"))
    candidate = catalog["visionRuntime"]["windowsCudaDevelopmentCandidate"]
    candidate["buildToolchain"] = {
        **_BASE_CATALOG_TOOLCHAIN,
        **catalog_toolchain,
    }
    _write(tmp_path / CATALOG_RELATIVE, catalog)

    if with_lock:
        lock = tmp_path / LOCK_RELATIVE
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("# frozen\n", encoding="utf-8")
    return tmp_path


def _run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    module = _load_verify_repo()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    errors: list[str] = []
    module.check_windows_cuda_build_contract(errors)
    return errors


_FROZEN_CONTRACT = {
    "verificationStatus": "verified",
    "msvcToolset": "14.39.33519",
    "windowsSdkVersion": "10.0.22621.0",
    "cudaToolkitVersion": "12.4",
}
_FROZEN_CATALOG = {
    "msvcToolset": "14.39.33519",
    "windowsSdk": "10.0.22621.0",
    "cudaToolkit": "12.4",
}


def test_repository_head_contract_passes_without_a_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_verify_repo()
    errors: list[str] = []
    module.check_windows_cuda_build_contract(errors)

    assert errors == []


@pytest.mark.parametrize(
    "contract_toolchain",
    [
        {},
        {"verificationStatus": "verified"},
        {"verificationStatus": "verified", "msvcToolset": "14.39.33519"},
        {
            "verificationStatus": "pending-r1-preflight",
            "msvcToolset": "14.39.33519",
            "windowsSdkVersion": "10.0.22621.0",
        },
        {
            "verificationStatus": "verified",
            "msvcToolset": "pending-something-else",
            "windowsSdkVersion": "10.0.22621.0",
        },
        {
            "verificationStatus": "verified",
            "msvcToolset": None,
            "windowsSdkVersion": None,
        },
    ],
)
def test_cuda_lock_is_refused_until_the_toolchain_is_frozen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    contract_toolchain: dict,
) -> None:
    """Absence, null and any placeholder must block the lock, not just one sentinel."""
    _stage(
        tmp_path,
        contract_toolchain=contract_toolchain,
        catalog_toolchain=_FROZEN_CATALOG,
        with_lock=True,
    )

    errors = _run(tmp_path, monkeypatch)

    assert any("Windows CUDA lock cannot be committed" in item for item in errors)


def test_cuda_lock_is_refused_when_only_the_catalogue_is_frozen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Freezing the weaker source of truth must not open the gate."""
    _stage(
        tmp_path,
        contract_toolchain={"verificationStatus": "pending-r1-preflight"},
        catalog_toolchain=_FROZEN_CATALOG,
        with_lock=True,
    )

    errors = _run(tmp_path, monkeypatch)

    assert any("Windows CUDA lock cannot be committed" in item for item in errors)


def test_cuda_lock_is_refused_when_only_the_contract_is_frozen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stage(
        tmp_path,
        contract_toolchain=_FROZEN_CONTRACT,
        catalog_toolchain={"msvcToolset": "pending-r1-preflight"},
        with_lock=True,
    )

    errors = _run(tmp_path, monkeypatch)

    assert any("Windows CUDA lock cannot be committed" in item for item in errors)


def test_cuda_lock_is_accepted_once_both_sources_are_frozen_and_agree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stage(
        tmp_path,
        contract_toolchain=_FROZEN_CONTRACT,
        catalog_toolchain=_FROZEN_CATALOG,
        with_lock=True,
    )

    assert _run(tmp_path, monkeypatch) == []


def test_frozen_toolchain_identities_must_not_drift_apart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stage(
        tmp_path,
        contract_toolchain=_FROZEN_CONTRACT,
        catalog_toolchain={**_FROZEN_CATALOG, "msvcToolset": "14.44.00000"},
        with_lock=False,
    )

    errors = _run(tmp_path, monkeypatch)

    assert any("disagree" in item for item in errors)


def test_verified_status_requires_a_complete_toolchain_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The contract may not claim verification without naming what was verified."""
    _stage(
        tmp_path,
        contract_toolchain={"verificationStatus": "verified"},
        catalog_toolchain=_FROZEN_CATALOG,
        with_lock=False,
    )

    errors = _run(tmp_path, monkeypatch)

    assert any("claims a verified toolchain" in item for item in errors)


def test_runtime_policy_must_keep_explicit_cuda_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stage(
        tmp_path,
        contract_toolchain={"verificationStatus": "pending-r1-preflight"},
        catalog_toolchain=_FROZEN_CATALOG,
        with_lock=False,
    )
    contract_path = tmp_path / CONTRACT_RELATIVE
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["runtimePolicy"]["explicitCudaMayFallbackToCpu"] = True
    _write(contract_path, contract)

    errors = _run(tmp_path, monkeypatch)

    assert any("fail-closed" in item for item in errors)


def test_repository_contract_records_the_r1_verified_toolchain() -> None:
    """The frozen identity is empirical evidence; it may not drift silently."""
    toolchain = json.loads(
        (ROOT / CONTRACT_RELATIVE).read_text(encoding="utf-8")
    )["toolchain"]

    assert toolchain["verificationStatus"] == "verified"
    assert toolchain["cudaToolkitVersion"] == "12.4"
    assert toolchain["msvcToolset"] == "14.44.35207"
    assert toolchain["windowsSdkVersion"] == "10.0.26100.0"
    assert toolchain["msvcCompilerVersion"] == "19.44.35222"


def test_repository_contract_and_catalogue_agree_on_the_frozen_toolchain() -> None:
    """One frozen toolchain identity, not two that can drift apart."""
    toolchain = json.loads(
        (ROOT / CONTRACT_RELATIVE).read_text(encoding="utf-8")
    )["toolchain"]
    catalogue = json.loads(
        (ROOT / CATALOG_RELATIVE).read_text(encoding="utf-8")
    )["visionRuntime"]["windowsCudaDevelopmentCandidate"]["buildToolchain"]

    assert catalogue["cudaToolkit"] == toolchain["cudaToolkitVersion"]
    assert catalogue["msvcToolset"] == toolchain["msvcToolset"]
    assert catalogue["windowsSdk"] == toolchain["windowsSdkVersion"]


def test_r1_evidence_binds_the_verified_toolchain_to_its_observations() -> None:
    """A verified toolchain must name the evidence that verified it."""
    evidence = json.loads(
        (ROOT / CONTRACT_RELATIVE).read_text(encoding="utf-8")
    )["toolchain"]["evidence"]

    assert evidence["probeExitCode"] == 0
    assert evidence["probeArchitecture"] == "-arch=sm_75"
    assert len(evidence["verifiedAtSourceHeadSha"]) == 40
    assert len(evidence["hostObservationSha256"]) == 64
    assert len(evidence["torchWheelSha256"]) == 64
    assert evidence["torchWheelFilename"].endswith("-cp312-cp312-win_amd64.whl")
    assert "+cu124" in evidence["torchWheelFilename"]


def test_verified_toolchain_does_not_imply_any_cuda_qualification() -> None:
    """R1 verifies a build toolchain; it qualifies nothing."""
    contract = json.loads(
        (ROOT / CONTRACT_RELATIVE).read_text(encoding="utf-8")
    )
    catalogue = json.loads(
        (ROOT / CATALOG_RELATIVE).read_text(encoding="utf-8")
    )["visionRuntime"]["windowsCudaDevelopmentCandidate"]
    runtime = json.loads(
        (
            ROOT / "src/vision/runtime/mmdetection-phase1-v1/runtime.json"
        ).read_text(encoding="utf-8")
    )

    assert contract["runtimePolicy"]["explicitCudaMayFallbackToCpu"] is False
    assert "not a Production-supported runtime" in catalogue["qualificationBoundary"]
    assert (
        runtime["platformVariants"]["windows-x86_64-cuda"]["status"]
        == "pending-hardware-qualification"
    )
    assert runtime["qualificationStatus"] == "partial"


@pytest.mark.parametrize(
    "value",
    ["TODO", "n/a", "N/A", "FIXME", "???", "xxx", "placeholder", "none", "-", "0", "14.44"],
)
def test_a_non_version_identity_is_not_a_frozen_toolchain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    """Identities are validated by shape, not by a list of known placeholders."""
    _stage(
        tmp_path,
        contract_toolchain={**_FROZEN_CONTRACT, "msvcToolset": value},
        catalog_toolchain={**_FROZEN_CATALOG, "msvcToolset": value},
        with_lock=True,
    )

    errors = _run(tmp_path, monkeypatch)

    assert any("claims a verified toolchain" in item for item in errors)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cudaToolkitVersion", "12"),
        ("cudaToolkitVersion", "12.4.1"),
        ("windowsSdkVersion", "10.0.26100"),
        ("msvcToolset", "14.44"),
    ],
)
def test_malformed_version_identities_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str,
) -> None:
    _stage(
        tmp_path,
        contract_toolchain={**_FROZEN_CONTRACT, field: value},
        catalog_toolchain=_FROZEN_CATALOG,
        with_lock=False,
    )

    errors = _run(tmp_path, monkeypatch)

    assert any("claims a verified toolchain" in item for item in errors)


def test_verified_contract_requires_the_catalogue_identity_even_without_a_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The catalogue may not quietly lack an identity the contract asserts."""
    _stage(
        tmp_path,
        contract_toolchain=_FROZEN_CONTRACT,
        catalog_toolchain={"policyId": "msvc-cuda-build-toolchain-win-x64"},
        with_lock=False,
    )

    errors = _run(tmp_path, monkeypatch)

    assert any(
        "catalogue does not carry the frozen toolchain identity" in item
        for item in errors
    )


def test_descriptive_top_level_status_is_never_proof_of_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`status` is descriptive. Only the frozen toolchain identity is proof.

    A contract whose top-level status reads as verified while its toolchain is
    still pending must not permit a CUDA lock.
    """
    _stage(
        tmp_path,
        contract_toolchain={
            "cudaToolkitVersion": "12.4",
            "verificationStatus": "pending-r1-preflight",
        },
        catalog_toolchain=_FROZEN_CATALOG,
        with_lock=True,
    )
    contract_path = tmp_path / CONTRACT_RELATIVE
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["status"] = "r1-toolchain-verified-pre-c2"
    _write(contract_path, contract)

    errors = _run(tmp_path, monkeypatch)

    assert any("Windows CUDA lock cannot be committed" in item for item in errors)


def _runtime_pack_tool():
    spec = importlib.util.spec_from_file_location(
        "build_runtime_pack",
        ROOT / "tools" / "vision" / "build_runtime_pack.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("build_runtime_pack_unloadable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_native_abi_is_derived_from_the_verified_toolchain() -> None:
    """Hand-typing the ABI is how it drifts from the toolchain R1 proved."""
    module = _runtime_pack_tool()
    contract = json.loads(CONTRACT_RELATIVE_TEXT())

    assert module.derive_native_abi(contract) == (
        "win_amd64-msvc-14.44.35207-sdk-10.0.26100.0-cuda12.4-sm75"
    )


def test_committed_native_abi_matches_the_derivation() -> None:
    module = _runtime_pack_tool()
    contract = json.loads(CONTRACT_RELATIVE_TEXT())

    assert contract["nativeAbi"] == module.derive_native_abi(contract)


def test_derived_native_abi_satisfies_the_runtime_pack_rule() -> None:
    """The derived string must pass the same check any supplied one does."""
    module = _runtime_pack_tool()
    contract = json.loads(CONTRACT_RELATIVE_TEXT())

    module._validate_native_abi_for_variant(
        module.derive_native_abi(contract), "windows-x86_64-cuda"
    )
    with pytest.raises(module.RuntimePackError):
        module._validate_native_abi_for_variant(
            module.derive_native_abi(contract), "windows-x86_64-cpu"
        )


def test_native_abi_tracks_a_changed_toolchain() -> None:
    module = _runtime_pack_tool()
    contract = json.loads(CONTRACT_RELATIVE_TEXT())
    contract["toolchain"] = {**contract["toolchain"], "msvcToolset": "14.39.33519"}

    assert "msvc-14.39.33519" in module.derive_native_abi(contract)


def test_native_abi_tracks_a_changed_target_architecture() -> None:
    module = _runtime_pack_tool()
    contract = json.loads(CONTRACT_RELATIVE_TEXT())
    contract["targetGpu"] = {**contract["targetGpu"], "computeCapability": "8.6"}

    assert module.derive_native_abi(contract).endswith("-sm86")


def test_an_unverified_toolchain_has_no_native_abi() -> None:
    """An unverified toolchain has no proven identity to name."""
    module = _runtime_pack_tool()
    contract = json.loads(CONTRACT_RELATIVE_TEXT())
    contract["toolchain"] = {
        **contract["toolchain"],
        "verificationStatus": "pending-r1-preflight",
    }

    with pytest.raises(
        module.NativeAbiDerivationError, match="native_abi_toolchain_not_verified"
    ):
        module.derive_native_abi(contract)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("msvcToolset", "14.44"),
        ("msvcToolset", "TODO"),
        ("windowsSdkVersion", "10.0.26100"),
        ("cudaToolkitVersion", "12"),
    ],
)
def test_a_malformed_toolchain_field_has_no_native_abi(
    field: str, value: str
) -> None:
    module = _runtime_pack_tool()
    contract = json.loads(CONTRACT_RELATIVE_TEXT())
    contract["toolchain"] = {**contract["toolchain"], field: value}

    with pytest.raises(
        module.NativeAbiDerivationError, match="native_abi_contract_field_invalid"
    ):
        module.derive_native_abi(contract)


def test_native_abi_derivation_refuses_a_non_cuda_variant() -> None:
    module = _runtime_pack_tool()
    contract = json.loads(CONTRACT_RELATIVE_TEXT())
    contract["platformVariant"] = "windows-x86_64-cpu"

    with pytest.raises(
        module.NativeAbiDerivationError,
        match="native_abi_platform_variant_unsupported",
    ):
        module.derive_native_abi(contract)
