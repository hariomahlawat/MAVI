"""H4 tooling on the synthetic benchmark: arm completion receipts and the paired 640 -> 1280 comparison.

Two "arms" are evaluated by the real harness on one prepared synthetic release; they differ only in what MAVI
predicted and in the producer tuple their exports attest, exactly as the two H4 Development producers do.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import eval_fixtures as e
from test_bench_synthetic_e2e import TOOLING, write_mavi
from tools.benchmarks import cli, run
from tools.benchmarks import prepare as preparation
from tools.benchmarks.capabilities.vehicle_tracks import policy as policies
from tools.benchmarks.core._stage3 import artefacts
from tools.benchmarks.core.identity import S32Error, canonical_json, sha256_hex
from tools.benchmarks.datasets import synthetic as s
from tools.benchmarks.h4 import compare, receipt

ARMS = ("reference", "candidate")
REFERENCE = {("seq-a", "1"): "car", ("seq-b", "7"): "bus", ("seq-c", "1"): "car"}
CANDIDATE = {("seq-a", "1"): "car", ("seq-a", "2"): "car", ("seq-a", "3"): "truck", ("seq-b", "7"): "bus",
             ("seq-c", "1"): "car"}
TUPLES = {
    "reference": {"producerId": "a2-scale640", "pipelineProfileSha256": "", "componentBindingSha256": "a" * 64,
                  "modelPackId": "mavi-model-v2-" + "1" * 64},
    "candidate": {"producerId": "a2-scale1280", "pipelineProfileSha256": "", "componentBindingSha256": "b" * 64,
                  "modelPackId": "mavi-model-v2-" + "2" * 64},
}
RUNTIME_PACK = {"runtimePackId": "mavi-runtime-v2-" + "3" * 64, "runtimeVariant": "windows-x86_64-cuda"}
FREEZE = "c" * 40  # the receipts' freeze commit (the registry lookup at it is stubbed below)


def attest(exports: Path, producer: dict[str, str]) -> None:
    """Rewrite every export's attestation to the arm's producer (what that arm's worker would attest)."""
    for path in sorted(exports.glob(f"*/{artefacts.EXPORT_FILE_NAME}")):
        document = json.loads(path.read_bytes())
        document["processingRun"]["attestation"].update(
            componentBindingSha256=producer["componentBindingSha256"], modelPackId=producer["modelPackId"],
            **RUNTIME_PACK)
        path.write_bytes(canonical_json(document))


@pytest.fixture(scope="module")
def campaign(tmp_path_factory, media_pack):
    root = tmp_path_factory.mktemp("h4")
    source = s.write_source(root / "source")
    (root / "release.json").write_bytes(canonical_json(s.descriptor()))
    assert cli.main(["describe", "--descriptor", str(root / "release.json"), "--freeze-manifest", "--source-root",
                     str(source), "--out", str(root / "frozen.json")]) == 0
    for split, name in (("val", "derived"), ("train", "derived-train")):
        assert cli.main(["prepare", "--descriptor", str(root / "frozen.json"), "--source-root", str(source), "--split",
                         split, "--adapter", "synthetic", "--media-tools", str(media_pack), "--out",
                         str(root / name)]) == 0
    (root / "profile.json").write_bytes(b'{"synthetic":"pipeline profile"}')
    profile_sha = sha256_hex((root / "profile.json").read_bytes())
    (root / "mapping.json").write_bytes(canonical_json(s.mapping()))
    (root / "policy.json").write_bytes(canonical_json(policies.POLICY_V1))
    tuples = {arm: dict(value, pipelineProfileSha256=profile_sha) for arm, value in TUPLES.items()}
    arms = {}
    for arm, predictions in (("reference", REFERENCE), ("candidate", CANDIDATE)):
        for partition, derived in (("val", "derived"), ("train", "derived-train")):
            unit = root / partition / arm
            exports, evidence = write_mavi(unit, root / derived, predictions, profile_sha)
            attest(exports, tuples[arm])
            manifest_sha = sha256_hex((root / derived / "derivation-manifest.json").read_bytes())
            (unit / "journal.json").write_bytes(canonical_json(
                {"schemaVersion": "t9", "sourcePoolSha256": manifest_sha, "developmentProducer": tuples[arm]}))
            arms[(partition, arm)] = {"derived": root / derived, "exports": exports, "evidence": evidence,
                                      "journal": unit / "journal.json"}
    return {"root": root, "tuples": tuples, "arms": arms}


def evaluate(campaign, arm: str, out: Path, monkeypatch, capsys, policy: Path | None = None,
             exports: Path | None = None, partition: str = "val") -> Path:
    root, paths = campaign["root"], campaign["arms"][(partition, arm)]
    monkeypatch.setattr(run, "tooling_identity", lambda: TOOLING)
    args = ["evaluate", "--descriptor", str(root / "frozen.json"), "--derived", str(paths["derived"]), "--exports",
            str(exports or paths["exports"]), "--evidence-root", str(paths["evidence"]), "--mapping",
            str(root / "mapping.json"), "--policy", str(policy or root / "policy.json"), "--requirements",
            str(e.REQUIREMENTS), "--pipeline-profile", str(root / "profile.json"), "--out", str(out)]
    assert cli.main(args) == 0, capsys.readouterr().err
    return out / capsys.readouterr().out.strip()


def partition_spec(campaign, results: dict[str, Path], name: str = "val", receipts: dict | None = None) -> dict:
    root = campaign["root"]
    entry = {"name": name, "derived": str(campaign["arms"][(name, "reference")]["derived"]),
             "mapping": str(root / "mapping.json"), "results": {arm: str(path) for arm, path in results.items()}}
    if name == "val":
        entry["conditions"] = {"seq-a": {"illumination": "day"}, "seq-b": {"illumination": "night"}}
    if receipts is not None:
        entry["receipts"] = receipts
    return entry


def spec(campaign, results: dict[str, Path], tuples=None) -> dict:
    return {"event": "H4-test", "domain": "synthetic", "producers": tuples or campaign["tuples"],
            "bootstrap": {"seed": 20261006, "draws": 200}, "partitions": [partition_spec(campaign, results)]}


@pytest.fixture
def results(campaign, tmp_path, monkeypatch, capsys):
    return {arm: evaluate(campaign, arm, tmp_path / arm, monkeypatch, capsys) for arm in ARMS}


def test_paired_comparison_counts_deltas_costs_and_transitions(campaign, results):
    document = compare.compare(spec(campaign, results), frozen=False)
    reference, candidate = document["arms"]["reference"], document["arms"]["candidate"]
    verified = {arm: run.verify(path)["scopeA"] for arm, path in results.items()}
    for arm in ARMS:  # the arm figures are the results' own Scope A, never recomputed
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


def test_the_source_size_is_the_pre_padding_resolution(campaign, results):
    document = compare.compare(spec(campaign, results), frozen=False)
    assert all(row["sourceSize"] == row["encodedSize"] for row in document["sequences"])  # synthetic: even sizes


# --------------------------------------------------------------------------- arm completion receipts


@pytest.fixture(autouse=True)
def registry_producers(monkeypatch, campaign):
    """The fake tuples stand in for the registry producers as committed at the freeze (the lookup reads Git)."""
    by_id = {value["producerId"]: value for value in campaign["tuples"].values()}
    monkeypatch.setattr(receipt.producers, "producer_identity_at",
                        lambda producer_id, commit, root=None: dict(by_id[producer_id]))


def receipt_args(campaign, arm: str, partition: str = "val") -> dict:
    paths = campaign["arms"][(partition, arm)]
    return {"event": "H4-test", "domain": "synthetic", "partition": partition, "producer": campaign["tuples"][arm],
            "freeze_commit": FREEZE, "derived": paths["derived"], "exports_dir": paths["exports"],
            "evidence_root": paths["evidence"], "journal": paths["journal"]}


def verify_args(args: dict) -> dict:
    return {key: args[key] for key in ("derived", "exports_dir", "evidence_root", "journal", "producer", "freeze_commit")}


def test_a_receipt_builds_once_and_verifies_from_the_files(campaign, tmp_path):
    args = receipt_args(campaign, "candidate")
    out = tmp_path / "receipt.json"
    sha = receipt.build(out=out, **args)
    document = json.loads(out.read_bytes())
    assert document["receiptSha256"] == sha and document["receipt"]["sequencesCompleted"] == 2
    assert document["receipt"]["producer"] == campaign["tuples"]["candidate"]
    assert document["receipt"]["freezeCommit"] == FREEZE
    assert receipt.verify(receipt_path=out, **verify_args(args))["receiptSha256"] == sha
    with pytest.raises(S32Error, match="^h4_receipt_wrong_producer$"):
        receipt.verify(receipt_path=out, **dict(verify_args(args), producer=campaign["tuples"]["reference"]))
    with pytest.raises(S32Error, match="^h4_receipt_wrong_freeze_commit$"):
        receipt.verify(receipt_path=out, **dict(verify_args(args), freeze_commit="d" * 40))
    with pytest.raises(S32Error, match="^output_exists$"):
        receipt.build(out=out, **args)


def test_a_receipt_identity_is_deterministic_and_its_time_is_an_unhashed_sidecar(campaign, tmp_path):
    args = receipt_args(campaign, "reference")
    first, second = tmp_path / "1" / "arm-receipt.json", tmp_path / "2" / "arm-receipt.json"
    first.parent.mkdir()
    second.parent.mkdir()
    assert receipt.build(out=first, **args) == receipt.build(out=second, **args)
    assert first.read_bytes() == second.read_bytes()
    assert "completedAtUtc" not in json.loads(first.read_bytes())["receipt"]
    assert receipt.sidecar(first) == tmp_path / "1" / "arm-receipt.completed-at.txt"
    assert receipt.sidecar(first).read_text(encoding="ascii").strip().endswith("Z")
    receipt.sidecar(first).write_text("2000-01-01T00:00:00Z\n", encoding="ascii")  # the time is not identity
    assert receipt.verify(receipt_path=first, **verify_args(args))["receiptSha256"] == receipt.render(
        json.loads(second.read_bytes())["receipt"])["receiptSha256"]


def test_a_frozen_receipt_is_not_redefined_by_a_later_registry_change(campaign, tmp_path, monkeypatch):
    """The receipt's tuple is checked at its freeze commit; a later commit redefining the producer changes nothing."""
    args = receipt_args(campaign, "candidate")
    later = "e" * 40
    tuples = {value["producerId"]: value for value in campaign["tuples"].values()}
    redefined = dict(campaign["tuples"]["candidate"], componentBindingSha256="f" * 64)

    def at(producer_id, commit, root=None):
        return dict(redefined if commit == later and producer_id == redefined["producerId"] else tuples[producer_id])

    monkeypatch.setattr(receipt.producers, "producer_identity_at", at)
    monkeypatch.setattr(receipt.producers, "producer_identity",
                        lambda producer_id, root=None: pytest.fail("a receipt never reads the producer at HEAD"))
    out = tmp_path / "receipt.json"
    sha = receipt.build(out=out, **args)
    assert receipt.verify(receipt_path=out, **verify_args(args))["receiptSha256"] == sha
    with pytest.raises(S32Error, match="^h4_receipt_tuple_not_the_registry_producer$"):
        receipt.build(out=tmp_path / "later.json", **dict(args, freeze_commit=later))


def test_a_receipt_refuses_the_wrong_producer(campaign, tmp_path):
    args = receipt_args(campaign, "candidate")
    args["producer"] = campaign["tuples"]["reference"]
    args["journal"] = campaign["arms"][("val", "reference")]["journal"]  # bound to that producer: exports still differ
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
        receipt.verify(receipt_path=out, **dict(verify_args(args), journal=changed))


def test_a_receipt_refuses_a_journal_of_another_unit(campaign, tmp_path):
    args = receipt_args(campaign, "candidate")
    args["journal"] = campaign["arms"][("val", "reference")]["journal"]  # the other arm's journal
    with pytest.raises(S32Error, match="^h4_receipt_journal_not_this_unit$"):
        receipt.build(out=tmp_path / "receipt.json", **args)


def test_a_receipt_refuses_a_tuple_that_is_not_the_registry_producer(campaign, tmp_path, monkeypatch):
    args = receipt_args(campaign, "candidate")
    monkeypatch.setattr(receipt.producers, "producer_identity_at", lambda producer_id, commit, root=None: dict(
        campaign["tuples"]["reference"], producerId=producer_id))
    with pytest.raises(S32Error, match="^h4_receipt_tuple_not_the_registry_producer$"):
        receipt.build(out=tmp_path / "receipt.json", **args)


def copy_exports(source: Path, target: Path, **attestation) -> Path:
    shutil.copytree(source, target)
    for path in sorted(target.glob(f"*/{artefacts.EXPORT_FILE_NAME}")):
        document = json.loads(path.read_bytes())
        document["processingRun"]["attestation"].update(attestation)
        path.write_bytes(canonical_json(document))
    return target


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


# --------------------------------------------------------------------------- the frozen methodology, at its commit


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                             "-c", "core.autocrlf=false", *args], capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    return result.stdout.decode("ascii").strip()


def methodology(campaign, results: dict[str, Path], partitions=("val",)) -> dict:
    """The methodology the synthetic campaign was run under: every frozen value taken from what it really is."""
    envelope = json.loads((results["reference"] / "result.json").read_bytes())["envelope"]
    manifests = {name: preparation.load(campaign["arms"][(name, "reference")]["derived"])[0] for name in partitions}
    manifest = manifests[partitions[0]]
    return {"schemaVersion": "h4-methodology-v1", "eventId": "H4-test",
            "domains": [{"domain": "synthetic", "datasetId": manifest["datasetId"], "adapter": dict(manifest["adapter"]),
                         "frozenDescriptorSha256": manifest["descriptorSha256"],
                         "mappingSha256": envelope["tooling"]["mappingSha256"],
                         "frameTime": {"kind": "index-at-fps", "fpsNumerator": manifest["frameRate"]["numerator"],
                                       "fpsDenominator": manifest["frameRate"]["denominator"]},
                         "partitions": list(partitions),
                         "selection": {"sequences": [{"partition": name, "sequenceId": row["sequenceId"],
                                                      "frames": row["frameCount"]}
                                                     for name in partitions for row in manifests[name]["sequences"]]}}],
            "evaluation": {"associationPolicySha256": envelope["tooling"]["associationPolicySha256"],
                           "requirementsSha256": envelope["tooling"]["requirementsSha256"],
                           "bootstrap": {"seed": 20261006, "draws": 200}},
            "producers": {**{arm: dict(value) for arm, value in campaign["tuples"].items()},
                          "runtimePack": {"runtimePackId": RUNTIME_PACK["runtimePackId"],
                                          "variant": RUNTIME_PACK["runtimeVariant"]}}}


def freeze(tmp_path: Path, document: dict) -> tuple[Path, dict]:
    """Commit the methodology in a repository of its own: the file and the freeze that binds it."""
    repo = tmp_path / "freeze-repo"
    repo.mkdir(parents=True)
    (repo / "methodology.json").write_bytes(canonical_json(document))
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "freeze")
    return repo, {"H4-test": {"commit": _git(repo, "rev-parse", "HEAD"), "path": "methodology.json"}}




@pytest.fixture
def frozen(campaign, results, tmp_path, monkeypatch):
    """A spec bound to a committed methodology and to both arms' receipts, built under that freeze commit."""
    repo, freezes = freeze(tmp_path, methodology(campaign, results))
    commit = freezes["H4-test"]["commit"]
    monkeypatch.setattr(receipt.producers, "producer_identity_at", lambda producer_id, at, root=None: dict(
        {v["producerId"]: v for v in campaign["tuples"].values()}[producer_id]) if at == commit else pytest.fail(at))
    receipts = {}
    for arm in ARMS:
        args = dict(receipt_args(campaign, arm), freeze_commit=commit)
        path = tmp_path / f"receipt-{arm}.json"
        receipt.build(out=path, **args)
        receipts[arm] = {"receipt": str(path), "exports": str(args["exports_dir"]),
                         "evidenceRoot": str(args["evidence_root"]), "journal": str(args["journal"])}
    document = spec(campaign, results)
    document["partitions"][0]["receipts"] = receipts
    document["methodology"] = str(repo / "methodology.json")
    return {"spec": document, "repo": repo, "freezes": freezes, "commit": commit}


def frozen_compare(frozen) -> dict:
    return compare.compare(frozen["spec"], repository=frozen["repo"], freezes=frozen["freezes"])


def test_the_comparison_is_bound_to_the_frozen_methodology_commit_and_the_receipts(frozen):
    out = frozen_compare(frozen)
    assert out["methodologyCommit"] == frozen["commit"]
    assert out["methodologySha256"] == sha256_hex(Path(frozen["spec"]["methodology"]).read_bytes())
    for arm in ARMS:
        written = json.loads(Path(frozen["spec"]["partitions"][0]["receipts"][arm]["receipt"]).read_bytes())
        assert out["partitions"][0][arm]["receiptSha256"] == written["receiptSha256"]
    # Not frozen at all, or not the bytes frozen at the commit: refused.
    with pytest.raises(S32Error, match="^h4_methodology_not_frozen:H4-other$"):
        compare.compare(dict(frozen["spec"], event="H4-other"), repository=frozen["repo"], freezes=frozen["freezes"])
    path = Path(frozen["spec"]["methodology"])
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(S32Error, match="^h4_methodology_not_frozen:differs_from_commit$"):
        frozen_compare(frozen)


def test_the_spec_must_follow_the_frozen_bootstrap_partitions_and_producers(frozen, campaign):
    frozen["spec"]["bootstrap"] = {"seed": 1, "draws": 200}
    with pytest.raises(S32Error, match="^h4_spec_invalid:bootstrap$"):
        frozen_compare(frozen)
    frozen["spec"]["bootstrap"] = {"seed": 20261006, "draws": 200}
    frozen["spec"]["producers"] = {"reference": campaign["tuples"]["reference"],
                                   "candidate": dict(campaign["tuples"]["candidate"], modelPackId="x")}
    with pytest.raises(S32Error, match="^h4_spec_invalid:producers:candidate$"):
        frozen_compare(frozen)
    frozen["spec"]["producers"] = campaign["tuples"]
    frozen["spec"]["partitions"][0]["name"] = "test"
    with pytest.raises(S32Error, match="^h4_spec_invalid:partitions$"):
        frozen_compare(frozen)


ENVELOPE_MUTATIONS = {
    "descriptorSha256": ("dataset", "descriptorSha256", "0" * 64),
    "datasetId": ("dataset", "datasetId", "another-dataset"),
    "adapterId": ("tooling", "adapterId", "another-adapter"),
    "adapterVersion": ("tooling", "adapterVersion", "99"),
    "mappingSha256": ("tooling", "mappingSha256", "0" * 64),
    "associationPolicySha256": ("tooling", "associationPolicySha256", "0" * 64),
    "requirementsSha256": ("tooling", "requirementsSha256", "0" * 64),
    "runtimePackId": ("producer", "runtimePackId", "mavi-runtime-v2-" + "9" * 64),
    "runtimeVariant": ("producer", "runtimeVariant", "windows-x86_64-cpu"),
}


@pytest.mark.parametrize("key", sorted(ENVELOPE_MUTATIONS))
def test_results_must_carry_every_frozen_value(frozen, monkeypatch, key):
    """Each frozen value, changed identically in both arms (so no between-arm check can see it), is refused."""
    block, field, value = ENVELOPE_MUTATIONS[key]
    real = compare._arm_result

    def mutated(directory):
        result, association = real(directory)
        envelope = result["envelope"]
        (envelope["mavi"]["producer"] if block == "producer" else envelope[block])[field] = value
        return result, association

    monkeypatch.setattr(compare, "_arm_result", mutated)
    with pytest.raises(S32Error, match=f"^h4_not_frozen:{key}:reference$"):
        frozen_compare(frozen)


MANIFEST_MUTATIONS = {
    "descriptorSha256": lambda m: m.update(descriptorSha256="0" * 64),
    "datasetId": lambda m: m.update(datasetId="another-dataset"),
    "adapter": lambda m: m.update(adapter=dict(m["adapter"], version="99")),
    "frameRate": lambda m: m.update(frameRate={"numerator": 25, "denominator": 1}),
    "sequences:val": lambda m: m["sequences"][0].update(frameCount=m["sequences"][0]["frameCount"] + 1),
}


@pytest.mark.parametrize("key", sorted(MANIFEST_MUTATIONS))
def test_the_partition_must_be_the_frozen_derivation(frozen, monkeypatch, key):
    """The derivation both arms share: its descriptor, dataset, adapter, frame rate and selected sequences."""
    real = compare.preparation.load

    def mutated(directory):
        manifest, sha, documents = real(directory)
        manifest = json.loads(json.dumps(manifest))
        MANIFEST_MUTATIONS[key](manifest)
        return manifest, sha, documents

    monkeypatch.setattr(compare.preparation, "load", mutated)
    with pytest.raises(S32Error, match=f"^h4_not_frozen:{key}$"):
        frozen_compare(frozen)


def test_a_selection_missing_a_sequence_is_refused(frozen, campaign, results, tmp_path):
    document = methodology(campaign, results)
    document["domains"][0]["selection"]["sequences"].pop()
    repo, freezes = freeze(tmp_path / "other", document)
    frozen["spec"]["methodology"] = str(repo / "methodology.json")
    with pytest.raises(S32Error, match="^h4_not_frozen:sequences:val$"):
        compare.compare(frozen["spec"], repository=repo, freezes=freezes)


def test_every_unit_result_requires_its_verified_receipt(frozen, monkeypatch):
    receipts = frozen["spec"]["partitions"][0].pop("receipts")
    with pytest.raises(S32Error, match="^h4_spec_invalid:receipts:val$"):
        frozen_compare(frozen)
    # The arms' receipts swapped: each verifies only under its own frozen tuple.
    frozen["spec"]["partitions"][0]["receipts"] = {"reference": receipts["candidate"], "candidate": receipts["reference"]}
    with pytest.raises(S32Error, match="^h4_receipt_wrong_producer$"):
        frozen_compare(frozen)
    # A receipt that no longer re-derives from its retained journal.
    frozen["spec"]["partitions"][0]["receipts"] = receipts
    journal = Path(receipts["candidate"]["journal"])
    original = journal.read_bytes()
    try:
        journal.write_bytes(original + b" ")
        with pytest.raises(S32Error, match="^h4_receipt_mismatch$"):
            frozen_compare(frozen)
    finally:
        journal.write_bytes(original)
    # A result that is not the evaluation of the receipted exports.
    real = compare._arm_result

    def other_exports(directory):
        result, association = real(directory)
        if directory == Path(frozen["spec"]["partitions"][0]["results"]["candidate"]):
            result["envelope"]["mavi"]["exportSha256s"] = ["0" * 64, *result["envelope"]["mavi"]["exportSha256s"][1:]]
        return result, association

    monkeypatch.setattr(compare, "_arm_result", other_exports)
    with pytest.raises(S32Error, match="^h4_result_not_the_receipted_exports:val:candidate$"):
        frozen_compare(frozen)


# --------------------------------------------------------------------------- shared runtime and one evaluation identity


def test_arms_with_a_different_shared_runtime_are_refused(campaign, tmp_path, monkeypatch, capsys):
    reference = evaluate(campaign, "reference", tmp_path / "r", monkeypatch, capsys)
    other = copy_exports(campaign["arms"][("val", "candidate")]["exports"], tmp_path / "exports", maviCommit="f" * 40)
    candidate = evaluate(campaign, "candidate", tmp_path / "c", monkeypatch, capsys, exports=other)
    with pytest.raises(S32Error, match="^h4_arms_differ:runtime:maviCommit$"):
        compare.compare(spec(campaign, {"reference": reference, "candidate": candidate}), frozen=False)


def test_partitions_must_share_one_evaluation_identity(campaign, results, tmp_path, monkeypatch, capsys):
    """Two distinct valid partitions (val and train), each arm-consistent; only the evaluation identity differs."""
    train = {arm: evaluate(campaign, arm, tmp_path / f"train-{arm}", monkeypatch, capsys, partition="train")
             for arm in ARMS}
    document = spec(campaign, results)
    document["partitions"].append(partition_spec(campaign, train, "train"))
    compare.compare(document, frozen=False)  # the same evaluation identity: two partitions compare
    (tmp_path / "policy-2.json").write_bytes(canonical_json(dict(policies.POLICY_V1, minOverlapFrames=2)))
    looser = {arm: evaluate(campaign, arm, tmp_path / f"train-2-{arm}", monkeypatch, capsys,
                            policy=tmp_path / "policy-2.json", partition="train") for arm in ARMS}
    document["partitions"][1] = partition_spec(campaign, looser, "train")
    with pytest.raises(S32Error, match="^h4_partitions_differ:evaluation_identity$"):
        compare.compare(document, frozen=False)
