"""Class-free association inputs: canonical GT validation and projection, and the MAVI Vehicle projection."""

from __future__ import annotations

import copy
import dataclasses
import json
from fractions import Fraction

import pytest

import track_fixtures as f
from tools.benchmarks.capabilities.vehicle_tracks import ground_truth as g
from tools.benchmarks.capabilities.vehicle_tracks import mavi_tracks as mt
from tools.benchmarks.core import descriptor as d
from tools.benchmarks.core import mavi
from tools.benchmarks.core.identity import S32Error
from tools.benchmarks.datasets import synthetic as s

B = (0.1, 0.1, 0.2, 0.2)
CLASS_WORDS = ("class", "subclass", "confidence", "mapping", "kind", "outcome", "label")


def refused(code: str):
    return pytest.raises(S32Error, match=f"^{code}")


def all_fields(cls) -> set[str]:
    names = set()
    for item in dataclasses.fields(cls):
        names.add(item.name)
    return names


def test_projection_types_carry_no_class_subclass_or_confidence_field():
    for cls in (g.Box, g.GtFrame, g.GtTrack, g.GtSequence, mt.Observation, mt.MaviTrack, mt.MaviRun):
        assert not [name for name in all_fields(cls) if any(word in name.lower() for word in CLASS_WORDS)], cls


def test_synthetic_adapter_ground_truth_validates_and_projects(tmp_path):
    source = s.write_source(tmp_path / "source")
    frozen = d.freeze(s.descriptor(), source)
    entries = d.reconcile(frozen, source)
    document = s.SyntheticAdapter().ground_truth(source, entries, frozen, "val", "seq-a")
    projected = g.project(document)
    assert projected.sequence_id == "seq-a" and len(projected.instants) == 8
    assert [track.gt_track_id for track in projected.tracks] == ["1", "2", "3"]
    pedestrian = projected.tracks[2]
    assert [frame.ignore for frame in pedestrian.frames] == [False, False, False, True, False]
    assert len(pedestrian.evaluable) == 4
    assert projected.instants[3] == Fraction(600)


def test_native_class_never_changes_the_projection():
    document = f.gt_document({"1": f.static(B, range(4)), "2": f.static((0.5, 0.5, 0.2, 0.2), range(4))},
                             classes={"1": "car", "2": "pedestrian"})
    mutated = copy.deepcopy(document)
    for track in mutated["tracks"]:
        track["nativeClass"] = "zeppelin"
    assert g.project(document) == g.project(mutated)


@pytest.mark.parametrize("edit, code", [
    (lambda doc: doc.pop("instants"), "ground_truth_invalid:fields"),
    (lambda doc: doc.update(extra=1), "ground_truth_invalid:fields"),
    (lambda doc: doc["instants"].reverse(), "ground_truth_invalid:instants_order"),
    (lambda doc: doc["instants"][1].update(videoOffsetMs={"numerator": 400, "denominator": 2}),
     "ground_truth_invalid:instant_time:not_lowest_terms"),
    (lambda doc: doc["tracks"].reverse(), "ground_truth_invalid:track_order"),
    (lambda doc: doc["tracks"][0].update(gtTrackId=""), "ground_truth_invalid:gtTrackId"),
    (lambda doc: doc["tracks"][0].update(gtTrackId="a b"), "ground_truth_invalid:gtTrackId"),
    (lambda doc: doc["tracks"][0].pop("nativeClass"), "ground_truth_invalid:track"),
    (lambda doc: doc["tracks"][0]["frames"].reverse(), "ground_truth_invalid:frame_order:1"),
    (lambda doc: doc["tracks"][0]["frames"].append(copy.deepcopy(doc["tracks"][0]["frames"][0])),
     "ground_truth_invalid:frame_order:1"),
    (lambda doc: doc["tracks"][0]["frames"][0].update(frameIndex=99), "ground_truth_invalid:frame_not_an_instant:1"),
    (lambda doc: doc["tracks"][0]["frames"][1].update(videoOffsetMs={"numerator": 201, "denominator": 1}),
     "ground_truth_invalid:frame_time:1"),
    (lambda doc: doc["tracks"][0]["frames"][0]["box"].update(width=0), "ground_truth_invalid:box:1"),
    (lambda doc: doc["tracks"][0]["frames"][0]["box"].update(x=0.95), "ground_truth_invalid:box:1"),
    (lambda doc: doc["tracks"][0]["frames"][0]["box"].update(x=float("nan")), "ground_truth_invalid:box:1"),
    (lambda doc: doc["tracks"][0]["frames"][0].update(ignore=0), "ground_truth_invalid:ignore:1"),
    (lambda doc: doc["tracks"][0].update(frames="x"), "ground_truth_invalid:frames:1"),
    (lambda doc: doc.update(ignoreRegions=[{"frameIndex": 99, "box": doc["tracks"][0]["frames"][0]["box"]}]),
     "ground_truth_invalid:ignoreRegions"),
])
def test_malformed_ground_truth_is_refused(edit, code):
    document = f.gt_document({"1": f.static(B, range(4)), "2": f.static((0.5, 0.5, 0.2, 0.2), range(4))})
    edit(document)
    with refused(code):
        g.project(document)


def test_non_dict_ground_truth_is_a_refusal():
    for value in (None, [], "x", {"tracks": None}):
        with refused("ground_truth_invalid"):
            g.project(value)


# MAVI projection


def spec(n, frames, box=B, **extra):
    return {"n": n, "points": f.follow(box, frames), "observations": [(200 * frames[0], box)], **extra}


def test_only_vehicle_tracks_are_projected_and_no_class_survives(tmp_path):
    path = f.write_export(tmp_path / "run", tmp_path / "evidence",
                          [spec(1, list(range(5))), spec(2, list(range(5)), objectClass="Person"),
                           spec(3, list(range(2, 7)), subclass="truck", confidence=0.4)])
    export = mavi.load_exports([path])[next(iter(mavi.load_exports([path])))]
    run = mt.project(export, tmp_path / "evidence")
    assert [track.mavi_track_id for track in run.tracks] == [f.mid(1), f.mid(3)]
    assert run.frame_rate == 5 and run.point_count == 10
    assert run.tracks[0].points == tuple(f.follow(B, range(5)))
    assert run.tracks[0].observations == (mt.Observation(0, g.Box(*B)),)


def test_observation_timing_must_follow_the_declared_rate(tmp_path):
    path = f.write_export(tmp_path / "run", tmp_path / "evidence", [spec(1, list(range(5)))])
    document = json.loads(path.read_bytes())
    document["tracks"][0]["observations"][0]["videoOffsetMs"] += 1
    path.write_bytes(json.dumps(document, sort_keys=True, separators=(",", ":")).encode())
    export = next(iter(mavi.load_exports([path]).values()))
    with refused(f"export_invalid:observation_timing:{f.mid(1)}$"):
        mt.project(export, tmp_path / "evidence")


def test_ntsc_observation_timing_rounds_half_up(tmp_path):
    assert mt.round_half_up(Fraction(1001, 2)) == 501
    assert mt.round_half_up(Fraction(3 * 1001, 30)) == 100  # 100.1
    assert mt.round_half_up(Fraction(5 * 1001, 30)) == 167  # 166.83…


def test_example_export_observations_satisfy_the_timing_rule():
    export = next(iter(mavi.load_exports([f.EXPORT_EXAMPLE]).values()))
    mt.require_observation_timing(export)


def test_a_vehicle_track_without_trajectory_or_with_a_bad_one_is_refused(tmp_path):
    path = f.write_export(tmp_path / "run", tmp_path / "evidence", [spec(1, list(range(5)))])
    export = next(iter(mavi.load_exports([path]).values()))
    for item in (tmp_path / "evidence").iterdir():
        item.write_bytes(item.read_bytes() + b"\0")
    with refused("trajectory_hash_mismatch:"):
        mt.project(export, tmp_path / "evidence")
