"""The ``embeddings`` role's contracts, identity, model math, settings and startup (PoC S4; ADR-021).

Runs without onnxruntime or sentencepiece: the ONNX adapter is exercised through a fake ``onnxruntime`` module, and
the real-model checks live outside pytest (the S4 smoke) because the pack is not in Git.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from mavi_vision.embeddings.contracts import EmbeddingLease, TextQueryLease
from mavi_vision.embeddings.identity import (
    EmbeddingIdentity,
    load_pipeline_profile,
    resolve_embedding_pack,
    verify_model_pack,
)
from mavi_vision.embeddings.model import (
    FixtureEmbeddingModel,
    OutputInvalid,
    decode_vector,
    encode_vector,
    l2_normalise_rows,
    mean_l2,
)
from mavi_vision.embeddings.onnx_model import DeviceResolution, create_sessions, load_onnx_model
from mavi_vision.embeddings.settings import EmbeddingWorkerSettings
from mavi_vision.embeddings.supervisor import EmbeddingRuntimeState, EmbeddingSupervisor, LoadedModel
from mavi_vision.embeddings.tokenizer import sentencepiece_ids

VISION_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = VISION_ROOT.parents[1]
CONTRACTS = REPOSITORY_ROOT / "contracts"
IDENTITY_VECTORS = CONTRACTS / "test-vectors" / "embedding-identity-v1.json"
FIXTURE_MANIFEST = VISION_ROOT / "tests" / "fixtures" / "model-manifests" / "embedding-fixture-v2.json"
FIXTURE_PROFILE = VISION_ROOT / "tests" / "fixtures" / "embeddings" / "fixture-pipeline-v1.json"


# --- identity ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("vector", json.loads(IDENTITY_VECTORS.read_text(encoding="utf-8"))["vectors"], ids=lambda v: v["name"])
def test_identity_matches_the_cross_language_vector(vector: dict) -> None:
    resolved = resolve_embedding_pack(REPOSITORY_ROOT / vector["modelManifest"], REPOSITORY_ROOT / vector["pipelineProfile"])
    assert resolved.identity.canonical == vector["canonicalIdentity"]
    assert resolved.identity.fingerprint == vector["fingerprint"]
    assert hashlib.sha256(vector["canonicalIdentity"].encode("utf-8")).hexdigest() == vector["fingerprint"]


def test_identity_matches_only_an_identical_leased_identity() -> None:
    example = json.loads((CONTRACTS / "examples" / "embedding-lease-v1.example.json").read_text(encoding="utf-8"))
    lease = EmbeddingLease.model_validate_json(json.dumps(example))
    identity = resolve_embedding_pack(REPOSITORY_ROOT / "models/manifests/embeddings-siglip2-base-p16-224-dev-v1.json",
                                      REPOSITORY_ROOT / "src/vision/config/embeddings/development-embeddings-siglip2-v1.json").identity
    assert identity.matches(lease.identity)
    tampered = dict(example["identity"], pipeline=dict(example["identity"]["pipeline"], version="1.0.1"))
    altered = EmbeddingLease.model_validate_json(json.dumps(dict(example, identity=tampered)))
    assert not identity.matches(altered.identity)


def test_profile_and_manifest_must_agree(tmp_path: Path) -> None:
    profile = json.loads(FIXTURE_PROFILE.read_text(encoding="utf-8"))
    (tmp_path / "profile.json").write_text(json.dumps(dict(profile, dimension=768)), encoding="utf-8")
    with pytest.raises(ValueError, match="^embedding_profile_dimension_mismatch$"):
        resolve_embedding_pack(FIXTURE_MANIFEST, tmp_path / "profile.json")
    (tmp_path / "profile.json").write_text(json.dumps(dict(profile, modelManifest="models/manifests/other.json")), encoding="utf-8")
    with pytest.raises(ValueError, match="^embedding_profile_manifest_mismatch$"):
        resolve_embedding_pack(FIXTURE_MANIFEST, tmp_path / "profile.json")
    (tmp_path / "profile.json").write_text(json.dumps(dict(profile, aggregation="max")), encoding="utf-8")
    with pytest.raises(ValueError, match="^embedding_pipeline_profile_invalid$"):
        load_pipeline_profile(tmp_path / "profile.json")


# --- contract examples ----------------------------------------------------------------------------------


def _example(name: str) -> dict:
    return json.loads((CONTRACTS / "examples" / f"{name}.example.json").read_text(encoding="utf-8"))


def test_lease_examples_parse_and_round_trip() -> None:
    for name, model in (("embedding-lease-v1", EmbeddingLease), ("embedding-text-query-lease-v1", TextQueryLease)):
        example = _example(name)
        parsed = model.model_validate_json(json.dumps(example))
        assert json.loads(parsed.model_dump_json()) == example


def test_lease_refuses_extra_members_and_the_capability_in_the_body() -> None:
    example = _example("embedding-lease-v1")
    with pytest.raises(ValueError):
        EmbeddingLease.model_validate_json(json.dumps(dict(example, leaseCapability="x" * 43)))


@pytest.mark.parametrize("name", ["embedding-complete-v1", "embedding-text-query-complete-v1"])
def test_completion_example_vectors_round_trip(name: str) -> None:
    example = _example(name)
    vectors = [track["embedding"] for track in example.get("tracks", []) if track["outcome"] == "embedded"] or [example.get("embedding")]
    for text in vectors:
        vector = decode_vector(text, 768)
        assert abs(float(np.linalg.norm(vector.astype(np.float64))) - 1.0) <= 1e-3
        assert encode_vector(vector, 768) == text


@pytest.mark.parametrize("name", ["embedding-lease-v1", "embedding-complete-v1", "embedding-text-query-lease-v1",
                                  "embedding-text-query-complete-v1"])
def test_examples_validate_against_their_schemas(name: str) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((CONTRACTS / "schemas" / f"{name}.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(_example(name))


# --- vectors and aggregation ----------------------------------------------------------------------------------


def test_mean_l2_normalises_each_crop_before_averaging() -> None:
    rows = np.array([[3.0, 0.0, 0.0], [0.0, 0.5, 0.0]], dtype=np.float32)
    vector = mean_l2(rows, 3)
    # A plain mean would weight the first crop six times more; mean-l2-v1 weights crops equally.
    assert np.allclose(vector, [2 ** -0.5, 2 ** -0.5, 0.0])
    assert abs(np.linalg.norm(vector) - 1.0) < 1e-12


@pytest.mark.parametrize("rows", [np.zeros((1, 3)), np.array([[np.nan, 1.0, 0.0]]), np.ones((1, 4)), np.ones(3)])
def test_invalid_model_output_is_refused(rows: np.ndarray) -> None:
    with pytest.raises(OutputInvalid):
        mean_l2(rows, 3)


def test_vectors_are_little_endian_float32_base64() -> None:
    vector = l2_normalise_rows(np.array([[1.0, 2.0, 2.0]]), 3)[0]
    text = encode_vector(vector, 3)
    assert base64.b64decode(text) == np.asarray(vector, dtype="<f4").tobytes()
    with pytest.raises(OutputInvalid):
        encode_vector(np.array([1.0, 1.0, 0.0]), 3)


def test_fixture_model_is_deterministic_and_unit_norm() -> None:
    model = FixtureEmbeddingModel(512)
    first, second = model.embed_images([b"a", b"b"]), model.embed_images([b"a", b"b"])
    assert first.shape == (2, 512) and np.array_equal(first, second)
    assert not np.allclose(first[0], first[1])
    assert np.allclose(np.linalg.norm(model.embed_texts(["white van"]), axis=1), 1.0, atol=1e-6)


# --- tokenizer ------------------------------------------------------------------------------------------------


class _CharacterProcessor:
    """A stand-in SentencePiece processor: one id per character, offset past the special ids."""

    def encode(self, text: str) -> list[int]:
        return [ord(character) + 10 for character in text]


def test_tokenizer_lowercases_appends_eos_and_pads_to_64() -> None:
    ids = sentencepiece_ids(_CharacterProcessor(), "A Car")
    assert ids[:6] == [ord(c) + 10 for c in "a car"] + [1]
    assert ids[6:] == [0] * 58 and len(ids) == 64


def test_tokenizer_truncates_to_63_tokens_before_eos() -> None:
    ids = sentencepiece_ids(_CharacterProcessor(), "x" * 200)
    assert len(ids) == 64 and ids[-1] == 1 and ids[:63] == [ord("x") + 10] * 63


def test_tokenizer_equals_the_pack_builder_rule() -> None:
    spec = importlib.util.spec_from_file_location("build_siglip2_pack", REPOSITORY_ROOT / "tools/vision/build_siglip2_pack.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    for text in ("a person wearing a red jacket", "Person, RED upper clothing", "", "y" * 100):
        assert sentencepiece_ids(_CharacterProcessor(), text) == module.sentencepiece_ids(_CharacterProcessor(), text)


# --- settings: Development only -------------------------------------------------------------------------------


def _settings(**overrides) -> dict:
    return {
        "api_base_url": "http://127.0.0.1:5000",
        "worker_id": "mavi-embeddings-1",
        "model_root": "models",
        "embedding_manifest_path": str(FIXTURE_MANIFEST),
        "pipeline_profile_path": str(FIXTURE_PROFILE),
        **overrides,
    }


def test_production_mode_is_refused_by_settings() -> None:
    with pytest.raises(ValueError, match="embedding_role_development_only"):
        EmbeddingWorkerSettings(**_settings(production_mode=True))


def test_settings_read_the_mavi_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _settings(device_policy="auto", cuda_dll_directory="E:/cuda").items():
        monkeypatch.setenv(f"MAVI_{key.upper()}", str(value))
    settings = EmbeddingWorkerSettings()  # type: ignore[call-arg]
    assert settings.device_policy == "auto" and settings.cuda_dll_directory == Path("E:/cuda")
    assert settings.text_query_poll_interval_seconds == 0.5
    monkeypatch.setenv("MAVI_PRODUCTION_MODE", "true")
    with pytest.raises(ValueError, match="embedding_role_development_only"):
        EmbeddingWorkerSettings()  # type: ignore[call-arg]


def test_heartbeat_must_fit_inside_the_minimum_lease() -> None:
    with pytest.raises(ValueError, match="embedding_heartbeat_margin_invalid"):
        EmbeddingWorkerSettings(**_settings(heartbeat_interval_seconds=40.0, request_timeout_seconds=10.0))


# --- the ONNX adapter's device policy, through a fake onnxruntime ---------------------------------------------


class _FakeSession:
    def __init__(self, path: str, sess_options=None, providers=None, *, active: str, log: list) -> None:
        log.append((Path(path).name, providers))
        self._active = active
        self._input = "pixel_values" if "vision" in path else "input_ids"
        self._output = "image_embeds" if "vision" in path else "text_embeds"

    def get_providers(self) -> list[str]:
        return [self._active] + (["CPUExecutionProvider"] if self._active != "CPUExecutionProvider" else [])

    def get_inputs(self):
        return [SimpleNamespace(name=self._input)]

    def get_outputs(self):
        return [SimpleNamespace(name=self._output)]


def _fake_ort(*, available: list[str], cuda_loads: bool) -> SimpleNamespace:
    log: list = []

    def session(path, sess_options=None, providers=None):
        wants_cuda = any((p[0] if isinstance(p, tuple) else p) == "CUDAExecutionProvider" for p in providers)
        active = "CUDAExecutionProvider" if wants_cuda and cuda_loads else "CPUExecutionProvider"
        return _FakeSession(path, sess_options, providers, active=active, log=log)

    return SimpleNamespace(
        __version__="1.31.0",
        get_available_providers=lambda: list(available),
        SessionOptions=lambda: SimpleNamespace(log_severity_level=0),
        InferenceSession=session,
        log=log,
    )


PATHS = (Path("vision.onnx"), Path("text.onnx"))


def test_explicit_cpu() -> None:
    _, resolution = create_sessions(_fake_ort(available=["CPUExecutionProvider"], cuda_loads=False), PATHS,
                                    device_policy="cpu", device_index=0)
    assert resolution == DeviceResolution("CPUExecutionProvider", "cpu", "explicit_cpu")


def test_cuda_fails_closed_when_the_provider_is_not_available() -> None:
    with pytest.raises(ValueError, match="^embedding_cuda_unavailable$"):
        create_sessions(_fake_ort(available=["CPUExecutionProvider"], cuda_loads=False), PATHS, device_policy="cuda", device_index=0)


def test_cuda_fails_closed_when_onnxruntime_silently_falls_back_to_cpu() -> None:
    ort = _fake_ort(available=["CUDAExecutionProvider", "CPUExecutionProvider"], cuda_loads=False)
    with pytest.raises(ValueError, match="^embedding_cuda_provider_inactive$"):
        create_sessions(ort, PATHS, device_policy="cuda", device_index=0)
    # Never asked for a CPU fallback in the first place.
    assert all(providers == [("CUDAExecutionProvider", {"device_id": 0})] for _, providers in ort.log)


def test_explicit_cuda_when_active() -> None:
    _, resolution = create_sessions(_fake_ort(available=["CUDAExecutionProvider", "CPUExecutionProvider"], cuda_loads=True),
                                    PATHS, device_policy="cuda", device_index=1)
    assert resolution == DeviceResolution("CUDAExecutionProvider", "cuda:1", "explicit_cuda")


@pytest.mark.parametrize(("available", "loads", "expected"), [
    (["CUDAExecutionProvider", "CPUExecutionProvider"], True, DeviceResolution("CUDAExecutionProvider", "cuda:0", "cuda_selected")),
    (["CUDAExecutionProvider", "CPUExecutionProvider"], False, DeviceResolution("CPUExecutionProvider", "cpu", "cuda_unavailable")),
    (["CPUExecutionProvider"], False, DeviceResolution("CPUExecutionProvider", "cpu", "cuda_unavailable")),
])
def test_auto_resolution(available, loads, expected) -> None:
    _, resolution = create_sessions(_fake_ort(available=available, cuda_loads=loads), PATHS, device_policy="auto", device_index=0)
    assert resolution == expected


def test_adapter_refuses_a_pack_without_its_artefact_roles() -> None:
    with pytest.raises(ValueError, match="^embedding_model_artifact_role_missing:onnx-vision-encoder$"):
        load_onnx_model({}, dimension=768, device_policy="cpu", ort=_fake_ort(available=[], cuda_loads=False))


# --- startup: every artefact verified before loading ----------------------------------------------------------


def _pack(tmp_path: Path, *, corrupt: bool = False) -> tuple[Path, Path, Path]:
    root = tmp_path / "models"
    pack = root / "embedding-fixture-v1"
    pack.mkdir(parents=True)
    (pack / "LICENSE").write_bytes(b"fixture licence\n")
    (pack / "weights.bin").write_bytes(b"fixture weights")
    manifest = json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))
    for artifact in manifest["artifacts"]:
        artifact["sha256"] = hashlib.sha256((root / artifact["relativePath"]).read_bytes()).hexdigest()
    if corrupt:
        (pack / "weights.bin").write_bytes(b"tampered weights")
    manifest_path = tmp_path / "embedding-fixture-v2.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return root, manifest_path, FIXTURE_PROFILE


class _FactorySpy:
    def __init__(self) -> None:
        self.calls: list = []

    def __call__(self, artifacts, dimension, settings) -> LoadedModel:
        self.calls.append(dict(artifacts))
        return LoadedModel(FixtureEmbeddingModel(dimension), DeviceResolution("CPUExecutionProvider", "cpu", "explicit_cpu"), "fixture")


def test_supervisor_verifies_every_artefact_then_loads(tmp_path: Path) -> None:
    root, manifest, profile = _pack(tmp_path)
    spy = _FactorySpy()
    supervisor = EmbeddingSupervisor(EmbeddingWorkerSettings(**_settings(model_root=str(root), embedding_manifest_path=str(manifest),
                                                                         pipeline_profile_path=str(profile))), model_factory=spy)
    supervisor.start()
    assert supervisor.state is EmbeddingRuntimeState.READY
    assert sorted(spy.calls[0]) == ["licence-notice", "weights"]
    runtime = supervisor.runtime
    assert runtime.provenance["identityFingerprint"] == runtime.identity.fingerprint
    assert runtime.provenance["roleId"] == "embeddings" and runtime.provenance["runtimeProfileId"] == "embeddings-onnx-v1"


def test_supervisor_refuses_a_tampered_artefact_before_loading(tmp_path: Path) -> None:
    root, manifest, profile = _pack(tmp_path, corrupt=True)
    spy = _FactorySpy()
    supervisor = EmbeddingSupervisor(EmbeddingWorkerSettings(**_settings(model_root=str(root), embedding_manifest_path=str(manifest),
                                                                         pipeline_profile_path=str(profile))), model_factory=spy)
    supervisor.start()
    assert supervisor.state is EmbeddingRuntimeState.UNAVAILABLE
    assert supervisor.unavailable_reason == "embedding_model_artifact_hash_mismatch:weights"
    assert spy.calls == []


def test_verify_refuses_a_missing_artefact(tmp_path: Path) -> None:
    root, manifest, _ = _pack(tmp_path)
    (root / "embedding-fixture-v1" / "LICENSE").unlink()
    from mavi_vision.embeddings.identity import load_embedding_manifest

    with pytest.raises(ValueError, match="^embedding_model_artifact_missing:licence-notice$"):
        verify_model_pack(load_embedding_manifest(manifest)[0], root)


def test_supervisor_refuses_production_mode_even_if_settings_were_bypassed(tmp_path: Path) -> None:
    root, manifest, profile = _pack(tmp_path)
    settings = EmbeddingWorkerSettings(**_settings(model_root=str(root), embedding_manifest_path=str(manifest),
                                                   pipeline_profile_path=str(profile)))
    settings.production_mode = True  # no assignment validation: the supervisor checks again
    spy = _FactorySpy()
    supervisor = EmbeddingSupervisor(settings, model_factory=spy)
    supervisor.start()
    assert supervisor.unavailable_reason == "embedding_role_development_only" and spy.calls == []


def test_identity_is_independent_of_device_and_provenance() -> None:
    identity = resolve_embedding_pack(FIXTURE_MANIFEST, FIXTURE_PROFILE).identity
    assert isinstance(identity, EmbeddingIdentity)
    assert set(identity.document()) == {"model", "pipeline", "schemaVersion"}


# --- runtime family ---------------------------------------------------------------------------------------------


def test_runtime_family_profile_and_lock_verify() -> None:
    from mavi_vision.runtime.qualification import verify_runtime_release_locks
    from mavi_vision.runtime.runtime_profile_v2 import load_runtime_profile_v2

    path = VISION_ROOT / "runtime" / "embeddings-onnx-v1" / "runtime.json"
    profile = load_runtime_profile_v2(path)
    assert profile.runtime_profile_id == "embeddings-onnx-v1" and profile.graph.development_only
    assert set(verify_runtime_release_locks(path, profile)) == {"windows-x86_64-cpu"}


# --- import boundary ----------------------------------------------------------------------------------------------

PACKAGE = VISION_ROOT / "mavi_vision" / "embeddings"
FORBIDDEN = frozenset({"torch", "torchvision", "mmcv", "mmdet", "mmengine", "transformers", "tokenizers"})
LAZY_ONLY = frozenset({"onnxruntime", "sentencepiece"})


def _modules() -> list[str]:
    return sorted(f"mavi_vision.embeddings.{path.stem}" for path in PACKAGE.glob("*.py") if path.stem != "__init__")


def test_embedding_modules_never_import_the_deep_learning_stack_and_import_runtimes_lazily() -> None:
    for path in PACKAGE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:  # module level: neither forbidden nor runtime-only packages
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else (
                [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            for name in names:
                assert name.split(".", 1)[0] not in FORBIDDEN | LAZY_ONLY, (path.name, name)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                assert all(name.split(".", 1)[0] not in FORBIDDEN for name in names), path.name


def test_importing_every_embedding_module_loads_no_model_runtime() -> None:
    script = (
        "import importlib, sys\n"
        f"for name in {_modules()!r}:\n"
        "    importlib.import_module(name)\n"
        f"loaded = sorted(name for name in sys.modules if name.split('.', 1)[0] in {sorted(FORBIDDEN | LAZY_ONLY)!r})\n"
        "print(','.join(loaded))\n"
    )
    result = subprocess.run([sys.executable, "-c", script], cwd=VISION_ROOT, capture_output=True, text=True, check=True)
    assert result.stdout.strip() == ""
