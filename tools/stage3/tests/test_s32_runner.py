"""T6: the measurement runner and the requirement comparison."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import run_subclass_measurement as rm
import s32fixtures as f
import s32pipeline as p

a = f.a
LAYOUT = {"CAM-A": [f.TrackSpec(number=n, subclass=("car", "truck")[n % 2], start=300 * n, end=300 * n + 700,
                                track_id=f"00000000-0000-4000-8000-{n:012d}") for n in range(1, 9)]}
HUMANS = {n: ("car", None) for n in range(1, 9)}


def fraction(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator, "value": numerator / denominator if denominator else None}


@pytest.mark.parametrize("minimum, observed, support, expected", [
    (None, fraction(1, 2), 50, "no-requirement"),
    (None, fraction(15, 29), 29, "insufficient-support"),  # null minimum, one below the support floor
    (None, fraction(15, 30), 30, "no-requirement"),        # null minimum, support exactly at the floor
    (None, fraction(0, 0), 0, "insufficient-support"),     # null minimum, no support at all
    (0.5, fraction(1, 2), 30, "meets"),          # at the bound
    (0.5, fraction(49, 100), 30, "does-not-meet"),  # below
    (0.5, fraction(51, 100), 30, "meets"),       # above
    (0.5, fraction(30, 30), 29, "insufficient-support"),  # one below the minimum support
    (0.5, fraction(0, 0), 30, "does-not-meet"),           # undefined with adequate support: not demonstrated
    (0.5, fraction(0, 0), 29, "insufficient-support"),    # undefined and below the minimum support
    (0.1, fraction(1, 10), 30, "meets"),         # exact rational compare: 1/10 is not below 0.1
])
def test_status_rules(minimum, observed, support, expected):
    assert rm.status(minimum, observed, support, 30) == expected


def test_support_status_flips_exactly_at_the_minimum():
    assert rm.status(0.5, fraction(15, 29), 29, 30) == "insufficient-support"
    assert rm.status(0.5, fraction(15, 30), 30, 30) == "meets"


def test_support_floor_applies_with_a_null_minimum():
    """Support takes precedence over a null operational minimum (plan §13), so a below-floor class is never
    reported as merely having no requirement."""
    assert rm.status(None, fraction(15, 29), 29, 30) == "insufficient-support"
    assert rm.status(None, fraction(15, 30), 30, 30) == "no-requirement"


def test_all_null_requirements_compare_by_support_only():
    """The committed shape (every minimum null): each criterion is decided by support alone."""
    null = {"minimum": None}
    requirements = {"schemaVersion": "vehicle-subclass-requirements-v1", "labelVocabulary": "mavi-vehicle-subclass-labels-v1",
                    "operational": {"coverageOverEvaluable": dict(null),
                                    "perClass": {c: {"precision": dict(null), "recall": dict(null)} for c in a.CLASSES}},
                    "minimumSupport": {"evaluablePerClass": 30, "evaluableTotal": 30},
                    "insufficientSupportOutcome": "insufficient-support"}
    supports = {"car": 30, "truck": 29, "bus": 0, "motorcycle": 31}
    metrics = {"coverageOverEvaluable": fraction(40, 90), "evaluableTracks": 90,
               "perClass": {c: {"support": s, "precision": fraction(0, 0), "recall": fraction(0, 0)} for c, s in supports.items()}}
    comparison = rm.compare(requirements, "0" * 64, {"primary": {"metrics": metrics}}, "1" * 64)
    status = {(c["criterion"], c["class"]): c["status"] for c in comparison["criteria"]}
    assert status[("coverageOverEvaluable", None)] == "no-requirement"
    for name, support in supports.items():
        expected = "insufficient-support" if support < 30 else "no-requirement"
        assert status[("precision", name)] == status[("recall", name)] == expected


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("runner")
    world = f.build_world(root / "world", LAYOUT)
    batch = p.batch(world, root / "pilot", target=8, seed="runner", primary=HUMANS)
    return world, batch, root


def measure_args(world, batch, out, **overrides):
    values = dict(samples=[batch["sample"]], labels=[batch["primaryLabels"]], overlap=[batch["overlapLabels"]],
                  adjudications=[batch["adjudication"]], packs=[batch["primaryPack"], batch["overlapPack"]])
    values.update(overrides)
    return p.measure(world, out, **values)


def refused(capsys, args, code, out):
    assert rm.main(args) == 2
    assert f"refused {code}" in capsys.readouterr().err
    assert not out.exists()
    assert not any(path.name.startswith(f".{out.name}.partial") for path in out.parent.iterdir())


def test_runner_writes_three_deterministic_outputs(built, tmp_path):
    world, batch, _ = built
    p.run(rm.main, measure_args(world, batch, tmp_path / "one"))
    p.run(rm.main, measure_args(world, batch, tmp_path / "two"))
    names = sorted(path.name for path in (tmp_path / "one").iterdir())
    assert names == [rm.SUMMARY, rm.RESULT, rm.COMPARISON] or names == sorted([rm.SUMMARY, rm.RESULT, rm.COMPARISON])
    for name in names:
        assert (tmp_path / "one" / name).read_bytes() == (tmp_path / "two" / name).read_bytes()
    comparison = json.loads((tmp_path / "one" / rm.COMPARISON).read_text(encoding="utf-8"))
    assert comparison["measurementSha256"] == a.sha256_hex((tmp_path / "one" / rm.RESULT).read_bytes())
    assert comparison["requirementsSha256"] == a.sha256_hex(world.requirements.read_bytes())
    assert {c["status"] for c in comparison["criteria"]} <= {"meets", "does-not-meet", "insufficient-support", "no-requirement"}


def test_requirements_must_be_the_ones_the_samples_bound(built, tmp_path, capsys):
    world, batch, _ = built
    # Committed, but not what the sample bound: refused even though it is in the repository.
    original = world.requirements.read_bytes()
    try:
        changed = json.loads(original)
        changed["minimumSupport"]["evaluableTotal"] = 1
        world.requirements.write_text(json.dumps(changed, indent=2), encoding="utf-8")
        f.git(world.repository, "commit", "-q", "-am", "requirements changed after sampling")
        refused(capsys, measure_args(world, batch, tmp_path / "o1"), "requirements_binding_mismatch", tmp_path / "o1")
    finally:
        world.requirements.write_bytes(original)
    missing = tmp_path / "absent.json"
    args = measure_args(world, batch, tmp_path / "o2")
    args[args.index("--requirements") + 1] = str(missing)
    refused(capsys, args, "requirements_missing", tmp_path / "o2")


def test_overlap_labels_without_adjudication_are_refused(built, tmp_path, capsys):
    world, batch, _ = built
    refused(capsys, measure_args(world, batch, tmp_path / "o", adjudications=[]), "adjudication_missing", tmp_path / "o")


def test_packs_are_verified_before_measuring(built, tmp_path, capsys):
    world, batch, _ = built
    refused(capsys, measure_args(world, batch, tmp_path / "o1", packs=[batch["primaryPack"]]), "pack_missing", tmp_path / "o1")
    edited = tmp_path / "edited-pack"
    shutil.copytree(batch["primaryPack"], edited)
    pack_data = edited / "pack-data.js"
    pack_data.write_bytes(pack_data.read_bytes().replace(b"window.MAVI_PACK", b"window.MAVI_PACK "))
    refused(capsys, measure_args(world, batch, tmp_path / "o2", packs=[edited, batch["overlapPack"]]), "pack_data_mismatch",
            tmp_path / "o2")


def test_input_hash_mismatches_are_refused(built, tmp_path, capsys):
    world, batch, _ = built
    labels = json.loads(batch["primaryLabels"].read_text(encoding="utf-8"))
    labels["reviewedOn"] = "2026-10-05"
    changed = tmp_path / "labels.json"
    changed.write_bytes(a.canonical_json(labels))
    refused(capsys, measure_args(world, batch, tmp_path / "o1", labels=[changed]), "batch_pairing_invalid", tmp_path / "o1")
    # An export the batch never sampled is refused rather than silently ignored.
    other = f.build_world(tmp_path / "other", {"CAM-Q": f.numbered(40, 1)}, base=9)
    refused(capsys, measure_args(world, batch, tmp_path / "o2") + ["--export", str(other.exports()[0])],
            "export_unused", tmp_path / "o2")


def test_existing_output_is_refused(built, tmp_path, capsys):
    world, batch, _ = built
    out = tmp_path / "exists"
    out.mkdir()
    assert rm.main(measure_args(world, batch, out)) == 2
    assert "refused output_exists" in capsys.readouterr().err
    assert list(out.iterdir()) == []


def test_a_decision_moved_to_another_track_is_refused(built, tmp_path, capsys):
    world, batch, _ = built
    labels = json.loads(batch["primaryLabels"].read_text(encoding="utf-8"))
    first, second = labels["decisions"][0], labels["decisions"][1]
    first["trackId"], second["trackId"] = second["trackId"], first["trackId"]
    swapped = tmp_path / "swapped.json"
    swapped.write_bytes(a.canonical_json(labels))
    adjudication = json.loads(batch["adjudication"].read_text(encoding="utf-8"))
    adjudication["primaryLabelsSha256"] = a.sha256_hex(swapped.read_bytes())
    rebound = tmp_path / "adjudication.json"
    rebound.write_bytes(a.canonical_json(adjudication))
    refused(capsys, measure_args(world, batch, tmp_path / "o", labels=[swapped], adjudications=[rebound]),
            "pack_labels_mismatch", tmp_path / "o")


def test_undefined_precision_with_adequate_support_does_not_meet_and_stays_null(tmp_path):
    # Humans call three Tracks a bus; MAVI never predicts bus. Bus precision is 0/0 (null) with support 3,
    # above the synthetic minimum of 2, against a non-null precision requirement: not demonstrated.
    requirements = json.loads(json.dumps(f.SYNTHETIC_REQUIREMENTS))
    requirements["operational"]["perClass"]["bus"]["precision"]["minimum"] = 0.5
    requirements["operational"]["perClass"]["motorcycle"]["precision"]["minimum"] = 0.5
    world = f.build_world(tmp_path / "w", LAYOUT, requirements=requirements)
    humans = {n: (("bus", None) if n <= 3 else ("motorcycle", None) if n == 4 else ("car", None)) for n in range(1, 9)}
    batch = p.batch(world, tmp_path / "pilot", target=8, seed="undefined", primary=humans)
    p.run(rm.main, measure_args(world, batch, tmp_path / "out"))
    result = json.loads((tmp_path / "out" / rm.RESULT).read_text(encoding="utf-8"))
    comparison = json.loads((tmp_path / "out" / rm.COMPARISON).read_text(encoding="utf-8"))
    rows = {(c["criterion"], c["class"]): c for c in comparison["criteria"]}
    bus = result["primary"]["metrics"]["perClass"]["bus"]
    assert bus["support"] == 3 and bus["predicted"] == 0
    assert bus["precision"] == {"numerator": 0, "denominator": 0, "value": None}  # the raw value stays null
    assert rows[("precision", "bus")]["status"] == "does-not-meet"
    # Motorcycle: also never predicted, but support 1 is below the minimum of 2.
    assert rows[("precision", "motorcycle")]["status"] == "insufficient-support"
    assert "insufficient-support" in (tmp_path / "out" / rm.SUMMARY).read_text(encoding="utf-8")
