#!/usr/bin/env python3
"""One-shot generator: component binding v1 -> v2 (ADR-014 migration; S2a plan §4.1).

Reads the v1 binding, model manifest, runtime profile and qualification record
and writes the four v2 artefacts. It is a tested migration aid, not a runtime
reader: no runtime code reads v1 through it.

What it validates (fail closed on any mismatch; no evidence is carried across):
- the v1 record is entirely pending and binds the live v1 manifest and runtime
  profile by SHA-256, and the model id, checkpoint and config SHAs;
- the v1 manifest is unverified and claims no qualification;
- binding, manifest and runtime profile agree on model identity, and the v1
  ``modelPackId`` re-derives from it;
- every bound variant is deployable and every deployable variant is bound;
- each bound lock and requirements hash equals the file beside the runtime profile;
- no output path exists or is repeated (the generator never overwrites).

What it does NOT validate: the pipeline policy. ``policies.pipelineProfileId`` and
``policies.pipelineProfileSha256`` are copied from the v1 record as recorded; the
live pipeline profile is not read or hashed here. Reconciling ``policies.*``
against the live pipeline profile is the job of the resolver and ``verify_repo``
at the S2a.3 cut-over.

Publication is all-or-nothing: every document is written to a temporary file
beside its destination, then each destination is created (never replaced) from
its temporary file; if any creation fails, every destination this invocation
created is removed, so a failure leaves no partial v2 set and never touches a
pre-existing file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
VISION_ROOT = ROOT / "src" / "vision"
if str(VISION_ROOT) not in sys.path:
    sys.path.insert(0, str(VISION_ROOT))

from mavi_vision.runtime.binding import (  # noqa: E402
    COMPONENT_BINDING_V2_SCHEMA,
    parse_component_binding,
)
from mavi_vision.runtime.component_identity import (  # noqa: E402
    ModelPackIdentityInputs,
    model_pack_id,
)
from mavi_vision.runtime.component_relationships import (  # noqa: E402
    check_binding_variants,
    check_record_variants,
)
from mavi_vision.runtime.manifest import (  # noqa: E402
    ReleaseMetadataError,
    load_model_manifest,
    read_release_json,
    sha256_release_file,
)
from mavi_vision.runtime.model_manifest_v2 import (  # noqa: E402
    LICENCE_NOTICE_ROLE,
    MODEL_MANIFEST_V2_SCHEMA,
    parse_model_manifest_v2,
)
from mavi_vision.runtime.qualification import (  # noqa: E402
    load_qualification_record,
    load_runtime_profile,
)
from mavi_vision.runtime.qualification_v2 import (  # noqa: E402
    QUALIFICATION_RECORD_V2_SCHEMA,
    applicable_gate_set_ids,
    load_capability_gate_sets,
    parse_qualification_record_v2,
)
from mavi_vision.runtime.runtime_profile_v2 import (  # noqa: E402
    RUNTIME_PROFILE_V2_SCHEMA,
    classify_runtime_variants,
    parse_runtime_profile_v2,
)
from mavi_vision.runtime.variants import RUNTIME_VARIANTS, VariantClass  # noqa: E402

V1_BINDING_SCHEMA = "mavi-vision-component-requirements-v1"
DETECTOR_CAPABILITY = "detector"
DETECTOR_ROLE = {
    "roleId": "vision",
    "entryPoint": "mavi_vision.worker.main",
    "readinessContract": "worker-health-v2",
    "provenanceContract": "vision-job-complete-v3.2",
}
V1_MODEL_PACK_SCHEMA = "mavi-vision-model-pack-v1"
_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
DETECTOR_INPUT_CONTRACT = {"kind": "video-frame-rgb", "colourSpace": "RGB"}
DETECTOR_OUTPUT_CONTRACT = {"schemaId": "detector-output-v1"}


class MigrationError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def serialize(document: dict) -> bytes:
    """Deterministic release text: two-space indent, ASCII, LF, trailing newline."""
    return (json.dumps(document, indent=2, ensure_ascii=True) + "\n").encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise MigrationError(code)


def build_v2_documents(
    *,
    v1_binding_path: Path,
    v1_manifest_path: Path,
    v1_runtime_profile_path: Path,
    v1_qualification_path: Path,
    gate_sets_path: Path,
    licence_notice_path: Path,
    licence_spdx_id: str,
    source_repository: str,
    source_revision: str,
    binding_id: str,
    qualification_id: str,
) -> dict[str, bytes]:
    """Return the serialized v2 documents keyed binding/manifest/runtimeProfile/qualification."""
    try:
        v1_manifest = load_model_manifest(v1_manifest_path)
        v1_profile = load_runtime_profile(v1_runtime_profile_path)
        v1_record = load_qualification_record(v1_qualification_path)
        v1_binding = read_release_json(v1_binding_path, code="migration_v1_binding_invalid")
        raw_profile = read_release_json(v1_runtime_profile_path, code="runtime_profile_invalid")
        gate_sets = load_capability_gate_sets(gate_sets_path)
    except ReleaseMetadataError as exc:
        raise MigrationError(exc.code) from exc

    # --- the v1 set must be one consistent, still-pending identity ------------------
    _require(v1_binding.get("schemaVersion") == V1_BINDING_SCHEMA, "migration_v1_binding_schema_unsupported")
    v1_model_pack = v1_binding.get("modelPack")
    v1_runtime_packs = v1_binding.get("runtimePacks")
    _require(isinstance(v1_model_pack, dict) and isinstance(v1_runtime_packs, dict), "migration_v1_binding_invalid")
    _require(v1_model_pack.get("schemaVersion") == V1_MODEL_PACK_SCHEMA, "migration_v1_binding_invalid")
    _require(
        v1_model_pack.get("modelPackId")
        == model_pack_id(
            ModelPackIdentityInputs(
                model_id=v1_manifest.model_id,
                checkpoint_sha256=v1_manifest.checkpoint.sha256,
                resolved_config_sha256=v1_manifest.resolved_config.sha256,
            )
        ),
        "migration_v1_model_identity_mismatch",
    )
    _require(_REVISION_RE.fullmatch(source_revision) is not None, "migration_source_revision_invalid")
    _require(v1_binding.get("runtimeProfileId") == v1_profile.runtime_profile_id, "migration_v1_runtime_profile_mismatch")
    _require(v1_manifest.runtime_profile_id == v1_profile.runtime_profile_id, "migration_v1_runtime_profile_mismatch")
    _require(
        v1_model_pack.get("modelId") == v1_manifest.model_id
        and v1_model_pack.get("checkpointSha256") == v1_manifest.checkpoint.sha256
        and v1_model_pack.get("resolvedConfigSha256") == v1_manifest.resolved_config.sha256
        and v1_profile.checkpoint.sha256 == v1_manifest.checkpoint.sha256
        and v1_profile.resolved_config.sha256 == v1_manifest.resolved_config.sha256,
        "migration_v1_model_identity_mismatch",
    )
    _require(
        v1_manifest.verification_status == "unverified" and v1_manifest.qualification_id is None,
        "migration_v1_verified_not_migratable",
    )
    _require(
        v1_record.overall_result == "pending"
        and all(status == "pending" for status in v1_record.required_gates.values())
        and not v1_record.evidence
        and not v1_record.profile_qualifications
        and not v1_record.qualified_profiles,
        "migration_v1_record_not_pending",
    )
    _require(
        v1_record.model_id == v1_manifest.model_id
        and v1_record.model_manifest_sha256 == sha256_release_file(v1_manifest_path)
        and v1_record.runtime_profile_id == v1_profile.runtime_profile_id
        and v1_record.runtime_profile_sha256 == sha256_release_file(v1_runtime_profile_path)
        and v1_record.checkpoint_sha256 == v1_manifest.checkpoint.sha256
        and v1_record.resolved_config_sha256 == v1_manifest.resolved_config.sha256,
        "migration_v1_record_stale",
    )
    try:
        gate_set_ids = applicable_gate_set_ids(gate_sets, DETECTOR_CAPABILITY)
    except ReleaseMetadataError as exc:
        raise MigrationError(exc.code) from exc

    family_id = v1_profile.runtime_profile_id
    runtime_dir = v1_runtime_profile_path.parent

    # --- runtime profile v2: identical except no model identity ----------------------
    profile_document = {key: value for key, value in raw_profile.items() if key not in {"checkpoint", "resolvedConfig"}}
    profile_document["schemaVersion"] = RUNTIME_PROFILE_V2_SCHEMA
    profile_document["platformVariants"] = {
        name: {key: value for key, value in variant.items() if key != "resolvedConfigSha256"}
        for name, variant in raw_profile["platformVariants"].items()
    }
    profile_bytes = serialize(profile_document)
    try:
        profile_v2 = parse_runtime_profile_v2(json.loads(profile_bytes))
        tracked_locks = [variant for variant in sorted(RUNTIME_VARIANTS) if (runtime_dir / f"{variant}.lock").is_file()]
        classes = classify_runtime_variants(profile_v2, tracked_lock_variants=tracked_locks)
    except ReleaseMetadataError as exc:
        raise MigrationError(exc.code) from exc

    # --- source model manifest v2 ------------------------------------------------------
    pack_directory = PurePosixPath(v1_manifest.checkpoint.relative_path).parts[0]
    _require(
        PurePosixPath(v1_manifest.resolved_config.relative_path).parts[0] == pack_directory,
        "model_pack_directory_not_unique",
    )
    try:
        licence_sha256 = sha256_release_file(licence_notice_path)
    except ReleaseMetadataError as exc:
        raise MigrationError("migration_licence_notice_unreadable") from exc
    artifacts = sorted(
        [
            {"artifactRole": "checkpoint", "relativePath": v1_manifest.checkpoint.relative_path, "sha256": v1_manifest.checkpoint.sha256},
            {"artifactRole": LICENCE_NOTICE_ROLE, "relativePath": f"{pack_directory}/LICENSE", "sha256": licence_sha256},
            {"artifactRole": "resolved-config", "relativePath": v1_manifest.resolved_config.relative_path, "sha256": v1_manifest.resolved_config.sha256},
        ],
        key=lambda item: item["artifactRole"],
    )
    manifest_document = {
        "schemaVersion": MODEL_MANIFEST_V2_SCHEMA,
        "modelId": v1_manifest.model_id,
        "modelVersion": v1_manifest.model_version,
        "capabilityIds": [DETECTOR_CAPABILITY],
        "artifacts": artifacts,
        "inputContract": dict(DETECTOR_INPUT_CONTRACT),
        "outputContract": dict(DETECTOR_OUTPUT_CONTRACT),
        "runtimeCompatibility": {"runtimePackFamilyIds": [family_id]},
        "licence": {"spdxId": licence_spdx_id, "noticeArtifactRole": LICENCE_NOTICE_ROLE, "reviewStatus": "pending-review"},
        "provenance": {
            "publisher": v1_profile.checkpoint.publisher,
            "sourceRepository": source_repository,
            "sourceRevision": source_revision,
        },
        "verificationStatus": "unverified",
        "qualificationId": None,
        "capabilitySpecific": {
            DETECTOR_CAPABILITY: {
                "backend": v1_manifest.backend,
                "architecture": v1_manifest.architecture,
                "classVocabulary": list(v1_manifest.class_vocabulary),
                "checkpointArtifactRole": "checkpoint",
                "resolvedConfigArtifactRole": "resolved-config",
            }
        },
    }
    manifest_bytes = serialize(manifest_document)
    try:
        manifest_v2 = parse_model_manifest_v2(json.loads(manifest_bytes))
    except ReleaseMetadataError as exc:
        raise MigrationError(exc.code) from exc

    # --- component binding v2 ---------------------------------------------------------
    for variant in sorted(v1_runtime_packs):
        _require(variant in RUNTIME_VARIANTS, f"binding_variant_unknown:{variant}")
    bound_variants = {}
    for variant in sorted(v1_runtime_packs):
        entry = v1_runtime_packs[variant]
        if classes.get(variant) is not VariantClass.DEPLOYABLE:
            raise MigrationError(f"binding_variant_not_releasable:{variant}")
        lock_path = runtime_dir / f"{variant}.lock"
        _require(entry.get("thirdPartyLockSha256") == sha256_release_file(lock_path), f"runtime_lock_binding_mismatch:{variant}")
        requirements_path = runtime_dir / f"{variant}.requirements.txt"
        _require(
            requirements_path.is_file()
            and entry.get("runtimeRequirementsSha256") == sha256_release_file(requirements_path),
            f"runtime_requirements_binding_mismatch:{variant}",
        )
        bound_variants[variant] = {
            "runtimePackId": entry.get("runtimePackId"),
            "thirdPartyLockSha256": entry.get("thirdPartyLockSha256"),
            "runtimeRequirementsSha256": entry.get("runtimeRequirementsSha256"),
            "nativeAbi": entry.get("nativeAbi"),
        }
    binding_document = {
        "schemaVersion": COMPONENT_BINDING_V2_SCHEMA,
        "bindingId": binding_id,
        "runtimePacks": [{"runtimePackFamilyId": family_id, "variants": bound_variants}],
        "roles": [
            {
                "roleId": DETECTOR_ROLE["roleId"],
                "runtimePackFamilyId": family_id,
                "capabilityIds": [DETECTOR_CAPABILITY],
                "entryPoint": DETECTOR_ROLE["entryPoint"],
                "readinessContract": DETECTOR_ROLE["readinessContract"],
                "provenanceContract": DETECTOR_ROLE["provenanceContract"],
            }
        ],
        "capabilityBindings": [
            {
                "capabilityId": DETECTOR_CAPABILITY,
                "roleId": DETECTOR_ROLE["roleId"],
                "modelPackId": manifest_v2.model_pack_id,
                "qualificationId": qualification_id,
                "enabled": True,
            }
        ],
    }
    binding_bytes = serialize(binding_document)
    try:
        binding_v2 = parse_component_binding(json.loads(binding_bytes), component_binding_sha256=_sha256(binding_bytes))
        check_binding_variants(binding_variants=binding_v2.family_variants(family_id), variant_classes=classes)
    except ReleaseMetadataError as exc:
        raise MigrationError(exc.code) from exc

    # --- qualification record v2: every gate pending, nothing carried forward ------------
    gates = {gate: "pending" for gate_set_id in gate_set_ids for gate in gate_sets[gate_set_id].gates}
    record_document = {
        "schemaVersion": QUALIFICATION_RECORD_V2_SCHEMA,
        "qualificationId": qualification_id,
        "capabilityId": DETECTOR_CAPABILITY,
        "modelPackId": manifest_v2.model_pack_id,
        "modelId": manifest_v2.model_id,
        "modelManifestSha256": _sha256(manifest_bytes),
        "artifactSha256": {artifact.artifact_role: artifact.sha256 for artifact in manifest_v2.artifacts},
        "runtimePackFamilyId": family_id,
        "runtimeProfileSha256": _sha256(profile_bytes),
        "outputContract": dict(DETECTOR_OUTPUT_CONTRACT),
        "policies": {
            "pipelineProfileId": v1_record.pipeline_profile_id,
            "pipelineProfileSha256": v1_record.pipeline_profile_sha256,
        },
        "protocol": {"corpusId": None, "protocolVersion": None},
        "gateSetIds": list(gate_set_ids),
        "variants": {
            variant: {
                "status": "pending",
                "runtimePackId": (
                    bound_variants[variant]["runtimePackId"] if classes[variant] is VariantClass.DEPLOYABLE else None
                ),
                "gates": dict(gates),
            }
            for variant in sorted(RUNTIME_VARIANTS)
        },
        "qualifiedProfiles": [],
        "profileQualifications": {},
        "evidence": {},
        "overallResult": "pending",
        "supersedes": {
            "qualificationId": v1_record.qualification_id,
            "reason": "ADR-014 runtime-profile v2 / manifest v2 identity migration; model bytes unchanged; no gate result carried forward",
        },
    }
    record_bytes = serialize(record_document)
    try:
        record_v2 = parse_qualification_record_v2(json.loads(record_bytes), gate_sets=gate_sets)
        check_record_variants(record=record_v2, binding_variants=binding_v2.family_variants(family_id), variant_classes=classes)
    except ReleaseMetadataError as exc:
        raise MigrationError(exc.code) from exc

    return {
        "binding": binding_bytes,
        "manifest": manifest_bytes,
        "runtimeProfile": profile_bytes,
        "qualification": record_bytes,
    }


def _publish(temporary: Path, destination: Path) -> None:
    """Create ``destination`` from a fully written temporary file; never replace.

    A hard link is created atomically and fails with ``FileExistsError`` when the
    destination exists, so an existing file can never be overwritten, even if it
    appeared after the up-front existence check. Supported on NTFS and on the
    POSIX file systems MAVI development uses.
    """
    os.link(temporary, destination)


def _remove_all(paths: list[Path]) -> list[Path]:
    """Remove every path; return those that could not be removed (never raises OSError)."""
    left: list[Path] = []
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            left.append(path)
    return left


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in (
        "v1-binding", "v1-manifest", "v1-runtime-profile", "v1-qualification", "gate-sets", "licence-notice",
        "out-binding", "out-manifest", "out-runtime-profile", "out-qualification",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    for name in ("licence-spdx-id", "source-repository", "source-revision", "binding-id", "qualification-id"):
        parser.add_argument(f"--{name}", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    outputs = {
        "binding": args.out_binding,
        "manifest": args.out_manifest,
        "runtimeProfile": args.out_runtime_profile,
        "qualification": args.out_qualification,
    }
    try:
        resolved = [path.resolve() for path in outputs.values()]
        _require(len(set(resolved)) == len(resolved), "migration_output_paths_not_distinct")
        for path in outputs.values():
            _require(not path.exists(), "migration_output_exists")
        documents = build_v2_documents(
            v1_binding_path=args.v1_binding,
            v1_manifest_path=args.v1_manifest,
            v1_runtime_profile_path=args.v1_runtime_profile,
            v1_qualification_path=args.v1_qualification,
            gate_sets_path=args.gate_sets,
            licence_notice_path=args.licence_notice,
            licence_spdx_id=args.licence_spdx_id,
            source_repository=args.source_repository,
            source_revision=args.source_revision,
            binding_id=args.binding_id,
            qualification_id=args.qualification_id,
        )
    except MigrationError as exc:
        print(exc.code, file=sys.stderr)
        return 2
    # Stage every document, then create each destination; on any failure remove
    # exactly the destinations this invocation created. Nothing else is touched.
    staged: list[tuple[Path, Path]] = []
    published: list[Path] = []
    try:
        for key, path in outputs.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
            staged.append((Path(temporary), path))  # tracked before any write can fail
            with os.fdopen(handle, "wb") as stream:
                stream.write(documents[key])
        for temporary, path in staged:
            _publish(temporary, path)
            published.append(path)
    except BaseException as exc:
        # Any failure, including an interrupt, removes every destination this
        # invocation created; one failed removal does not stop the others.
        left = _remove_all([path for path in reversed(published)])
        _remove_all([temporary for temporary, _path in staged])
        if not isinstance(exc, Exception):
            raise
        message = "migration_publication_failed"
        if left:
            message += ":left=" + ",".join(str(path) for path in left)
        print(message, file=sys.stderr)
        return 2
    left_temporaries = _remove_all([temporary for temporary, _path in staged])
    if left_temporaries:
        print("migration_temporary_cleanup_failed:" + ",".join(map(str, left_temporaries)), file=sys.stderr)
    print(json.dumps({key: hashlib.sha256(value).hexdigest() for key, value in documents.items()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
