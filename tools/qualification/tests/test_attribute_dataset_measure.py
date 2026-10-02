"""mavi-dev-colour-probe-v1 and mavi-attribute-component-result-v1 (plan §7–§8).

Probe fixtures are PNGs, so pixel colours are exact. Measurement fixtures reuse the
real-format synthetic releases with controlled colour images, so confusion matrices are
hand-computable.
"""

from __future__ import annotations

import copy
import io
import json

import numpy as np
import pytest
from attribute_dataset_fixtures import colour_values, determination
from test_attribute_dataset_still import PA, UP, build, member, small_release  # noqa: F401  (autouse fixture)

from attributes.corpus.canonical import CorpusError, canonical_json
from attributes.datasets import colour_probe as cp
from attributes.datasets import measure as ms
from attributes.datasets import still_manifest as sm
from attributes.datasets.adapters import pa100k

CODE = {"repository": {"commit": "a" * 40, "localChanges": False}, "moduleSha256": {"measure.py": "b" * 64}, "dataSha256": {"task:x.json": "c" * 64}}


def png(rows: list[tuple[int, tuple[int, int, int]]], width: int = 100, height: int = 200, marker: int = 0) -> bytes:
    """Horizontal bands ``[(until_row, rgb), ...]``; ``marker`` makes otherwise-equal images byte-distinct
    by changing pixel (0, 0), which lies outside every probe region."""
    from PIL import Image

    image = Image.new("RGB", (width, height))
    start = 0
    for until, rgb in rows:
        for y in range(start, until):
            for x in range(width):
                image.putpixel((x, y), rgb)
        start = until
    image.putpixel((0, 0), (marker % 256, marker // 256 % 256, 7))
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def stripes(colours: list[tuple[int, int, int]], width: int = 100, height: int = 200) -> bytes:
    from PIL import Image

    image = Image.new("RGB", (width, height))
    region = (20, 80)  # the configured central 60% of a 100-pixel width
    step = (region[1] - region[0]) // len(colours)
    for x in range(width):
        i = min(max(x - region[0], 0) // step, len(colours) - 1)
        for y in range(height):
            image.putpixel((x, y), colours[i])
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


RED, BLUE, WHITE, GREY = (180, 30, 40), (40, 70, 160), (235, 235, 235), (128, 128, 128)


@pytest.fixture(scope="module")
def probe():
    return cp.ColourProbe(cp.load_probe_config())


# ---------------------------------------------------------------- configuration


def test_the_committed_configuration_parses_and_has_a_stable_identity():
    config = cp.load_probe_config()
    assert config["methodId"] == "mavi-dev-colour-probe-v1" and "not PC-B0 or VC-B0" in config["status"]
    assert cp.probe_sha256(config) == cp.probe_sha256(json.loads(cp.CONFIG_PATH.read_text(encoding="utf-8")))


@pytest.mark.parametrize("edit,code", [
    (lambda c: c["centres"]["person"].pop("pink"), "centre_missing:person:pink"),
    (lambda c: c["centres"]["person"].update(magenta=[50, 50, 0]), "centre_unknown:person:magenta"),
    (lambda c: c["centres"]["person"]["red"].pop(), "centre_shape"),
    (lambda c: c["centres"]["person"]["red"].__setitem__(0, "39.2"), "centre_value"),
    (lambda c: c["centres"]["vehicle"].pop("silver"), "centre_missing:vehicle:silver"),
    (lambda c: c["regions"]["person-upper-colour"].update(rows=[0.5, 0.15]), "region_rows"),
    (lambda c: c["regions"]["person-lower-colour"].update(columns=[0.2, 1.2]), "region_columns"),
    (lambda c: c["regions"].pop("vehicle-colour"), "regions"),
    (lambda c: c["regions"]["person-upper-colour"].update(objectClass="vehicle"), "region_class"),
    (lambda c: c["srgbLinearisation"].pop("threshold"), "linearisation"),
    (lambda c: c["srgbToXyz"].pop(), "matrix"),
    (lambda c: c["whitePointD65"].append(1.0), "white"),
    (lambda c: c["cieLab"].pop("kappa"), "lab"),
    (lambda c: c.update(minWinningShare=1.5), "min_share"),
    (lambda c: c.update(minRegionPixels=0), "min_pixels"),
    (lambda c: c.update(distance="ciede2000"), "distance"),
    (lambda c: c.update(abstentionReasons=["ambiguous"]), "abstentions"),
    (lambda c: c["decoding"].update(resize="64x128"), "decoding"),
    (lambda c: c.update(extra=1), "unexpected"),
])
def test_a_malformed_configuration_is_refused(edit, code):
    config = copy.deepcopy(cp.load_probe_config())
    edit(config)
    with pytest.raises(CorpusError, match=code):
        cp.parse_probe_config(config)


def test_changing_one_centre_or_threshold_changes_the_method_identity():
    base = cp.load_probe_config()
    moved = copy.deepcopy(base)
    moved["centres"]["person"]["red"][0] += 0.0001
    stricter = copy.deepcopy(base)
    stricter["minWinningShare"] = 0.41
    assert len({cp.probe_sha256(base), cp.probe_sha256(moved), cp.probe_sha256(stricter)}) == 3


# ---------------------------------------------------------------- probe behaviour


def test_lab_conversion_matches_a_hand_computed_value(probe):
    # sRGB (128,128,128): linear 0.2158605, Y = 0.2158605, f = 0.6000149 -> L* = 53.5850, a* = b* = 0.
    assert np.allclose(probe.to_lab(np.array([128, 128, 128])), [53.5850, 0.0, 0.0], atol=1e-3)
    # sRGB (180,30,40): the configured red swatch reproduces its own centre.
    assert np.allclose(probe.to_lab(np.array(RED)), cp.load_probe_config()["centres"]["person"]["red"], atol=1e-3)


def test_lab_uses_the_linear_segment_for_very_dark_colours(probe):
    # sRGB (5,5,5): linear 0.0015176 <= epsilon, so f = (kappa * Y + 16) / 116 and L* = 1.3708.
    assert np.allclose(probe.to_lab(np.array([5, 5, 5])), [1.3708, 0.0, 0.0], atol=1e-3)


def test_region_bounds_are_floored(probe):
    # Height 203: rows floor(30.45)=30 .. floor(101.5)=101. Row 30 is red, every other region row blue.
    result = probe.predict("person-upper-colour", png([(31, RED), (203, BLUE)], height=203))
    assert result["value"] == "blue" and result["share"] == {"numerator": 70 * 60, "denominator": 71 * 60}


@pytest.mark.parametrize("rgb,expected", [(RED, "red"), (BLUE, "blue"), (WHITE, "white"), (GREY, "grey"), ((30, 30, 30), "black")])
def test_a_solid_crop_takes_its_nearest_centre(probe, rgb, expected):
    result = probe.predict("person-upper-colour", png([(200, rgb)]))
    assert result["outcome"] == "value" and result["value"] == expected
    assert result["share"]["numerator"] == result["share"]["denominator"] == 70 * 60  # rows 30..100, columns 20..80


def test_upper_and_lower_regions_use_their_own_geometry(probe):
    image = png([(100, RED), (200, BLUE)])  # the band edge (row 100) lies between the regions
    assert probe.predict("person-upper-colour", image)["value"] == "red"
    assert probe.predict("person-lower-colour", image)["value"] == "blue"
    # One row too far: a band ending at row 99 puts blue into the upper region (rows 30..99).
    shifted = probe.predict("person-upper-colour", png([(99, RED), (200, BLUE)]))
    assert shifted["value"] == "red" and shifted["share"]["numerator"] == 69 * 60


def test_insufficient_area_abstains(probe):
    assert probe.predict("person-upper-colour", png([(40, RED)], width=20, height=40)) == {"outcome": "abstain", "reason": "insufficient-area"}


def test_an_undecodable_crop_abstains(probe):
    assert probe.predict("person-upper-colour", b"not an image") == {"outcome": "abstain", "reason": "undecodable"}
    assert probe.predict("person-upper-colour", png([(200, RED)])[:60]) == {"outcome": "abstain", "reason": "undecodable"}


def test_a_low_winning_share_is_ambiguous(probe):
    assert probe.predict("person-upper-colour", stripes([RED, BLUE, WHITE])) == {"outcome": "abstain", "reason": "ambiguous"}  # 1/3 < 0.40


def test_a_winner_tie_goes_to_the_first_name_in_schema_order(probe):
    result = probe.predict("person-upper-colour", stripes([RED, BLUE]))  # 50/50
    assert result["value"] == "blue"  # blue precedes red in task order
    assert probe.predict("person-upper-colour", stripes([BLUE, RED]))["value"] == "blue"


def test_a_pixel_tie_goes_to_the_first_centre_in_schema_order():
    config = copy.deepcopy(cp.load_probe_config())
    config["centres"]["person"]["blue"] = list(config["centres"]["person"]["black"])  # black and blue now coincide
    tied = cp.ColourProbe(cp.parse_probe_config(config))
    assert tied.predict("person-upper-colour", png([(200, (30, 30, 30))]))["value"] == "black"  # black precedes blue
    config["centres"]["person"]["black"] = [999.0, 0.0, 0.0]  # move black away: blue now wins alone
    assert cp.ColourProbe(cp.parse_probe_config(config)).predict("person-upper-colour", png([(200, (30, 30, 30))]))["value"] == "blue"


def test_the_vehicle_region_is_declared_but_not_implemented(probe):
    with pytest.raises(CorpusError, match="region_not_implemented"):
        probe.predict("vehicle-colour", png([(200, RED)]))


# ---------------------------------------------------------------- measurement


def benchmark_case(tmp_path, **over):
    """Official test images 1301..1316 have UPAR truth: upper red, lower grey; 1317 has two upper
    colours. Images: 1301..1310 solid red, 1311..1315 solid blue, 1316 too small. Every other test
    image has no UPAR truth."""
    images = {n: png([(200, RED)], marker=n) for n in range(1301, 1311)}
    images.update({n: png([(200, BLUE)], marker=n) for n in range(1311, 1316)})
    images[1316] = png([(40, RED)], width=20, height=40, marker=1316)
    upar_val = [(f"PA100k/{member(n)}", colour_values("Red", "Grey")) for n in range(1301, 1317)]
    upar_val.append((f"PA100k/{member(1317)}", colour_values(("Red", "Blue"), "Grey")))
    manifest, _ = build(tmp_path, images=images, upar_train=[], upar_val=upar_val, **over)
    return manifest


def releases_of(tmp_path, pa_det=..., up_det=...):
    from attribute_dataset_fixtures import release_record
    from attributes.datasets.adapters import upar
    return (release_record(PA, tmp_path / "pa", "cc-by-4.0", pa_det),
            release_record(UP, tmp_path / "upar", "cc-by-nc-sa-3.0-de", up_det, pinned=upar.PINNED_REVISION))


def measure(tmp_path, manifest, roles=("benchmark",), config=None, code=CODE, **dets):
    pa, up = releases_of(tmp_path, **dets)
    return ms.measure_person(manifest, pa, tmp_path / "pa", up, list(roles), config or cp.load_probe_config(), code=code)


def test_colour_confusion_and_denominators_match_a_hand_computation(tmp_path):
    result = measure(tmp_path, benchmark_case(tmp_path))
    upper = result["attributes"]["person-upper-colour"]["byRole"]["benchmark"]
    assert upper["rows"] == 100 and upper["truth"] == {"missing": 83, "unmapped": 0, "unscorable": 1, "value": 16}
    assert upper["eligible"] == 16 and upper["abstentions"] == {"ambiguous": 0, "insufficient-area": 1, "undecodable": 0}
    assert upper["predicted"] == 15 and upper["coverage"] == {"numerator": 15, "denominator": 16}
    assert upper["confusion"]["red"]["red"] == 10 and upper["confusion"]["red"]["blue"] == 5
    assert sum(sum(r.values()) for r in upper["confusion"].values()) == 15
    assert upper["perValue"]["red"] == {"support": 16, "predictedAs": 10, "correct": 10,
                                        "recallOverSupport": {"numerator": 10, "denominator": 16},  # the abstention counts against recall
                                        "precisionOverPredicted": {"numerator": 10, "denominator": 10}}
    assert upper["perValue"]["blue"]["precisionOverPredicted"] == {"numerator": 0, "denominator": 5}
    assert upper["perValue"]["blue"]["recallOverSupport"] is None  # no blue truth: undefined, not zero
    assert upper["aggregate"] == {"correctOverEligible": {"numerator": 10, "denominator": 16}, "correctOverPredicted": {"numerator": 10, "denominator": 15},
                                  "macroRecallOverSupportedValues": {"numerator": 5, "denominator": 8}, "supportedValues": 1}
    assert upper["unsupportedValues"] == ["multicolour"]
    lower = result["attributes"]["person-lower-colour"]["byRole"]["benchmark"]
    assert lower["truth"]["value"] == 17 and lower["confusion"]["grey"]["grey"] == 0  # solid red/blue never read as grey
    assert result["attributes"]["person-upper-colour"]["semantics"] == "source-native"


def test_presence_attributes_never_get_prediction_metrics(tmp_path):
    result = measure(tmp_path, benchmark_case(tmp_path))
    for attribute in ms.PRESENCE_ATTRIBUTES:
        metrics = result["attributes"][attribute]["byRole"]["benchmark"]
        assert metrics["predictions"] is None and "confusion" not in metrics and "perValue" not in metrics and "aggregate" not in metrics
        positive = metrics["truth"]["source-binary:positive"]
        assert metrics["prevalence"] == {"numerator": positive, "denominator": metrics["support"]} and metrics["support"] == 100
    assert result["attributes"]["person-bag"]["semantics"] == "proxy" and result["attributes"]["person-bag"]["method"] == "dataset-prevalence-diagnostic-v1"
    forged = copy.deepcopy(result)
    forged["attributes"]["person-bag"]["byRole"]["benchmark"]["confusion"] = {}
    with pytest.raises(CorpusError, match="presence_prediction_metrics"):
        ms.parse_component_result(forged)


def test_a_rerun_is_byte_identical_and_every_identity_is_bound(tmp_path):
    manifest = benchmark_case(tmp_path)
    first, second = measure(tmp_path, manifest), measure(tmp_path, manifest)
    assert canonical_json(first) == canonical_json(second)
    assert first["evidence"]["stillDatasetSha256"] == sm.still_dataset_sha256(manifest)
    assert first["evidence"]["methodConfigSha256"] == cp.probe_sha256(cp.load_probe_config())
    moved = copy.deepcopy(cp.load_probe_config())
    moved["centres"]["person"]["red"][0] += 0.0001
    assert measure(tmp_path, manifest, config=moved)["evidence"]["methodConfigSha256"] != first["evidence"]["methodConfigSha256"]
    other_code = {**CODE, "repository": {"commit": "c" * 40, "localChanges": True}}
    assert ms.result_sha256(measure(tmp_path, manifest, code=other_code)) != ms.result_sha256(first)
    smoke_manifest, _ = build(tmp_path, smoke=True)
    smoke = measure(tmp_path, smoke_manifest)
    assert smoke["evidence"]["smoke"] and smoke["evidence"]["stillDatasetSha256"] != first["evidence"]["stillDatasetSha256"]


@pytest.mark.parametrize("edit,code", [
    (lambda r: r["evidence"].pop("stillDatasetSha256"), "manifest_sha256"),
    (lambda r: r["evidence"].update(stillDatasetSha256="0" * 63), "manifest_sha256"),
    (lambda r: r["evidence"].pop("methodConfigSha256"), "method_sha256"),
    (lambda r: r["evidence"].pop("code"), "code_identity"),
    (lambda r: r["evidence"]["code"]["repository"].update(commit=None), "code_identity:commit"),
    (lambda r: r["evidence"]["code"]["repository"].update(localChanges=None), "local_changes"),
    (lambda r: r["evidence"]["code"].update(moduleSha256={}), "code_identity:moduleSha256"),
    (lambda r: r["evidence"]["code"].pop("dataSha256"), "code_identity:dataSha256"),
    (lambda r: r.update(claim="MAVI operational accuracy"), "claim"),
    (lambda r: r.update(rolesMeasured=["frozen-test"]), "roles"),
])
def test_a_result_without_its_evidence_binding_is_refused(tmp_path, edit, code):
    result = copy.deepcopy(measure(tmp_path, benchmark_case(tmp_path)))
    edit(result)
    with pytest.raises(CorpusError, match=code):
        ms.parse_component_result(result)


def test_measurement_refuses_without_code_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(ms, "code_identity", lambda: {"repository": {"commit": None, "localChanges": None}, "moduleSha256": {"m.py": "b" * 64}, "dataSha256": {"d": "c" * 64}})
    with pytest.raises(CorpusError, match="code_identity:commit"):
        measure(tmp_path, benchmark_case(tmp_path), code=None)


def test_a_release_that_is_not_the_bound_one_is_refused(tmp_path):
    manifest = benchmark_case(tmp_path)
    with pytest.raises(CorpusError, match="release_not_bound"):
        measure(tmp_path, manifest, pa_det=determination("cc-by-4.0", purposes=["benchmarking"]))


def test_measurement_reauthorises_and_the_real_path_stays_blocked(tmp_path):
    manifest = benchmark_case(tmp_path)
    # Training samples are measured as a development diagnostic: refused when development is not granted.
    no_dev = determination("cc-by-4.0", purposes=["benchmarking", "selection", "training", "tuning"])
    built = benchmark_case(tmp_path / "b", pa_det=no_dev)
    with pytest.raises(CorpusError, match="component_result_unauthorised"):
        measure(tmp_path / "b", built, roles=("training",), pa_det=no_dev)
    assert measure(tmp_path / "b", built, roles=("benchmark",), pa_det=no_dev)["rolesMeasured"] == ["benchmark"]
    # A manifest forged to bind a release without a determination (the real releases' state) is refused.
    pa_null, _ = releases_of(tmp_path, pa_det=None)
    from attributes.datasets.release import release_sha256
    forged = copy.deepcopy(manifest)
    forged["releases"] = [{"releaseId": r["releaseId"], "releaseSha256": release_sha256(pa_null) if r["releaseId"] == PA else r["releaseSha256"]} for r in forged["releases"]]
    with pytest.raises(CorpusError, match="determination-missing"):
        measure(tmp_path, forged, pa_det=None)


def test_a_tampered_image_is_refused(tmp_path):
    manifest = benchmark_case(tmp_path)
    forged = copy.deepcopy(manifest)
    target = next(s for s in forged["samples"] if s["memberPath"] == member(1301))
    other = next(s for s in forged["samples"] if s["memberPath"] == member(1302))
    target["memberPath"] = other["memberPath"]  # same bytes are no longer under that sample id
    with pytest.raises(CorpusError, match="image_differs"):
        measure(tmp_path, forged)


def test_cli_measure_refuses_non_canonical_manifests_inside_git_and_overwrites(tmp_path, capsys):
    from attributes.datasets import cli
    manifest = benchmark_case(tmp_path)
    pa, up = releases_of(tmp_path)
    paths = {}
    for name, doc in (("manifest.json", manifest), ("pa.json", pa), ("up.json", up)):
        paths[name] = tmp_path / name
        paths[name].write_bytes(canonical_json(doc))
    argv = ["measure", "--still-dataset", str(paths["manifest.json"]), "--pa100k-release", str(paths["pa.json"]), "--pa100k-root", str(tmp_path / "pa"),
            "--upar-release", str(paths["up.json"]), "--out", str(tmp_path / "out" / "result.json")]
    assert cli.main(argv) == 0
    produced = json.loads(capsys.readouterr().out)
    assert produced["componentResultSha256"] == __import__("hashlib").sha256((tmp_path / "out" / "result.json").read_bytes()).hexdigest()
    assert cli.main(argv) == 2 and "overwrite" in capsys.readouterr().err
    paths["manifest.json"].write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    assert cli.main(argv[:-1] + [str(tmp_path / "out" / "second.json")]) == 2 and "not_canonical" in capsys.readouterr().err
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    assert cli.main(argv[:-1] + [str(tmp_path / "repo" / "r.json")]) == 2 and "Git" in capsys.readouterr().err


def test_code_identity_binds_the_task_vocabulary_and_data_files_lf_normalised():
    identity = ms.code_identity()
    assert "task:attribute-task-v1-candidate.json" in identity["dataSha256"]
    assert "data/mavi-dev-colour-probe-v1.json" in identity["dataSha256"]
    assert "data/mappings/upar-task1-person-colour-v1.json" in identity["dataSha256"]
    assert "measure.py" in identity["moduleSha256"] and "adapters/pa100k.py" in identity["moduleSha256"]
    from attributes.corpus.canonical import lf_normalised_sha256
    assert identity["dataSha256"]["data/mavi-dev-colour-probe-v1.json"] == lf_normalised_sha256(cp.CONFIG_PATH)
