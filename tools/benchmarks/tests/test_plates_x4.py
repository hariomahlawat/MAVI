"""X4-0 offline multi-frame counterfactual: frozen-rule binding, truth-free selection, seam isolation from the
Production plate contracts, fail-closed records, repeat equality and the A0 stop gate. Development tooling only."""
from __future__ import annotations

import ast
import importlib.util
import json
import random
import shutil
import sys
from pathlib import Path
from uuid import UUID

import numpy as np
import pytest
from PIL import Image

_PLATES = Path(__file__).resolve().parents[1] / "plates"
sys.path.insert(0, str(_PLATES))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _PLATES / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


c = _load("x4_common")
sel = _load("x4_select")
x4_extract = _load("x4_extract")
x4_infer = _load("x4_infer")
x4_eval = _load("x4_eval")

TRUTH_NAMES = {"truth", "truth_texts", "O5", "PILOT_RESULT", "PILOT_EXPORTS", "gt_population", "a_eval", "A-eval",
               "oracle", "oracleReadable", "association", "pilot", "gts", "hits", "evaluate_arm"}


# frozen record --------------------------------------------------------------------------------------------------

def test_frozen_record_is_bound_and_matches_the_implementation():
    record, digest = c.rules()
    assert digest == c.EXPECTED["rules"]
    assert record["id"] == c.RULES_ID
    assert "K in {4, 8, all}" in record["arms"]["A-K"] and sel.KS == (4, 8, "all")
    rule = record["decisionRule"]
    for outcome in ("NO_RESULT", "REJECT", "PURSUE", "INCONCLUSIVE"):
        assert outcome in rule
    assert {"P1_PREFERRED", "VISIONJOB_K_PREFERRED", "X4_NATIVE_PREFERRED"} <= set(rule["designPreferenceUnderPursueOnly"])
    assert "scouting" in record["metrics"]["cost"] and "wrongTrackReturns" in record["metrics"]
    assert "wrongTexts" in record["metrics"]
    assert x4_eval.K_ARMS == ("A-4", "A-8", "A-4-native", "A-8-native") and x4_eval.A0_HITS == 52


def test_a_changed_frozen_record_fails_closed(tmp_path, monkeypatch):
    copy = tmp_path / "rules.json"
    copy.write_bytes(c.RULES.read_bytes().replace(b"K in {4, 8, all}", b"K in {4, 8, 16, all}"))
    assert copy.read_bytes() != c.RULES.read_bytes()
    monkeypatch.setattr(c, "RULES", copy)
    with pytest.raises(c.X4Error, match="x4_rules_changed"):
        c.rules()


# selection never sees truth ---------------------------------------------------------------------------------------

def _imports(tree: ast.AST) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            names.add((node.module or "").split(".")[0])
    return names


def _identifiers(tree: ast.AST) -> set[str]:
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            out.add(node.id)
        elif isinstance(node, ast.Attribute):
            out.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.add(node.value)
    return out


def test_selector_module_is_standard_library_only_and_reads_no_truth():
    tree = ast.parse((_PLATES / "x4_select.py").read_text(encoding="utf-8"))
    assert _imports(tree) <= {"__future__", "collections"}
    lowered = {i.lower() for i in _identifiers(tree)}
    assert not {n.lower() for n in TRUTH_NAMES} & lowered


def test_extraction_and_inference_read_no_truth():
    for name in ("x4_extract.py", "x4_infer.py"):
        tree = ast.parse((_PLATES / name).read_text(encoding="utf-8"))
        assert not TRUTH_NAMES & _identifiers(tree), name


def test_eval_selection_and_texts_phase_reads_no_truth():
    tree = ast.parse((_PLATES / "x4_eval.py").read_text(encoding="utf-8"))
    functions = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    for name in ("select_all", "arm_crops", "arm_frames_needed", "texts_all", "seam_summary", "crop_record",
                 "load_inputs", "max_score"):
        assert not TRUTH_NAMES & _identifiers(functions[name]), name
    # In evaluate(), truth is first touched after the selection and text digests are fixed.
    body = [ast.unparse(s) for s in functions["evaluate"].body]
    first_truth = next(i for i, s in enumerate(body) if "gt_population" in s)
    assert first_truth > next(i for i, s in enumerate(body) if s.startswith("texts_digest ="))
    assert first_truth > next(i for i, s in enumerate(body) if "select_all" in s)


def _rows(frames, areas=None):
    return [{"frame": f, "area": (areas or {}).get(f, 0.01 * (f % 7 + 1))} for f in frames]


def test_select_k_takes_everything_when_the_pool_is_small_or_k_is_all():
    pool = _rows([3, 1, 2])
    assert sel.select_k(sorted(pool, key=lambda r: r["frame"]), 4) == (1, 2, 3)
    assert sel.select_k(_rows(range(40)), "all") == tuple(range(40))


def test_select_k_is_temporally_spread_largest_area_per_bin():
    frames = list(range(10, 50))
    areas = {f: 0.001 for f in frames} | {12: 0.5, 25: 0.4, 33: 0.3, 41: 0.2, 11: 0.9}
    # bins of 10 frames: [10..19] -> 11 (0.9), [20..29] -> 25, [30..39] -> 33, [40..49] -> 41
    assert sel.select_k(_rows(frames, areas), 4) == (11, 25, 33, 41)


def test_select_k_fills_empty_bins_by_area_and_breaks_ties_by_lower_frame():
    rows = _rows([0, 1, 2, 3, 100], {0: 0.2, 1: 0.2, 2: 0.1, 3: 0.3, 100: 0.05})
    # 4 bins over 0..100: bin 0 holds 0..3 -> 3; bin 3 holds 100; fill by area: 0 (tie with 1, lower frame)
    assert sel.select_k(rows, 3) == (0, 3, 100)


def test_select_k_ignores_every_field_but_frame_and_area_and_row_order():
    rows = _rows(range(30))
    rng = random.Random(7)
    tagged = [dict(r, truth="ABC123", oracleReadable=rng.random() > 0.5, plateScore=rng.random()) for r in rows]
    rng.shuffle(tagged)
    for k in (4, 8, "all"):
        assert sel.select_k(tagged, k) == sel.select_k(rows, k)


def test_pool_excludes_a0_and_unavailable_frames_and_rejects_duplicates():
    rows = [{"frame": f, "area": 0.1, "box_x": 0} for f in (5, 1, 3, 4)]
    assert [r["frame"] for r in sel.pool(rows, [3], [1, 3, 4])] == [1, 4]
    with pytest.raises(ValueError):
        sel.pool(rows + [{"frame": 1, "area": 0.2}], [], [1])


@pytest.mark.parametrize("a0, pool, expected", [
    ([0.7, None], {4: 0.6, 5: 0.65}, None),          # A0 already holds the best box
    ([0.7], {4: 0.7}, None),                          # ties prefer A0
    ([0.5], {9: 0.8, 4: 0.8}, 4),                     # ties prefer the lower frame
    ([None], {4: None, 5: None}, None),               # no box anywhere
    ([None], {4: None, 5: 0.1}, 5),
])
def test_select_p1_uses_detector_scores_only(a0, pool, expected):
    assert sel.select_p1(a0, pool) == expected


# seam isolation -----------------------------------------------------------------------------------------------------

def _record(rng: random.Random) -> dict:
    detections = []
    for i in range(rng.randint(0, 2)):
        plate = None
        if i == 0 and rng.random() < 0.8:
            text = rng.choice(["AB12CD", "AB12CO", "XY99", "ab-12 cd", "", "??"])
            plate = {"plateIndex": 0, "outcome": rng.choice(["read", "read", "unreadable"]),
                     "readings": [{"rank": 0, "rawText": text, "rawLineCount": 1, "confidence": rng.random()}]}
        detections.append({"box": [1, 1, 5, 3], "score": rng.random(), "plate": plate})
    status = rng.choice(["scored"] * 5 + ["abstained", "output_invalid"])
    return {"status": status, "reason": None if status == "scored" else "detector_error", "width": 40, "height": 30,
            "detections": detections if status == "scored" else []}


def test_seam_summary_equals_production_summarise_track_on_random_four_role_tracks():
    rng = random.Random(11)
    roles = ("representative", "near-view", "early-diverse", "late-diverse")
    for n in range(300):
        k = rng.randint(1, 4)
        observations = [{"role": roles[i], "rank": i, "crop": {"sha256": f"{i:064x}", "sizeBytes": 100}}
                        for i in range(k)]
        crops = tuple(x4_eval.crop_record(_record(rng), x4_eval._uuid(f"t{n}/{o['role']}"), o["role"], o["rank"])
                      for o in observations)
        assert x4_eval.seam_summary(crops) == x4_eval.production_summary("s", f"t{n}", observations, crops)


def test_extra_frames_never_enter_the_v1_lease_contract():
    from mavi_vision.plates import contracts
    from pydantic import ValidationError

    assert contracts.MAXIMUM_TRACK_OBSERVATIONS == 4
    assert contracts.ROLES == ("representative", "near-view", "early-diverse", "late-diverse")
    rng = random.Random(3)
    observations = [{"role": "representative", "rank": i, "crop": {"sha256": f"{i:064x}", "sizeBytes": 100}}
                    for i in range(6)]
    crops = tuple(x4_eval.crop_record(_record(rng), x4_eval._uuid(f"x/{i}"), "x4-extra", i) for i in range(6))
    assert isinstance(x4_eval.seam_summary(crops), tuple)  # the seam takes any number of frames
    with pytest.raises(ValidationError):  # the Production lease still refuses more than four
        x4_eval.production_summary("s", "t", observations, crops)
    # No X4 module writes to a mavi_vision attribute or constructs a lease object for an extra frame.
    for name in ("x4_common.py", "x4_select.py", "x4_extract.py", "x4_infer.py", "x4_eval.py"):
        tree = ast.parse((_PLATES / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AugAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in targets:
                    assert not (isinstance(t, ast.Attribute) and "mavi_vision" in ast.unparse(t)), name
    tree = ast.parse((_PLATES / "x4_eval.py").read_text(encoding="utf-8"))
    users = {f.name for f in ast.walk(tree) if isinstance(f, ast.FunctionDef)
             and {"LeaseObservation", "LeaseTrack"} & _identifiers(f)}
    assert users == {"production_summary"}
    assert "x4-extra" == x4_infer.EXPERIMENT_ROLE


def test_native_crop_is_lossless_through_the_plate_decoder():
    from mavi_vision.plates.inference import decode_crop

    rng = np.random.default_rng(5)
    crop = rng.integers(0, 256, size=(37, 53, 3), dtype=np.uint8)
    assert np.array_equal(np.asarray(decode_crop(x4_extract._native_png(crop))), crop)
    assert x4_extract._native_png(crop) == x4_extract._native_png(crop.copy())


def test_consensus_is_support_then_confidence_then_text():
    oid = UUID(int=0)
    assert x4_eval.consensus(()) is None
    assert x4_eval.consensus((("A", 1, 0.9, oid, 0), ("B", 2, 0.5, oid, 0))) == "B"
    assert x4_eval.consensus((("B", 2, 0.9, oid, 0), ("A", 2, 0.9, oid, 0))) == "A"
    assert x4_eval.consensus((("B", 2, 0.95, oid, 0), ("A", 2, 0.9, oid, 0))) == "B"


# fail-closed records ------------------------------------------------------------------------------------------------

def test_logs_are_deterministic_and_tamper_evident(tmp_path):
    rows = [{"b": 2, "a": [1.5, None]}, {"z": "x"}]
    first = c.write_log(tmp_path / "a.jsonl.gz", rows)
    second = c.write_log(tmp_path / "b.jsonl.gz", rows)
    assert first == second and c.read_log(tmp_path / "a.jsonl.gz", first) == rows
    data = bytearray((tmp_path / "a.jsonl.gz").read_bytes())
    data[-5] ^= 1
    (tmp_path / "a.jsonl.gz").write_bytes(bytes(data))
    with pytest.raises(c.X4Error):
        c.read_log(tmp_path / "a.jsonl.gz", first)
    with pytest.raises(c.X4Error, match="rowcount"):
        c.read_log(tmp_path / "b.jsonl.gz", {**second, "rows": 3})


def _fake_extract(root: Path) -> Path:
    out = root / "extract"
    crops = out / "crops" / "s1"
    crops.mkdir(parents=True)
    png = x4_extract._native_png(np.zeros((4, 4, 3), dtype=np.uint8))
    sha = c.sha_bytes(png)
    (crops / f"{sha}.png").write_bytes(png)
    manifest = [{"trackId": "vehicle-000001", "frame": 0, "native": {"sha256": sha, "sizeBytes": len(png)},
                 "jpeg": None, "excluded": "ladder_refused", "a0Role": None, "offsetMs": 0,
                 "nativeHeightPx": 4, "nativeWidthPx": 4}]
    entry = {"frames": c.write_log(out / "frames" / "s1.jsonl.gz", [{"frame": 0, "offsetMs": 0, "rgbSha256": "0"}]),
             "crops": c.write_log(out / "manifest" / "s1.jsonl.gz", manifest), "store": c.directory_digest(crops),
             "gate": {}, "decodedFrames": 1, "trackFrames": 1}
    c.dump(out / "index.json", {"kind": "x4-extract", "inventorySha256": "i", "gate": {"passed": True},
                                "sequences": {"s1": entry}})
    return out


def test_extract_verify_accepts_a_complete_record(tmp_path):
    assert x4_extract.verify(_fake_extract(tmp_path))["crops"] == 1


@pytest.mark.parametrize("tamper", ["extra_crop", "changed_crop", "missing_manifest", "gate_failed", "missing_crops"])
def test_extract_verify_fails_closed(tmp_path, tamper):
    out = _fake_extract(tmp_path)
    crop = next((out / "crops" / "s1").iterdir())
    if tamper == "extra_crop":
        (out / "crops" / "s1" / "extra.png").write_bytes(b"x")
    elif tamper == "changed_crop":
        crop.write_bytes(crop.read_bytes() + b"\0")
    elif tamper == "missing_manifest":
        (out / "manifest" / "s1.jsonl.gz").unlink()
    elif tamper == "gate_failed":
        index = c.load(out / "index.json")
        index["gate"]["passed"] = False
        c.dump(out / "index.json", index)
    else:
        shutil.rmtree(out / "crops" / "s1")
    with pytest.raises((c.X4Error, FileNotFoundError)):
        x4_extract.verify(out)


def _fake_infer(root: Path) -> Path:
    out = root / "infer"
    rows = [{"sha256": "a" * 64, "kind": "sealed", "sizeBytes": 1, "record": {"status": "scored"}}]
    c.dump(out / "timings.json", {"s1": {}})
    c.dump(out / "index.json", {"kind": "x4-infer", "records": {"s1": c.write_log(out / "records" / "s1.jsonl.gz", rows)}})
    return out


@pytest.mark.parametrize("tamper", ["none", "record_changed", "extra_file", "timings_population"])
def test_infer_verify_fails_closed(tmp_path, tamper):
    out = _fake_infer(tmp_path)
    if tamper == "none":
        assert x4_infer.verify(out)["records"] == 1
        return
    if tamper == "record_changed":
        c.write_log(out / "records" / "s1.jsonl.gz", [{"sha256": "b" * 64}])
    elif tamper == "extra_file":
        c.write_log(out / "records" / "s2.jsonl.gz", [])
    else:
        c.dump(out / "timings.json", {})
    with pytest.raises(c.X4Error):
        x4_infer.verify(out)


def test_runs_require_committed_code_identical_to_the_inventory(monkeypatch):
    monkeypatch.setattr(c, "git_identity", lambda: {"head": "h", "trackedChangesPresent": True})
    with pytest.raises(c.X4Error, match="dirty"):
        c.require_clean_code({"code": {"files": {}}})
    monkeypatch.setattr(c, "git_identity", lambda: {"head": "h", "trackedChangesPresent": False})
    monkeypatch.setattr(c, "code_files", lambda: {"x": "1"})
    with pytest.raises(c.X4Error, match="changed"):
        c.require_clean_code({"code": {"files": {"x": "2"}}})


def test_missing_input_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(c, "PILOT_RESULT", tmp_path / "missing.json")
    with pytest.raises(FileNotFoundError):
        c.inventory()


# repeat equality ----------------------------------------------------------------------------------------------------

def test_repeat_equality_is_on_canonical_content_and_ignores_cpu(tmp_path):
    doc = {"canonical": {"summary": {"A0": {"hits": 52}}}, "cpu": {"A0": {"cpu": 1.0}}, "inputs": {"inventory": "i"}}
    c.dump(tmp_path / "a.json", doc)
    c.dump(tmp_path / "b.json", doc | {"cpu": {"A0": {"cpu": 2.0}}})
    assert x4_eval.equal(tmp_path / "a.json", tmp_path / "b.json")["canonicalEqual"]
    c.dump(tmp_path / "c.json", doc | {"canonical": {"summary": {"A0": {"hits": 53}}}})
    result = x4_eval.equal(tmp_path / "a.json", tmp_path / "c.json")
    assert not result["canonicalEqual"] and result["differing"] == ["summary"]


# decision rule and A0 gate -----------------------------------------------------------------------------------------

def _delta(g, l=0, w=0):
    return {"G": g, "L": l, "W": w, "signTestP": x4_eval.sign_test(max(g, 0), l)}


def _primary(hits):
    return {a: {"hits": h} for a, h in hits.items()}


def _cost(extra_passes):
    return {a: {"detectorPasses": 100 + p, "ocrReads": 0} for a, p in extra_passes.items()}


ALL = ("A0", "A-4", "A-8", "A-all", "A-4-native", "A-8-native", "A-all-native", "P1")


def _decide(g, w=None, p1_hits=52, p1_extra=10_000, l=None):
    w = w or {}
    l = l or {}
    deltas = {a: _delta(g.get(a, 0), l.get(a, 0), w.get(a, 0)) for a in ALL}
    deltas["P1"] = _delta(p1_hits - 52)
    primary = _primary({a: 52 + g.get(a, 0) for a in ALL} | {"P1": p1_hits})
    cost = _cost({a: 0 if a == "A0" else 1000 for a in ALL} | {"P1": p1_extra})
    return x4_eval.decide(primary, deltas, cost)


def test_decision_reject_pursue_and_inconclusive():
    assert _decide({"A-8": 4, "A-8-native": 4})["outcome"] == "REJECT"
    assert _decide({"A-8": 9}, w={"A-8": 9})["outcome"] == "REJECT"           # wrong-Track rise >= gain
    assert _decide({"A-8": 6})["outcome"] == "INCONCLUSIVE"                    # 5..7
    assert _decide({"A-8": 9}, w={"A-8": 3})["outcome"] == "INCONCLUSIVE"      # 2 < W < G
    assert _decide({"A-8": 10}, w={"A-8": 2})["outcome"] == "PURSUE"
    assert _decide({"A-8": 10}, l={"A-8": 1})["outcome"] != "PURSUE"


def test_design_preference_under_pursue():
    vjk = _decide({"A-8": 10, "A-8-native": 11})
    assert vjk["designPreference"] == "VISIONJOB_K_PREFERRED" and vjk["best"] == "A-8-native"
    x4 = _decide({"A-8": 8, "A-8-native": 12})
    assert x4["designPreference"] == "X4_NATIVE_PREFERRED"
    p1 = _decide({"A-8": 10}, p1_hits=60, p1_extra=500)
    assert p1["designPreference"] == "P1_PREFERRED"
    scouted = _decide({"A-8": 10}, p1_hits=62, p1_extra=5000)   # scouting makes P1 costlier
    assert scouted["designPreference"] != "P1_PREFERRED"
    assert _decide({"A-8": 6})["designPreference"] is None


def test_sign_test():
    assert x4_eval.sign_test(0, 0) == 1.0
    assert x4_eval.sign_test(8, 0) == pytest.approx(1 / 256)
    assert x4_eval.sign_test(4, 0) == pytest.approx(1 / 16)


def test_a0_parity_failure_stops_the_evaluation(monkeypatch):
    monkeypatch.setattr(x4_eval, "load_inputs", lambda *a: {"inputs": {}, "frames": {}})
    monkeypatch.setattr(x4_eval, "select_all", lambda data: {})
    monkeypatch.setattr(x4_eval, "texts_all", lambda data, s: ({a: {} for a in x4_eval.ARMS + x4_eval.CEILING_ARMS},
                                                               {}, {"passed": True}))
    monkeypatch.setattr(x4_eval, "gt_population", lambda data: ({}, {}, {}))
    monkeypatch.setattr(x4_eval, "evaluate_arm", lambda texts, gts, agg: {"rows": {}, "hits": 51, "wrongTrackReturns": 0})
    monkeypatch.setattr(x4_eval, "a0_parity", lambda *a: {"passed": False, "hits": 51})
    with pytest.raises(c.X4Error, match="x4_a0_parity_failed"):
        x4_eval.evaluate(Path("i"), Path("e"), Path("f"))


def test_seam_mismatch_stops_the_evaluation(monkeypatch):
    monkeypatch.setattr(x4_eval, "load_inputs", lambda *a: {"inputs": {}, "frames": {}})
    monkeypatch.setattr(x4_eval, "select_all", lambda data: {})
    monkeypatch.setattr(x4_eval, "texts_all", lambda data, s: ({}, {}, {"passed": False}))
    with pytest.raises(c.X4Error, match="x4_seam_summary_differs"):
        x4_eval.evaluate(Path("i"), Path("e"), Path("f"))


def test_wrong_track_returns_wrong_texts_and_hits():
    oid = UUID(int=0)
    texts = {("s", "t1"): (("AB12", 1, 0.9, oid, 0), ("ZZ9", 1, 0.8, oid, 0)), ("s", "t2"): (("AB12", 1, 0.7, oid, 0),),
             ("s", "t3"): ()}
    gts = {"s/g1": {"state": "matched", "mavi": ("s", "t1"), "wanted": ["AB12"], "oracleReadable": True},
           "s/g2": {"state": "unmatchedGt", "mavi": None, "wanted": ["AB12"], "oracleReadable": False}}
    result = x4_eval.evaluate_arm(texts, gts, "primary")
    assert result["hits"] == 1 and result["hitsOracleReadable"] == 1
    assert result["rows"]["s/g1"]["wrongTrackReturns"] == 1 and result["rows"]["s/g2"]["wrongTrackReturns"] == 2
    assert result["rows"]["s/g1"]["wrongTexts"] == ["ZZ9"] and result["tracksCarryingText"] == 2
    consensus = x4_eval.evaluate_arm(texts, gts, "consensus")
    assert consensus["hits"] == 1 and consensus["catalogueTrackTextPairs"] == 2
