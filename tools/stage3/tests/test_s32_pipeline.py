"""The S3.2a-2 integration proof: synthetic T1 exports, evidence and sources + synthetic
derivations + committed synthetic requirements and guide → T3 sample → T4 primary and overlap
packs → scripted blind decisions → T5 freeze → T5 adjudication → T2/T6 measurement and
comparison. Run twice; every artefact must be byte-identical."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import s32fixtures as f
import s32pipeline as p

# Track number → MAVI prediction (None: the vote abstained).
LAYOUT = {
    "CAM-A": [
        f.TrackSpec(number=1, subclass="car", roles=("Representative", "NearView"), start=0, end=3000),
        f.TrackSpec(number=2, subclass="car", start=500, end=2500, box=(0.1, 0.1, 0.2, 0.2), quality=0.6),
        f.TrackSpec(number=3, subclass="truck", start=4000, end=9000, roles=("Representative", "EarlyDiverse", "LateDiverse")),
        f.TrackSpec(number=4, subclass="car", start=100, end=900, box=(0.4, 0.4, 0.1, 0.1), quality=0.4),
        f.TrackSpec(number=5, subclass="bus", start=2000, end=8000),
        f.TrackSpec(number=6, subclass=None, start=7000, end=7500, quality=0.9),
        f.TrackSpec(number=50, object_class="Person", subclass=None),
    ],
    "CAM-B": [
        f.TrackSpec(number=20, subclass="truck", start=0, end=6000, roles=("Representative", "NearView", "EarlyDiverse", "LateDiverse")),
        f.TrackSpec(number=21, subclass="truck", start=1000, end=2000, box=(0.0, 0.5, 0.3, 0.3)),
        f.TrackSpec(number=22, subclass="motorcycle", start=3000, end=3300, quality=0.5),
        f.TrackSpec(number=23, subclass="car", start=5000, end=9000, box=(0.6, 0.1, 0.35, 0.6)),
    ],
}
for tracks in LAYOUT.values():
    for spec in tracks:
        spec.track_id = f"00000000-0000-4000-8000-{spec.number:012d}"

# Primary reviewer: track → (label, unknownReason).
PRIMARY = {1: ("car", None), 2: ("truck", None), 3: ("truck", None), 4: ("car", None), 5: ("unknown", "occluded"),
           6: ("car", None), 20: ("truck", None), 21: ("car", None), 22: ("motorcycle", None), 23: ("car", None)}


def pipeline(world: f.World, out: Path) -> dict[str, Path]:
    out.mkdir()
    sample = out / "sample.json"
    p.run(p.sample_tracks.main, p.sample(world, sample, target=10, overlap="0.3"))
    overlap_numbers = _overlap_numbers(world, sample)
    primary_pack, overlap_pack = out / "pack-primary", out / "pack-overlap"
    p.run(p.build_labeling_pack.main, p.pack(world, sample, primary_pack))
    p.run(p.build_labeling_pack.main, p.pack(world, sample, overlap_pack, view="overlap", parent=primary_pack))

    # The overlap reviewer disagrees on the first overlap Track the primary called a car: unknown/too-small.
    disputed = next(n for n in overlap_numbers if PRIMARY[n] == ("car", None))
    overlap_choices = {n: PRIMARY[n] for n in overlap_numbers}
    overlap_choices[disputed] = ("unknown", "too-small")
    primary_labels, overlap_labels = out / "labels-primary.json", out / "labels-overlap.json"
    p.run(p.freeze_labels.main, p.freeze(primary_pack, p.draft(primary_pack, p.by_track(world, PRIMARY), "Reviewer A",
                                                                 out / "draft-primary.json"), "Reviewer A", primary_labels))
    p.run(p.freeze_labels.main, p.freeze(overlap_pack, p.draft(overlap_pack, p.by_track(world, overlap_choices), "Reviewer B",
                                                                 out / "draft-overlap.json"), "Reviewer B", overlap_labels))
    sheet = out / "adjudication-sheet"
    p.run(p.freeze_labels.main, ["adjudicate-prepare", "--primary", str(primary_labels), "--overlap", str(overlap_labels),
                                 "--pack", str(primary_pack), "--out", str(sheet)])
    data = json.loads((sheet / "adjudication-data.js").read_text(encoding="utf-8").removeprefix("window.MAVI_ADJUDICATION = ").rstrip(";\n"))
    decisions = {"primaryLabelsSha256": data["primaryLabelsSha256"], "overlapLabelsSha256": data["overlapLabelsSha256"],
                 "sessionId": data["sessionId"],
                 "decisions": [{"itemId": item["itemId"], "adjudicatedLabel": "unknown", "adjudicatedUnknownReason": "too-small"}
                               for item in data["items"] if item["needsDecision"]]}
    (out / "adjudication-decisions.json").write_text(json.dumps(decisions), encoding="utf-8")
    adjudication = out / "adjudication.json"
    p.run(p.freeze_labels.main, ["adjudicate", "--primary", str(primary_labels), "--overlap", str(overlap_labels),
                                 "--decisions", str(out / "adjudication-decisions.json"), "--adjudicator", "Adjudicator C",
                                 "--adjudicated-on", "2026-10-04", "--out", str(adjudication)])
    result = out / "measurement"
    p.run(p.run_subclass_measurement.main, p.measure(world, result, samples=[sample], labels=[primary_labels],
                                                     overlap=[overlap_labels], adjudications=[adjudication],
                                                     packs=[primary_pack, overlap_pack]))
    return {"sample": sample, "primaryPack": primary_pack, "overlapPack": overlap_pack, "primaryLabels": primary_labels,
            "overlapLabels": overlap_labels, "adjudication": adjudication, "result": result, "disputed": disputed,
            "sheet": sheet}


def _overlap_numbers(world: f.World, sample: Path) -> list[int]:
    numbers = {t.track_id: t.number for v in world.videos for t in v.tracks}
    document = json.loads(sample.read_text(encoding="utf-8"))
    return sorted(numbers[item["trackId"]] for item in document["overlapSelected"])


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    root = tmp_path_factory.mktemp("s32-pipeline")
    world = f.build_world(root / "world", LAYOUT)
    return world, pipeline(world, root / "first"), pipeline(world, root / "second")


def _tree(directory: Path) -> dict[str, bytes]:
    return {path.relative_to(directory).as_posix(): path.read_bytes()
            for path in sorted(directory.rglob("*")) if path.is_file() and not path.name.startswith("draft-")}


def test_every_artefact_is_byte_identical_across_two_runs(runs):
    _, first, second = runs
    first_tree, second_tree = _tree(first["result"].parent), _tree(second["result"].parent)
    assert first_tree.keys() == second_tree.keys()
    assert first_tree == second_tree


def test_measurement_carries_the_expected_outcomes(runs):
    world, first, _ = runs
    result = json.loads((first["result"] / "measurement-result.json").read_text(encoding="utf-8"))
    metrics = result["primary"]["metrics"]
    disputed = first["disputed"]
    # Ten labelled Tracks; the human unknown (track 5) and the adjudicated unknown are not scored.
    assert metrics["labelledTracks"] == 10
    assert metrics["humanUnknown"]["occluded"] == 1 and metrics["humanUnknown"]["too-small"] == 1
    assert metrics["evaluableTracks"] == 8
    # The overlap (chosen blind) is tracks 2, 4 and 22; track 4 is the disputed car → unknown/too-small.
    assert disputed == 4
    # Track 6: the vote abstained on a car; abstention is never correct and lowers coverage.
    assert metrics["confusion"]["car"]["undetermined"] == 1
    assert metrics["abstained"] == 1 and metrics["resolved"] == 7
    assert metrics["coverageOverEvaluable"] == {"numerator": 7, "denominator": 8, "value": 7 / 8}
    # Mismatches: track 2 (truck called car) and track 21 (car called truck).
    assert metrics["confusion"]["truck"]["car"] == 1 and metrics["confusion"]["car"]["truck"] == 1
    # The human-unknown bus prediction sits in unknownRow only, so bus precision and recall are undefined.
    assert metrics["unknownRow"]["bus"] == 1
    assert metrics["perClass"]["bus"]["precision"]["value"] is None and metrics["perClass"]["bus"]["recall"]["value"] is None
    correct = sum(metrics["confusion"][c][c] for c in ("car", "truck", "bus", "motorcycle"))
    assert metrics["accuracyOverEvaluable"]["numerator"] == correct
    assert metrics["confusion"]["car"]["car"] == 2 and correct == 5
    # The adjudicated unknown (track 4, predicted car) is reported in unknownRow, never scored.
    assert metrics["unknownRow"]["car"] == 1
    # Clusters sum to the totals.
    clusters = result["primary"]["clusters"]
    assert clusters["videoCount"] == 2 and clusters["cameraCount"] == 2
    assert sum(v["evaluableTracks"] for v in clusters["perVideo"]) == metrics["evaluableTracks"]
    assert sum(v["labelledTracks"] for v in clusters["perCamera"]) == metrics["labelledTracks"]
    assert sum(v["correct"] for v in clusters["perVideo"]) == correct
    # Reliability comes from the two label files: exactly one disagreement on the overlap.
    reliability = result["primary"]["reliability"]
    assert reliability["overlapTracks"] == 3 and reliability["labelAgreements"] == 2
    assert reliability["disagreement"]["car"]["unknown"] == 1
    assert result["supplemental"] == [] and len(result["batches"]) == 1
    assert result["scope"].startswith("This measurement is Track-conditional.")


def test_requirement_comparison_reports_status_only(runs):
    _, first, _ = runs
    comparison = json.loads((first["result"] / "requirement-comparison.json").read_text(encoding="utf-8"))
    statuses = {(c["criterion"], c["class"]): c["status"] for c in comparison["criteria"]}
    assert statuses[("coverageOverEvaluable", None)] == "meets"  # 7/8 >= 0.5 with 8 >= 3
    assert statuses[("precision", "bus")] == "no-requirement"
    assert statuses[("recall", "truck")] == "no-requirement"
    assert statuses[("precision", "motorcycle")] == "insufficient-support"  # support 1 < 2
    assert set(statuses.values()) <= {"meets", "does-not-meet", "insufficient-support", "no-requirement"}
    assert "verdict" not in json.dumps(comparison)


def test_summary_is_generated_and_free_of_wall_clock_values(runs):
    _, first, second = runs
    summary = (first["result"] / "measurement-summary.md").read_bytes()
    assert summary == (second["result"] / "measurement-summary.md").read_bytes()
    text = summary.decode("utf-8")
    assert "Track-conditional" in text and "| car |" in text
    assert "\r" not in text


def test_adjudication_sheet_and_artefact_are_prediction_blind(runs):
    world, first, _ = runs
    sheet_text = "".join(path.read_text(encoding="utf-8", errors="ignore") for path in first["sheet"].rglob("*")
                         if path.suffix in (".js", ".html", ".json", ".md"))
    adjudication = first["adjudication"].read_text(encoding="utf-8")
    for text in (sheet_text, adjudication):
        assert "objectSubclass" not in text and "Confidence" not in text and "detector-native" not in text
        assert world.profile_sha not in text
    # The sheet carries no hidden run/Track mapping at all.
    assert not (first["sheet"] / "pack-manifest.json").exists()
    for video in world.videos:
        assert video.run_id not in sheet_text
