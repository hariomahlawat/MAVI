"""External dataset release records and intended-use authorisation (public-data slice §3).

Parsing a determination proves its shape only. A use is authorised only when the
determination affirmatively covers the purposes, the licence, the rights-inventory
operations those purposes exercise, the privacy basis and any required R-5 ruling, and the
member is not excluded. Release files are operator-placed and verified by size and SHA-256.
"""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from attributes.corpus.canonical import CorpusError
from attributes.datasets import release as rel
from source_acquisition import admission

BODY = {"README.txt": b"readme bytes\r\n", "annotation.zip": b"PK annotation", "data/data.zip": b"PK" + b"\x00" * 64}
INVENTORY_ALL = {op: "granted" for op in rel.INVENTORY_OPERATIONS}


def files() -> list[dict]:
    return [{"path": path, "sizeBytes": len(data), "sha256": hashlib.sha256(data).hexdigest()} for path, data in sorted(BODY.items())]


def determination(**over) -> dict:
    record = {
        "determinationId": "pa-100k-release", "reviewedOn": "2026-10-03",
        "purposes": ["benchmarking", "development", "regression-challenge", "selection", "training", "tuning"],
        "licenceCodes": ["cc-by-4.0"],
        "rights": {"reviewedBy": "R-5", "determination": "PERMITTED_FOR_ENGINEERING_USE", "evidence": "release-level review", "inventory": dict(INVENTORY_ALL)},
        "privacy": {"reviewedBy": "Hari Om Ahlawat", "disposition": "PERMITTED", "basis": "internal processing of surveillance crops; no identity processing"},
        "r5Ruling": None,
    }
    record.update(over)
    return record


def release(det=..., **over) -> dict:
    record = {
        "schemaVersion": rel.RELEASE_SCHEMA, "releaseId": "pa-100k-2017", "name": "PA-100K", "version": "2017-09-07 release",
        "origin": "public", "officialUrl": "https://github.com/xh-liu/HydraPlus-Net",
        "pinnedSource": {"kind": "google-drive-folder", "reference": "0B5_Ra3JsEOyOUlhKM0VPZ1ZWR2M", "retrievedOn": "2026-10-02"},
        "licence": {"codes": ["cc-by-4.0"], "url": "https://creativecommons.org/licenses/by/4.0/", "textSha256": "a" * 64},
        "files": files(), "excludedMembers": [],
        "determination": determination() if det is ... else det,
        "knownExposure": [{"subject": "PO-7", "evidence": "reported trained on PA-100K"}],
    }
    record.update(over)
    return rel.parse_release(record)


def with_rights(**over) -> dict:
    d = determination()
    d["rights"] = {**d["rights"], **over}
    return d


def with_inventory(**statuses) -> dict:
    d = determination()
    d["rights"]["inventory"] = {**INVENTORY_ALL, **{k.replace("_", "-"): v for k, v in statuses.items()}}
    return d


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "store"
    for path, data in BODY.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(data)
    return root


# ---------------------------------------------------------------- authorisation


def test_a_valid_release_determination_authorises_every_member_for_its_purposes():
    r = release()
    for member in ("release_data/000001.jpg", "release_data/099999.jpg", None):
        assert rel.authorise_release_use(r, ["benchmarking", "selection"], (), member) == []
    assert rel.authorise_release_use(r, ["training", "tuning"], (), "release_data/000001.jpg") == []


@pytest.mark.parametrize("rights,blocker", [
    ({"reviewedBy": None}, "rights-determination-missing"),
    ({"evidence": None}, "rights-determination-missing"),
    ({"determination": "NOT_PERMITTED"}, "rights-determination-missing"),
    ({"determination": None}, "rights-determination-missing"),
])
def test_empty_or_denied_rights_block(rights, blocker):
    assert blocker in rel.authorise_release_use(release(det=with_rights(**rights)), ["benchmarking"])


def test_entirely_empty_reviews_parse_but_never_authorise():
    empty = determination(rights={"inventory": dict(INVENTORY_ALL)}, privacy={"disposition": "PERMITTED"})
    r = release(det=empty)  # structure is valid
    blockers = rel.authorise_release_use(r, ["benchmarking"])
    assert "rights-determination-missing" in blockers and "privacy-determination-missing" in blockers


@pytest.mark.parametrize("privacy", [{"disposition": "PERMITTED"}, {"disposition": "PERMITTED", "reviewedBy": "x"},
                                     {"disposition": "PERMITTED", "basis": "y"}, {"disposition": "PERMITTED", "reviewedBy": None, "basis": "y"}])
def test_an_incomplete_permitted_privacy_review_blocks(privacy):
    assert "privacy-determination-missing" in rel.authorise_release_use(release(det=determination(privacy=privacy)), ["benchmarking"])


def test_a_privacy_permitted_review_authorises():
    privacy = {"reviewedBy": "Hari Om Ahlawat", "disposition": "PERMITTED", "basis": "internal processing; no identity processing"}
    assert rel.authorise_release_use(release(det=determination(privacy=privacy)), ["benchmarking"]) == []


def test_a_reviewed_but_denied_privacy_review_blocks_even_with_reviewer_and_basis():
    denied = {"reviewedBy": "Hari Om Ahlawat", "disposition": "DENIED", "basis": "identifiable faces at close range"}
    blockers = rel.authorise_release_use(release(det=determination(privacy=denied)), ["benchmarking"])
    assert "privacy-denied" in blockers and "privacy-determination-missing" not in blockers
    assert "privacy-denied" in admission.determination_blockers(determination(privacy=denied), ["cc-by-4.0"], ["benchmarking"], False)


@pytest.mark.parametrize("disposition", [None, "", "permitted", "APPROVED"])
def test_a_missing_or_unknown_privacy_disposition_is_refused_structurally(disposition):
    privacy = {"reviewedBy": "Hari Om Ahlawat", "basis": "b"}
    if disposition is not None:
        privacy["disposition"] = disposition
    with pytest.raises(CorpusError, match="privacy_disposition"):
        release(det=determination(privacy=privacy))
    # A hand-built determination that bypasses the parser is still not authorised.
    assert "privacy-determination-missing" in admission.determination_blockers(determination(privacy=privacy), ["cc-by-4.0"], ["benchmarking"], False)


def test_purpose_not_covered_blocks():
    narrow = determination(purposes=["benchmarking"])
    assert rel.authorise_release_use(release(det=narrow), ["benchmarking"]) == []
    assert "purpose-not-covered-by-determination" in rel.authorise_release_use(release(det=narrow), ["benchmarking", "selection"])


def test_licence_not_covered_blocks():
    other = determination(licenceCodes=["cc-by-sa-4.0"])
    assert "licence-not-covered-by-determination" in rel.authorise_release_use(release(det=other), ["benchmarking"])


@pytest.mark.parametrize("codes", [["cc-by-nc-sa-3.0-de"], ["cc-by-sa-4.0"], ["veri-776-terms"]])
def test_restricted_share_alike_or_bespoke_terms_need_r5(codes):
    det = determination(licenceCodes=codes)
    r = release(det=det, licence={"codes": codes, "url": None, "textSha256": "b" * 64})
    assert "r5-ruling-missing" in rel.authorise_release_use(r, ["benchmarking"])
    ruled = determination(licenceCodes=codes, r5Ruling={"ruledBy": "R-5", "ruling": "PERMITTED", "reference": "R-5 ruling #2"})
    r = release(det=ruled, licence={"codes": codes, "url": None, "textSha256": "b" * 64})
    assert rel.authorise_release_use(r, ["benchmarking"]) == []
    not_permitted = determination(licenceCodes=codes, r5Ruling={"ruledBy": "R-5", "ruling": "NOT_PERMITTED", "reference": "R-5 ruling #3"})
    r = release(det=not_permitted, licence={"codes": codes, "url": None, "textSha256": "b" * 64})
    assert "r5-ruling-missing" in rel.authorise_release_use(r, ["benchmarking"])


def test_an_open_licence_needs_no_r5():
    assert rel.authorise_release_use(release(), ["benchmarking"]) == []


def test_an_excluded_member_is_refused_and_others_are_not():
    r = release(excludedMembers=[{"path": "release_data/000042.jpg", "reason": "privacy: identifiable face at close range"}])
    assert "member-excluded:release_data/000042.jpg" in rel.authorise_release_use(r, ["benchmarking"], (), "release_data/000042.jpg")
    assert rel.authorise_release_use(r, ["benchmarking"], (), "release_data/000043.jpg") == []


def test_no_determination_means_no_use():
    assert rel.authorise_release_use(release(det=None), ["benchmarking"]) == ["determination-missing"]


# ---------------------------------------------------------------- rights operations


def test_purpose_allowed_but_a_required_operation_denied_blocks():
    blockers = rel.authorise_release_use(release(det=with_inventory(train="not-granted")), ["training"])
    assert "rights-operation-not-granted:train" in blockers


@pytest.mark.parametrize("status", ["not-stated", "pending-r5"])
def test_purpose_allowed_but_a_required_operation_not_stated_is_pending_r5(status):
    blockers = rel.authorise_release_use(release(det=with_inventory(create_derivatives=status)), ["tuning"])
    assert "rights-operation-pending-r5:create-derivatives" in blockers


def test_evaluation_needs_only_evaluate():
    only_evaluate = with_inventory(train="not-granted", create_derivatives="not-stated", run_operationally="not-granted", redistribute_derived_weights="not-granted")
    r = release(det=only_evaluate)
    for purpose in ("benchmarking", "selection", "regression-challenge", "development"):
        assert rel.authorise_release_use(r, [purpose]) == []
    assert "rights-operation-not-granted:evaluate" in rel.authorise_release_use(release(det=with_inventory(evaluate="not-granted")), ["benchmarking"])


def test_training_needs_train_and_create_derivatives():
    assert rel.authorise_release_use(release(det=with_inventory(evaluate="not-granted")), ["training"]) == []
    assert "rights-operation-not-granted:train" in rel.authorise_release_use(release(det=with_inventory(train="not-granted")), ["training"])
    assert "rights-operation-pending-r5:create-derivatives" in rel.authorise_release_use(release(det=with_inventory(create_derivatives="pending-r5")), ["training"])


def test_tuning_needs_evaluate_and_create_derivatives():
    assert "rights-operation-not-granted:create-derivatives" in rel.authorise_release_use(release(det=with_inventory(create_derivatives="not-granted")), ["tuning"])
    assert "rights-operation-not-granted:evaluate" in rel.authorise_release_use(release(det=with_inventory(evaluate="not-granted")), ["tuning"])


def test_a_purpose_never_implies_an_operation_and_extra_operations_are_checked():
    # The broad purpose token is covered, but the extra operation the caller exercises is not granted.
    r = release(det=with_inventory(train="not-granted"))
    assert rel.authorise_release_use(r, ["benchmarking"]) == []
    assert "rights-operation-not-granted:train" in rel.authorise_release_use(r, ["benchmarking"], ["train"])


def test_route_operations_are_not_dataset_use_operations_and_unknown_inputs_are_refused():
    r = release()
    for op in ("run-operationally", "redistribute-derived-weights", "fly"):
        with pytest.raises(CorpusError, match="dataset_operation"):
            rel.authorise_release_use(r, ["benchmarking"], [op])
    with pytest.raises(CorpusError, match="dataset_purpose_has_no_operations"):
        rel.authorise_release_use(r, ["reference"])
    with pytest.raises(CorpusError, match="frozen_qualification_requires_protected_origin"):
        rel.authorise_release_use(r, ["frozen-qualification"])


def test_the_purpose_operation_mapping_is_the_planned_one():
    assert rel.PURPOSE_OPERATIONS == {
        "benchmarking": ("evaluate",), "selection": ("evaluate",), "regression-challenge": ("evaluate",), "development": ("evaluate",),
        "tuning": ("create-derivatives", "evaluate"), "training": ("create-derivatives", "train"),
    }


# ---------------------------------------------------------------- structure


@pytest.mark.parametrize("edit,code", [
    (lambda d: d.update(schemaVersion="mavi-attribute-dataset-release-v0"), "schema"),
    (lambda d: d.update(origin="owner-captured"), "origin"),
    (lambda d: d.update(officialUrl="http://example.org"), "official_url"),
    (lambda d: d["files"].reverse(), "files"),
    (lambda d: d["files"][0].update(path="../escape.zip"), "path"),
    (lambda d: d["files"][0].update(path="C:/Users/ops/data.zip"), "path"),
    (lambda d: d["files"][0].update(sizeBytes=-1), "size"),
    (lambda d: d["files"][0].update(sha256="xyz"), "sha256"),
    (lambda d: d.update(excludedMembers=[{"path": "b.jpg", "reason": "r"}, {"path": "a.jpg", "reason": "r"}]), "excluded"),
    (lambda d: d["licence"].update(codes=["CC-BY-4.0"]), "licence"),
    (lambda d: d["determination"]["rights"].pop("inventory"), "inventory"),
    (lambda d: d["determination"]["rights"]["inventory"].update(evaluate="yes"), "inventory"),
    (lambda d: d["determination"]["rights"]["inventory"].pop("train"), "inventory"),
    (lambda d: d["determination"].update(reviewedOn="soon"), "date"),
    (lambda d: d["determination"].update(purposes=["frozen-qualification"]), "frozen_qualification_requires_protected_origin"),
    (lambda d: d["knownExposure"].append({"subject": "x"}), "exposure"),
    (lambda d: d.update(extra=1), "unexpected"),
])
def test_a_malformed_release_record_is_refused(edit, code):
    record = copy.deepcopy(release())
    edit(record)
    with pytest.raises(CorpusError, match=code):
        rel.parse_release(record)


def test_release_identity_is_canonical_and_content_bound():
    a, b = release(), release()
    assert rel.release_sha256(a) == rel.release_sha256(b)
    assert rel.release_sha256(release(version="2017-09-07 release (repacked)")) != rel.release_sha256(a)


# ---------------------------------------------------------------- operator-placed files


def test_operator_placed_files_verify_by_size_and_hash(store):
    assert rel.verify_release_files(release(), store) == []


def test_wrong_hash_wrong_size_and_missing_files_are_refused(store):
    (store / "annotation.zip").write_bytes(b"PK annotatioN")  # same size, different bytes
    (store / "README.txt").write_bytes(b"short")
    (store / "data" / "data.zip").unlink()
    problems = rel.verify_release_files(release(), store)
    assert "annotation.zip: sha256 differs" in problems
    assert "README.txt: size differs" in problems
    assert "data/data.zip: missing" in problems


def test_a_store_inside_git_is_refused(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "store").mkdir()
    with pytest.raises(rel.ReleaseError, match="Git"):
        rel.verify_release_files(release(), tmp_path / "store")


def test_cli_verify_release_reports_files_and_blockers(store, tmp_path, capsys):
    from attributes.datasets import cli
    path = tmp_path / "release.json"
    record = release(det=with_inventory(train="not-granted"))
    path.write_text(json.dumps(record), encoding="utf-8")

    def run(*purposes):
        argv = ["verify-release", "--release", str(path), "--root", str(store)]
        for purpose in purposes:
            argv += ["--purpose", purpose]
        code = cli.main(argv)
        return code, json.loads(capsys.readouterr().out)

    code, report = run("benchmarking")
    assert code == 0 and report == {"releaseSha256": rel.release_sha256(record), "fileProblems": [], "blockers": []}
    code, report = run("training")
    assert code == 1 and report["fileProblems"] == [] and "rights-operation-not-granted:train" in report["blockers"]
    (store / "README.txt").write_bytes(b"tampered bytes")
    code, report = run("benchmarking")
    assert code == 1 and report["fileProblems"] and report["blockers"] == []


# ---------------------------------------------------------------- shared seam and Commons


def test_commons_and_datasets_share_one_determination_check():
    d = determination(rights={"inventory": dict(INVENTORY_ALL)})
    assert admission.determination_blockers(d, ["cc-by-4.0"], ["benchmarking"], False) == ["rights-determination-missing"]
    assert "rights-determination-missing" in rel.authorise_release_use(release(det=d), ["benchmarking"])
    assert admission.determination_blockers(determination(), [None], ["benchmarking"], False) == ["file-licence-missing"]


def test_qualification_tooling_reads_matlab_5_files():
    """The PA-100K annotation file is a MATLAB 5.0 MAT-file; the tooling environment must read it
    (tools/requirements.txt pins scipy, the same pin as the vision-runtime extra)."""
    import io

    import numpy as np
    from scipy.io import loadmat, savemat

    buffer = io.BytesIO()
    savemat(buffer, {"train_label": np.array([[0, 1], [1, 0]], dtype=np.uint8)}, format="5")
    assert buffer.getvalue()[:19] == b"MATLAB 5.0 MAT-file"
    assert loadmat(io.BytesIO(buffer.getvalue()))["train_label"].tolist() == [[0, 1], [1, 0]]


# ---------------------------------------------------------------- non-string approval fields (Codex P1 on #141)

NON_TEXT = [True, 1, 0.5, ["R-5"], {"name": "R-5"}, "", "   "]
TEXT_FIELDS = [("rights", "reviewedBy"), ("rights", "evidence"), ("rights", "determination"),
               ("privacy", "reviewedBy"), ("privacy", "basis")]


@pytest.mark.parametrize("section,field", TEXT_FIELDS)
@pytest.mark.parametrize("value", NON_TEXT)
def test_a_non_text_review_field_is_refused_and_never_authorises(section, field, value):
    det = determination()
    det[section] = {**det[section], field: value}
    with pytest.raises(CorpusError, match="review_text"):
        release(det=det)
    # Bypassing the parser does not help: the authorisation check requires real text too.
    assert admission.determination_blockers(det, ["cc-by-4.0"], ["benchmarking"], False)


@pytest.mark.parametrize("field", ["ruledBy", "ruling", "reference"])
@pytest.mark.parametrize("value", NON_TEXT)
def test_a_non_text_r5_field_is_refused_and_never_permits(field, value):
    ruling = {"ruledBy": "R-5", "ruling": "PERMITTED", "reference": "R-5 ruling #2", field: value}
    det = determination(licenceCodes=["cc-by-sa-4.0"], r5Ruling=ruling)
    with pytest.raises(CorpusError, match="review_text"):
        release(det=det, licence={"codes": ["cc-by-sa-4.0"], "url": None, "textSha256": "b" * 64})
    assert not admission.r5_permits(det)


def test_null_review_fields_parse_and_block():
    det = determination(rights={"reviewedBy": None, "determination": None, "evidence": None, "inventory": dict(INVENTORY_ALL)})
    assert "rights-determination-missing" in rel.authorise_release_use(release(det=det), ["benchmarking"])


# ---------------------------------------------------------------- unhashable list elements (Codex P2 on #141)

UNHASHABLE = [{"code": "cc-by-4.0"}, ["cc-by-4.0"], 1, None]


@pytest.mark.parametrize("bad", UNHASHABLE)
def test_non_string_licence_codes_are_refused_not_crashed(bad):
    with pytest.raises(CorpusError, match="licence_codes"):
        release(licence={"codes": [bad], "url": None, "textSha256": "b" * 64})
    with pytest.raises(CorpusError, match="licence_codes"):
        release(det=determination(licenceCodes=[bad]))


@pytest.mark.parametrize("bad", UNHASHABLE)
def test_non_string_purposes_are_refused_not_crashed(bad):
    with pytest.raises(CorpusError, match="purposes"):
        release(det=determination(purposes=[bad]))
    with pytest.raises(CorpusError, match="purposes"):
        rel.authorise_release_use(release(), [bad])


def test_cli_refuses_an_unhashable_licence_code_with_exit_2(store, tmp_path, capsys):
    from attributes.datasets import cli
    record = copy.deepcopy(release())
    record["licence"]["codes"] = [{"code": "cc-by-4.0"}]
    path = tmp_path / "release.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    assert cli.main(["verify-release", "--release", str(path), "--root", str(store), "--purpose", "benchmarking"]) == 2
    assert "REFUSED" in capsys.readouterr().err


# ---------------------------------------------------------------- exclusions and exposure identity (Codex P2s on #141)


def test_whole_release_use_is_blocked_while_members_are_excluded():
    excluded = [{"path": "release_data/000042.jpg", "reason": "privacy: identifiable face at close range"}]
    r = release(excludedMembers=excluded)
    assert "release-has-excluded-members:1" in rel.authorise_release_use(r, ["benchmarking"])
    assert rel.authorise_release_use(r, ["benchmarking"], (), "release_data/000043.jpg") == []  # per member is fine
    assert rel.authorise_release_use(release(), ["benchmarking"]) == []  # no exclusions: whole release is fine


def test_cli_cannot_report_a_release_with_exclusions_as_wholly_authorised(store, tmp_path, capsys):
    from attributes.datasets import cli
    record = release(excludedMembers=[{"path": "release_data/000042.jpg", "reason": "privacy review"}])
    path = tmp_path / "release.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    assert cli.main(["verify-release", "--release", str(path), "--root", str(store), "--purpose", "benchmarking"]) == 1
    assert "release-has-excluded-members:1" in json.loads(capsys.readouterr().out)["blockers"]


@pytest.mark.parametrize("exposure", [
    [{"subject": "b", "evidence": "x"}, {"subject": "a", "evidence": "x"}],
    [{"subject": "a", "evidence": "y"}, {"subject": "a", "evidence": "x"}],
    [{"subject": "a", "evidence": "x"}, {"subject": "a", "evidence": "x"}],
])
def test_known_exposure_must_be_sorted_and_duplicate_free(exposure):
    with pytest.raises(CorpusError, match="exposure_not_sorted_unique"):
        release(knownExposure=exposure)


def test_reordering_known_exposure_cannot_create_a_second_identity():
    entries = [{"subject": "PO-7", "evidence": "reported trained on PA-100K"}, {"subject": "pretraining", "evidence": "widely used"}]
    assert rel.release_sha256(release(knownExposure=entries))
    with pytest.raises(CorpusError):
        release(knownExposure=list(reversed(entries)))
