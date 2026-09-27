from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from mavi_vision.runtime.binding import parse_component_binding
from mavi_vision.runtime.model_manifest_v2 import parse_model_manifest_v2
from mavi_vision.runtime.qualification_v2 import parse_qualification_record_v2
from mavi_vision.runtime.runtime_profile_v2 import parse_runtime_profile_v2
from tests.component_binding_v2_fixtures import (
    GATE_SETS,
    V1_BINDING,
    V1_MANIFEST,
    V1_QUALIFICATION,
    V1_RUNTIME_PROFILE,
    gate_sets,
    generate,
    load_migration_tool,
)

V1_FILES = (V1_BINDING, V1_MANIFEST, V1_RUNTIME_PROFILE, V1_QUALIFICATION)


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _copy_v1(tmp_path: Path) -> dict[str, Path]:
    runtime_dir = tmp_path / "runtime" / "mmdetection-phase1-v1"
    runtime_dir.mkdir(parents=True)
    for item in V1_RUNTIME_PROFILE.parent.iterdir():
        shutil.copy2(item, runtime_dir / item.name)
    paths = {
        "v1_binding": tmp_path / "binding-v1.json",
        "v1_manifest": tmp_path / "manifest-v1.json",
        "v1_runtime_profile": runtime_dir / "runtime.json",
        "v1_qualification": tmp_path / "qualification-v1.json",
    }
    shutil.copy2(V1_BINDING, paths["v1_binding"])
    shutil.copy2(V1_MANIFEST, paths["v1_manifest"])
    shutil.copy2(V1_QUALIFICATION, paths["v1_qualification"])
    return paths


def _edit(path: Path, mutate) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    mutate(document)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def _rebind_record(paths: dict[str, Path]) -> None:
    """Keep the copied v1 record consistent with edited v1 files."""
    manifest_sha = _sha(paths["v1_manifest"].read_bytes())
    profile_sha = _sha(paths["v1_runtime_profile"].read_bytes())
    _edit(paths["v1_qualification"], lambda d: d.update(modelManifestSha256=manifest_sha, runtimeProfileSha256=profile_sha))


def test_generated_documents_load_and_relate(tmp_path) -> None:
    documents = generate(tmp_path)
    binding = parse_component_binding(json.loads(documents["binding"]), component_binding_sha256=_sha(documents["binding"]))
    manifest = parse_model_manifest_v2(json.loads(documents["manifest"]))
    profile = parse_runtime_profile_v2(json.loads(documents["runtimeProfile"]))
    record = parse_qualification_record_v2(json.loads(documents["qualification"]), gate_sets=gate_sets())
    (detector,) = binding.capability_bindings
    assert detector.model_pack_id == manifest.model_pack_id == record.model_pack_id
    assert detector.qualification_id == record.qualification_id
    assert record.model_manifest_sha256 == _sha(documents["manifest"])
    assert record.runtime_profile_sha256 == _sha(documents["runtimeProfile"])
    assert record.runtime_pack_family_id == profile.runtime_pack_family_id
    assert dict(record.artifact_sha256) == {a.artifact_role: a.sha256 for a in manifest.artifacts}


def test_rtmdet_stays_pending_and_unverified(tmp_path) -> None:
    documents = generate(tmp_path)
    manifest = json.loads(documents["manifest"])
    record = json.loads(documents["qualification"])
    assert manifest["verificationStatus"] == "unverified" and manifest["qualificationId"] is None
    assert manifest["licence"]["reviewStatus"] == "pending-review"
    assert record["overallResult"] == "pending" and record["evidence"] == {} and record["profileQualifications"] == {}
    assert {status for v in record["variants"].values() for status in (v["status"], *v["gates"].values())} == {"pending"}


def test_linux_cuda_is_carried_as_known_not_releasable_without_a_fake_pack(tmp_path) -> None:
    documents = generate(tmp_path)
    binding = json.loads(documents["binding"])
    record = json.loads(documents["qualification"])
    assert "linux-x86_64-cuda" not in binding["runtimePacks"][0]["variants"]
    assert record["variants"]["linux-x86_64-cuda"]["runtimePackId"] is None


def test_output_is_deterministic_and_leaves_v1_untouched(tmp_path) -> None:
    before = {path: _sha(path.read_bytes()) for path in V1_FILES}
    first = generate(tmp_path / "a")
    second = generate(tmp_path / "b")
    assert first == second
    assert all(value.endswith(b"\n") and b"\r" not in value for value in first.values())
    assert {path: _sha(path.read_bytes()) for path in V1_FILES} == before


def test_licence_notice_bytes_participate_in_model_pack_identity(tmp_path) -> None:
    a = json.loads(generate(tmp_path / "a")["binding"])["capabilityBindings"][0]["modelPackId"]
    b = json.loads(generate(tmp_path / "b", licence_bytes=b"different notice\n")["binding"])["capabilityBindings"][0]["modelPackId"]
    assert a != b


def test_model_identity_changes_deliberately_and_runtime_identity_does_not(tmp_path) -> None:
    documents = generate(tmp_path)
    v1_binding = json.loads(V1_BINDING.read_text(encoding="utf-8"))
    v2_binding = json.loads(documents["binding"])
    assert v2_binding["capabilityBindings"][0]["modelPackId"] != v1_binding["modelPack"]["modelPackId"]
    assert _sha(documents["runtimeProfile"]) != _sha(V1_RUNTIME_PROFILE.read_bytes())
    assert {k: v["runtimePackId"] for k, v in v2_binding["runtimePacks"][0]["variants"].items()} == {
        k: v["runtimePackId"] for k, v in v1_binding["runtimePacks"].items()}


@pytest.mark.parametrize(("edit", "code"), [
    (lambda p: (_edit(p["v1_qualification"], lambda d: d["requiredGates"].update({"cctv-quality-baseline": "passed"}))), "qualification_record_invalid"),
    (lambda p: (_edit(p["v1_qualification"], lambda d: d.update(qualifiedProfiles=[], profileQualifications={})),
                _edit(p["v1_manifest"], lambda d: d.update(modelVersion="1.0.1"))), "migration_v1_record_stale"),
    (lambda p: _edit(p["v1_manifest"], lambda d: d.update(verificationStatus="verified", qualificationId="rtmdet-m-coco-phase1-v1")), "migration_v1_verified_not_migratable"),
    (lambda p: _edit(p["v1_binding"], lambda d: d["modelPack"].update(checkpointSha256="0" * 64)), "migration_v1_model_identity_mismatch"),
    (lambda p: _edit(p["v1_binding"], lambda d: d.update(runtimeProfileId="other")), "migration_v1_runtime_profile_mismatch"),
    (lambda p: _edit(p["v1_binding"], lambda d: d.update(schemaVersion="mavi-vision-component-binding-v2")), "migration_v1_binding_schema_unsupported"),
    (lambda p: _edit(p["v1_binding"], lambda d: d["runtimePacks"]["windows-x86_64-cpu"].update(thirdPartyLockSha256="0" * 64)), "runtime_lock_binding_mismatch:windows-x86_64-cpu"),
    (lambda p: _edit(p["v1_binding"], lambda d: d["runtimePacks"].pop("linux-x86_64-cpu")), "binding_variant_missing:linux-x86_64-cpu"),
    (lambda p: _edit(p["v1_binding"], lambda d: d["runtimePacks"].update({"linux-x86_64-cuda": d["runtimePacks"]["linux-x86_64-cpu"]})), "binding_variant_not_releasable:linux-x86_64-cuda"),
    (lambda p: (p["v1_runtime_profile"].parent / "windows-x86_64-cpu.lock").unlink(), "runtime_variant_classification_invalid:windows-x86_64-cpu"),
    (lambda p: _edit(p["v1_binding"], lambda d: d["modelPack"].update(modelPackId="mavi-model-v1-" + "0" * 64)), "migration_v1_model_identity_mismatch"),
    (lambda p: _edit(p["v1_binding"], lambda d: d["runtimePacks"]["linux-x86_64-cpu"].update(runtimeRequirementsSha256="0" * 64)), "runtime_requirements_binding_mismatch:linux-x86_64-cpu"),
])
def test_inconsistent_or_qualified_v1_state_is_not_migrated(tmp_path, edit, code) -> None:
    tool = load_migration_tool()
    paths = _copy_v1(tmp_path)
    edit(paths)
    with pytest.raises(tool.MigrationError) as error:
        generate(tmp_path, **paths)
    assert error.value.code == code


def test_passed_v1_record_cannot_be_carried_forward(tmp_path) -> None:
    tool = load_migration_tool()
    paths = _copy_v1(tmp_path)
    evidence = {"kind": "workflow", "reference": "run", "sha256": "e" * 64}
    _edit(paths["v1_qualification"], lambda d: (d["requiredGates"].update({"cctv-quality-baseline": "passed"}),
                                                  d["evidence"].update({"cctv-quality-baseline": evidence})))
    with pytest.raises(tool.MigrationError) as error:
        generate(tmp_path, **paths)
    assert error.value.code == "migration_v1_record_not_pending"


def test_source_revision_must_be_a_full_commit(tmp_path) -> None:
    tool = load_migration_tool()
    licence = tmp_path / "LICENSE"
    licence.write_bytes(b"notice\n")
    with pytest.raises(tool.MigrationError) as error:
        tool.build_v2_documents(
            v1_binding_path=V1_BINDING, v1_manifest_path=V1_MANIFEST, v1_runtime_profile_path=V1_RUNTIME_PROFILE,
            v1_qualification_path=V1_QUALIFICATION, gate_sets_path=GATE_SETS, licence_notice_path=licence,
            licence_spdx_id="Apache-2.0", source_repository="open-mmlab/mmdetection", source_revision="main",
            binding_id="phase1-v2", qualification_id="rtmdet-m-coco-phase1-v2",
        )
    assert error.value.code == "migration_source_revision_invalid"


def test_cli_rejects_one_path_for_two_outputs(tmp_path, capsys) -> None:
    tool = load_migration_tool()
    licence = tmp_path / "LICENSE"
    licence.write_bytes(b"notice\n")
    same = tmp_path / "out" / "same.json"
    argv = [
        "--v1-binding", str(V1_BINDING), "--v1-manifest", str(V1_MANIFEST),
        "--v1-runtime-profile", str(V1_RUNTIME_PROFILE), "--v1-qualification", str(V1_QUALIFICATION),
        "--gate-sets", str(GATE_SETS), "--licence-notice", str(licence),
        "--licence-spdx-id", "Apache-2.0", "--source-repository", "open-mmlab/mmdetection",
        "--source-revision", "44ebd17b145c2372c4b700bfb9cb20dbd28ab64a",
        "--binding-id", "phase1-v2", "--qualification-id", "rtmdet-m-coco-phase1-v2",
        "--out-binding", str(same), "--out-manifest", str(same),
        "--out-runtime-profile", str(tmp_path / "out" / "r.json"), "--out-qualification", str(tmp_path / "out" / "q.json"),
    ]
    assert tool.main(argv) == 2
    assert "migration_output_paths_not_distinct" in capsys.readouterr().err
    assert not same.exists()


def test_cli_writes_outputs_and_refuses_to_overwrite(tmp_path, capsys) -> None:
    tool = load_migration_tool()
    licence = tmp_path / "LICENSE"
    licence.write_bytes(b"notice\n")
    outputs = {name: tmp_path / "out" / f"{name}.json" for name in ("binding", "manifest", "runtime", "qualification")}
    argv = [
        "--v1-binding", str(V1_BINDING), "--v1-manifest", str(V1_MANIFEST),
        "--v1-runtime-profile", str(V1_RUNTIME_PROFILE), "--v1-qualification", str(V1_QUALIFICATION),
        "--gate-sets", str(GATE_SETS), "--licence-notice", str(licence),
        "--licence-spdx-id", "Apache-2.0", "--source-repository", "open-mmlab/mmdetection",
        "--source-revision", "44ebd17b145c2372c4b700bfb9cb20dbd28ab64a",
        "--binding-id", "phase1-v2", "--qualification-id", "rtmdet-m-coco-phase1-v2",
        "--out-binding", str(outputs["binding"]), "--out-manifest", str(outputs["manifest"]),
        "--out-runtime-profile", str(outputs["runtime"]), "--out-qualification", str(outputs["qualification"]),
    ]
    assert tool.main(argv) == 0
    assert all(path.is_file() for path in outputs.values())
    before = outputs["binding"].read_bytes()
    capsys.readouterr()
    assert tool.main(argv) == 2
    assert "migration_output_exists" in capsys.readouterr().err
    assert outputs["binding"].read_bytes() == before


def _cli_argv(tmp_path: Path, outputs: dict[str, Path]) -> list[str]:
    licence = tmp_path / "LICENSE"
    licence.write_bytes(b"notice\n")
    return [
        "--v1-binding", str(V1_BINDING), "--v1-manifest", str(V1_MANIFEST),
        "--v1-runtime-profile", str(V1_RUNTIME_PROFILE), "--v1-qualification", str(V1_QUALIFICATION),
        "--gate-sets", str(GATE_SETS), "--licence-notice", str(licence),
        "--licence-spdx-id", "Apache-2.0", "--source-repository", "open-mmlab/mmdetection",
        "--source-revision", "44ebd17b145c2372c4b700bfb9cb20dbd28ab64a",
        "--binding-id", "phase1-v2", "--qualification-id", "rtmdet-m-coco-phase1-v2",
        "--out-binding", str(outputs["binding"]), "--out-manifest", str(outputs["manifest"]),
        "--out-runtime-profile", str(outputs["runtime"]), "--out-qualification", str(outputs["qualification"]),
    ]


@pytest.mark.parametrize("fail_on_call", [2, 3, 4])
def test_publication_failure_leaves_no_partial_output_set(tmp_path, capsys, monkeypatch, fail_on_call) -> None:
    tool = load_migration_tool()
    out = tmp_path / "out"
    out.mkdir()
    unrelated = out / "unrelated.json"
    unrelated.write_bytes(b'{"keep": true}\n')
    outputs = {name: out / f"{name}.json" for name in ("binding", "manifest", "runtime", "qualification")}
    real_publish = tool._publish
    calls: list[Path] = []

    def failing_publish(temporary: Path, destination: Path) -> None:
        calls.append(destination)
        if len(calls) == fail_on_call:
            raise OSError("injected publication failure")
        real_publish(temporary, destination)

    monkeypatch.setattr(tool, "_publish", failing_publish)
    assert tool.main(_cli_argv(tmp_path, outputs)) == 2
    assert "migration_publication_failed" in capsys.readouterr().err
    # at least one destination really was published before the failure
    assert len(calls) == fail_on_call
    assert not any(path.exists() for path in outputs.values())
    assert sorted(item.name for item in out.iterdir()) == ["unrelated.json"]  # no temp files either
    assert unrelated.read_bytes() == b'{"keep": true}\n'


def test_publication_never_replaces_a_file_that_appears_after_the_check(tmp_path, capsys, monkeypatch) -> None:
    tool = load_migration_tool()
    out = tmp_path / "out"
    out.mkdir()
    outputs = {name: out / f"{name}.json" for name in ("binding", "manifest", "runtime", "qualification")}
    real_publish = tool._publish
    intruder = b"written by someone else\n"

    def racing_publish(temporary: Path, destination: Path) -> None:
        if destination == outputs["runtime"]:
            destination.write_bytes(intruder)  # appears between the check and publication
        real_publish(temporary, destination)

    monkeypatch.setattr(tool, "_publish", racing_publish)
    assert tool.main(_cli_argv(tmp_path, outputs)) == 2
    assert outputs["runtime"].read_bytes() == intruder
    assert not any(path.exists() for name, path in outputs.items() if name != "runtime")


def test_successful_publication_is_deterministic(tmp_path, capsys) -> None:
    tool = load_migration_tool()
    first = {name: tmp_path / "a" / f"{name}.json" for name in ("binding", "manifest", "runtime", "qualification")}
    second = {name: tmp_path / "b" / f"{name}.json" for name in ("binding", "manifest", "runtime", "qualification")}
    assert tool.main(_cli_argv(tmp_path, first)) == 0
    assert tool.main(_cli_argv(tmp_path, second)) == 0
    assert {k: v.read_bytes() for k, v in first.items()} == {k: v.read_bytes() for k, v in second.items()}
    assert sorted(p.name for p in (tmp_path / "a").iterdir()) == sorted(f"{n}.json" for n in first)
