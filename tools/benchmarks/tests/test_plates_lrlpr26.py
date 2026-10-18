"""LRLPR-26 aggregation experiment (Stage 4, Development only): the read-only adapter's fail-closed data binding and
text-free split, the frozen eligibility/policy/selection/statistics/decision rules, and the run-integrity refusals.
Synthetic fixtures only: no dataset bytes and no dataset plate strings."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from tools.benchmarks.datasets import lrlpr26

_PLATES = Path(__file__).resolve().parents[1] / "plates"
sys.path.insert(0, str(_PLATES))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _PLATES / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


core = _load("lrlpr26_core")
rd = _load("lrlpr26_read")
ev = _load("lrlpr26_eval")

E = core.Lrlpr26ExperimentError


# synthetic dataset ------------------------------------------------------------------------------------------------

def _image(ext: str, seed: int) -> bytes:
    image = Image.new("RGB", (40, 16), (seed % 256, (seed * 7) % 256, (seed * 13) % 256))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG" if ext == "png" else "JPEG", quality=90)
    return buffer.getvalue()


TRACKS = [  # (track, scenario, layout, synthetic text)
    ("track_00001", "Scenario-A", "Brazilian", "AAA1111"),
    ("track_00002", "Scenario-A", "Mercosur", "BBB2C22"),
    ("track_00003", "Scenario-A", "Brazilian", "AAA1111"),  # repeats track 1's text: one group
    ("track_00501", "Scenario-B", "Brazilian", "CCC3333"),
    ("track_00502", "Scenario-B", "Mercosur", "DDD4E44"),
    ("track_00503", "Scenario-B", "Mercosur", "EEE5F55"),  # shares one image with 502: one group
]


def _write_dataset(tmp_path: Path, mutate=None) -> dict:
    root = tmp_path / "train"
    manifest_lines, members = [], {}
    shared = None
    for n, (track, scenario, layout, text) in enumerate(TRACKS):
        ext = lrlpr26.SCENARIOS[scenario]
        tdir = root / scenario / layout / track
        tdir.mkdir(parents=True)
        for i, frame in enumerate(lrlpr26.FRAMES):
            data = _image(ext, n * 20 + i)
            if track == "track_00502" and frame == "hr-005":
                shared = data
            if track == "track_00503" and frame == "hr-005":
                data = shared
            (tdir / f"{frame}.{ext}").write_bytes(data)
            rel = f"{scenario}/{layout}/{track}/{frame}.{ext}"
            manifest_lines.append(f"{hashlib.sha256(data).hexdigest()}  {len(data)}  {rel}")
        annotation = json.dumps({"plate_text": text, "plate_layout": layout}).encode()
        (tdir / "annotations.json").write_bytes(annotation)
        members[f"train/{scenario}/{layout}/{track}/annotations.json"] = annotation
    manifest = tmp_path / "manifest.sha256"
    manifest.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
    archive = tmp_path / "train.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    if mutate:
        mutate(root, manifest, archive)
    expected = {"trainArchiveSha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                "trainArchiveBytes": archive.stat().st_size,
                "trainManifestSha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
                "trainManifestRows": len(TRACKS) * 10, "tracks": len(TRACKS)}
    return {"root": root, "manifest": manifest, "archive": archive, "expected": expected}


def _load_ds(ds):
    return lrlpr26.load_tracks(ds["root"], ds["manifest"], ds["archive"], ds["expected"])


def test_adapter_loads_hash_bound_tracks_with_normalised_truth(tmp_path):
    ds = _write_dataset(tmp_path)
    tracks, extra = _load_ds(ds)
    assert [t.track_id for t in tracks] == [t[0] for t in sorted(TRACKS, key=lambda r: (r[1], r[2], r[0]))]
    first = next(t for t in tracks if t.track_id == "track_00002")
    assert first.truth == "BBB2C22" and first.stratum == "Scenario-A/Mercosur"
    assert [f.name for f in first.lr_frames] == list(core.FRAMES)
    assert extra["inventory"]["trainArchive"]["annotationMembers"] == len(TRACKS)


@pytest.mark.parametrize("mutation,code", [
    (lambda root, m, a: (root / "Scenario-A/Brazilian/track_00001/extra.txt").write_bytes(b"x"),
     "lrlpr26_unexpected_track_files"),
    (lambda root, m, a: (root / "Scenario-A/Brazilian/track_00001/lr-003.png").unlink(), "lrlpr26_unexpected_track_files"),
    (lambda root, m, a: (root / "Scenario-C").mkdir(), "lrlpr26_unexpected_scenarios"),
    (lambda root, m, a: (root / "Scenario-A/Brazilian/notatrack").mkdir(), "lrlpr26_unexpected_entry"),
])
def test_adapter_fails_closed_on_unexpected_structure(tmp_path, mutation, code):
    ds = _write_dataset(tmp_path, mutation)
    with pytest.raises(lrlpr26.Lrlpr26Error, match=code):
        _load_ds(ds)


def test_adapter_fails_closed_on_changed_image_byte(tmp_path):
    ds = _write_dataset(tmp_path)
    path = ds["root"] / "Scenario-B/Mercosur/track_00502/lr-001.jpg"
    data = bytearray(path.read_bytes())
    data[-3] ^= 1
    path.write_bytes(bytes(data))
    with pytest.raises(lrlpr26.Lrlpr26Error, match="lrlpr26_image_mismatch"):
        _load_ds(ds)


def test_adapter_fails_closed_on_manifest_archive_and_annotation_mismatch(tmp_path):
    ds = _write_dataset(tmp_path)
    with pytest.raises(lrlpr26.Lrlpr26Error, match="lrlpr26_manifest_sha_mismatch"):
        lrlpr26.load_tracks(ds["root"], ds["manifest"], ds["archive"], {**ds["expected"], "trainManifestSha256": "0" * 64})
    with pytest.raises(lrlpr26.Lrlpr26Error, match="lrlpr26_archive_sha_mismatch"):
        lrlpr26.load_tracks(ds["root"], ds["manifest"], ds["archive"], {**ds["expected"], "trainArchiveSha256": "0" * 64})
    (ds["root"] / "Scenario-A/Mercosur/track_00002/annotations.json").write_bytes(
        json.dumps({"plate_text": "BBB2C23", "plate_layout": "Mercosur"}).encode())
    with pytest.raises(lrlpr26.Lrlpr26Error, match="lrlpr26_annotation_differs_from_archive"):
        _load_ds(ds)


def test_adapter_refuses_layout_mismatch_and_unnormalisable_text(tmp_path):
    def wrong_layout(root, m, archive):
        (root / "Scenario-A/Mercosur/track_00002/annotations.json").write_bytes(
            json.dumps({"plate_text": "BBB2C22", "plate_layout": "Brazilian"}).encode())
    ds = _write_dataset(tmp_path / "a", wrong_layout)
    with pytest.raises(lrlpr26.Lrlpr26Error, match="lrlpr26_annotation_differs_from_archive|lrlpr26_annotation_layout"):
        _load_ds(ds)
    ds = _write_dataset(tmp_path / "b", wrong_layout)
    with pytest.raises(lrlpr26.Lrlpr26Error, match="lrlpr26_annotation_layout"):
        lrlpr26.load_tracks(ds["root"], ds["manifest"], None, ds["expected"])
    with pytest.raises(lrlpr26.Lrlpr26Error, match="lrlpr26_annotation_text_not_normalisable"):
        lrlpr26.normalised_truth("AB#12")


def test_split_groups_by_text_and_image_and_is_text_free_and_deterministic(tmp_path):
    ds = _write_dataset(tmp_path)
    tracks, extra = _load_ds(ds)
    groups = lrlpr26.plate_groups(tracks, extra["imageHashes"])
    assert sorted(map(sorted, groups.values())) == sorted([["track_00001", "track_00003"], ["track_00002"],
                                                           ["track_00501"], ["track_00502", "track_00503"]])
    identities = lrlpr26.split_identities(extra["inventory"])
    first = core.canonical(lrlpr26.build_split(tracks, extra["imageHashes"], identities))
    second = core.canonical(lrlpr26.build_split(tracks, extra["imageHashes"], identities))
    assert first == second
    doc = json.loads(first)
    for _, _, _, text in TRACKS:
        assert text.encode() not in first and hashlib.sha256(text.encode()).hexdigest().encode() not in first
    assert doc["tracks"]["track_00001"][:2] == doc["tracks"]["track_00003"][:2]  # same side, same group
    assert doc["tracks"]["track_00502"][:2] == doc["tracks"]["track_00503"][:2]
    expected = "EVAL" if int(hashlib.sha256(b"lrlpr26-split-v1|AAA1111").hexdigest(), 16) % 2 else "DEV"
    assert doc["tracks"]["track_00001"][0] == expected
    assert doc["counts"]["tracks"] == len(TRACKS) and doc["counts"]["groups"] == 4


def test_block_split_excludes_eval_side_of_conflict_groups():
    tracks = [lrlpr26.CropTrack(tid, "Scenario-A", "Brazilian", (), text)
              for tid, text in (("track_00001", "AAA1111"), ("track_00600", "AAA1111"), ("track_01100", "BBB2222"))]
    hashes = {t.track_id: [] for t in tracks}
    sides = {b: lrlpr26._hash_side(f"lrlpr26-block-v1|Scenario-A|{b}") for b in (0, 1, 2)}
    doc = lrlpr26.build_split(tracks, hashes, {})
    block = {tid: row[2] for tid, row in doc["tracks"].items()}
    if sides[0] != sides[1]:
        eval_member = "track_00001" if sides[0] == "EVAL" else "track_00600"
        assert block[eval_member] == "EXCLUDED" and doc["blockSplitCounts"]["excluded"] == 1
    else:
        assert "EXCLUDED" not in block.values()
    assert block["track_01100"] == sides[2]


def test_read_truths_rebinds_annotation_digest(tmp_path):
    ds = _write_dataset(tmp_path)
    _, extra = _load_ds(ds)
    digest = extra["inventory"]["annotationsDigest"]
    assert lrlpr26.read_truths({"track_00001"}, digest, ds["root"]) == {"track_00001": "AAA1111"}
    with pytest.raises(lrlpr26.Lrlpr26Error, match="lrlpr26_annotations_digest_mismatch"):
        lrlpr26.read_truths({"track_00001"}, "0" * 64, ds["root"])


# eligibility and policies -----------------------------------------------------------------------------------------

def _r(text, confidence, status="ok"):
    if status != "ok":
        return {"status": status, "rawText": None, "confidence": None}
    return {"status": "ok", "rawText": text, "confidence": confidence}


NONE = _r(None, None, "empty")


def test_floor_is_inclusive_at_half_and_normalisation_must_be_ok():
    readings = [_r("AAA1111", 0.5), _r("AAA1111", 0.49999999), _r("aa-a1 111", 0.9), _r("A#1", 0.9), NONE]
    assert core.eligible_readings(readings, 0.5) == [(0, "AAA1111", 0.5), (2, "AAA1111", 0.9)]
    assert core.raw_texts(readings) == ["AAA1111", "AAA1111", "AAA1111"]  # U-raw: no floor


def test_ineligible_statuses_contribute_nothing_and_invalid_records_are_refused():
    readings = [_r(None, None, s) for s in ("empty", "ocrError", "outputInvalid")]
    assert core.eligible_readings(readings, 0.5) == []
    with pytest.raises(E, match="lrlpr26_reading_ok_invalid"):
        core.eligible_readings([_r("AAA1111", float("nan"))], 0.5)
    with pytest.raises(E, match="lrlpr26_reading_status_invalid"):
        core.eligible_readings([{"status": "weird", "rawText": None, "confidence": None}], 0.5)


def test_n0_and_n1_abstentions():
    zero = core.accept_all([NONE] * 5, 0.5, k=2, tau="0.50")
    assert all(v == [] for v in zero.values())
    one_last = core.accept_all([NONE] * 4 + [_r("AAA1111", 0.9)], 0.5, k=2, tau="0.50")
    assert one_last["S1"] == one_last["SB"] == one_last["U"] == ["AAA1111"]
    assert one_last["C*"] == [] and one_last["A*"] == []
    one_first = core.accept_all([_r("AAA1111", 0.9)] + [NONE] * 4, 0.5, k=2, tau="0.50")
    assert one_first["S1"] == [] and one_first["SB"] == ["AAA1111"]


def test_sb_tie_goes_to_lowest_frame_and_u_is_distinct_union():
    eligible = [(0, "AAA1111", 0.8), (1, "BBB2222", 0.9), (3, "CCC3333", 0.9)]
    assert core.policy_sb(eligible) == ["BBB2222"]
    assert core.policy_u(eligible + [(4, "AAA1111", 0.7)]) == ["AAA1111", "BBB2222", "CCC3333"]


def test_c_requires_unique_leader_with_support_k():
    two_two = [(0, "AAA1111", 0.9), (1, "AAA1111", 0.9), (2, "BBB2222", 0.9), (3, "BBB2222", 0.9), (4, "CCC3333", 0.9)]
    assert core.policy_c(two_two, 2) == []  # tie in support
    three = [(0, "AAA1111", 0.6), (1, "AAA1111", 0.6), (2, "AAA1111", 0.6), (3, "BBB2222", 0.99)]
    assert core.policy_c(three, 3) == ["AAA1111"] and core.policy_c(three, 4) == []


def test_a_ties_minimum_support_and_exact_tau_boundary():
    tie = [(0, "AAA1111", 0.5), (1, "AAA1111", 0.5), (2, "BBB2222", 0.5), (3, "BBB2222", 0.5)]
    assert core.policy_a(tie, "0.50") == []  # equal w
    lone = [(0, "AAA1111", 0.99), (1, "BBB2222", 0.5)]
    assert core.policy_a(lone, "0.50") == []  # s(t*) < 2
    c = 0.7
    share = [(0, "AAA1111", c), (1, "AAA1111", c), (2, "AAA1111", c), (3, "BBB2222", c), (4, "CCC3333", c)]
    assert core.policy_a(share, "0.60") == ["AAA1111"]  # exactly 3/5 >= 0.60
    assert core.policy_a(share, "0.70") == []
    agree = [(0, "AAA1111", 0.6), (1, "AAA1111", 0.8)]
    assert core.policy_a(agree, "1.00") == ["AAA1111"]


def test_a_zero_and_non_finite_weight_guard():
    assert core.policy_a([(0, "AAA1111", 0.0), (1, "AAA1111", 0.0)], "0.50") == []
    assert core.policy_a([(0, "AAA1111", float("nan")), (1, "AAA1111", 0.9)], "0.50") == []
    assert core.policy_a([(0, "AAA1111", float("inf")), (1, "AAA1111", 0.9)], "0.50") == []


# measures and selection -------------------------------------------------------------------------------------------

def test_track_outcome_union_counts_both_correct_and_incorrect():
    o = core.track_outcome(["AAA1111", "BBB2222", "CCC3333"], "AAA1111")
    assert o == {"correct": 1, "incorrect": 1, "covered": 1, "pairs": 3, "correctPairs": 1, "wrong": 2}
    m = core.measures([o, core.track_outcome([], "AAA1111")])
    assert m["correctTextRecall"]["value"] == 0.5 and m["coverage"]["value"] == 0.5
    assert m["predictionPrecision"]["numerator"] == 1 and m["predictionPrecision"]["denominator"] == 3
    assert m["wrongTextDistribution"] == {"0": 1, "1": 0, ">=2": 1}
    assert core.measures([core.track_outcome([], "AAA1111")])["predictionPrecision"]["value"] is None


def _m(tracks, correct, incorrect):
    return {"tracks": tracks, "correctTextRecall": {"numerator": correct},
            "incorrectTextAcceptance": {"numerator": incorrect}}


def test_selection_feasibility_recall_and_tie_breaks():
    rows = {2: _m(1000, 800, 11), 3: _m(1000, 780, 10), 4: _m(1000, 780, 9), 5: _m(1000, 700, 2)}
    picked = core.select_family("C", rows)
    assert picked["status"] == core.FEASIBLE and picked["selected"] == 4  # 2 infeasible; 3/4 tie → lower incorrect
    rows = {2: _m(1000, 800, 20), 3: _m(1000, 780, 5), 4: _m(1000, 780, 5), 5: _m(1000, 700, 2)}
    assert core.select_family("C", rows)["selected"] == 4  # full tie → stricter
    rows = {t: _m(1000, 500, 10) for t in core.A_GRID}
    assert core.select_family("A", rows)["selected"] == "1.00"  # all tie, 10/1000 = 1.0% is feasible
    rows = {t: _m(1000, 500, 11) for t in core.A_GRID}
    infeasible = core.select_family("A", rows)
    assert infeasible["status"] == core.INFEASIBLE and infeasible["selected"] == "1.00"
    with pytest.raises(E, match="lrlpr26_selection_grid_incomplete"):
        core.select_family("C", {2: _m(1, 1, 0)})


# statistics -------------------------------------------------------------------------------------------------------

def _outcomes(pattern):
    return [core.track_outcome(acc, "AAA1111") for acc in pattern]


def test_bootstrap_is_deterministic_and_paired():
    x = _outcomes([["AAA1111"], [], ["BBB2222"], ["AAA1111"]] * 25)
    y = _outcomes([["AAA1111", "BBB2222"], ["AAA1111"], ["BBB2222"], ["AAA1111"]] * 25)
    groups = [i // 2 for i in range(100)]
    w1 = core.resample_weights(50)
    w2 = core.resample_weights(50)
    assert (w1 == w2).all() and w1.shape == (2000, 50) and (w1.sum(axis=1) == 50).all()
    sx, sy = core.group_sums(x, groups, 50), core.group_sums(y, groups, 50)
    a, b = core.paired_bootstrap(sx, sy, w1), core.paired_bootstrap(sx, sy, w2)
    assert a == b
    assert a["recallLoss"]["point"] == pytest.approx(0.25)
    assert a["incorrectTextAcceptance"]["point"] == pytest.approx(-0.25)
    self_diff = core.paired_bootstrap(sx, sx, w1)
    assert self_diff["correctTextRecall"]["ci95"] == [0.0, 0.0]


def test_mcnemar_exact():
    assert core.mcnemar([1, 1, 0, 0], [1, 1, 0, 0]) == {"b": 0, "c": 0, "p": 1.0}
    result = core.mcnemar([1] * 6 + [0], [0] * 6 + [0])
    assert result["b"] == 6 and result["c"] == 0 and result["p"] == pytest.approx(2 / 64)


# decision ---------------------------------------------------------------------------------------------------------

def _vs_u(inc_ci, loss_point, loss_ci):
    return {"incorrectTextAcceptance": {"ci95": list(inc_ci)}, "recallLoss": {"point": loss_point, "ci95": list(loss_ci)}}


def _amc(**cis):
    base = {m: {"ci95": [-0.01, 0.01]} for m in core.MEASURES}
    for k, v in cis.items():
        base[k] = {"ci95": list(v)}
    return base


GOOD = _vs_u((-0.05, -0.02), 0.01, (0.0, 0.02))


def test_decision_supported_and_simplicity_default():
    c1, a1 = core.family_step1(core.FEASIBLE, GOOD), core.family_step1(core.FEASIBLE, GOOD)
    d = core.decide(c1, a1, _amc())
    assert d["outcome"] == core.SUPPORTED and d["preferred"] == "C*"
    d = core.decide(c1, a1, _amc(correctTextRecall=(0.001, 0.02)))
    assert d["preferred"] == "A*"
    d = core.decide(c1, a1, _amc(correctTextRecall=(0.001, 0.02), predictionPrecision=(-0.03, -0.001)))
    assert d["preferred"] == "C*"  # a measure favours C*
    only_a = core.decide(core.family_step1(core.FEASIBLE, _vs_u((-0.01, 0.01), 0.0, (0, 0.01))), a1, _amc())
    assert only_a["outcome"] == core.SUPPORTED and only_a["preferred"] == "A*"


def test_decision_recall_limits_and_infeasible_cannot_be_supported():
    assert not core.family_step1(core.FEASIBLE, _vs_u((-0.05, -0.02), 0.031, (0.02, 0.04)))["supported"]
    assert not core.family_step1(core.FEASIBLE, _vs_u((-0.05, -0.02), 0.02, (0.01, 0.051)))["supported"]
    assert core.family_step1(core.FEASIBLE, _vs_u((-0.05, -0.02), 0.03, (0.01, 0.05)))["supported"]
    assert not core.family_step1(core.INFEASIBLE, GOOD)["supported"]


def test_decision_not_supported_requires_negative_evidence_in_every_family():
    infeasible = core.family_step1(core.INFEASIBLE, GOOD)
    no_reduction = core.family_step1(core.FEASIBLE, _vs_u((0.0, 0.02), 0.0, (0.0, 0.01)))
    recall_missed = core.family_step1(core.FEASIBLE, _vs_u((-0.05, -0.02), 0.06, (0.031, 0.08)))
    spans = core.family_step1(core.FEASIBLE, _vs_u((-0.02, 0.01), 0.01, (0.0, 0.02)))
    assert core.decide(infeasible, no_reduction, _amc())["outcome"] == core.NOT_SUPPORTED
    assert core.decide(recall_missed, infeasible, _amc())["outcome"] == core.NOT_SUPPORTED
    assert core.decide(spans, infeasible, _amc())["outcome"] == core.INCONCLUSIVE
    straddle = core.family_step1(core.FEASIBLE, _vs_u((-0.05, -0.02), 0.04, (0.02, 0.06)))
    assert core.decide(straddle, no_reduction, _amc())["outcome"] == core.INCONCLUSIVE


# integrity --------------------------------------------------------------------------------------------------------

def test_repeat_mismatch_is_invalid():
    core.require_repeat_equal([("phase1", "a"), ("phase2", "a"), ("phase2T", "a")])
    with pytest.raises(E, match="lrlpr26_repeat_not_equal:phase2"):
        core.require_repeat_equal([("phase1", "a"), ("phase2", "b"), ("phase2T", "a")])
    with pytest.raises(E, match="lrlpr26_pass_order"):
        core.require_repeat_equal([("phase1", "a"), ("phase2T", "a"), ("phase2", "a")])


def test_canonical_logs_are_deterministic_and_fail_closed():
    rows = [{"trackId": "track_00001", "frames": [{"b": 1, "a": 0.5}]}]
    data1, entry1 = core.log_entry(rows)
    data2, entry2 = core.log_entry(json.loads(json.dumps(rows)))
    assert data1 == data2 and entry1 == entry2
    assert core.decode_log(data1, entry1, "x") == rows
    with pytest.raises(E, match="lrlpr26_log_gzip_mismatch"):
        core.decode_log(data1 + b"\0", entry1, "x")
    with pytest.raises(E, match="lrlpr26_log_rowcount_mismatch"):
        core.decode_log(data1, {**entry1, "rows": 2}, "x")


class _Recogniser:
    def __init__(self, result):
        self.result = result

    def read(self, region, verified, box):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_read_frame_maps_outputs_to_statuses():
    png = _image("png", 3)
    ok = SimpleNamespace(raw_text="ABC1234", confidence=0.75)
    assert rd.read_frame(_Recogniser([ok]), png)[0] == {"status": "ok", "rawText": "ABC1234", "confidence": 0.75}
    assert rd.read_frame(_Recogniser([]), png)[0]["status"] == "empty"
    assert rd.read_frame(_Recogniser(ValueError("plate_recogniser_confidence_invalid")), png)[0]["status"] == "ocrError"
    assert rd.read_frame(_Recogniser([ok, ok]), png)[0]["status"] == "outputInvalid"
    bad = SimpleNamespace(raw_text="ABC\x01", confidence=0.75)
    assert rd.read_frame(_Recogniser([bad]), png)[0]["status"] == "outputInvalid"
    assert rd.read_frame(_Recogniser([ok]), b"not an image")[0]["status"] == "ocrError"


def test_rules_inventory_and_read_bindings_refuse_mismatch(tmp_path):
    rules = tmp_path / "rules.json"
    rules.write_bytes(core.canonical({"id": rd.RULES_ID}))
    digest = core.sha_bytes(rules.read_bytes())
    assert rd.rules(rules, digest)[1] == digest
    with pytest.raises(E, match="lrlpr26_rules_sha_mismatch"):
        rd.rules(rules, "0" * 64)
    bogus = tmp_path / "inv.json"
    bogus.write_bytes(core.canonical({"kind": "something-else"}))
    with pytest.raises(E, match="lrlpr26_inventory_invalid"):
        rd.load_inventory(bogus)
    out = tmp_path / "read"
    out.mkdir()
    rows = [{"trackId": "track_00001", "frames": [{"frame": f, "sha256": "0" * 64, **NONE} for f in core.FRAMES]}]
    data, entry = core.log_entry(rows)
    (out / "records.jsonl.gz").write_bytes(data)
    rd.dump(out / "timings.json", {"track_00001": {"frames": []}})
    index = {"kind": "lrlpr26-read", "pass": "phase1", "records": entry,
             "timingsSha256": rd.sha_file(out / "timings.json"),
             "statusCounts": {"empty": 5, "ok": 0, "ocrError": 0, "outputInvalid": 0}}
    rd.dump(out / "index.json", index)
    assert rd.verify(out)["tracks"] == 1
    (out / "stray.txt").write_bytes(b"")
    with pytest.raises(E, match="lrlpr26_read_files_extra_or_missing"):
        rd.verify(out)
    with pytest.raises(E, match="lrlpr26_output_exists"):
        rd.dump(out / "index.json", index)


def test_eval_refuses_missing_or_mismatched_selection(tmp_path, monkeypatch):
    selection = tmp_path / "selection.json"
    selection.write_bytes(core.canonical({"kind": ev.KIND_SELECTION}))
    digest = core.sha_bytes(selection.read_bytes())
    with pytest.raises(E, match="lrlpr26_selection_sha_mismatch"):
        ev.load_selection(selection, "0" * 64, {})
    monkeypatch.setattr(ev, "COMMITTED_SELECTION", tmp_path / "missing.json")
    with pytest.raises(E, match="lrlpr26_selection_not_committed"):
        ev.load_selection(selection, digest, {})
    with pytest.raises(E, match="lrlpr26_selection_missing"):
        ev.load_selection(tmp_path / "absent.json", digest, {})


# committed frozen identities --------------------------------------------------------------------------------------

def test_committed_rules_bind_split_parameters_models_and_grids():
    record, digest = rd.rules()
    assert digest == rd.EXPECTED_RULES_SHA256
    split = lrlpr26.load_split(rd.ROOT / record["data"]["split"]["path"], record["data"]["split"]["sha256"])
    assert split["counts"]["tracks"] == 20000 and len(split["tracks"]) == 20000
    assert {row[0] for row in split["tracks"].values()} == {"DEV", "EVAL"}
    assert rd.sha_file(rd.PARAMETERS) == record["parameters"]["sha256"] and rd.floor_of(record) == 0.5
    assert record["grids"] == {"C": {"k": list(core.C_GRID)}, "A": {"tau": list(core.A_GRID)}}
    assert record["statistics"]["bootstrap"]["seed"] == core.BOOTSTRAP_SEED
    assert record["statistics"]["bootstrap"]["resamples"] == core.BOOTSTRAP_RESAMPLES
    assert record["data"]["trainArchiveSha256"] == lrlpr26.EXPECTED["trainArchiveSha256"]
    assert record["data"]["trainManifestSha256"] == lrlpr26.EXPECTED["trainManifestSha256"]
    for name, sha in record["ocr"]["codeSha256AtFreeze"].items():
        assert rd.sha_file(rd.ROOT / name) == sha, name
    payloads = {p["file"]: p["sha256"] for p in json.loads(rd.PAYLOADS.read_bytes())["payloads"]
                if p["packDirectory"] == "plates-oc1-s-dev-v1"}
    assert all(payloads[name] == sha for name, sha in record["ocr"]["files"].items())


# synthetic end-to-end scoring -------------------------------------------------------------------------------------

def _synthetic_inputs(n: int = 240) -> dict:
    import random

    rng = random.Random(7)
    tracks, readings, truths, strata, timing = {}, {}, {}, {}, {}
    letters = "ABCDEFGHJK"
    for i in range(1, n + 1):
        tid = f"track_{i:05d}"
        truth = "".join(rng.choice(letters) for _ in range(3)) + f"{i:04d}"
        truths[tid] = truth
        side = "DEV" if i % 2 else "EVAL"
        block = ("DEV", "EVAL", "EXCLUDED")[i % 3]
        tracks[tid] = [side, i // 2, block]
        strata[tid] = {"stratum": ("Scenario-A/Brazilian", "Scenario-B/Mercosur")[i % 2 == 0 and i % 4 == 0]}
        frames = []
        for f in core.FRAMES:
            roll = rng.random()
            if roll < 0.1:
                frames.append(NONE)
            elif roll < 0.75:
                frames.append(_r(truth, round(rng.uniform(0.3, 1.0), 6)))
            else:
                frames.append(_r(truth[:-1] + "9", round(rng.uniform(0.3, 1.0), 6)))
        readings[tid] = frames
        timing[tid] = {"frames": [{"decodeCpuMs": 0.1, "readCpuMs": 40.0 + k, "readWallMs": 41.0} for k in range(5)]}
    read = {"indexSha256": "1" * 64, "recordsCanonicalSha256": "2" * 64, "machine": {"python": "x"},
            "execution": {"workers": 10}, "wallSeconds": 1.0}
    return {"inventory": {"parametersSha256": "3" * 64, "models": {}, "tracks": strata}, "inventorySha256": "4" * 64,
            "rulesSha256": "5" * 64, "splitSha256": "6" * 64, "floor": 0.5, "split": {"tracks": tracks},
            "readings": readings, "truths": truths, "reads": {p: read for p in rd.PASSES},
            "timings": [timing, timing, timing]}


def test_synthetic_selection_evaluation_and_secondary_are_deterministic():
    inputs = _synthetic_inputs()
    selection = ev.select_from_inputs(inputs)
    assert selection["population"]["tracks"] == 120 and set(selection["families"]) == {"C", "A"}
    assert selection == ev.select_from_inputs(inputs)
    first = core.canonical(ev.evaluate_document(inputs, selection, "7" * 64))
    assert first == core.canonical(ev.evaluate_document(inputs, selection, "7" * 64))
    document = json.loads(first)
    assert document["population"]["tracks"] == 120
    assert document["decision"]["outcome"] in (core.SUPPORTED, core.NOT_SUPPORTED, core.INCONCLUSIVE)
    assert set(document["measures"]["overall"]) == {"S1", "SB", "U", "C*", "A*", "U-raw"}
    assert document["costs"]["medianOcrCpuMsPerTrack"] == pytest.approx(210.0)
    assert document["costs"]["medianS1OcrCpuMsPerTrack"] == pytest.approx(44.0)
    secondary = ev.secondary_document(inputs, selection, "7" * 64, core.sha_bytes(first))
    assert secondary["blockSplit"]["population"]["excluded"] == 80
    assert set(secondary["frameBudget"]["byFrames"]) == {"1", "3", "5"}
    assert secondary["frameBudget"]["byFrames"]["1"]["measures"]["A*"]["coverage"]["numerator"] == 0
    assert core.canonical(secondary) == core.canonical(
        ev.secondary_document(inputs, selection, "7" * 64, core.sha_bytes(first)))


def test_selection_never_reads_eval_truth():
    inputs = _synthetic_inputs()
    dev_only = {**inputs, "truths": {t: v for t, v in inputs["truths"].items() if inputs["split"]["tracks"][t][0] == "DEV"}}
    assert ev.select_from_inputs(dev_only) == ev.select_from_inputs(inputs)
    with pytest.raises(KeyError):
        ev.evaluate_document(dev_only, ev.select_from_inputs(dev_only), "7" * 64)
