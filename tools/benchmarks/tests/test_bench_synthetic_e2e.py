"""The synthetic end-to-end benchmark through the CLI (S3.2d-1 plan §9, §17; H2 evidence).

synthetic source → frozen descriptor and manifest → prepare (canonical GT, derived MP4s by the verified FFmpeg pack)
→ T1 exports and sealed trajectories → class-free association → subclass evaluation → result → report.

The release's two sequences exercise every mapping kind (exact car/truck/motorcycle, subset minibus → bus,
vehicle-unresolved van, outside-capability pedestrian) and every outcome kind: a correct prediction, a wrong one, an
undetermined one, an unmatched GT, a Vehicle Track assigned to a pedestrian, a Person Track (never in association)
and a GT frame flagged ignore. Golden hashes pin the class-free association body and the scope A and B content;
the envelope (derived-video and tooling hashes) legitimately varies with the FFmpeg build and the commit.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import eval_fixtures as e
import track_fixtures as f
from tools.benchmarks import cli, run
from tools.benchmarks.capabilities.vehicle_subclass import evaluate as evaluation
from tools.benchmarks.capabilities.vehicle_tracks import policy as policies
from tools.benchmarks.core.identity import S32Error, canonical_json, document_sha256, sha256_hex
from tools.benchmarks.datasets import synthetic as s

TOOLING = {"toolingCommit": "1" * 40, "toolingSha256": document_sha256(f.FILES), "toolingFiles": f.FILES}
# What MAVI "predicted" for each GT track (by sequence and native track id); absent = no MAVI Track (unmatched).
PREDICTIONS = {("seq-a", "1"): "car", ("seq-a", "2"): "car", ("seq-a", "3"): "truck",
               ("seq-b", "7"): "bus", ("seq-b", "9"): None}
GOLDEN_ASSOCIATION_BODY = "57266783a8bc97fce8b8a11a80e0fd7dc7dd85195d1f65425f233899f740db9b"
GOLDEN_SCOPES = "dfa53811a90ef76f90bf76ac8bf7ee87e6b3f7f67f23738079080d35a6bf0a73"


def box_of(frame):
    b = frame["box"]
    return b["x"], b["y"], b["width"], b["height"]


def write_mavi(root: Path, derived: Path, predictions: dict, profile_sha: str) -> tuple[Path, Path]:
    manifest = json.loads((derived / "derivation-manifest.json").read_bytes())
    exports, evidence = root / "exports", root / "evidence"
    for video, row in enumerate(manifest["sequences"], start=1):
        document = json.loads((derived / "sequences" / row["sequenceId"] / "ground-truth.json").read_bytes())
        specs = []
        for track in document["tracks"]:
            key = (row["sequenceId"], track["gtTrackId"])
            if key not in predictions:
                continue
            frames = track["frames"]
            points = [(200 * fr["frameIndex"], box_of(fr)[0] + box_of(fr)[2] / 2, box_of(fr)[1] + box_of(fr)[3] / 2)
                      for fr in frames]
            specs.append({"n": 10 * video + int(track["gtTrackId"]), "points": points,
                          "observations": [(200 * frames[1]["frameIndex"], box_of(frames[1]))],
                          "subclass": predictions[key]})
        specs.append({"n": 90 + video, "points": [(0, 0.95, 0.95), (200, 0.95, 0.95)], "objectClass": "Person"})
        f.write_export(exports / f"run-{video}", evidence, specs, video=video, profile_sha256=profile_sha,
                       source_sha256=row["derivedVideoSha256"])
    return exports, evidence


@pytest.fixture(scope="module")
def benchmark(tmp_path_factory, media_pack):
    root = tmp_path_factory.mktemp("e2e")
    source = s.write_source(root / "source")
    (root / "release.json").write_bytes(canonical_json(s.descriptor()))
    assert cli.main(["describe", "--descriptor", str(root / "release.json"), "--freeze-manifest", "--source-root",
                     str(source), "--out", str(root / "frozen.json")]) == 0
    assert cli.main(["prepare", "--descriptor", str(root / "frozen.json"), "--source-root", str(source), "--split",
                     "val", "--adapter", "synthetic", "--media-tools", str(media_pack), "--out",
                     str(root / "derived")]) == 0
    (root / "profile.json").write_bytes(b'{"synthetic":"pipeline profile"}')
    profile_sha = sha256_hex((root / "profile.json").read_bytes())
    exports, evidence = write_mavi(root, root / "derived", PREDICTIONS, profile_sha)
    (root / "mapping.json").write_bytes(canonical_json(s.mapping()))
    (root / "policy.json").write_bytes(canonical_json(policies.POLICY_V1))
    args = ["evaluate", "--descriptor", str(root / "frozen.json"), "--derived", str(root / "derived"), "--exports",
            str(exports), "--evidence-root", str(evidence), "--mapping", str(root / "mapping.json"), "--policy",
            str(root / "policy.json"), "--requirements", str(e.REQUIREMENTS), "--pipeline-profile",
            str(root / "profile.json")]
    return {"root": root, "args": args, "exports": exports, "evidence": evidence, "profile_sha": profile_sha}


def evaluate_into(benchmark, out: Path, monkeypatch, capsys) -> Path:
    monkeypatch.setattr(run, "tooling_identity", lambda: TOOLING)
    assert cli.main([*benchmark["args"], "--out", str(out)]) == 0, capsys.readouterr().err
    run_id = capsys.readouterr().out.strip()
    return out / run_id


def test_end_to_end_is_complete_bound_and_deterministic(benchmark, tmp_path, monkeypatch, capsys):
    first = evaluate_into(benchmark, tmp_path / "one", monkeypatch, capsys)
    second = evaluate_into(benchmark, tmp_path / "two", monkeypatch, capsys)
    for name in (run.ASSOCIATION, run.RESULT, run.REPORT):
        assert (first / name).read_bytes() == (second / name).read_bytes(), name
    result = run.verify(first)
    association = json.loads((first / run.ASSOCIATION).read_bytes())
    assert result["associationSha256"] == document_sha256(association)
    assert association["envelope"]["tooling"]["requirementsSha256"] == e.load_requirements_sha()
    assert association["associationBodySha256"] == GOLDEN_ASSOCIATION_BODY
    assert document_sha256({"scopeA": result["scopeA"], "scopeB": result["scopeB"]}) == GOLDEN_SCOPES


def test_end_to_end_outcomes(benchmark, tmp_path, monkeypatch, capsys):
    result = run.verify(evaluate_into(benchmark, tmp_path / "out", monkeypatch, capsys))
    a, b = result["scopeA"], result["scopeB"]
    assert a["expectedVehicleGt"] == {"total": 5, "assigned": 4, "ambiguous": 0, "fragmented": 0, "merged": 0,
                                      "unverified": 0, "unmatched": 1}  # motorcycle "11" has no MAVI Track
    assert a["outsideCapabilityGt"] == {"total": 1, "vehicleTracksOnOutsideCapabilityGt": 1}
    assert a["maviTracks"]["total"] == 5 and a["coverageLimited"] is False  # Person Tracks never counted
    car, truck, bus, moto = (e.cls(result, name) for name in ("car", "truck", "bus", "motorcycle"))
    assert car["precision"]["value"]["numerator"] == 1 and car["precision"]["value"]["denominator"] == 2
    assert truck["precision"]["value"] == {"numerator": 0, "denominator": 1, "value": 0.0}  # pedestrian FP
    assert value_of(truck["recall"]) == 0.0 and truck["support"] == 1  # truck predicted car
    assert bus["recall"]["status"] == "not-in-dataset" and bus["precision"]["value"]["value"] == 1.0
    assert moto["support"] == 0 and moto["recall"]["status"] == "computed"
    assert b["subsetBlocks"][0]["nativeClass"] == "minibus" and b["subsetBlocks"][0]["resolvedToMapped"]["value"] == 1.0
    van = next(item for item in b["excluded"] if item["nativeClass"] == "van")
    assert {o["outcome"]: o["count"] for o in van["outcomes"]}["undetermined"] == 1
    assert b["taxonomyCoverage"] == "partial"


def value_of(block):
    return None if block["value"] is None else block["value"]["value"]


def test_prediction_mutation_changes_scope_b_only(benchmark, tmp_path, monkeypatch, capsys):
    base = run.verify(evaluate_into(benchmark, tmp_path / "base", monkeypatch, capsys))
    mutated_root = tmp_path / "mutated"
    predictions = {**PREDICTIONS, ("seq-a", "2"): "truck"}
    exports, evidence = write_mavi(mutated_root, benchmark["root"] / "derived", predictions, benchmark["profile_sha"])
    args = list(benchmark["args"])
    args[args.index("--exports") + 1], args[args.index("--evidence-root") + 1] = str(exports), str(evidence)
    monkeypatch.setattr(run, "tooling_identity", lambda: TOOLING)
    assert cli.main([*args, "--out", str(tmp_path / "out2")]) == 0
    mutated = run.verify(tmp_path / "out2" / capsys.readouterr().out.strip())
    base_association = json.loads((tmp_path / "base" / base["envelope"]["benchmarkRunId"] / run.ASSOCIATION).read_bytes())
    mutated_association = json.loads(
        (tmp_path / "out2" / mutated["envelope"]["benchmarkRunId"] / run.ASSOCIATION).read_bytes())
    assert base_association["associationBodySha256"] == mutated_association["associationBodySha256"]
    assert base["envelope"]["benchmarkRunId"] != mutated["envelope"]["benchmarkRunId"]  # other exports
    assert base["scopeA"] == mutated["scopeA"] and base["scopeB"] != mutated["scopeB"]


@pytest.mark.parametrize("name, code", [(run.ASSOCIATION, "association_invalid"), (run.RESULT, "result_invalid")])
@pytest.mark.parametrize("damage", ["trailing_lf", "appended_space", "pretty"])
def test_verify_requires_canonical_artifact_bytes(benchmark, tmp_path, monkeypatch, capsys, name, code, damage):
    directory = evaluate_into(benchmark, tmp_path / "out", monkeypatch, capsys)
    run.verify(directory)  # the canonical bytes as written pass
    path = directory / name
    data = path.read_bytes()
    path.write_bytes({"trailing_lf": data + b"\n", "appended_space": data + b" ",
                      "pretty": json.dumps(json.loads(data), indent=2, sort_keys=True).encode("utf-8")}[damage])
    with pytest.raises(S32Error, match=f"^{code}:not_canonical$"):
        run.verify(directory)


def test_results_are_written_once(benchmark, tmp_path, monkeypatch, capsys):
    evaluate_into(benchmark, tmp_path / "out", monkeypatch, capsys)
    assert cli.main([*benchmark["args"], "--out", str(tmp_path / "out")]) == 2
    assert capsys.readouterr().err.strip() == "refused output_exists"


def test_evaluate_refuses_unbound_or_mismatched_inputs(benchmark, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(run, "tooling_identity", lambda: TOOLING)
    root = benchmark["root"]
    changed = copy.deepcopy(json.loads((root / "mapping.json").read_bytes()))
    changed["mappings"][0]["reason"] = "Other wording."
    (tmp_path / "mapping.json").write_bytes(canonical_json(changed))
    args = list(benchmark["args"])
    args[args.index("--policy") + 1] = str(tmp_path / "missing-policy.json")
    assert cli.main([*args, "--out", str(tmp_path / "a")]) == 2
    assert capsys.readouterr().err.strip().startswith("refused association_policy_invalid")
    args = list(benchmark["args"])
    args[args.index("--pipeline-profile") + 1] = str(root / "mapping.json")  # another profile
    assert cli.main([*args, "--out", str(tmp_path / "b")]) == 2
    assert capsys.readouterr().err.strip() == "refused profile_mismatch"
    assert not (tmp_path / "a").exists() and not (tmp_path / "b").exists()


def test_prepare_is_deterministic_and_bound(benchmark, media_pack, tmp_path):
    from tools.benchmarks import prepare as preparation

    root = benchmark["root"]
    sha = preparation.prepare(descriptor_path=root / "frozen.json", source_root=root / "source", split="val",
                              adapter_id="synthetic", media_tools_dir=media_pack, out=tmp_path / "again")
    assert sha == sha256_hex((root / "derived" / "derivation-manifest.json").read_bytes())
    manifest, _, documents = preparation.load(tmp_path / "again")
    assert sorted(documents) == ["seq-a", "seq-b"] and manifest["frameRate"] == {"numerator": 5, "denominator": 1}
    (tmp_path / "again" / "sequences" / "seq-a" / "video.mp4").write_bytes(b"not the video")
    with pytest.raises(S32Error, match="^derivation_invalid:video:seq-a$"):
        preparation.load(tmp_path / "again")


def test_real_tooling_identity_binds_the_run_when_the_checkout_is_clean(benchmark, tmp_path, capsys):
    import os

    status = cli.main([*benchmark["args"], "--out", str(tmp_path / "out")])
    error = capsys.readouterr().err.strip()
    if status != 0 and error.startswith("refused tooling_dirty") and not os.environ.get("CI"):
        pytest.skip("uncommitted harness files in this local checkout (CI runs on a clean checkout)")
    assert status == 0, error
    result = run.verify(next((tmp_path / "out").iterdir()))
    paths = [item["path"] for item in result["envelope"]["tooling"]["toolingFiles"]]
    assert "tools/benchmarks/capabilities/vehicle_subclass/evaluate.py" in paths
    assert "tools/phase1/evaluate_vehicle_subclass.py" in paths and "tools/stage3/run_subclass_measurement.py" in paths
