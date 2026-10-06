"""H4 tooling on the synthetic benchmark: arm completion receipts and the paired 640 -> 1280 comparison.

Two "arms" are evaluated by the real harness on one prepared synthetic release; they differ only in what MAVI
predicted and in the producer tuple their exports attest, exactly as the two H4 Development producers do.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import eval_fixtures as e
from test_bench_synthetic_e2e import TOOLING, write_mavi
from tools.benchmarks import cli, run
from tools.benchmarks.capabilities.vehicle_tracks import policy as policies
from tools.benchmarks.core._stage3 import artefacts
from tools.benchmarks.core.identity import S32Error, canonical_json, sha256_hex
from tools.benchmarks.datasets import synthetic as s
from tools.benchmarks.h4 import compare, receipt

REFERENCE = {("seq-a", "1"): "car", ("seq-b", "7"): "bus"}
CANDIDATE = {("seq-a", "1"): "car", ("seq-a", "2"): "car", ("seq-a", "3"): "truck", ("seq-b", "7"): "bus"}
TUPLES = {
    "reference": {"producerId": "a2-scale640", "pipelineProfileSha256": "", "componentBindingSha256": "a" * 64,
                  "modelPackId": "mavi-model-v2-" + "1" * 64},
    "candidate": {"producerId": "a2-scale1280", "pipelineProfileSha256": "", "componentBindingSha256": "b" * 64,
                  "modelPackId": "mavi-model-v2-" + "2" * 64},
}


def attest(exports: Path, producer: dict[str, str]) -> None:
    """Rewrite every export's attestation to the arm's producer (what that arm's worker would attest)."""
    for path in sorted(exports.glob(f"*/{artefacts.EXPORT_FILE_NAME}")):
        document = json.loads(path.read_bytes())
        document["processingRun"]["attestation"].update(
            componentBindingSha256=producer["componentBindingSha256"], modelPackId=producer["modelPackId"])
        path.write_bytes(canonical_json(document))


@pytest.fixture(scope="module")
def campaign(tmp_path_factory, media_pack):
    root = tmp_path_factory.mktemp("h4")
    source = s.write_source(root / "source")
    (root / "release.json").write_bytes(canonical_json(s.descriptor()))
    assert cli.main(["describe", "--descriptor", str(root / "release.json"), "--freeze-manifest", "--source-root",
                     str(source), "--out", str(root / "frozen.json")]) == 0
    assert cli.main(["prepare", "--descriptor", str(root / "frozen.json"), "--source-root", str(source), "--split",
                     "val", "--adapter", "synthetic", "--media-tools", str(media_pack), "--out",
                     str(root / "derived")]) == 0
    (root / "profile.json").write_bytes(b'{"synthetic":"pipeline profile"}')
    profile_sha = sha256_hex((root / "profile.json").read_bytes())
    (root / "mapping.json").write_bytes(canonical_json(s.mapping()))
    (root / "policy.json").write_bytes(canonical_json(policies.POLICY_V1))
    tuples = {arm: dict(value, pipelineProfileSha256=profile_sha) for arm, value in TUPLES.items()}
    arms = {}
    for arm, predictions in (("reference", REFERENCE), ("candidate", CANDIDATE)):
        exports, evidence = write_mavi(root / arm, root / "derived", predictions, profile_sha)
        attest(exports, tuples[arm])
        (root / arm / "journal.json").write_bytes(b'{"journal":"' + arm.encode() + b'"}')
        arms[arm] = {"exports": exports, "evidence": evidence, "journal": root / arm / "journal.json"}
    return {"root": root, "tuples": tuples, "arms": arms}


def evaluate(campaign, arm: str, out: Path, monkeypatch, capsys) -> Path:
    root, paths = campaign["root"], campaign["arms"][arm]
    monkeypatch.setattr(run, "tooling_identity", lambda: TOOLING)
    args = ["evaluate", "--descriptor", str(root / "frozen.json"), "--derived", str(root / "derived"), "--exports",
            str(paths["exports"]), "--evidence-root", str(paths["evidence"]), "--mapping", str(root / "mapping.json"),
            "--policy", str(root / "policy.json"), "--requirements", str(e.REQUIREMENTS), "--pipeline-profile",
            str(root / "profile.json"), "--out", str(out)]
    assert cli.main(args) == 0, capsys.readouterr().err
    return out / capsys.readouterr().out.strip()


def spec(campaign, results: dict[str, Path], tuples=None) -> dict:
    root = campaign["root"]
    return {"event": "H4-test", "domain": "synthetic", "producers": tuples or campaign["tuples"],
            "bootstrap": {"seed": 20261006, "draws": 200},
            "partitions": [{"name": "val", "derived": str(root / "derived"), "mapping": str(root / "mapping.json"),
                            "results": {arm: str(path) for arm, path in results.items()},
                            "conditions": {"seq-a": {"illumination": "day"}, "seq-b": {"illumination": "night"}}}]}


@pytest.fixture
def results(campaign, tmp_path, monkeypatch, capsys):
    return {arm: evaluate(campaign, arm, tmp_path / arm, monkeypatch, capsys) for arm in ("reference", "candidate")}


def test_paired_comparison_counts_deltas_costs_and_transitions(campaign, results):
    document = compare.compare(spec(campaign, results))
    reference, candidate = document["arms"]["reference"], document["arms"]["candidate"]
    verified = {arm: run.verify(path)["scopeA"] for arm, path in results.items()}
    for arm in ("reference", "candidate"):  # the arm figures are the results' own Scope A, never recomputed
        assert document["arms"][arm]["expectedVehicleGt"] == verified[arm]["expectedVehicleGt"]
        assert document["arms"][arm]["vehicleTracks"] == verified[arm]["maviTracks"]
    gained = candidate["expectedVehicleGt"]["assigned"] - reference["expectedVehicleGt"]["assigned"]
    assert reference["expectedVehicleGt"]["total"] == candidate["expectedVehicleGt"]["total"] == 5
    assert gained > 0  # the candidate predicted more GT tracks
    paired = document["paired"]
    assert paired["deltaAssigned"] == gained and paired["deltaAssociation"] == pytest.approx(gained / 5)
    transitions = paired["transitions"]
    assert sum(transitions[a]["assigned"] for a in transitions if a != "assigned") - sum(
        transitions["assigned"][b] for b in transitions["assigned"] if b != "assigned") == gained
    assert sum(sum(row.values()) for row in transitions.values()) == 5
    assert paired["costPerExtraAssigned"]["vehicleTracksPerExtraAssigned"] == pytest.approx(
        paired["deltaVehicleTracks"] / gained)
    low, high = paired["deltaAssociationCI95"]
    assert low <= paired["deltaAssociation"] <= high
    assert document["strata"]["conditions"]["illumination"]["day"]["sequences"] == 1
    assert set(document["strata"]["nativeClass"]) <= set(s.descriptor()["nativeTaxonomy"][i]["code"] for i in range(len(s.descriptor()["nativeTaxonomy"])))
    assert sum(item["gt"] for item in document["strata"]["heightBand"].values()) == 5
    # Deterministic: the same retained results give byte-identical comparisons.
    assert canonical_json(compare.compare(spec(campaign, results))) == canonical_json(document)


def test_a_result_under_another_producer_is_refused(campaign, results):
    swapped = {"reference": campaign["tuples"]["candidate"], "candidate": campaign["tuples"]["reference"]}
    with pytest.raises(S32Error, match="^h4_result_wrong_producer:reference:componentBindingSha256$"):
        compare.compare(spec(campaign, results, swapped))


def test_arms_on_another_partition_are_refused(campaign, results):
    document = spec(campaign, {"reference": results["reference"], "candidate": results["reference"]})
    with pytest.raises(S32Error, match="^h4_result_wrong_producer:candidate"):
        compare.compare(document)


def receipt_args(campaign, arm: str) -> dict:
    paths = campaign["arms"][arm]
    return {"event": "H4-test", "domain": "synthetic", "partition": "val", "producer": campaign["tuples"][arm],
            "derived": campaign["root"] / "derived", "exports_dir": paths["exports"],
            "evidence_root": paths["evidence"], "journal": paths["journal"]}


def test_a_receipt_builds_once_and_verifies_from_the_files(campaign, tmp_path):
    args = receipt_args(campaign, "candidate")
    out = tmp_path / "receipt.json"
    sha = receipt.build(out=out, **args)
    document = json.loads(out.read_bytes())
    assert document["receiptSha256"] == sha and document["receipt"]["sequencesCompleted"] == 2
    assert document["receipt"]["producer"] == campaign["tuples"]["candidate"]
    assert receipt.verify(receipt_path=out, derived=args["derived"], exports_dir=args["exports_dir"],
                          evidence_root=args["evidence_root"], journal=args["journal"]) == sha
    with pytest.raises(S32Error, match="^output_exists$"):
        receipt.build(out=out, **args)


def test_a_receipt_refuses_the_wrong_producer(campaign, tmp_path):
    args = receipt_args(campaign, "candidate")
    args["producer"] = campaign["tuples"]["reference"]
    with pytest.raises(S32Error, match="^benchmark_producer_mismatch:componentBindingSha256$"):
        receipt.build(out=tmp_path / "receipt.json", **args)


def test_a_receipt_no_longer_verifies_after_its_journal_changes(campaign, tmp_path):
    args = receipt_args(campaign, "reference")
    out = tmp_path / "receipt.json"
    receipt.build(out=out, **args)
    changed = tmp_path / "journal.json"
    changed.write_bytes(args["journal"].read_bytes() + b" ")
    with pytest.raises(S32Error, match="^h4_receipt_mismatch$"):
        receipt.verify(receipt_path=out, derived=args["derived"], exports_dir=args["exports_dir"],
                       evidence_root=args["evidence_root"], journal=changed)
