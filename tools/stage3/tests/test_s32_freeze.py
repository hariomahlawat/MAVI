"""T5: freezing reviewer decisions and the prediction-blind adjudication of the overlap."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import build_labeling_pack as bp
import freeze_labels as fl
import s32fixtures as f
import s32pipeline as p

a = f.a
LAYOUT = {"CAM-A": [f.TrackSpec(number=n, subclass="car", start=200 * n, end=200 * n + 900,
                                track_id=f"00000000-0000-4000-8000-{n:012d}") for n in range(1, 7)]}


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("freeze")
    world = f.build_world(root / "world", LAYOUT)
    sample = root / "sample.json"
    p.run(p.sample_tracks.main, p.sample(world, sample, target=6, overlap="0.5"))  # k = 3
    primary, overlap = root / "primary", root / "overlap"
    p.run(bp.main, p.pack(world, sample, primary))
    p.run(bp.main, p.pack(world, sample, overlap, view="overlap", parent=primary))
    numbers = {t.track_id: t.number for t in LAYOUT["CAM-A"]}
    overlap_numbers = sorted(numbers[i["trackId"]] for i in json.loads(sample.read_text(encoding="utf-8"))["overlapSelected"])
    return world, root, primary, overlap, overlap_numbers


def items(pack: Path) -> list[dict]:
    return json.loads((pack / bp.MANIFEST).read_text(encoding="utf-8"))["items"]


def write_draft(pack: Path, decisions: list[dict], out: Path, reviewer: str = "Reviewer A", pack_sha: str | None = None) -> Path:
    pack_sha = pack_sha or a.sha256_hex((pack / bp.MANIFEST).read_bytes())
    out.write_text(json.dumps({"packSha256": pack_sha, "reviewerName": reviewer, "decisions": decisions}), encoding="utf-8")
    return out


def all_car(pack: Path) -> list[dict]:
    return [{"itemId": item["itemId"], "label": "car"} for item in items(pack)]


def refused(capsys, args, code, out=None):
    assert fl.main(args) == 2
    assert f"refused {code}" in capsys.readouterr().err
    if out is not None:
        assert not out.exists()


def freeze(pack: Path, decisions: list[dict], out: Path, reviewer: str = "Reviewer A") -> Path:
    draft = write_draft(pack, decisions, out.with_suffix(".draft.json"), reviewer)
    p.run(fl.main, p.freeze(pack, draft, reviewer, out))
    return out


# freeze


def test_freeze_binds_pack_view_guide_sample_and_resolves_tracks(built, tmp_path):
    world, _, primary, overlap, _ = built
    labels = json.loads(freeze(overlap, all_car(overlap), tmp_path / "o.json", "Reviewer B").read_text(encoding="utf-8"))
    manifest = json.loads((overlap / bp.MANIFEST).read_text(encoding="utf-8"))
    assert labels["viewKind"] == "overlap"
    assert labels["parentPackSha256"] == a.sha256_hex((primary / bp.MANIFEST).read_bytes())
    assert labels["packSha256"] == a.sha256_hex((overlap / bp.MANIFEST).read_bytes())
    assert labels["labelingGuideSha256"] == manifest["labelingGuide"]["sha256"]
    assert labels["sampleSha256"] == manifest["sampleSha256"] and labels["exportSha256s"] == manifest["exportSha256s"]
    assert labels["reviewer"] == {"name": "Reviewer B", "role": "fixture reviewer"} and labels["reviewedOn"] == "2026-10-03"
    by_item = {i["itemId"]: i for i in manifest["items"]}
    for decision in labels["decisions"]:
        assert decision["trackId"] == by_item[decision["itemId"]]["trackId"]
    assert [d["trackId"] for d in labels["decisions"]] == sorted(d["trackId"] for d in labels["decisions"])
    primary_labels = json.loads(freeze(primary, all_car(primary), tmp_path / "p.json").read_text(encoding="utf-8"))
    assert primary_labels["viewKind"] == "primary" and "parentPackSha256" not in primary_labels


def test_freeze_is_deterministic_and_write_once(built, tmp_path, capsys):
    _, _, primary, _, _ = built
    first = freeze(primary, all_car(primary), tmp_path / "a.json")
    second = freeze(primary, all_car(primary), tmp_path / "b.json")
    assert first.read_bytes() == second.read_bytes()
    draft = write_draft(primary, all_car(primary), tmp_path / "d.json")
    refused(capsys, p.freeze(primary, draft, "Reviewer A", first), "output_exists")


def _bad(primary, kind):
    decisions = all_car(primary)
    if kind == "missing":
        return decisions[1:]
    if kind == "duplicate":
        return decisions + [decisions[0]]
    if kind == "foreign":
        return decisions[:-1] + [{"itemId": "0123456789abcdef", "label": "car"}]
    if kind == "vocabulary":
        decisions[0]["label"] = "van"
    if kind == "reason_without_unknown":
        decisions[0]["unknownReason"] = "occluded"
    if kind == "unknown_without_reason":
        decisions[0]["label"] = "unknown"
    if kind == "bad_reason":
        decisions[0].update(label="unknown", unknownReason="dark")
    if kind == "long_note":
        decisions[0]["note"] = "n" * 201
    if kind == "multiline_note":
        decisions[0]["note"] = "two\nlines"
    if kind == "extra_member":
        decisions[0]["predicted"] = "car"
    return decisions


@pytest.mark.parametrize("kind, code", [
    ("missing", "decision_missing"), ("duplicate", "decision_duplicate"), ("foreign", "decision_item_not_in_pack"),
    ("vocabulary", "decision_vocabulary"), ("reason_without_unknown", "decision_vocabulary"),
    ("unknown_without_reason", "decision_vocabulary"), ("bad_reason", "decision_vocabulary"),
    ("long_note", "decision_note_invalid"), ("multiline_note", "decision_note_invalid"), ("extra_member", "decision_invalid"),
])
def test_freeze_refusals(built, tmp_path, capsys, kind, code):
    _, _, primary, _, _ = built
    draft = write_draft(primary, _bad(primary, kind), tmp_path / "d.json")
    refused(capsys, p.freeze(primary, draft, "Reviewer A", tmp_path / "l.json"), code, tmp_path / "l.json")


def test_freeze_refuses_another_pack_reviewer_or_date(built, tmp_path, capsys):
    _, _, primary, _, _ = built
    draft = write_draft(primary, all_car(primary), tmp_path / "d1.json", pack_sha="f" * 64)
    refused(capsys, p.freeze(primary, draft, "Reviewer A", tmp_path / "l1.json"), "draft_pack_mismatch", tmp_path / "l1.json")
    draft = write_draft(primary, all_car(primary), tmp_path / "d2.json")
    refused(capsys, p.freeze(primary, draft, "Someone else", tmp_path / "l2.json"), "draft_reviewer_mismatch", tmp_path / "l2.json")
    refused(capsys, p.freeze(primary, draft, " ", tmp_path / "l3.json"), "reviewer_invalid", tmp_path / "l3.json")
    args = p.freeze(primary, draft, "Reviewer A", tmp_path / "l4.json")
    args[args.index("--reviewed-on") + 1] = "2026-13-40"
    refused(capsys, args, "reviewed_on_invalid", tmp_path / "l4.json")


def test_freeze_refuses_a_tampered_pack(built, tmp_path, capsys):
    _, _, primary, _, _ = built
    copy = tmp_path / "pack"
    shutil.copytree(primary, copy)
    (copy / bp.PACK_DATA).write_bytes((copy / bp.PACK_DATA).read_bytes() + b"// edited\n")
    draft = write_draft(primary, all_car(primary), tmp_path / "d.json")
    refused(capsys, p.freeze(copy, draft, "Reviewer A", tmp_path / "l.json"), "pack_data_mismatch", tmp_path / "l.json")


# adjudication


def frozen_pair(built, tmp_path, primary_choice, overlap_choice):
    """Primary and overlap labels; choices map an overlap Track position (0, 1, 2) to (label, reason)."""
    world, _, primary, overlap, overlap_numbers = built
    by_track = {t.track_id: t.number for t in LAYOUT["CAM-A"]}

    def decisions(pack, choice):
        out = []
        for item in items(pack):
            number = by_track[item["trackId"]]
            label, reason = choice.get(overlap_numbers.index(number), ("car", None)) if number in overlap_numbers else ("car", None)
            out.append({"itemId": item["itemId"], "label": label, **({"unknownReason": reason} if reason else {})})
        return out

    first = freeze(primary, decisions(primary, primary_choice), tmp_path / "primary-labels.json")
    second = freeze(overlap, decisions(overlap, overlap_choice), tmp_path / "overlap-labels.json", "Reviewer B")
    return first, second


def adjudicate_args(first, second, decisions_path, out):
    return ["adjudicate", "--primary", str(first), "--overlap", str(second), "--decisions", str(decisions_path),
            "--adjudicator", "Adjudicator C", "--adjudicated-on", "2026-10-04", "--out", str(out)]


def write_decisions(first, second, decisions, path):
    primary_sha, overlap_sha = a.sha256_hex(first.read_bytes()), a.sha256_hex(second.read_bytes())
    path.write_text(json.dumps({"primaryLabelsSha256": primary_sha, "overlapLabelsSha256": overlap_sha,
                                "sessionId": fl.session_id(primary_sha, overlap_sha), "decisions": decisions}), encoding="utf-8")
    return path


def primary_item(first, built, position):
    _, _, _, _, overlap_numbers = built
    track = f"00000000-0000-4000-8000-{overlap_numbers[position]:012d}"
    return next(d["itemId"] for d in json.loads(first.read_text(encoding="utf-8"))["decisions"] if d["trackId"] == track)


def test_agreement_carries_and_disagreement_needs_a_decision(built, tmp_path):
    first, second = frozen_pair(built, tmp_path,
                                {0: ("truck", None), 1: ("unknown", "occluded"), 2: ("unknown", "occluded")},
                                {0: ("truck", None), 1: ("unknown", "occluded"), 2: ("unknown", "too-small")})
    decisions = write_decisions(first, second, [{"itemId": primary_item(first, built, 2), "adjudicatedLabel": "unknown",
                                                 "adjudicatedUnknownReason": "too-small"}], tmp_path / "d.json")
    out = tmp_path / "adj.json"
    p.run(fl.main, adjudicate_args(first, second, decisions, out))
    document = json.loads(out.read_text(encoding="utf-8"))
    resolutions = sorted((i["resolution"], i["adjudicatedLabel"], i.get("adjudicatedUnknownReason")) for i in document["items"])
    assert resolutions == [("adjudicated", "unknown", "too-small"), ("carried", "truck", None), ("carried", "unknown", "occluded")]
    differing = next(i for i in document["items"] if i["resolution"] == "adjudicated")
    assert differing["primary"] == {"label": "unknown", "unknownReason": "occluded"}  # both originals preserved
    assert differing["overlap"] == {"label": "unknown", "unknownReason": "too-small"}
    again = tmp_path / "adj2.json"
    p.run(fl.main, adjudicate_args(first, second, decisions, again))
    assert again.read_bytes() == out.read_bytes()


def test_car_against_unknown_too_small_is_adjudicated_to_unknown(built, tmp_path, capsys):
    first, second = frozen_pair(built, tmp_path, {0: ("car", None)}, {0: ("unknown", "too-small")})
    item = primary_item(first, built, 0)
    missing = write_decisions(first, second, [{"itemId": item, "adjudicatedLabel": "unknown"}], tmp_path / "d1.json")
    refused(capsys, adjudicate_args(first, second, missing, tmp_path / "a1.json"), "adjudication_reason_missing", tmp_path / "a1.json")
    invalid = write_decisions(first, second, [{"itemId": item, "adjudicatedLabel": "unknown", "adjudicatedUnknownReason": "far"}],
                              tmp_path / "d2.json")
    refused(capsys, adjudicate_args(first, second, invalid, tmp_path / "a2.json"), "adjudication_reason_invalid", tmp_path / "a2.json")
    with_reason = write_decisions(first, second, [{"itemId": item, "adjudicatedLabel": "car", "adjudicatedUnknownReason": "too-small"}],
                                  tmp_path / "d3.json")
    refused(capsys, adjudicate_args(first, second, with_reason, tmp_path / "a3.json"), "adjudication_reason_not_allowed", tmp_path / "a3.json")
    good = write_decisions(first, second, [{"itemId": item, "adjudicatedLabel": "unknown", "adjudicatedUnknownReason": "too-small"}],
                           tmp_path / "d4.json")
    p.run(fl.main, adjudicate_args(first, second, good, tmp_path / "a4.json"))
    document = json.loads((tmp_path / "a4.json").read_text(encoding="utf-8"))
    disputed = next(i for i in document["items"] if i["resolution"] == "adjudicated")
    assert (disputed["adjudicatedLabel"], disputed["adjudicatedUnknownReason"]) == ("unknown", "too-small")


def test_decisions_for_carried_items_and_missing_decisions_are_refused(built, tmp_path, capsys):
    first, second = frozen_pair(built, tmp_path, {0: ("car", None)}, {0: ("bus", None)})
    carried = primary_item(first, built, 1)
    disputed = primary_item(first, built, 0)
    unexpected = write_decisions(first, second, [{"itemId": disputed, "adjudicatedLabel": "bus"},
                                                 {"itemId": carried, "adjudicatedLabel": "car"}], tmp_path / "d1.json")
    refused(capsys, adjudicate_args(first, second, unexpected, tmp_path / "a1.json"), "adjudication_decision_unexpected")
    none = write_decisions(first, second, [], tmp_path / "d2.json")
    refused(capsys, adjudicate_args(first, second, none, tmp_path / "a2.json"), "adjudication_decision_missing")
    stranger = write_decisions(first, second, [{"itemId": "0123456789abcdef", "adjudicatedLabel": "bus"}], tmp_path / "d3.json")
    refused(capsys, adjudicate_args(first, second, stranger, tmp_path / "a3.json"), "adjudication_item_unknown")
    stale = tmp_path / "d4.json"
    stale.write_text(json.dumps({"primaryLabelsSha256": "0" * 64, "overlapLabelsSha256": a.sha256_hex(second.read_bytes()),
                                 "sessionId": fl.session_id(a.sha256_hex(first.read_bytes()), a.sha256_hex(second.read_bytes())),
                                 "decisions": [{"itemId": disputed, "adjudicatedLabel": "bus"}]}), encoding="utf-8")
    refused(capsys, adjudicate_args(first, second, stale, tmp_path / "a4.json"), "adjudication_decisions_mismatch")


def test_unfrozen_or_mismatched_label_files_are_refused(built, tmp_path, capsys):
    _, _, primary, _, _ = built
    first, second = frozen_pair(built, tmp_path, {}, {})
    pretty = tmp_path / "pretty.json"
    pretty.write_text(json.dumps(json.loads(first.read_text(encoding="utf-8")), indent=2), encoding="utf-8")
    refused(capsys, ["adjudicate-prepare", "--primary", str(pretty), "--overlap", str(second), "--pack", str(primary),
                     "--out", str(tmp_path / "sheet")], "labels_not_frozen", tmp_path / "sheet")
    refused(capsys, ["adjudicate-prepare", "--primary", str(second), "--overlap", str(first), "--pack", str(primary),
                     "--out", str(tmp_path / "sheet")], "overlap_pack_not_derived", tmp_path / "sheet")


def test_adjudication_sheet_shows_evidence_and_both_human_decisions_only(built, tmp_path):
    world, _, primary, _, _ = built
    first, second = frozen_pair(built, tmp_path, {0: ("car", None)}, {0: ("unknown", "too-small")})
    sheet = tmp_path / "sheet"
    p.run(fl.main, ["adjudicate-prepare", "--primary", str(first), "--overlap", str(second), "--pack", str(primary),
                    "--out", str(sheet)])
    payload = json.loads((sheet / fl.ADJUDICATION_DATA).read_text(encoding="utf-8")
                         .removeprefix("window.MAVI_ADJUDICATION = ").rstrip(";\n"))
    assert set(payload) == {"packSha256", "primaryLabelsSha256", "overlapLabelsSha256", "sessionId", "items"}
    assert payload["sessionId"] == fl.session_id(a.sha256_hex(first.read_bytes()), a.sha256_hex(second.read_bytes()))
    assert payload["sessionId"] == a.h("mavi-s32-adjudication-session", payload["primaryLabelsSha256"], payload["overlapLabelsSha256"])
    for item in payload["items"]:
        assert set(item) == {"itemId", "primary", "overlap", "needsDecision"}
    assert sum(item["needsDecision"] for item in payload["items"]) == 1
    assert not (sheet / bp.MANIFEST).exists()
    text = "".join(path.read_text(encoding="utf-8", errors="ignore") for path in sheet.rglob("*") if path.suffix in (".js", ".html"))
    for forbidden in ("objectSubclass", "Confidence", "detector-native", world.profile_sha, *(v.run_id for v in world.videos)):
        assert forbidden not in text


def test_adjudication_commands_accept_no_prediction_inputs():
    parser = fl.parser()
    commands = next(action for action in parser._actions if action.dest == "command").choices
    for name in ("adjudicate-prepare", "adjudicate"):
        options = {option for action in commands[name]._actions for option in action.option_strings}
        assert not {o for o in options if any(word in o for word in ("export", "result", "attestation", "measurement", "profile"))}


def test_each_frozen_pair_is_its_own_adjudication_session(built, tmp_path, capsys):
    _, _, primary_pack, _, _ = built
    (tmp_path / "one").mkdir()
    (tmp_path / "two").mkdir()
    first_pair = frozen_pair(built, tmp_path / "one", {0: ("car", None)}, {0: ("bus", None)})
    second_pair = frozen_pair(built, tmp_path / "two", {0: ("car", None)}, {0: ("truck", None)})
    sessions = []
    for index, (first, second) in enumerate((first_pair, second_pair)):
        sheet = tmp_path / f"sheet-{index}"
        p.run(fl.main, ["adjudicate-prepare", "--primary", str(first), "--overlap", str(second), "--pack", str(primary_pack),
                        "--out", str(sheet)])
        payload = json.loads((sheet / fl.ADJUDICATION_DATA).read_text(encoding="utf-8")
                             .removeprefix("window.MAVI_ADJUDICATION = ").rstrip(";\n"))
        assert payload["packSha256"] == a.sha256_hex((primary_pack / bp.MANIFEST).read_bytes())
        sessions.append(payload["sessionId"])
    assert sessions[0] != sessions[1]  # same primary pack, different frozen pairs

    first, second = first_pair
    item = primary_item(first, built, 0)
    stale = write_decisions(first, second, [{"itemId": item, "adjudicatedLabel": "bus"}], tmp_path / "stale.json")
    later_first, later_second = second_pair
    # As exported for the first pair: refused against the second.
    refused(capsys, adjudicate_args(later_first, later_second, stale, tmp_path / "a1.json"), "adjudication_session_mismatch",
            tmp_path / "a1.json")
    # Even with its file hashes rewritten to the second pair, the stale session is refused.
    document = json.loads(stale.read_text(encoding="utf-8"))
    document["primaryLabelsSha256"] = a.sha256_hex(later_first.read_bytes())
    document["overlapLabelsSha256"] = a.sha256_hex(later_second.read_bytes())
    rewritten = tmp_path / "rewritten.json"
    rewritten.write_text(json.dumps(document), encoding="utf-8")
    refused(capsys, adjudicate_args(later_first, later_second, rewritten, tmp_path / "a2.json"), "adjudication_session_mismatch",
            tmp_path / "a2.json")
    # A decisions document without a session is malformed.
    del document["sessionId"]
    rewritten.write_text(json.dumps(document), encoding="utf-8")
    refused(capsys, adjudicate_args(later_first, later_second, rewritten, tmp_path / "a3.json"), "adjudication_decisions_invalid",
            tmp_path / "a3.json")


def test_page_resume_keys_labelling_by_pack_and_adjudication_by_session():
    script = (bp.TEMPLATES / "labeling.js").read_text(encoding="utf-8")
    assert '"mavi-s32-adjudication:" + adjudication.sessionId' in script
    assert '"mavi-s32-labels:" + pack.packSha256' in script
    assert '"mavi-s32-adjudication:" + pack.packSha256' not in script
    assert "sessionId: adjudication.sessionId" in script  # carried in the exported decisions
