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
        manifest_sha = sha256_hex((root / "derived" / "derivation-manifest.json").read_bytes())
        (root / arm / "journal.json").write_bytes(canonical_json(
            {"schemaVersion": "t9", "sourcePoolSha256": manifest_sha, "developmentProducer": tuples[arm]}))
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
    document = compare.compare(spec(campaign, results), frozen=False)
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
    assert canonical_json(compare.compare(spec(campaign, results), frozen=False)) == canonical_json(document)


def test_a_result_under_another_producer_is_refused(campaign, results):
    swapped = {"reference": campaign["tuples"]["candidate"], "candidate": campaign["tuples"]["reference"]}
    with pytest.raises(S32Error, match="^h4_result_wrong_producer:reference:componentBindingSha256$"):
        compare.compare(spec(campaign, results, swapped), frozen=False)


def test_arms_on_another_partition_are_refused(campaign, results):
    document = spec(campaign, {"reference": results["reference"], "candidate": results["reference"]})
    with pytest.raises(S32Error, match="^h4_result_wrong_producer:candidate"):
        compare.compare(document, frozen=False)


@pytest.fixture(autouse=True)
def registry_producers(monkeypatch, campaign):
    """The fake tuples stand in for the committed registry producers (producer_identity reads Git)."""
    by_id = {value["producerId"]: value for value in campaign["tuples"].values()}
    monkeypatch.setattr(receipt.producers, "producer_identity", lambda producer_id, root=None: dict(by_id[producer_id]))


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
                          evidence_root=args["evidence_root"], journal=args["journal"], producer=args["producer"]) == sha
    with pytest.raises(S32Error, match="^h4_receipt_wrong_producer$"):
        receipt.verify(receipt_path=out, derived=args["derived"], exports_dir=args["exports_dir"],
                       evidence_root=args["evidence_root"], journal=args["journal"],
                       producer=campaign["tuples"]["reference"])
    with pytest.raises(S32Error, match="^output_exists$"):
        receipt.build(out=out, **args)


def test_a_receipt_refuses_the_wrong_producer(campaign, tmp_path):
    args = receipt_args(campaign, "candidate")
    args["producer"] = campaign["tuples"]["reference"]
    args["journal"] = campaign["arms"]["reference"]["journal"]  # a journal bound to that producer: exports still differ
    with pytest.raises(S32Error, match="^benchmark_producer_mismatch:componentBindingSha256$"):
        receipt.build(out=tmp_path / "receipt.json", **args)


def test_a_receipt_no_longer_verifies_after_its_journal_changes(campaign, tmp_path):
    args = receipt_args(campaign, "reference")
    out = tmp_path / "receipt.json"
    receipt.build(out=out, **args)
    changed = tmp_path / "journal.json"
    document = json.loads(args["journal"].read_bytes())
    document["members"] = {"seq-a": {}}
    changed.write_bytes(canonical_json(document))
    with pytest.raises(S32Error, match="^h4_receipt_mismatch$"):
        receipt.verify(receipt_path=out, derived=args["derived"], exports_dir=args["exports_dir"],
                       evidence_root=args["evidence_root"], journal=changed, producer=args["producer"])


def test_a_receipt_refuses_a_journal_of_another_unit(campaign, tmp_path):
    args = receipt_args(campaign, "candidate")
    args["journal"] = campaign["arms"]["reference"]["journal"]  # the other arm's journal
    with pytest.raises(S32Error, match="^h4_receipt_journal_not_this_unit$"):
        receipt.build(out=tmp_path / "receipt.json", **args)


def test_a_receipt_refuses_a_tuple_that_is_not_the_registry_producer(campaign, tmp_path, monkeypatch):
    args = receipt_args(campaign, "candidate")
    monkeypatch.setattr(receipt.producers, "producer_identity",
                        lambda producer_id, root=None: dict(campaign["tuples"]["reference"], producerId=producer_id))
    with pytest.raises(S32Error, match="^h4_receipt_tuple_not_the_registry_producer$"):
        receipt.build(out=tmp_path / "receipt.json", **args)


def write_methodology(campaign, path: Path, **changes) -> Path:
    document = {"schemaVersion": "h4-methodology-v1",
                "domains": [{"domain": "synthetic", "partitions": ["val"]}],
                "evaluation": {"bootstrap": {"seed": 20261006, "draws": 200}},
                "producers": {arm: dict(value) for arm, value in campaign["tuples"].items()}}
    document.update(changes)
    path.write_bytes(canonical_json(document))
    return path


def test_the_comparison_is_bound_to_the_frozen_methodology(campaign, results, tmp_path):
    document = spec(campaign, results)
    document["methodology"] = str(write_methodology(campaign, tmp_path / "m.json"))
    out = compare.compare(document)
    assert out["methodologySha256"] == sha256_hex((tmp_path / "m.json").read_bytes())
    document["bootstrap"] = {"seed": 1, "draws": 200}
    with pytest.raises(S32Error, match="^h4_spec_invalid:bootstrap$"):
        compare.compare(document)
    document["bootstrap"] = {"seed": 20261006, "draws": 200}
    document["methodology"] = str(write_methodology(campaign, tmp_path / "m2.json",
                                                    domains=[{"domain": "synthetic", "partitions": ["val", "test"]}]))
    with pytest.raises(S32Error, match="^h4_spec_invalid:partitions$"):
        compare.compare(document)


def test_the_source_size_is_the_pre_padding_resolution(campaign, results):
    document = compare.compare(spec(campaign, results), frozen=False)
    assert all(row["sourceSize"] == row["encodedSize"] for row in document["sequences"])  # synthetic: even sizes


# --------------------------------------------------------------------------- shared runtime and one evaluation identity


def evaluate_with(campaign, arm: str, out: Path, monkeypatch, capsys, policy: Path | None = None,
                  exports: Path | None = None) -> Path:
    root, paths = campaign["root"], campaign["arms"][arm]
    monkeypatch.setattr(run, "tooling_identity", lambda: TOOLING)
    args = ["evaluate", "--descriptor", str(root / "frozen.json"), "--derived", str(root / "derived"), "--exports",
            str(exports or paths["exports"]), "--evidence-root", str(paths["evidence"]), "--mapping",
            str(root / "mapping.json"), "--policy", str(policy or root / "policy.json"), "--requirements",
            str(e.REQUIREMENTS), "--pipeline-profile", str(root / "profile.json"), "--out", str(out)]
    assert cli.main(args) == 0, capsys.readouterr().err
    return out / capsys.readouterr().out.strip()


def copy_exports(source: Path, target: Path, **attestation) -> Path:
    import shutil

    shutil.copytree(source, target)
    for path in sorted(target.glob(f"*/{artefacts.EXPORT_FILE_NAME}")):
        document = json.loads(path.read_bytes())
        document["processingRun"]["attestation"].update(attestation)
        path.write_bytes(canonical_json(document))
    return target


def test_arms_with_a_different_shared_runtime_are_refused(campaign, tmp_path, monkeypatch, capsys):
    reference = evaluate_with(campaign, "reference", tmp_path / "r", monkeypatch, capsys)
    other = copy_exports(campaign["arms"]["candidate"]["exports"], tmp_path / "exports", maviCommit="f" * 40)
    candidate = evaluate_with(campaign, "candidate", tmp_path / "c", monkeypatch, capsys, exports=other)
    with pytest.raises(S32Error, match="^h4_arms_differ:runtime:maviCommit$"):
        compare.compare(spec(campaign, {"reference": reference, "candidate": candidate}), frozen=False)


def test_partitions_must_share_one_evaluation_identity(campaign, tmp_path, monkeypatch, capsys):
    first = {arm: evaluate_with(campaign, arm, tmp_path / f"1-{arm}", monkeypatch, capsys) for arm in ("reference", "candidate")}
    looser = dict(policies.POLICY_V1, minOverlapFrames=2)
    (tmp_path / "policy-2.json").write_bytes(canonical_json(looser))
    second = {arm: evaluate_with(campaign, arm, tmp_path / f"2-{arm}", monkeypatch, capsys, policy=tmp_path / "policy-2.json")
              for arm in ("reference", "candidate")}
    document = spec(campaign, first)
    document["partitions"].append({**document["partitions"][0], "name": "val",
                                   "results": {arm: str(path) for arm, path in second.items()}})
    with pytest.raises(S32Error, match="^h4_spec_invalid:duplicate_partition$"):
        compare.compare(document, frozen=False)


def test_a_receipt_refuses_a_unit_with_mixed_runtime_attestations(campaign, tmp_path):
    args = receipt_args(campaign, "candidate")
    mixed = copy_exports(args["exports_dir"], tmp_path / "exports")
    first = sorted(mixed.glob(f"*/{artefacts.EXPORT_FILE_NAME}"))[0]
    document = json.loads(first.read_bytes())
    document["processingRun"]["attestation"]["maviCommit"] = "f" * 40
    first.write_bytes(canonical_json(document))
    args["exports_dir"] = mixed
    with pytest.raises(S32Error, match="producer_mixed"):
        receipt.build(out=tmp_path / "receipt.json", **args)
