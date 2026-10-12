"""The Stage 4 evidence-adequacy commands (plan §3; protocol ``docs/qualification/stage4/adequacy-protocol.md``).

    python -m tools.benchmarks.plates.cli truth    --descriptor D --source-root S --adapter A --split P --out T.json
    python -m tools.benchmarks.plates.cli ea       --truth T.json --descriptor D --source-root S
                                                   --instrument SPEC --instrument SPEC --model-root M
                                                   [--vehicle-candidates V.json] --out EA.json
    python -m tools.benchmarks.plates.cli eb       --truth T.json --descriptor D --source-root S --association A.json
                                                   --exports DIR --ea EA.json --instrument SPEC --instrument SPEC
                                                   --model-root M --out EB.json
    python -m tools.benchmarks.plates.cli verdict  --ea EA.json --eb EB.json --out V.json

Every command reconciles the frozen source manifest before reading a byte, reads source images only through
``descriptor.read_verified``, binds each input by SHA-256 and the protocol by its LF-normalised SHA-256, records the
committed tooling identity (``tooling_dirty`` refuses an uncommitted harness), and writes its canonical result once.
E-B runs only on the ``testing`` split of a sequence dataset (training/validation stay unread).
"""

from __future__ import annotations

import argparse
import json
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any

from tools.benchmarks.capabilities.plates import adequacy, coverage, instruments as instrument_module
from tools.benchmarks.capabilities.plates import measure, truth as truths, verdict as verdicts
from tools.benchmarks.capabilities.vehicle_tracks import association as associations
from tools.benchmarks.capabilities.vehicle_tracks.mavi_tracks import frame_rate, round_half_up
from tools.benchmarks.core import descriptor as descriptors
from tools.benchmarks.core._stage3 import ROOT, artefacts
from tools.benchmarks.core.identity import (
    S32Error, canonical_json, read_artefact, require, sha256_hex, tooling_identity, validate,
    write_once)
from tools.benchmarks.datasets import bdd_plate_labels, uc3m_lp, ufpr_alpr, voc_plates

RESULT = "benchmark-plate-adequacy-v1"
PROTOCOL = "docs/qualification/stage4/adequacy-protocol.md"
SCHEMA_STEMS = ("benchmark-dataset-release-v1", "benchmark-association-v1", truths.SCHEMA, RESULT)
CANDIDATES = "benchmark-plate-vehicle-candidates-v1"


def protocol_identity(root: Path = ROOT) -> dict[str, str]:
    data = (Path(root) / PROTOCOL).read_bytes().replace(b"\r\n", b"\n")
    return {"path": PROTOCOL, "sha256": sha256_hex(data)}


def _file_sha(path: Path) -> str:
    return sha256_hex(Path(path).read_bytes())


def _reconciled(descriptor_path: Path, source_root: Path) -> tuple[dict[str, Any], str, dict[str, dict[str, Any]]]:
    document, sha = descriptors.load(descriptor_path)
    return document, sha, descriptors.reconcile(document, source_root)


def _write(document: dict[str, Any], out: Path, schema: str) -> str:
    validate(document, schema, "plate_result_invalid")
    data = canonical_json(document)
    write_once(out, data)
    return sha256_hex(data)


def _truth(path: Path, descriptor_sha: str) -> tuple[dict[str, Any], str]:
    document, _, sha = read_artefact(path, truths.SCHEMA, truths.CODE)
    truths.validate_document(document)
    require(document["descriptorSha256"] == descriptor_sha, f"{truths.CODE}:descriptor_mismatch")
    return document, sha


# truth


def build_truth(descriptor_path: Path, source_root: Path, adapter_id: str, split: str,
                labels_path: Path | None = None) -> dict[str, Any]:
    document, descriptor_sha, entries = _reconciled(descriptor_path, source_root)
    require(descriptors.split(document, split)["labelled"], f"descriptor_invalid:split_unlabelled:{split}")
    if adapter_id == ufpr_alpr.ADAPTER_ID:
        adapter = ufpr_alpr.UfprAlprAdapter()
        adapter.require_descriptor(document)
        items, exclusions = [], []
        for sequence in adapter.discover(source_root, entries, split):
            found, refused = adapter.plate_items(source_root, entries, split, sequence)
            items += found
            exclusions += refused
        kind, version = "sequence", ufpr_alpr.ADAPTER_VERSION
    elif adapter_id == bdd_plate_labels.ADAPTER_ID:
        require(labels_path is not None, "adapter_labels_required")
        items = bdd_plate_labels.plate_items(
            Path(labels_path).read_bytes(), entries, descriptor_sha,
            lambda path: measure.display_size(descriptors.read_verified(entries, source_root, path)))
        exclusions, kind, version = [], "sequence", bdd_plate_labels.ADAPTER_VERSION
    elif adapter_id == uc3m_lp.ADAPTER_ID:
        require(split == uc3m_lp.MEASUREMENT_SPLIT, f"adapter_split_reserved:{split}")
        items, exclusions = uc3m_lp.Uc3mLpAdapter().plate_items(source_root, entries, split)
        kind, version = "still", uc3m_lp.ADAPTER_VERSION
    elif adapter_id == voc_plates.ADAPTER_ID:
        require(split == voc_plates.SPLIT, f"adapter_split_unknown:{split}")
        items, exclusions = voc_plates.VocPlatesAdapter().plate_items(source_root, entries)
        kind, version = "still", voc_plates.ADAPTER_VERSION
    else:
        raise S32Error(f"adapter_unknown:{adapter_id}")
    truth = {"schemaVersion": truths.SCHEMA, "datasetId": document["datasetId"], "release": document["release"],
             "split": split, "descriptorSha256": descriptor_sha, "adapterId": adapter_id, "adapterVersion": version,
             "kind": kind, "normalisationId": "mavi-plate-normalisation-v1",
             "items": sorted(items, key=lambda item: item["itemId"]),
             "exclusions": sorted(exclusions, key=lambda entry: (entry["path"], entry["reason"]))}
    return truths.validate_document(truth)


# E-A


def _instruments(specs: list[Path], model_root: Path) -> tuple[list[Any], list[str]]:
    require(len(specs) == 2, "instrument_invalid:two_instruments_required")
    loaded = [instrument_module.load(spec, model_root) for spec in specs]
    ids = [instrument.instrument_id for instrument in loaded]
    roles = sorted(instrument.identity()["role"] for instrument in loaded)
    require(len(set(ids)) == 2 and roles == ["generic", "plate-specific"], "instrument_invalid:diversity")
    return loaded, [_file_sha(spec) for spec in specs]


def _candidates(path: Path | None, truth_sha: str) -> tuple[dict[str, list[dict[str, float]]], str | None]:
    if path is None:
        return {}, None
    document = json.loads(Path(path).read_bytes())
    require(isinstance(document, dict) and document.get("schemaVersion") == CANDIDATES
            and document.get("truthSha256") == truth_sha and isinstance(document.get("items"), dict)
            and isinstance(document.get("producer"), dict), f"{CANDIDATES}:invalid")
    return document["items"], _file_sha(path)


def run_ea(*, truth_path: Path, descriptor_path: Path, source_root: Path, instrument_specs: list[Path],
           model_root: Path, candidates_path: Path | None = None, tooling: dict[str, Any] | None = None
           ) -> dict[str, Any]:
    document, descriptor_sha, entries = _reconciled(descriptor_path, source_root)
    truth, truth_sha = _truth(truth_path, descriptor_sha)
    loaded, spec_shas = _instruments(instrument_specs, model_root)
    candidates, candidates_sha = _candidates(candidates_path, truth_sha)
    rows = []
    for item in truth["items"]:
        data = descriptors.read_verified(entries, source_root, item["imagePath"])
        require(sha256_hex(data) == item["imageSha256"], f"{truths.CODE}:image_sha256:{item['itemId']}")
        rows += adequacy.measure_item(item, measure.decode_image(data), loaded, candidates.get(item["itemId"]))
    ids = [instrument.instrument_id for instrument in loaded]
    inputs: dict[str, Any] = {"truth": truth_sha, "descriptor": descriptor_sha, "instrumentSpecs": sorted(spec_shas)}
    if candidates_sha is not None:
        inputs["vehicleCandidates"] = candidates_sha
    return {"schemaVersion": RESULT, "kind": "encoding-loss", "protocol": protocol_identity(), "inputs": inputs,
            "instruments": [instrument.identity() for instrument in loaded], "encoder": measure.encoder_identity(),
            "tooling": tooling or tooling_identity(schema_stems=SCHEMA_STEMS), "rows": rows,
            "summary": adequacy.summarise(rows, ids)}


# E-B


def _verified_evidence(export: artefacts.Export, observation: dict[str, Any]):
    def load() -> bytes:
        data = artefacts.read_bytes(export.directory / observation["evidencePath"], "evidence_missing")
        require(len(data) == observation["evidenceSizeBytes"] and sha256_hex(data) == observation["evidenceSha256"],
                f"evidence_hash_mismatch:{observation['evidenceSha256']}")
        return data
    return load


def run_eb(*, truth_path: Path, descriptor_path: Path, source_root: Path, association_path: Path, exports_dir: Path,
           ea_path: Path, instrument_specs: list[Path], model_root: Path, tooling: dict[str, Any] | None = None
           ) -> dict[str, Any]:
    document, descriptor_sha, entries = _reconciled(descriptor_path, source_root)
    truth, truth_sha = _truth(truth_path, descriptor_sha)
    # Sequences of the release's declared evaluation split only (UFPR-ALPR testing, BDD100K MOT val).
    require(truth["kind"] == "sequence" and descriptors.split(document, truth["split"])["role"] == "evaluation",
            "plate_coverage_invalid:evaluation_sequences_only")
    ea, _, ea_sha = read_artefact(ea_path, RESULT, "plate_result_invalid")
    require(ea["kind"] == "encoding-loss", "plate_result_invalid:not_encoding_loss")
    h_min = ea["summary"]["hMin"]["hMinPx"]
    require(h_min is not None, "plate_coverage_invalid:h_min_not_measured")
    association, _, association_sha = read_artefact(association_path, associations.SCHEMA, associations.CODE)
    associations.check(association)
    exports = artefacts.load_exports(sorted(Path(exports_dir).rglob("*.json")))
    by_run = {export.run_id: export for export in exports.values()}
    loaded, spec_shas = _instruments(instrument_specs, model_root)
    frames_by_track: dict[tuple[str, str], list[coverage.PlateFrame]] = {}
    for item in truth["items"]:
        def load_native(path: str = item["imagePath"]) -> Any:
            return measure.decode_image(descriptors.read_verified(entries, source_root, path))
        for plate in item["plates"]:
            frames_by_track.setdefault((item["sequenceId"], item["gtTrackId"]), []).append(
                coverage.PlateFrame(item["frameIndex"], plate, load_native))
    sizes = {item["sequenceId"]: item["frameSize"] for item in truth["items"]}
    tracks = []
    for entry in association["sequences"]:
        export = by_run.get(entry["processingRunId"])
        require(export is not None, f"plate_coverage_invalid:export_missing:{entry['processingRunId']}")
        rate = frame_rate(export)
        size = (export.video["width"], export.video["height"])
        observations: dict[str, list[coverage.EvidenceObservation]] = {}
        for track in export.tracks:
            for item in track["observations"]:
                number = item["sourceFrameNumber"]
                require(item["videoOffsetMs"] == round_half_up(Fraction(number * 1000) / rate),
                        f"plate_coverage_invalid:frame_alignment:{track['id']}")
                observations.setdefault(track["id"], []).append(coverage.EvidenceObservation(
                    item["evidenceRole"], item["evidenceRank"], number,
                    tuple(item["boundingBox"][k] for k in ("x", "y", "width", "height")),
                    _verified_evidence(export, item)))
        for gt_id, (state, mavi_id) in sorted(coverage.association_states(entry).items()):
            if state == "ignoredGt":
                continue
            frames = frames_by_track.get((entry["sequenceId"], gt_id), [])
            if frames:
                # Geometry maps labelled-frame pixels into the run's frames: they must be the same frame size.
                require(sizes[entry["sequenceId"]] == {"width": size[0], "height": size[1]},
                        f"plate_coverage_invalid:frame_size:{entry['sequenceId']}")
            usable = any(frame.plate["textUsable"] for frame in frames)
            result = coverage.evaluate_track(frames, observations.get(mavi_id) if mavi_id else None, size, loaded,
                                             h_min) if usable else None
            tracks.append({"sequenceId": entry["sequenceId"], "gtTrackId": gt_id, "state": state,
                           "maviTrackId": mavi_id, "usablePlate": usable, "result": result})
    ids = [instrument.instrument_id for instrument in loaded]
    return {"schemaVersion": RESULT, "kind": "track-coverage", "protocol": protocol_identity(),
            "inputs": {"truth": truth_sha, "descriptor": descriptor_sha, "association": association_sha,
                       "encodingLoss": ea_sha, "exports": sorted(exports), "instrumentSpecs": sorted(spec_shas)},
            "instruments": [instrument.identity() for instrument in loaded],
            "tooling": tooling or tooling_identity(schema_stems=SCHEMA_STEMS), "rows": tracks,
            "summary": {"hMinPx": h_min, **coverage.summarise(tracks, ids)}}


# verdict


def _fraction(value: dict[str, int] | None) -> Fraction | None:
    return None if value is None else Fraction(value["numerator"], value["denominator"])


def run_verdict(*, ea_path: Path, eb_path: Path | None, tooling: dict[str, Any] | None = None) -> dict[str, Any]:
    ea, _, ea_sha = read_artefact(ea_path, RESULT, "plate_result_invalid")
    require(ea["kind"] == "encoding-loss", "plate_result_invalid:not_encoding_loss")
    losses, sufficient, errors = {}, {}, dict(ea["summary"]["instrumentErrors"])
    loss = ea["summary"].get("encodingLoss")
    for instrument in ea["instruments"]:
        instrument_id = instrument["instrumentId"]
        overall = loss[instrument_id]["supplemental"]["overall"] if loss else None
        losses[instrument_id] = _fraction(overall["deltaEmPp"]) if overall else None
        sufficient[instrument_id] = bool(overall and overall["sufficient"])
    inputs = {"encodingLoss": ea_sha}
    coverage_counts, coverage_sufficient = None, False
    if eb_path is not None:
        eb, _, eb_sha = read_artefact(eb_path, RESULT, "plate_result_invalid")
        require(eb["kind"] == "track-coverage" and eb["inputs"]["encodingLoss"] == ea_sha,
                "plate_result_invalid:coverage_not_bound_to_encoding_loss")
        inputs["trackCoverage"] = eb_sha
        ratio = eb["summary"]["coverage"]
        coverage_counts, coverage_sufficient = (ratio["numerator"], ratio["denominator"]), ratio["sufficient"]
        for instrument_id, count in eb["summary"]["instrumentErrors"].items():
            errors[instrument_id] = errors.get(instrument_id, 0) + count
    decision = verdicts.decide(coverage=coverage_counts, coverage_sufficient=coverage_sufficient, losses=losses,
                               losses_sufficient=sufficient, instrument_errors=errors)
    return {"schemaVersion": RESULT, "kind": "verdict", "protocol": protocol_identity(), "inputs": inputs,
            "tooling": tooling or tooling_identity(schema_stems=SCHEMA_STEMS),
            "summary": {**decision, "coverage": None if coverage_counts is None else
                        {"numerator": coverage_counts[0], "denominator": coverage_counts[1]},
                        "encodingLossSupplementalPp": {k: None if v is None else
                                                       {"numerator": v.numerator, "denominator": v.denominator}
                                                       for k, v in sorted(losses.items())}}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools.benchmarks.plates.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    t = commands.add_parser("truth")
    t.add_argument("--descriptor", type=Path, required=True)
    t.add_argument("--source-root", type=Path, required=True)
    t.add_argument("--adapter", required=True)
    t.add_argument("--split", required=True)
    t.add_argument("--labels", type=Path)
    t.add_argument("--out", type=Path, required=True)
    for name in ("ea", "eb"):
        c = commands.add_parser(name)
        c.add_argument("--truth", type=Path, required=True)
        c.add_argument("--descriptor", type=Path, required=True)
        c.add_argument("--source-root", type=Path, required=True)
        c.add_argument("--instrument", type=Path, action="append", required=True)
        c.add_argument("--model-root", type=Path, required=True)
        c.add_argument("--out", type=Path, required=True)
        if name == "ea":
            c.add_argument("--vehicle-candidates", type=Path)
        else:
            c.add_argument("--association", type=Path, required=True)
            c.add_argument("--exports", type=Path, required=True)
            c.add_argument("--ea", type=Path, required=True)
    v = commands.add_parser("verdict")
    v.add_argument("--ea", type=Path, required=True)
    v.add_argument("--eb", type=Path)
    v.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "truth":
            document = build_truth(args.descriptor, args.source_root, args.adapter, args.split, args.labels)
            sha = _write(document, args.out, truths.SCHEMA)
        elif args.command == "ea":
            sha = _write(run_ea(truth_path=args.truth, descriptor_path=args.descriptor, source_root=args.source_root,
                                instrument_specs=args.instrument, model_root=args.model_root,
                                candidates_path=args.vehicle_candidates), args.out, RESULT)
        elif args.command == "eb":
            sha = _write(run_eb(truth_path=args.truth, descriptor_path=args.descriptor, source_root=args.source_root,
                                association_path=args.association, exports_dir=args.exports, ea_path=args.ea,
                                instrument_specs=args.instrument, model_root=args.model_root), args.out, RESULT)
        else:
            sha = _write(run_verdict(ea_path=args.ea, eb_path=args.eb), args.out, RESULT)
    except S32Error as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(sha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
