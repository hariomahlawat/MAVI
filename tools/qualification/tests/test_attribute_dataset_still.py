"""PA-100K and UPAR adapters, label mappings and the person still-dataset manifest (plan §4–§6).

Synthetic releases in the real formats prove the tooling. The real pinned files are
verified separately and never enter tests.
"""

from __future__ import annotations

import copy
import json

import numpy as np
import pytest
from attribute_dataset_fixtures import (
    SMALL_ROWS,
    annotation_mat,
    colour_values,
    determination,
    image_for,
    jpeg,
    release_record,
    upar_csv,
    write_pa100k,
    write_upar,
)

from attributes.corpus.canonical import CorpusError, canonical_json
from attributes.corpus.duplicates import dhash64, pigeonhole_pairs
from attributes.datasets import mapping as mp
from attributes.datasets import still_manifest as sm
from attributes.datasets.adapters import pa100k, upar

PA, UP = "pa-100k-2017", "upar-challenge-2027-a19ab2fb"


@pytest.fixture(autouse=True)
def small_release(monkeypatch):
    monkeypatch.setattr(pa100k, "SPLIT_ROWS", dict(SMALL_ROWS))
    monkeypatch.setattr(sm, "SMOKE", {"seed": "fixture-smoke", "perSplit": {"train": 120, "val": 20, "test": 20}})


def member(n: int) -> str:
    return f"{pa100k.IMAGE_PREFIX}{n:06d}.jpg"


def build(tmp_path, images=None, upar_train=None, upar_val=None, pa_det=..., up_det=..., excluded=(), smoke=False, policy=None):
    pa_root, up_root = tmp_path / "pa", tmp_path / "upar"
    if not pa_root.exists():
        write_pa100k(pa_root, images=images)
        train = upar_train if upar_train is not None else [(f"PA100k/{member(n)}", colour_values("Blue", "Black")) for n in range(1, 1201, 2)]
        val = upar_val if upar_val is not None else [(f"PA100k/{member(n)}", colour_values("Red", "Grey")) for n in range(1301, 1401)]
        write_upar(up_root, train, val)
    pa = release_record(PA, pa_root, "cc-by-4.0", pa_det, excluded)
    up = release_record(UP, up_root, "cc-by-nc-sa-3.0-de", up_det)
    return sm.build_person_manifest(pa, pa_root, up, up_root, smoke=smoke, policy=policy or sm.PERSON_POLICY)


def by_member(manifest) -> dict:
    return {s["memberPath"]: s for s in manifest["samples"]}


# ---------------------------------------------------------------- PA-100K adapter


def test_pa100k_rows_preserve_official_splits_and_synthetic_groups():
    rows = pa100k.parse_annotation(annotation_mat())
    assert [sum(r["sourceSplit"] == s for r in rows) for s in pa100k.SPLITS] == [1200, 100, 100]
    first = rows[0]
    assert first["memberPath"] == member(1) and first["sourceSplit"] == "train"
    assert first["group"] == {"id": "pa100k-block-0000", "kind": "synthetic-allocation"}
    assert rows[499]["imageNumber"] == 500 and rows[499]["group"]["id"] == "pa100k-block-0000"  # images 1..500
    assert rows[500]["imageNumber"] == 501 and rows[500]["group"]["id"] == "pa100k-block-0001"
    assert set(first["labels"]) == set(pa100k.ATTRIBUTES) and all(v in (0, 1) for v in first["labels"].values())


@pytest.mark.parametrize("edit,code", [
    (lambda c: c.pop("val_label"), "variables"),
    (lambda c: c.update(extra_variable=np.zeros((1, 1))), "variables"),
    (lambda c: c.update(train_label=c["train_label"][:-1]), "label_shape"),
    (lambda c: c.update(test_images_name=c["test_images_name"][:-1]), "row_count"),
    (lambda c: c.update(attributes=c["attributes"][::-1]), "attributes_differ"),
    (lambda c: c.update(train_label=c["train_label"][:, :-1]), "label_shape"),
    (lambda c: c["val_label"].__setitem__((3, 4), 2), "not_binary"),
    (lambda c: c["test_images_name"].__setitem__((0, 0), "000001.jpg"), "repeated"),
    (lambda c: c["test_images_name"].__setitem__((0, 0), "../x.jpg"), "image_name"),
])
def test_malformed_matlab_structures_are_refused(edit, code):
    with pytest.raises(CorpusError, match=code):
        pa100k.parse_annotation(annotation_mat(edit=edit))


def test_a_non_matlab5_file_is_refused():
    with pytest.raises(CorpusError, match="not_matlab5"):
        pa100k.parse_annotation(b"MATLAB 7.3 MAT-file, HDF5" + b"\x00" * 200)
    with pytest.raises(CorpusError, match="unreadable"):
        pa100k.parse_annotation(b"MATLAB 5.0 MAT-file" + b"\x00" * 50)


def test_wrong_row_counts_against_the_pinned_release_are_refused(monkeypatch):
    monkeypatch.setattr(pa100k, "SPLIT_ROWS", {"train": 80000, "val": 10000, "test": 10000})
    with pytest.raises(CorpusError, match="row_count"):
        pa100k.parse_annotation(annotation_mat())


# ---------------------------------------------------------------- UPAR adapter


def test_upar_keeps_only_pa100k_rows_by_the_exact_prefix_rule():
    data = upar_csv([(f"PA100k/{member(7)}", colour_values("Blue", "Black")), ("PETA/x/1.png", colour_values("Red", "Red")),
                     ("pa100k/release_data/release_data/000008.jpg", colour_values("Red", "Red"))])
    rows, counts = upar.parse_csv(data, "train")
    assert list(rows) == [member(7)] and counts == {"PA100k": 1, "PETA": 1, "pa100k": 1}
    assert rows[member(7)]["labels"]["UpperBody-Color-Blue"] == 1


def test_the_misaligned_top_level_csv_layout_is_refused():
    misaligned = upar_csv([], header=("# " + upar.COLUMNS[0],) + upar.COLUMNS[1:])
    with pytest.raises(CorpusError, match="misaligned_top_level_layout"):
        upar.parse_csv(misaligned, "train")


@pytest.mark.parametrize("header,code", [
    (upar.HEADER[:-1] + ("Accessory-Umbrella",), "header_unexpected"),
    (upar.HEADER[:-1] + ("Accessory-Bag",), "repeated_column"),
    (upar.HEADER + ("Extra",), "header_unexpected"),
    (("image",) + upar.COLUMNS, "header_unexpected"),
])
def test_unknown_repeated_or_shifted_columns_are_refused(header, code):
    with pytest.raises(CorpusError, match=code):
        upar.parse_csv(upar_csv([], header=header), "train")


@pytest.mark.parametrize("row,code", [
    ([f"PA100k/{member(1)}"] + ["0"] * 39, "row_width"),
    ([f"PA100k/{member(1)}"] + ["0"] * 41, "row_width"),
    ([f"PA100k/{member(1)}"] + ["0"] * 39 + ["2"], "not_binary"),
    ([f"PA100k/{member(1)}"] + ["0"] * 39 + [" 1"], "not_binary"),
    (["no-prefix.jpg"] + ["0"] * 40, "row_key"),
])
def test_malformed_rows_are_refused(row, code):
    data = (",".join(upar.HEADER) + "\n" + ",".join(row) + "\n").encode()
    with pytest.raises(CorpusError, match=code):
        upar.parse_csv(data, "train")


def test_a_repeated_key_or_one_in_both_files_is_refused(tmp_path):
    key = f"PA100k/{member(1)}"
    with pytest.raises(CorpusError, match="row_repeated"):
        upar.parse_csv(upar_csv([(key, colour_values("Red", "Red")), (key, colour_values("Red", "Red"))]), "train")
    write_upar(tmp_path, [(key, colour_values("Red", "Red"))], [(key, colour_values("Red", "Red"))])
    with pytest.raises(CorpusError, match="both_splits"):
        upar.read_rows(tmp_path)


# ---------------------------------------------------------------- mappings


def test_committed_mappings_parse_and_keep_their_identities():
    mappings = sm.load_person_mappings()
    assert {m: mp.mapping_sha256(d) for m, d in mappings.items()} == {
        "pa100k-person-presence-v1": "a89f9c52535652cdb73328e2f64ba02e16456dc686741c39844641078a64cd0f",
        "upar-task1-person-colour-v1": "6c3b58878f0c14b296f8934133abd88b5db69022af989ec32e1cf77c51db06bc",
    }


@pytest.mark.parametrize("edit,code", [
    (lambda d: d["unmapped"].pop(), "label_unaccounted"),
    (lambda d: d["unmapped"].append({"label": "Umbrella", "reason": "x"}), "label_unknown"),
    (lambda d: d["unmapped"].append({"label": "Backpack", "reason": "x"}), "label_repeated"),
    (lambda d: d["attributes"][1]["sourceLabels"].append("HoldObjectsInFront"), "label_repeated"),
    (lambda d: d["attributes"][0].update(attributeType="person-upper-colour"), "binary_needs_presence"),
    (lambda d: d["attributes"][0].update(attributeType="vehicle-colour"), "object_class"),
    (lambda d: d["attributes"][0].update(semantics="operational"), "semantics"),
    (lambda d: d.update(sourceLabels=d["sourceLabels"][::-1]), "source_labels"),
])
def test_a_mapping_must_account_for_every_label_exactly_once(edit, code):
    doc = copy.deepcopy(sm.load_person_mappings()["pa100k-person-presence-v1"])
    edit(doc)
    with pytest.raises(CorpusError, match=code):
        mp.parse_mapping(doc)


def test_colour_mapping_values_must_be_known_and_unique():
    doc = copy.deepcopy(sm.load_person_mappings()["upar-task1-person-colour-v1"])
    doc["attributes"][0]["columns"]["UpperBody-Color-Other"] = "multicolour"
    with pytest.raises(CorpusError, match="colour_value_unknown"):
        mp.parse_mapping(doc)
    doc = copy.deepcopy(sm.load_person_mappings()["upar-task1-person-colour-v1"])
    doc["attributes"][0]["columns"]["UpperBody-Color-Pink"] = "red"
    with pytest.raises(CorpusError, match="colour_value_repeated"):
        mp.parse_mapping(doc)


def test_presence_mapping_semantics():
    m = sm.load_person_mappings()["pa100k-person-presence-v1"]
    labels = dict.fromkeys(pa100k.ATTRIBUTES, 0)
    out = mp.apply_mapping(m, {**labels, "HoldObjectsInFront": 1})
    assert out["person-bag"] == {"outcome": "source-binary", "value": "negative", "semantics": "proxy"}  # never a bag
    assert mp.apply_mapping(m, {**labels, "ShoulderBag": 1})["person-bag"]["value"] == "positive"
    assert mp.apply_mapping(m, {**labels, "HandBag": 1})["person-bag"]["value"] == "positive"
    assert out["person-headwear"] == {"outcome": "source-binary", "value": "negative", "semantics": "proxy"}  # Hat=0 is not MAVI absent
    assert out["person-backpack"] == {"outcome": "source-binary", "value": "negative", "semantics": "source-native"}
    with pytest.raises(CorpusError, match="source_labels_differ"):
        mp.apply_mapping(m, {"Backpack": 1})


@pytest.mark.parametrize("upper,expected", [
    ("Blue", {"outcome": "value", "value": "blue"}),
    ("Grey", {"outcome": "value", "value": "grey"}),
    ("Other", {"outcome": "unmapped", "value": None}),
    (("Red", "White"), {"outcome": "unscorable", "value": "ambiguous"}),
    (("Other", "Red"), {"outcome": "unscorable", "value": "ambiguous"}),
])
def test_colour_mapping_semantics(upper, expected):
    m = sm.load_person_mappings()["upar-task1-person-colour-v1"]
    labels = dict(zip(upar.COLUMNS, colour_values(upper, "Black")))
    assert mp.apply_mapping(m, labels)["person-upper-colour"] == {**expected, "semantics": "source-native"}
    assert mp.apply_mapping(m, dict(zip(upar.COLUMNS, colour_values(None, "Black"))))["person-upper-colour"] is None


# ---------------------------------------------------------------- pigeonhole primitive


def test_pigeonhole_finds_near_pairs_and_not_far_ones():
    values = {"a": 0x0000_0000_0000_0000, "b": 0x0000_0000_0000_000F, "c": 0xFFFF_FFFF_FFFF_FFFF, "d": 0x00FF_00FF_00FF_00FF}
    pairs, degenerate = pigeonhole_pairs(values, 4)
    assert pairs == [("a", "b", 4)] and degenerate == []
    assert pigeonhole_pairs(values, 3)[0] == []
    assert pigeonhole_pairs(values, 4, lambda x, y: {x, y} == {"a", "b"})[0] == []
    with pytest.raises(CorpusError, match="duplicate_threshold"):
        pigeonhole_pairs(values, 8)


def test_a_degenerate_bucket_is_reported_and_not_expanded():
    # 30 hashes that differ only in byte 1: every other byte is one 30-member bucket.
    values = {f"k{i:02d}": i << 8 for i in range(30)}
    pairs, degenerate = pigeonhole_pairs(values, 7, bucket_cap=10)
    assert pairs == [] and sorted(d["byte"] for d in degenerate) == [0, 2, 3, 4, 5, 6, 7]
    assert all(d == {"byte": d["byte"], "value": 0, "members": 30} for d in degenerate)
    uncapped, none = pigeonhole_pairs(values, 7)
    assert len(uncapped) == 30 * 29 // 2 and none == []


def test_colour_distinct_solid_images_share_a_dhash():
    hashes = {c: dhash64(jpeg(rgb)) for c, rgb in {"red": (200, 0, 0), "green": (0, 120, 0), "blue": (0, 0, 255)}.items()}
    assert len(set(hashes.values())) == 1


# ---------------------------------------------------------------- manifest: roles, truth, lineage


def test_roles_follow_official_splits_and_seeded_allocation_groups(tmp_path):
    manifest, _ = build(tmp_path)
    samples = by_member(manifest)
    assert all(s["role"] == "development" for s in samples.values() if s["sourceSplit"] == "val")
    assert all(s["role"] == "benchmark" for s in samples.values() if s["sourceSplit"] == "test")
    train = [s for s in samples.values() if s["sourceSplit"] == "train"]
    selected_groups = {s["group"]["id"] for s in train if s["role"] == "selection"}
    assert len(selected_groups) == 1  # ceil(3 groups * 0.1)
    assert all((s["role"] == "selection") == (s["group"]["id"] in selected_groups) for s in train)
    assert {s["group"]["kind"] for s in samples.values()} == {"synthetic-allocation"}
    assert manifest["counts"]["roles"] == {"benchmark": 100, "development": 100, "selection": 500, "training": 700}


def test_truth_lineage_and_missing_coverage(tmp_path):
    manifest, _ = build(tmp_path, upar_train=[(f"PA100k/{member(1)}", colour_values(("Red", "Blue"), "Other"))], upar_val=[])
    one, two = by_member(manifest)[member(1)], by_member(manifest)[member(2)]
    assert one["attributes"]["person-upper-colour"] == {"truth": "present", "outcome": "unscorable", "value": "ambiguous", "semantics": "source-native",
                                                         "labelReleaseId": UP, "mappingId": "upar-task1-person-colour-v1"}
    assert one["attributes"]["person-lower-colour"]["outcome"] == "unmapped"
    assert two["attributes"]["person-upper-colour"] == {"truth": "missing", "outcome": None, "value": None, "semantics": "source-native",
                                                         "labelReleaseId": UP, "mappingId": "upar-task1-person-colour-v1"}
    assert two["attributes"]["person-bag"]["labelReleaseId"] == PA and two["attributes"]["person-bag"]["semantics"] == "proxy"
    assert manifest["sourceCoverage"]["uparPa100kRowsByOfficialSplit"] == {"train": 1, "val": 0, "test": 0}


def test_an_archive_that_differs_from_the_annotation_is_refused(tmp_path):
    import zipfile
    write_pa100k(tmp_path / "pa")
    write_upar(tmp_path / "upar", [], [])
    with zipfile.ZipFile(tmp_path / "pa" / pa100k.IMAGE_ARCHIVE, "a") as z:
        z.writestr(member(9999), image_for(9999))
    with pytest.raises(CorpusError, match="archive_differs_from_annotation:1-unlisted"):
        build(tmp_path)


def test_upar_naming_an_image_outside_pa100k_is_refused(tmp_path):
    with pytest.raises(CorpusError, match="not_in_pa100k"):
        build(tmp_path, upar_train=[(f"PA100k/{member(5000)}", colour_values("Red", "Red"))], upar_val=[])


def test_no_frozen_role_exists_and_an_unknown_role_is_refused(tmp_path):
    manifest, _ = build(tmp_path)
    assert "frozen-test" not in sm.ROLE_PURPOSE and "frozen-qualification" not in sm.ROLE_PURPOSE.values()
    forged = copy.deepcopy(manifest)
    forged["samples"][0]["role"] = "frozen-test"
    with pytest.raises(CorpusError, match="still_dataset_invalid:role"):
        sm.parse_still_dataset(forged)


# ---------------------------------------------------------------- authorisation of image and label lineage


def test_an_unauthorised_image_release_refuses_every_sample(tmp_path):
    with pytest.raises(CorpusError, match="still_dataset_empty"):
        build(tmp_path, pa_det=None)


def test_the_label_release_is_authorised_separately_per_role(tmp_path):
    evaluation_only = determination("cc-by-nc-sa-3.0-de", purposes=["benchmarking", "selection", "tuning"])
    manifest, _ = build(tmp_path, up_det=evaluation_only)
    refused = {r["memberPath"]: r for r in manifest["refusedSamples"]}
    kept = by_member(manifest)
    # Training samples with UPAR colour truth are refused; training samples without UPAR truth are kept.
    assert refused[member(1)]["role"] == "training" and any("rights" in b or "purpose-not-covered" in b for b in refused[member(1)]["blockers"])
    assert member(2) in kept and kept[member(2)]["role"] == "training"
    assert all(s["role"] != "training" or s["attributes"]["person-upper-colour"]["truth"] == "missing" for s in kept.values())
    assert any(s["role"] == "benchmark" and s["attributes"]["person-upper-colour"]["truth"] == "present" for s in kept.values())


def test_a_rights_operation_not_granted_blocks_its_role(tmp_path):
    no_train = determination("cc-by-4.0")
    no_train["rights"]["inventory"]["train"] = "not-granted"
    manifest, _ = build(tmp_path, pa_det=no_train)
    assert manifest["counts"]["roles"].get("training", 0) == 0 and manifest["counts"]["roles"]["benchmark"] == 100
    assert all(any("rights-operation-not-granted:train" in b for b in r["blockers"]) for r in manifest["refusedSamples"])


def test_an_excluded_member_is_refused_and_recorded(tmp_path):
    manifest, _ = build(tmp_path, excluded=[member(1301)])
    assert member(1301) not in by_member(manifest)
    assert next(r for r in manifest["refusedSamples"] if r["memberPath"] == member(1301))["blockers"] == [f"{PA}:member-excluded:{member(1301)}"]


# ---------------------------------------------------------------- exact duplicates


@pytest.mark.parametrize("a,b,kept_role", [
    (2, 1350, "benchmark"),      # training vs benchmark
    (2, 1250, "development"),    # training vs development
    (1300, 1350, "benchmark"),   # development vs benchmark
])
def test_exact_duplicates_keep_the_stronger_evaluation_copy(tmp_path, a, b, kept_role):
    manifest, _ = build(tmp_path, images={b: image_for(a)})
    sample = next(s for s in manifest["samples"] if s["memberPath"] in (member(a), member(b)))
    assert sample["role"] == kept_role
    [drop] = manifest["exactDuplicateDrops"]
    assert drop["keptRole"] == kept_role and drop["role"] != kept_role


def test_training_against_selection_keeps_selection(tmp_path):
    manifest, _ = build(tmp_path)
    roles = {s["memberPath"]: s["role"] for s in manifest["samples"]}
    selection = min(m for m, r in roles.items() if r == "selection")
    training = min(m for m, r in roles.items() if r == "training")
    dup, _ = build(tmp_path / "second", images={int(training[-10:-4]): image_for(int(selection[-10:-4]))})
    kept = next(s for s in dup["samples"] if s["memberPath"] in (selection, training))
    assert kept["memberPath"] == selection and kept["role"] == "selection"


def test_same_role_duplicates_keep_the_lowest_member_path(tmp_path):
    manifest, _ = build(tmp_path, images={9: image_for(7)})
    assert member(7) in by_member(manifest) and member(9) not in by_member(manifest)
    assert manifest["exactDuplicateDrops"][0]["memberPath"] == member(9)


def test_development_and_selection_without_a_benchmark_copy_refuse_the_build(tmp_path):
    manifest, _ = build(tmp_path)
    selection = next(s["memberPath"] for s in manifest["samples"] if s["role"] == "selection")
    with pytest.raises(CorpusError, match="duplicate_role_conflict"):
        build(tmp_path / "second", images={1250: image_for(int(selection[-10:-4]))})


# ---------------------------------------------------------------- near duplicates


def test_colour_distinct_identical_dhash_images_are_reported_never_removed(tmp_path):
    manifest, report = build(tmp_path, images={3: jpeg((200, 0, 0)), 1350: jpeg((0, 0, 255))})
    samples = by_member(manifest)
    assert member(3) in samples and member(1350) in samples
    pair = next(p for p in report["pairs"] if {p["a"], p["b"]} == {samples[member(3)]["sampleId"], samples[member(1350)]["sampleId"]})
    assert pair["crossRole"] and pair["distance"] == 0
    assert report["screeningOnly"] and manifest["nearDuplicateReport"]["totals"] == report["totals"]


def test_near_duplicate_report_puts_cross_role_pairs_first_and_caps_deterministically(tmp_path):
    images = {3: jpeg((200, 0, 0)), 5: jpeg((0, 120, 0)), 1350: jpeg((0, 0, 255))}  # one dHash, three images
    policy = {**sm.PERSON_POLICY, "nearDuplicate": {**sm.PERSON_POLICY["nearDuplicate"], "maxPairs": 2}}
    _, report = build(tmp_path, images=images, policy=policy)
    assert report["truncated"] and len(report["pairs"]) == 2 and report["totals"]["pairs"] >= 3
    assert all(p["crossRole"] for p in report["pairs"])


# ---------------------------------------------------------------- determinism and smoke


def test_the_build_is_byte_identical_on_rerun_and_canonically_identified(tmp_path):
    first, report = build(tmp_path)
    second, report2 = build(tmp_path)
    assert canonical_json(first) == canonical_json(second) and canonical_json(report) == canonical_json(report2)
    assert sm.still_dataset_sha256(first) == sm.still_dataset_sha256(second)
    assert first["nearDuplicateReport"]["sha256"] == __import__("hashlib").sha256(canonical_json(report)).hexdigest()


def test_smoke_subset_is_deterministic_per_split_and_keeps_full_release_roles(tmp_path):
    full, _ = build(tmp_path)
    smoke, _ = build(tmp_path, smoke=True)
    again, _ = build(tmp_path, smoke=True)
    assert canonical_json(smoke) == canonical_json(again)
    assert smoke["counts"]["samples"] == 160 and smoke["smoke"] is not None
    full_roles = {s["memberPath"]: s["role"] for s in full["samples"]}
    assert all(full_roles[s["memberPath"]] == s["role"] for s in smoke["samples"])
    assert {s: sum(x["sourceSplit"] == s for x in smoke["samples"]) for s in pa100k.SPLITS} == {"train": 120, "val": 20, "test": 20}


def test_cli_build_person_refuses_unauthorised_releases_and_outputs_inside_git(tmp_path, capsys):
    from attributes.datasets import cli
    pa_root, up_root = tmp_path / "pa", tmp_path / "upar"
    write_pa100k(pa_root)
    write_upar(up_root, [], [])
    paths = {}
    for rid, root, lic in ((PA, pa_root, "cc-by-4.0"), (UP, up_root, "cc-by-nc-sa-3.0-de")):
        paths[rid] = tmp_path / f"{rid}.json"
        paths[rid].write_text(json.dumps(release_record(rid, root, lic, None)), encoding="utf-8")
    argv = ["build-person", "--pa100k-release", str(paths[PA]), "--pa100k-root", str(pa_root), "--upar-release", str(paths[UP]),
            "--upar-root", str(up_root), "--out-dir", str(tmp_path / "out")]
    assert cli.main(argv) == 2 and "still_dataset_empty" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    assert cli.main(argv[:-1] + [str(tmp_path / "repo" / "out")]) == 2 and "Git" in capsys.readouterr().err
