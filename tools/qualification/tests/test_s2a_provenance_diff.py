"""S2a.3 behaviour regression (plan §9 C7): the cut-over changes identity, not behaviour.

The same real clips were run through ``tools/vision/dev/measure_evidence_real_clips.py``
at the accepted S1 baseline ``c176b048`` (v1 composition) and at the S2a.3 head
(binding v2). This test reads the retained summaries under
``docs/qualification/stage2-s2a/record-replay-s2a-3/`` and proves:

- zero result differences in the compared sections (``s1_b1.normalized``, which
  strips only host timing and provenance);
- the recorded detection streams and evidence candidates are byte-identical;
- the provenance keys that differ are within the allow-list, and the identity
  keys that must change did change, to the reconciled v1 -> v2 values
  (plan §9 table; ``2026-09-27-detector-identity-reconciliation.md``).

A change to tracker parameters, dependency versions, the pipeline profile or
any evidence byte is outside the allow-list and fails here.
"""

from __future__ import annotations

import json
from pathlib import Path

import s1_b1

REPO = Path(__file__).resolve().parents[3]
EVIDENCE = REPO / "docs/qualification/stage2-s2a/record-replay-s2a-3"
BASELINE = EVIDENCE / "baseline-c176b048.summary.json"
HEAD = EVIDENCE / "head.summary.json"
HASHES = EVIDENCE / "artifact-hashes.json"

# Plan §9: the provenance keys the cut-over may change, and nothing else. The
# summaries record provenance with the runtime's field names (snake_case);
# ``schemaVersion`` is a wire member that summaries do not carry.
ALLOWED_PROVENANCE_DIFFERENCES = frozenset(
    {
        "capability_id",
        "model_pack_id",
        "runtime_pack_id",
        "runtime_pack_source",
        "component_binding_sha256",
        "runtime_profile_sha256",
        "model_manifest_sha256",
        "qualification_id",
        "qualification_sha256",
        "mavi_commit",
        "mavi_build",
    }
)

RECONCILED = {
    # key: (v1 value at c176b048, v2 value at the S2a.3 head)
    "runtime_profile_sha256": (
        "b3c59ac4e535d5e2e7356fef55f5266937e56751207f37a06dd13140b01c6873",
        "296b034d5f80ee13ab3f3bf86ed41b84109abd47d0103600b15b24078412acfb",
    ),
    "model_manifest_sha256": (
        "0049875d8190af7f268b4613cba99afef8a9f0d39a64471fd84f9ab0bc8d8d7d",
        "bc8127c1c00513a90f1b00325dcae3d4f31243ef1ce04ebe38350f945cb79c90",
    ),
    "qualification_id": ("rtmdet-m-coco-phase1-v1", "rtmdet-m-coco-phase1-v2"),
    "qualification_sha256": (
        "7d7083d902f8a8ff4a8ebe4d114fd03255b1b0c0192461357b584a1a01f3e7b9",
        "100b8f102697dfaa7ac4cd02abfc7d83fd0fbbe73adaa1908fbf3f6dcfa40e40",
    ),
}
NEW_IDENTITY = {
    "capability_id": "detector",
    "model_pack_id": "mavi-model-v2-86754e364c7560c407b531900de58eb5e66fd365685677f8f24a5a61b3186700",
    "runtime_pack_id": None,
    "runtime_pack_source": "unpacked-environment",
    "component_binding_sha256": "081c0c8948a16480626dd6d05f18c4037758e1cf513c8bf891d06ee7fb9f2819",
}
UNCHANGED = {
    "checkpoint_sha256": "229f527ca88498e8894a778a62a878a322b4a3ea2cae09ea537d34b7e907792b",
    "resolved_config_sha256": "377d9f57abf6a73a6c308f765b70fc571715448c62998819d609d2eebc7c5ee3",
    "pipeline_profile_sha256": "503225be736d9622ed110aa69e49a83dde4ae02c858d5e8fa41e527b1c4b23fb",
    "runtime_variant": "linux-x86_64-cpu",
    "verification_status": "unverified",
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _differing_provenance_keys(baseline: dict, head: dict) -> set[str]:
    left, right = baseline["provenance"], head["provenance"]
    return {key for key in set(left) | set(right) if left.get(key, "<absent>") != right.get(key, "<absent>")}


def test_the_results_are_identical() -> None:
    baseline, head = _load(BASELINE), _load(HEAD)
    assert s1_b1.normalized(baseline) == s1_b1.normalized(head)
    assert s1_b1.diff(s1_b1.normalized(baseline), s1_b1.normalized(head)) == []
    # Same original clips, byte for byte.
    assert [(clip["clip"], clip["sha256"]) for clip in baseline["clips"]] == [
        (clip["clip"], clip["sha256"]) for clip in head["clips"]
    ]


def test_the_recorded_detection_streams_and_candidates_are_byte_identical() -> None:
    hashes = _load(HASHES)
    assert set(hashes) == {"baseline-c176b048", "head"}
    assert hashes["baseline-c176b048"] == hashes["head"]
    assert any(name.endswith(".detections.jsonl") for name in hashes["head"])
    assert "candidates.csv" in hashes["head"]


def test_only_allow_listed_provenance_keys_differ() -> None:
    differing = _differing_provenance_keys(_load(BASELINE), _load(HEAD))
    assert differing <= ALLOWED_PROVENANCE_DIFFERENCES, sorted(differing - ALLOWED_PROVENANCE_DIFFERENCES)


def test_the_identities_changed_exactly_as_reconciled() -> None:
    baseline, head = _load(BASELINE)["provenance"], _load(HEAD)["provenance"]
    for key, (old, new) in RECONCILED.items():
        assert baseline[key] == old, key
        assert head[key] == new, key
    for key, value in NEW_IDENTITY.items():
        assert key not in baseline, key  # the v1 worker had no component identity
        assert head[key] == value, key
    for key, value in UNCHANGED.items():
        assert baseline[key] == head[key] == value, key
    assert baseline["mavi_commit"].startswith("c176b048")
    assert head["mavi_commit"] != baseline["mavi_commit"]


def test_the_head_binding_identity_is_the_committed_binding() -> None:
    import hashlib

    binding = REPO / "src/vision/config/components/phase1-bindings-v2.json"
    assert _load(HEAD)["provenance"]["component_binding_sha256"] == hashlib.sha256(binding.read_bytes()).hexdigest()


def test_the_allow_list_is_discriminating() -> None:
    """A tracker or dependency change would be outside the allow-list."""
    baseline, head = _load(BASELINE), _load(HEAD)
    mutated = json.loads(json.dumps(head))
    mutated["provenance"]["tracker_parameters"]["track_activation_threshold"] = 0.71
    assert not _differing_provenance_keys(baseline, mutated) <= ALLOWED_PROVENANCE_DIFFERENCES
    mutated = json.loads(json.dumps(head))
    mutated["provenance"]["dependency_versions"]["mmdet"] = "3.3.1"
    assert not _differing_provenance_keys(baseline, mutated) <= ALLOWED_PROVENANCE_DIFFERENCES


def test_the_v1_side_is_the_frozen_v1_bytes_and_the_v2_side_the_committed_bytes() -> None:
    """Each reconciled digest is the digest of a file in the repository, not a typed value."""
    import hashlib

    def sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    frozen = REPO / "src/vision/tests/fixtures/component-binding-v1"
    assert sha(frozen / "rtmdet-m-coco-phase1-v1.manifest.json") == RECONCILED["model_manifest_sha256"][0]
    assert sha(frozen / "rtmdet-m-coco-phase1-v1.qualification.json") == RECONCILED["qualification_sha256"][0]
    assert sha(frozen / "runtime.v1.json") == RECONCILED["runtime_profile_sha256"][0]
    assert sha(REPO / "models/manifests/rtmdet-m-coco-phase1-v2.json") == RECONCILED["model_manifest_sha256"][1]
    assert sha(REPO / "models/qualifications/rtmdet-m-coco-phase1-v2.json") == RECONCILED["qualification_sha256"][1]
    assert sha(REPO / "src/vision/runtime/mmdetection-phase1-v1/runtime.json") == RECONCILED["runtime_profile_sha256"][1]
