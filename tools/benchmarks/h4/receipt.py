"""The immutable H4 arm completion receipt (``h4-arm-receipt-v2``).

Once an arm's ``execute`` has finished, its receipt binds, from retained bytes only:

* the event, domain and partition, and the derivation manifest (re-hashed through ``prepare.load``);
* the frozen producer tuple the arm was required to run (``producerId``, ``pipelineProfileSha256``,
  ``componentBindingSha256``, ``modelPackId``), which must be exactly that producer as committed at the methodology
  freeze commit (``freezeCommit``; read by ``producer.producer_identity_at``, so no later registry, binding or profile
  change and no later HEAD can redefine or invalidate a frozen receipt), and the fact that every export attests it;
* one ``Completed`` export per prepared sequence, bound to its derived video, with its processing run id and SHA-256;
* every Vehicle Track's sealed trajectory, present in the arm's evidence root with its attested hash;
* the execute journal's SHA-256.

The receipt's own identity is the SHA-256 of its canonical body (``receiptSha256`` is that value, kept beside the
body). The body is a pure function of the retained evidence: two builds from the same files give the same identity.
When it was built is recorded only in an unhashed sidecar (``<receipt>.completed-at.txt``). ``verify`` re-derives the
receipt from the same files and requires equality, so a receipt that verifies means the arm's product inference is
complete and is never to be rerun because downstream analysis changes.

Usage::

    python -m tools.benchmarks.h4.receipt build --event E --domain D --partition P --producer-tuple tuple.json
        --freeze-commit SHA --derived DIR --exports DIR --evidence-root DIR --journal FILE --out receipt.json
    python -m tools.benchmarks.h4.receipt verify --receipt receipt.json --producer-tuple tuple.json
        --freeze-commit SHA --derived DIR --exports DIR --evidence-root DIR --journal FILE
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.benchmarks import prepare as preparation
from tools.benchmarks.capabilities.vehicle_tracks import mavi_tracks
from tools.benchmarks.core import mavi, producer as producers
from tools.benchmarks.core._stage3 import artefacts
from tools.benchmarks.core.identity import S32Error, canonical_json, require, sha256_hex

SCHEMA = "h4-arm-receipt-v2"
TUPLE_KEYS = ("producerId", *producers.ATTESTED_KEYS)


def load_tuple(path: Path) -> dict[str, str]:
    """The frozen producer tuple of one arm (exactly the four keys, as the methodology freeze records them)."""
    document = artefacts.parse_json(artefacts.read_bytes(path, "h4_tuple_unreadable"), "h4_tuple_invalid")
    require(isinstance(document, dict) and set(document) == set(TUPLE_KEYS)
            and all(isinstance(document[key], str) and document[key] for key in TUPLE_KEYS), "h4_tuple_invalid")
    return document


def sidecar(receipt_path: Path) -> Path:
    """The unhashed record of when the receipt was built."""
    return Path(receipt_path).with_suffix(".completed-at.txt")


def body(*, event: str, domain: str, partition: str, producer: dict[str, str], freeze_commit: str, derived: Path,
         exports_dir: Path, evidence_root: Path, journal: Path) -> dict[str, Any]:
    """The receipt body, derived from the files; refuses anything incomplete or under another producer."""
    # The tuple must be exactly the producer of its id as committed at the freeze (registry, binding, profile).
    require(producers.journal_identity(producers.producer_identity_at(producer["producerId"], freeze_commit)) ==
            {key: producer[key] for key in TUPLE_KEYS}, "h4_receipt_tuple_not_the_registry_producer")
    manifest, manifest_sha, _ = preparation.load(derived)
    journal_bytes = artefacts.read_bytes(journal, "h4_receipt_journal_unreadable")
    journal_document = artefacts.parse_json(journal_bytes, "h4_receipt_journal_invalid")
    require(isinstance(journal_document, dict) and journal_document.get("sourcePoolSha256") == manifest_sha
            and journal_document.get("developmentProducer") == {key: producer[key] for key in TUPLE_KEYS},
            "h4_receipt_journal_not_this_unit")
    paths = sorted(Path(exports_dir).glob(f"*/{artefacts.EXPORT_FILE_NAME}"))
    exports = artefacts.load_exports(paths)
    by_video = {export.video["sourceSha256"]: export for export in exports.values()}
    require(len(by_video) == len(exports), "h4_receipt_export_duplicate_video")
    sequences = []
    for row in manifest["sequences"]:
        export = by_video.get(row["derivedVideoSha256"])
        require(export is not None, f"h4_receipt_sequence_missing:{row['sequenceId']}")
        require(export.document["processingRun"]["status"] == "Completed", f"h4_receipt_run_not_completed:{row['sequenceId']}")
        producers.require_attested(export.attestation, producer)
        run = mavi_tracks.project(export, evidence_root)  # every sealed trajectory present with its attested hash
        sequences.append({"sequenceId": row["sequenceId"], "derivedVideoSha256": row["derivedVideoSha256"],
                          "processingRunId": export.run_id, "exportSha256": export.sha256,
                          "exportPath": export.path.relative_to(Path(exports_dir)).as_posix(),
                          "vehicleTracks": len(mavi.vehicle_tracks(export)),
                          "trajectorySha256s": sorted(run.trajectory_sha256s)})
    require(len(sequences) == len(exports), "h4_receipt_export_unexpected")
    # Every export of the unit attests one identical producer and runtime (the harness's own single-producer rule,
    # producer_mixed otherwise): a unit resumed across a MAVI or runtime change is never receipted as complete.
    attested = mavi.producer(exports, producer["pipelineProfileSha256"])
    return {"schemaVersion": SCHEMA, "event": event, "domain": domain, "partition": partition,
            "producer": {key: producer[key] for key in TUPLE_KEYS}, "freezeCommit": freeze_commit,
            "attestedRuntime": attested,
            "derivationManifestSha256": manifest_sha, "datasetId": manifest["datasetId"], "split": manifest["split"],
            "sequencesExpected": len(manifest["sequences"]), "sequencesCompleted": len(sequences),
            "journalSha256": sha256_hex(journal_bytes),
            "sequences": sequences}


def build(*, out: Path, **kwargs: Any) -> str:
    require(not Path(out).exists() and not sidecar(out).exists(), "output_exists")
    receipt = render(body(**kwargs))
    Path(out).write_bytes(canonical_json(receipt))
    completed = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    sidecar(out).write_text(completed + "\n", encoding="ascii")
    return receipt["receiptSha256"]


def render(document: dict[str, Any]) -> dict[str, Any]:
    return {"receipt": document, "receiptSha256": sha256_hex(canonical_json(document))}


def verify(*, receipt_path: Path, derived: Path, exports_dir: Path, evidence_root: Path, journal: Path,
           producer: dict[str, str], freeze_commit: str) -> dict[str, Any]:
    """Re-derives the receipt from the files under the frozen ``producer`` tuple and ``freeze_commit``; refuses on any
    difference. Returns the verified receipt (body and ``receiptSha256``)."""
    data = artefacts.read_bytes(receipt_path, "h4_receipt_unreadable")
    receipt = artefacts.parse_json(data, "h4_receipt_invalid")
    require(isinstance(receipt, dict) and canonical_json(receipt) == data and set(receipt) == {"receipt", "receiptSha256"},
            "h4_receipt_invalid")
    document = receipt["receipt"]
    require(sha256_hex(canonical_json(document)) == receipt["receiptSha256"], "h4_receipt_invalid:sha256")
    require(isinstance(document, dict) and document.get("schemaVersion") == SCHEMA, "h4_receipt_invalid:schema")
    require(document["producer"] == {key: producer[key] for key in TUPLE_KEYS}, "h4_receipt_wrong_producer")
    require(document["freezeCommit"] == freeze_commit, "h4_receipt_wrong_freeze_commit")
    derived_now = body(event=document["event"], domain=document["domain"], partition=document["partition"],
                       producer=document["producer"], freeze_commit=freeze_commit, derived=derived,
                       exports_dir=exports_dir, evidence_root=evidence_root, journal=journal)
    require(derived_now == document, "h4_receipt_mismatch")
    return receipt


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="tools.benchmarks.h4.receipt")
    commands = p.add_subparsers(dest="command", required=True)
    b = commands.add_parser("build")
    for name in ("--event", "--domain", "--partition", "--freeze-commit"):
        b.add_argument(name, required=True)
    for name in ("--producer-tuple", "--derived", "--exports", "--evidence-root", "--journal", "--out"):
        b.add_argument(name, type=Path, required=True)
    v = commands.add_parser("verify")
    for name in ("--receipt", "--producer-tuple", "--derived", "--exports", "--evidence-root", "--journal"):
        v.add_argument(name, type=Path, required=True)
    v.add_argument("--freeze-commit", required=True)
    args = p.parse_args(argv)
    try:
        if args.command == "build":
            print(build(out=args.out, event=args.event, domain=args.domain, partition=args.partition,
                        producer=load_tuple(args.producer_tuple), freeze_commit=args.freeze_commit,
                        derived=args.derived, exports_dir=args.exports,
                        evidence_root=args.evidence_root, journal=args.journal))
        else:
            print(verify(receipt_path=args.receipt, derived=args.derived, exports_dir=args.exports,
                         evidence_root=args.evidence_root, journal=args.journal, producer=load_tuple(args.producer_tuple),
                         freeze_commit=args.freeze_commit)["receiptSha256"])
    except S32Error as exc:
        print(f"refused {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
