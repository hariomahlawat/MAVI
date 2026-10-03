"""T2: the Track-label evaluator mode (vehicle-subclass-measurement-v1)."""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

import evaluate_vehicle_subclass as ev
import s32fixtures as f
import s32pipeline as p

a = f.a

# Hand-computed case: predictions car, car, abstain, truck; humans car, truck, car, unknown/other.
HAND = {"CAM-A": [f.TrackSpec(number=1, subclass="car", start=0, end=900),
                  f.TrackSpec(number=2, subclass="car", start=300, end=1200, box=(0.1, 0.1, 0.2, 0.2)),
                  f.TrackSpec(number=3, subclass=None, start=2000, end=2600, quality=0.4),
                  f.TrackSpec(number=4, subclass="truck", start=5000, end=9000, box=(0.5, 0.5, 0.4, 0.4)),
                  f.TrackSpec(number=9, object_class="Person", subclass=None)]}
HAND_HUMANS = {1: ("car", None), 2: ("truck", None), 3: ("car", None), 4: ("unknown", "other")}
for tracks in HAND.values():
    for spec in tracks:
        spec.track_id = f"00000000-0000-4000-8000-{spec.number:012d}"


def larger() -> dict[str, list[f.TrackSpec]]:
    layout = {"CAM-A": [], "CAM-B": []}
    for n in range(1, 17):
        layout["CAM-A" if n <= 9 else "CAM-B"].append(f.TrackSpec(
            number=n, subclass=("car", "truck", None, "bus")[n % 4], start=250 * n, end=250 * n + 300 * (n % 4 + 1),
            box=(0.02 * (n % 5), 0.1, 0.2 + 0.02 * (n % 7), 0.3), quality=0.2 + 0.04 * (n % 9),
            track_id=f"00000000-0000-4000-8000-{n:012d}"))
    return layout


LARGER_HUMANS = {n: (("car", None) if n % 3 else ("truck", None)) for n in range(1, 17)}


def evaluate(world: f.World, batches: list[dict[str, Path]], *, exports: list[Path] | None = None,
             profile: Path | None = None, drop_adjudications: bool = False) -> dict:
    args = [*p.repeat("--sample", [b["sample"] for b in batches]),
            *p.repeat("--track-labels", [b["primaryLabels"] for b in batches]),
            *p.repeat("--overlap-labels", [b["overlapLabels"] for b in batches]),
            *p.repeat("--adjudication", [] if drop_adjudications else [b["adjudication"] for b in batches]),
            *p.repeat("--export", exports or world.exports()), "--pipeline-profile", str(profile or world.profile_path),
            "--out", "unused"]
    return ev.evaluate_track_labels(**ev.read_track_label_inputs(ev.track_label_parser().parse_args(args)))


def refused(code: str, call) -> None:
    with pytest.raises((a.S32Error, ev.SubclassEvaluationError)) as error:
        call()
    assert str(error.value).split(":", 1)[0] == code, str(error.value)


@pytest.fixture(scope="module")
def hand(tmp_path_factory):
    root = tmp_path_factory.mktemp("hand")
    world = f.build_world(root / "world", HAND)
    return world, p.batch(world, root / "pilot", target=4, seed="hand", primary=HAND_HUMANS)


def test_hand_computed_metrics(hand):
    world, pilot = hand
    m = evaluate(world, [pilot])["primary"]["metrics"]
    assert m["labelledTracks"] == 4 and m["humanUnknown"]["other"] == 1 and m["evaluableTracks"] == 3
    assert m["confusion"]["car"] == {"car": 1, "truck": 0, "bus": 0, "motorcycle": 0, "undetermined": 1}
    assert m["confusion"]["truck"] == {"car": 1, "truck": 0, "bus": 0, "motorcycle": 0, "undetermined": 0}
    assert m["unknownRow"]["truck"] == 1
    assert (m["resolved"], m["abstained"]) == (2, 1)
    assert m["coverageOverEvaluable"] == {"numerator": 2, "denominator": 3, "value": 2 / 3}
    assert m["accuracyOverEvaluable"] == {"numerator": 1, "denominator": 3, "value": 1 / 3}
    assert m["accuracyOverResolved"] == {"numerator": 1, "denominator": 2, "value": 0.5}
    assert m["perClass"]["car"] == {"support": 2, "predicted": 2, "correct": 1,
                                    "precision": {"numerator": 1, "denominator": 2, "value": 0.5},
                                    "recall": {"numerator": 1, "denominator": 2, "value": 0.5}}
    # No truck predictions on evaluable Tracks: truck precision is undefined (null), not zero.
    assert m["perClass"]["truck"]["precision"] == {"numerator": 0, "denominator": 0, "value": None}
    assert m["perClass"]["truck"]["recall"]["value"] == 0.0
    assert m["perClass"]["bus"]["precision"]["value"] is None and m["perClass"]["bus"]["recall"]["value"] is None
    assert m["macroRecallOverClassesWithSupport"] == {"classes": ["car", "truck"], "numerator": 1, "denominator": 4, "value": 0.25}


def test_mutants_of_unknown_and_abstention_handling_change_the_pinned_result(hand, monkeypatch):
    world, pilot = hand
    honest = ev._section

    def scores_unknown(entries, reliability, shas):  # mutant: human unknown counted as evaluable
        return honest([{**e, "label": "truck"} if e["label"] == "unknown" else e for e in entries], reliability, shas)

    monkeypatch.setattr(ev, "_section", scores_unknown)
    assert evaluate(world, [pilot])["primary"]["metrics"]["evaluableTracks"] != 3

    def abstention_correct(entries, reliability, shas):  # mutant: abstention counted as a correct classification
        return honest([{**e, "outcome": e["label"]} if e["outcome"] == "undetermined" else e for e in entries], reliability, shas)

    monkeypatch.setattr(ev, "_section", abstention_correct)
    assert evaluate(world, [pilot])["primary"]["metrics"]["accuracyOverEvaluable"]["numerator"] != 1


def test_input_order_does_not_change_the_bytes(tmp_path):
    world = f.build_world(tmp_path / "w", larger())
    pilot = p.batch(world, tmp_path / "pilot", target=8, seed="pilot", primary=LARGER_HUMANS)
    follow = p.batch(world, tmp_path / "follow", target=4, seed="follow", primary=LARGER_HUMANS, exclude=[pilot["sample"]])
    first = a.canonical_json(evaluate(world, [pilot, follow]))
    second = a.canonical_json(evaluate(world, [follow, pilot], exports=list(reversed(world.exports()))))
    assert first == second


def _with_overlap_dispute(world: f.World, root: Path, seed: str, final: tuple[str, str | None]) -> tuple[dict, int]:
    probe = root / f"probe-{seed}-{final[0]}.json"
    p.run(p.sample_tracks.main, p.sample(world, probe, target=8, seed=seed, overlap="0.25"))
    disputed = next(n for n in p.overlap_numbers(world, probe) if LARGER_HUMANS[n] == ("car", None))
    batch = p.batch(world, root / f"{seed}-{final[0]}", target=8, seed=seed, primary=LARGER_HUMANS,
                    overlap={disputed: ("unknown", "too-small")}, adjudicated={disputed: final})
    return batch, disputed


def test_adjudicated_truth_overrides_the_primary_on_overlap_tracks(tmp_path):
    world = f.build_world(tmp_path / "w", larger())
    unknown_batch, _ = _with_overlap_dispute(world, tmp_path, "dispute", ("unknown", "too-small"))
    car_batch, _ = _with_overlap_dispute(world, tmp_path, "dispute", ("car", None))
    adjudicated = evaluate(world, [unknown_batch])["primary"]["metrics"]
    primary_like = evaluate(world, [car_batch])["primary"]["metrics"]  # what a mutant using the primary label sees
    assert adjudicated["humanUnknown"]["too-small"] == 1 and adjudicated["evaluableTracks"] == 7
    assert primary_like["humanUnknown"]["too-small"] == 0 and primary_like["evaluableTracks"] == 8
    assert adjudicated != primary_like


def test_reliability_is_computed_from_the_two_label_files(tmp_path):
    world = f.build_world(tmp_path / "w", larger())
    agreed = p.batch(world, tmp_path / "agreed", target=8, seed="dispute", primary=LARGER_HUMANS)
    disputed, number = _with_overlap_dispute(world, tmp_path, "dispute", ("car", None))
    first = evaluate(world, [agreed])["primary"]["reliability"]
    second = evaluate(world, [disputed])["primary"]["reliability"]
    assert first["labelAgreements"] == first["overlapTracks"] == 2
    assert second["labelAgreements"] == 1 and second["disagreement"]["car"]["unknown"] == 1


def test_an_edited_adjudication_copy_is_refused(hand, tmp_path):
    world, pilot = hand
    document = json.loads(pilot["adjudication"].read_text(encoding="utf-8"))
    document["items"][0]["overlap"] = {"label": "bus"}
    edited = dict(pilot, adjudication=tmp_path / "edited.json")
    edited["adjudication"].write_bytes(a.canonical_json(document))
    refused("adjudication_not_from_labels", lambda: evaluate(world, [edited]))


def test_provenance_refusals(hand, tmp_path):
    world, pilot = hand
    other_profile = tmp_path / "profile.json"
    other_profile.write_bytes(world.profile_path.read_bytes() + b" ")
    refused("attestation_pipeline_profile_mismatch", lambda: evaluate(world, [pilot], profile=other_profile))
    refused("adjudication_missing", lambda: evaluate(world, [pilot], drop_adjudications=True))


def test_labels_on_foreign_runs_tracks_or_videos_are_refused(hand, tmp_path):
    world, pilot = hand

    def rebound(mutate) -> dict:
        labels = json.loads(pilot["primaryLabels"].read_text(encoding="utf-8"))
        mutate(labels["decisions"][0])
        out = dict(pilot, primaryLabels=tmp_path / f"labels-{len(list(tmp_path.iterdir()))}.json")
        out["primaryLabels"].write_bytes(a.canonical_json(labels))
        adjudication = json.loads(pilot["adjudication"].read_text(encoding="utf-8"))
        adjudication["primaryLabelsSha256"] = a.sha256_hex(out["primaryLabels"].read_bytes())
        out["adjudication"] = tmp_path / f"adjudication-{len(list(tmp_path.iterdir()))}.json"
        out["adjudication"].write_bytes(a.canonical_json(adjudication))
        return out

    person = world.track(9).track_id
    refused("labels_track_not_vehicle", lambda: evaluate(world, [rebound(lambda d: d.update(trackId=person))]))
    refused("labels_track_not_exported", lambda: evaluate(world, [rebound(lambda d: d.update(trackId="00000000-0000-4000-8000-000000000777"))]))
    refused("labels_video_mismatch", lambda: evaluate(world, [rebound(lambda d: d.update(videoSourceSha256="a" * 64))]))


def test_a_source_naming_another_profile_is_refused(tmp_path):
    world = f.build_world(tmp_path / "w", HAND)
    export_path = world.videos[0].export_path
    document = json.loads(export_path.read_text(encoding="utf-8"))
    document["tracks"][0]["objectSubclassSource"] = "detector-native:" + "f" * 64
    export_path.write_bytes(a.canonical_json(document))
    pilot = p.batch(world, tmp_path / "pilot", target=4, seed="hand", primary=HAND_HUMANS)
    refused("track_subclass_source_mismatch", lambda: evaluate(world, [pilot]))


def test_continuation_pools_only_for_the_same_design(tmp_path):
    world = f.build_world(tmp_path / "w", larger())
    pilot = p.batch(world, tmp_path / "pilot", target=8, seed="pilot", primary=LARGER_HUMANS)
    follow = p.batch(world, tmp_path / "follow", target=4, seed="follow", primary=LARGER_HUMANS, exclude=[pilot["sample"]])
    result = evaluate(world, [pilot, follow])
    assert result["primary"]["metrics"]["labelledTracks"] == 12
    assert [b["metrics"]["labelledTracks"] for b in result["batches"]] == [8, 4]
    assert result["supplemental"] == []
    pilot_alone = evaluate(world, [pilot])
    assert result["batches"][0] == pilot_alone["batches"][0]  # the pilot's own result is reproduced unchanged

    different = p.batch(world, tmp_path / "different", target=4, seed="different", primary=LARGER_HUMANS,
                        exclude=[pilot["sample"]], overlap_fraction="0.5")
    refused("continuation_design_mismatch", lambda: evaluate(world, [pilot, different]))


def test_overlapping_batches_and_mismatched_requirements_or_guides_are_refused(tmp_path):
    world = f.build_world(tmp_path / "w", larger())
    pilot = p.batch(world, tmp_path / "pilot", target=8, seed="pilot", primary=LARGER_HUMANS)
    clash = p.batch(world, tmp_path / "clash", target=4, seed="clash", primary=LARGER_HUMANS, design="supplemental",
                    reason="rare classes")
    refused("batch_tracks_overlap", lambda: evaluate(world, [pilot, clash]))

    world.guide.write_text(world.guide.read_text(encoding="utf-8") + "\n## Amended\n", encoding="utf-8")
    f.git(world.repository, "commit", "-q", "-am", "guide amended")
    world.commit = f.git(world.repository, "rev-parse", "HEAD")
    regrouped = p.batch(world, tmp_path / "regrouped", target=4, seed="regrouped", primary=LARGER_HUMANS, exclude=[pilot["sample"]])
    refused("labeling_guide_mismatch", lambda: evaluate(world, [pilot, regrouped]))

    requirements = json.loads(world.requirements.read_text(encoding="utf-8"))
    requirements["minimumSupport"]["evaluableTotal"] = 99
    world.requirements.write_text(json.dumps(requirements, indent=2), encoding="utf-8")
    f.git(world.repository, "commit", "-q", "-am", "requirements changed")
    world.commit = f.git(world.repository, "rev-parse", "HEAD")
    later = p.batch(world, tmp_path / "later", target=4, seed="later", primary=LARGER_HUMANS, exclude=[pilot["sample"]])
    refused("requirements_mismatch", lambda: evaluate(world, [pilot, later]))


def test_supplemental_never_changes_the_primary_aggregate(tmp_path):
    world = f.build_world(tmp_path / "w", larger())
    pilot = p.batch(world, tmp_path / "pilot", target=8, seed="pilot", primary=LARGER_HUMANS)
    extra = p.batch(world, tmp_path / "extra", target=4, seed="extra", primary={n: ("bus", None) for n in range(1, 17)},
                    design="supplemental", reason="buses look under-represented", exclude=[pilot["sample"]])
    alone = evaluate(world, [pilot])
    together = evaluate(world, [pilot, extra])
    assert a.canonical_json(together["primary"]) == a.canonical_json(alone["primary"])
    assert together["batches"] == alone["batches"]
    assert [s["design"]["kind"] for s in together["supplemental"]] == ["supplemental"]
    assert together["supplemental"][0]["metrics"]["perClass"]["bus"]["support"] == 4
    # A supplemental batch whose sample does not name the pilot still never pools.
    unrelated = p.batch(world, tmp_path / "unrelated", target=4, seed="unrelated", primary=LARGER_HUMANS,
                        exclude=[extra["sample"], pilot["sample"]], design="supplemental", reason="second look")
    assert a.canonical_json(evaluate(world, [pilot, extra, unrelated])["primary"]) == a.canonical_json(alone["primary"])


def test_a_continuation_that_does_not_name_the_pilot_is_refused(tmp_path):
    world = f.build_world(tmp_path / "w", larger())
    pilot = p.batch(world, tmp_path / "pilot", target=6, seed="pilot", primary=LARGER_HUMANS)
    side = p.batch(world, tmp_path / "side", target=3, seed="side", primary=LARGER_HUMANS, exclude=[pilot["sample"]],
                   design="supplemental", reason="side batch")
    orphan = p.batch(world, tmp_path / "orphan", target=3, seed="orphan", primary=LARGER_HUMANS, exclude=[side["sample"]])
    # The orphan's parent is the supplemental batch, not the pilot; it also shares no Track with the pilot by luck only.
    with pytest.raises((a.S32Error, ev.SubclassEvaluationError)) as error:
        evaluate(world, [pilot, side, orphan])
    assert str(error.value).split(":", 1)[0] in ("continuation_design_mismatch", "batch_tracks_overlap")


def test_the_event_mode_entry_point_is_unchanged():
    parser_options = {"--ground-truth", "--tracks", "--profile", "--pipeline-profile", "--attestation", "--out"}
    assert "--track-labels" not in parser_options
    assert callable(ev.evaluate) and ev.SCHEMA_VERSION == "mavi-vehicle-subclass-evaluation-v2"
