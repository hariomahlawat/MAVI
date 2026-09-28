"""Command line for the S2c.1 corpus workflow. Offline; writes canonical JSON records.

Run from the repository root:  python tools/qualification/attribute_corpus.py <command> ...

Every record written here is safe for Git review (no imagery, no local paths). Evidence
crops are read only by ``duplicates`` from a local directory given on the command line;
that location never enters a record. Frozen-test labels are written only where the
Corpus Custodian directs (``ground-truth --frozen-out``) and must stay outside Git and
outside the evaluation environment.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from .agreement import agreement_report, render_markdown as render_agreement
from .annotation import (
    AnnotationLedger,
    build_assignment,
    build_batch,
    build_ground_truth,
    build_reveal_packet,
    labels_from_csv,
    parse_adjudication,
    parse_batch,
    split_ground_truth,
    unit_key,
)
from .canonical import CorpusError, document_sha256, lf_normalised_sha256, read_json, require, write_canonical
from .duplicates import build_duplicate_audit, directory_reader, fingerprint_corpus, parse_duplicate_audit
from .f1 import check_file
from .frozen import access_frozen, build_seal, declare_improper_access, open_access_log, seal_evaluation_view, seal_status, verify_superseding_seal
from .ledger import Ledger
from .manifest import parse_corpus
from .partition import build_partition, verify_partition
from .pilot import pilot_report, sample_pilot_tracks
from .recurrence import draw_recall_sample, parse_recurrence
from .report import corpus_report, render_markdown as render_report
from .task import confirm_rules, freeze_task, load_task, parse_task


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _emit(path: Path, document: dict) -> None:
    digest = write_canonical(path, document)
    print(f"{path.name} sha256={digest}")


def _seal_outputs_atomically(args: argparse.Namespace, seal: dict, sealed_view: dict, record) -> None:
    """Write the seal, the sealed view and the new access log to temporary files, move them
    into place, and only then append ``seal-created`` (the one irreversible step). Any
    failure removes everything this run created, so a clean retry needs no manual cleanup."""
    finals = [(args.out, seal), (args.sealed_evaluation_out, sealed_view), (args.access_log, None)]
    partials = [final.with_name(final.name + ".partial") for final, _ in finals]
    created: list[Path] = []
    try:
        for partial in partials:
            partial.unlink(missing_ok=True)
        for (final, document), partial in zip(finals, partials):
            if document is None:
                open_access_log(partial, seal, _now(), create=True)
            else:
                write_canonical(partial, document)
        for (final, _), partial in zip(finals, partials):
            os.replace(partial, final)
            created.append(final)
        record()
    except BaseException:
        for path in [*partials, *created]:
            path.unlink(missing_ok=True)
        raise
    for (final, document) in finals:
        if document is not None:
            print(f"{final.name} sha256={document_sha256(document)}")


def _links(corpus, recurrence: Path | None, duplicates: Path | None):
    links, hashes = [], {"recurrence": None, "duplicate": None}
    if recurrence:
        hashes["recurrence"], found = parse_recurrence(read_json(recurrence), corpus)
        links += found
    if duplicates:
        hashes["duplicate"], found = parse_duplicate_audit(read_json(duplicates), corpus)
        links += found
    return links, hashes


def _task(path: Path | None):
    return load_task() if path is None else parse_task(read_json(path))


def _load_batches(paths: list[Path], assignments: dict[str, dict], task) -> list:
    loaded = []
    for path in paths:
        batch = read_json(path)
        loaded.append((batch, parse_batch(batch, assignments[batch["assignmentId"]], task)))
    return loaded


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="attribute_corpus", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, *arguments: tuple[str, dict]) -> argparse.ArgumentParser:
        command = sub.add_parser(name)
        for flag, options in arguments:
            command.add_argument(flag, **options)
        return command

    p = lambda **kw: {"type": Path, **kw}  # noqa: E731
    add("validate-corpus", ("--corpus", p(required=True)))
    add("partition", ("--corpus", p(required=True)), ("--policy", p(required=True)), ("--recurrence", p()), ("--duplicates", p()), ("--out", p(required=True)))
    add("verify-partition", ("--corpus", p(required=True)), ("--partition", p(required=True)), ("--recurrence", p()), ("--duplicates", p()))
    add("duplicates", ("--corpus", p(required=True)), ("--evidence-dir", p(required=True)), ("--threshold", {"type": int, "default": 6}), ("--decisions", p()), ("--out", p(required=True)))
    add("confirm-rules", ("--task", p()), ("--by", {"required": True}), ("--overrides", p()), ("--out", p(required=True)))
    add("register-annotator", ("--ledger", p(required=True)), ("--id", {"required": True}), ("--independent", {"action": "store_true"}))
    add("pilot-sample", ("--corpus", p(required=True)), ("--partition", p(required=True)), ("--size", {"type": int, "required": True}), ("--seed", {"required": True}), ("--out", p(required=True)))
    add(
        "assign",
        ("--corpus", p(required=True)), ("--partition", p(required=True)), ("--task", p()), ("--guide", p(required=True)),
        ("--ledger", p(required=True)), ("--id", {"required": True}), ("--annotator", {"required": True}),
        ("--phase", {"choices": ("pilot", "main"), "required": True}), ("--round", {"choices": ("independent", "single"), "required": True}),
        ("--tracks", p(required=True)), ("--unit-kind", {"choices": ("track", "crop"), "default": "track"}), ("--out", p(required=True)),
    )
    add("submit", ("--ledger", p(required=True)), ("--assignment", p(required=True)), ("--task", p()), ("--labels-csv", p(required=True)), ("--batch-id", {"required": True}), ("--active-seconds", {"type": int}), ("--out", p(required=True)))
    add("reveal", ("--ledger", p(required=True)), ("--id", {"required": True}), ("--recipient", {"required": True}), ("--units", p(required=True)), ("--phase", {"choices": ("pilot", "main"), "default": "main"}), ("--batches", {"type": Path, "nargs": "+", "required": True}), ("--out", p(required=True)))
    add("cancel-assignment", ("--ledger", p(required=True)), ("--assignment-id", {"required": True}), ("--replacement-id", {"required": True}), ("--actor", {"required": True}), ("--reason", {"required": True}))
    add("recall-sample", ("--corpus", p(required=True)), ("--partition", p(required=True)), ("--recurrence", p(required=True)), ("--seed", {"required": True}), ("--size", {"type": int, "required": True}), ("--by", {"required": True}), ("--out", p(required=True)))
    for name in ("agreement", "pilot-report"):
        add(name, ("--corpus", p(required=True)), ("--partition", p(required=True)), ("--task", p()), ("--ledger", p(required=True)), ("--assignments", {"type": Path, "nargs": "+", "required": True}), ("--batches", {"type": Path, "nargs": "+", "required": True}), ("--adjudications", {"type": Path, "nargs": "*", "default": []}), ("--phase", {"choices": ("pilot", "main"), "default": "main"}), ("--include-frozen-custodian-only", {"action": "store_true"}), ("--out", p(required=True)), ("--markdown", p()))
    add("adjudicate", ("--ledger", p(required=True)), ("--adjudication", p(required=True)), ("--assignments", {"type": Path, "nargs": "+", "required": True}), ("--task", p()))
    add("freeze-task", ("--task", p(required=True)), ("--pilot-report", p(required=True)), ("--decision", p(required=True)), ("--out", p(required=True)))
    add("ground-truth", ("--corpus", p(required=True)), ("--partition", p(required=True)), ("--task", p(required=True)), ("--ledger", p(required=True)), ("--assignments", {"type": Path, "nargs": "+", "required": True}), ("--batches", {"type": Path, "nargs": "+", "required": True}), ("--adjudications", {"type": Path, "nargs": "*", "default": []}), ("--evaluation-out", p(required=True)), ("--frozen-out", p(required=True)))
    add("seal", ("--corpus", p(required=True)), ("--partition", p(required=True)), ("--frozen", p(required=True)), ("--evaluation", p(required=True)), ("--sealed-evaluation-out", p(required=True)), ("--ledger", p(required=True)), ("--by", {"required": True}), ("--custody-note", {"required": True}), ("--access-log", p(required=True)), ("--supersedes", p()), ("--supersedes-reason", {}), ("--superseded-access-log", p()), ("--superseded-partition", p()), ("--superseded-corpus", p()), ("--out", p(required=True)))
    add("frozen-access", ("--seal", p(required=True)), ("--access-log", p(required=True)), ("--frozen", p(required=True)), ("--actor", {"required": True}), ("--purpose", {"required": True}), ("--stage", {"required": True}))
    add("declare-improper-access", ("--seal", p(required=True)), ("--access-log", p(required=True)), ("--actor", {"required": True}), ("--stage", {"required": True}), ("--description", {"required": True}))
    add("seal-status", ("--seal", p(required=True)), ("--access-log", p(required=True)), ("--recorded-head", {}))
    add("report", ("--corpus", p(required=True)), ("--partition", p(required=True)), ("--ground-truth", p()), ("--out", p(required=True)), ("--markdown", p()))
    add("check-f1", ("--record", p(required=True)), ("--store", p()))
    add("guide-sha256", ("--guide", p(required=True)))

    args = parser.parse_args(argv)
    try:
        return _run(args)
    except CorpusError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"refused: file_error:{type(error).__name__}:{error.filename}", file=sys.stderr)
        return 2


def _run(args: argparse.Namespace) -> int:  # noqa: C901 - one branch per command
    command = args.command
    if command == "validate-corpus":
        corpus = parse_corpus(read_json(args.corpus))
        print(f"corpus {corpus.corpus_id} ({corpus.corpus_kind}) sha256={corpus.sha256} tracks={len(corpus.tracks)}")
    elif command == "partition":
        corpus = parse_corpus(read_json(args.corpus))
        links, hashes = _links(corpus, args.recurrence, args.duplicates)
        document = build_partition(corpus, read_json(args.policy), links, hashes)
        verify_partition(corpus, document, links, hashes)
        _emit(args.out, document)
        for limitation in document["checks"]["limitations"]:
            print(f"limitation: {limitation}")
    elif command == "verify-partition":
        corpus = parse_corpus(read_json(args.corpus))
        links, hashes = _links(corpus, args.recurrence, args.duplicates)
        verify_partition(corpus, read_json(args.partition), links, hashes)
        print("partition verified")
    elif command == "duplicates":
        corpus = parse_corpus(read_json(args.corpus))
        decisions = read_json(args.decisions) if args.decisions else None
        audit = build_duplicate_audit(corpus, fingerprint_corpus(corpus, directory_reader(args.evidence_dir)), args.threshold, decisions)
        _emit(args.out, audit)
    elif command == "confirm-rules":
        overrides = read_json(args.overrides) if args.overrides else None
        _emit(args.out, confirm_rules(_task(args.task).document, args.by, _now(), overrides))
    elif command == "register-annotator":
        AnnotationLedger(args.ledger).register_annotator(args.id, args.independent, _now())
    elif command == "pilot-sample":
        corpus = parse_corpus(read_json(args.corpus))
        tracks = sample_pilot_tracks(corpus, read_json(args.partition), args.size, args.seed)
        _emit(args.out, {"schemaVersion": "mavi-attribute-pilot-sample-v1", "seed": args.seed, "trackIds": tracks})
    elif command == "assign":
        corpus = parse_corpus(read_json(args.corpus))
        partition = read_json(args.partition)
        track_ids = read_json(args.tracks)["trackIds"]
        units = []
        for track_id in track_ids:
            if args.unit_kind == "track":
                units.append(("track", track_id, None))
            else:
                units += [("crop", track_id, o.observation_id) for o in corpus.tracks[track_id].observations]
        assignment = build_assignment(args.id, args.annotator, args.phase, args.round, units, corpus, partition, document_sha256(partition), _task(args.task), lf_normalised_sha256(args.guide))
        AnnotationLedger(args.ledger).issue_assignment(assignment, _now())
        _emit(args.out, assignment)
    elif command == "submit":
        task = _task(args.task)
        assignment = read_json(args.assignment)
        batch = build_batch(args.batch_id, assignment, _now(), labels_from_csv(args.labels_csv.read_text(encoding="utf-8")), args.active_seconds, task)
        AnnotationLedger(args.ledger).submit_batch(batch, assignment, _now())
        _emit(args.out, batch)
    elif command == "reveal":
        batches = [read_json(path) for path in args.batches]
        packet = build_reveal_packet(args.id, args.recipient, read_json(args.units)["units"], args.phase, batches)
        AnnotationLedger(args.ledger).issue_reveal(packet, batches, _now())
        _emit(args.out, packet)
    elif command == "cancel-assignment":
        AnnotationLedger(args.ledger).cancel_assignment(args.assignment_id, args.actor, args.reason, args.replacement_id, _now())
    elif command == "recall-sample":
        corpus = parse_corpus(read_json(args.corpus))
        partition = read_json(args.partition)
        groups_sha, _ = parse_recurrence(read_json(args.recurrence), corpus)
        sample = draw_recall_sample(corpus, partition, document_sha256(partition), groups_sha, args.seed, args.size)
        # A review sheet: the reviewer fills each pair's decision, then it becomes the audit's
        # ``recallSample``. Only the decisions may change; F1 regenerates the pairs.
        _emit(args.out, {**sample, "by": args.by, "date": _now()[:10], "note": "decisions pending review"})
    elif command in ("agreement", "pilot-report"):
        corpus = parse_corpus(read_json(args.corpus))
        partition = read_json(args.partition)
        task = _task(args.task)
        ledger = AnnotationLedger(args.ledger)
        assignments = {a["assignmentId"]: a for a in map(read_json, args.assignments)}
        batches = _load_batches(args.batches, assignments, task)
        registered = set(ledger.batch_hashes())
        ledger.require_phase_complete(args.phase if command == "agreement" else "pilot")
        if command == "pilot-report":
            document = pilot_report(task, corpus, partition, document_sha256(partition), batches, assignments, ledger.annotators(), registered)
            markdown = render_agreement(document["agreement"])
        else:
            object_class = {unit_key(u["unitKind"], u["trackId"], u["observationId"]): u["objectClass"] for a in assignments.values() for u in a["units"]}
            recorded = set(ledger.effective_adjudications())
            adjudicated = set()
            for path in args.adjudications:
                document = read_json(path)
                require(document_sha256(document) in recorded, "agreement_adjudication_not_in_ledger_or_superseded")
                adjudicated |= set(parse_adjudication(document, task, object_class))
            document = agreement_report(args.phase, corpus, partition, document_sha256(partition), task.sha256, batches, assignments, ledger.annotators(), adjudicated, registered, args.include_frozen_custodian_only)
            markdown = render_agreement(document)
        _emit(args.out, document)
        if args.markdown:
            args.markdown.write_text(markdown, encoding="utf-8")
    elif command == "adjudicate":
        task = _task(args.task)
        assignments = [read_json(path) for path in args.assignments]
        object_class = {unit_key(u["unitKind"], u["trackId"], u["observationId"]): u["objectClass"] for a in assignments for u in a["units"]}
        document = read_json(args.adjudication)
        parse_adjudication(document, task, object_class)
        AnnotationLedger(args.ledger).record_adjudication(document, _now())
    elif command == "freeze-task":
        _emit(args.out, freeze_task(parse_task(read_json(args.task)), read_json(args.pilot_report), read_json(args.decision)))
    elif command == "ground-truth":
        corpus = parse_corpus(read_json(args.corpus))
        partition = read_json(args.partition)
        task = _task(args.task)
        ledger = AnnotationLedger(args.ledger)
        assignments = {a["assignmentId"]: a for a in map(read_json, args.assignments)}
        object_class = {unit_key(u["unitKind"], u["trackId"], u["observationId"]): u["objectClass"] for a in assignments.values() for u in a["units"]}
        adjudications = [parse_adjudication(read_json(path), task, object_class) for path in args.adjudications]
        truth = build_ground_truth(corpus, partition, document_sha256(partition), task, _load_batches(args.batches, assignments, task), adjudications, ledger, assignments)
        evaluation, frozen = split_ground_truth(truth, None)
        _emit(args.evaluation_out, evaluation)
        _emit(args.frozen_out, frozen)
    elif command == "seal":
        corpus = parse_corpus(read_json(args.corpus))
        partition = read_json(args.partition)
        evaluation = read_json(args.evaluation)
        ledger = AnnotationLedger(args.ledger)
        require(not args.access_log.exists(), "access_log_already_exists")
        for target in (args.access_log, args.out, args.sealed_evaluation_out):
            require(target.parent.is_dir(), f"seal_output_directory_missing:{target.name}")
        supersedes = None
        if args.supersedes:
            require(args.supersedes_reason and args.superseded_access_log and args.superseded_partition, "seal_supersedes_needs_reason_old_log_and_old_partition")
            old_seal = read_json(args.supersedes)
            supersedes = {"sealSha256": document_sha256(old_seal), "reason": args.supersedes_reason}
        seal = build_seal(corpus, partition, document_sha256(partition), read_json(args.frozen), evaluation, ledger.head, args.by, _now(), args.custody_note, supersedes)
        if supersedes is not None:
            old_corpus = parse_corpus(read_json(args.superseded_corpus)) if args.superseded_corpus else corpus
            require(old_corpus.sha256 == old_seal["corpusManifestSha256"], "seal_superseded_corpus_mismatch:pass --superseded-corpus")
            verify_superseding_seal(seal, old_seal, Ledger(args.superseded_access_log), old_corpus, read_json(args.superseded_partition), partition, corpus)
        # Validate everything, write the seal's files, and only then record it in the ledger:
        # a failed run leaves no ledger entry, so a retry is not mistaken for a re-seal.
        ledger.check_seal(seal, corpus, partition)
        sealed_view = seal_evaluation_view(evaluation, seal)
        _seal_outputs_atomically(args, seal, sealed_view, lambda: ledger.record_seal(seal, corpus, partition, _now()))
    elif command == "frozen-access":
        seal = read_json(args.seal)
        result = access_frozen(open_access_log(args.access_log, seal, _now()), seal, args.frozen, args.actor, args.purpose, args.stage, _now())
        print(result if isinstance(result, str) else f"frozen labels released for {args.purpose}")
    elif command == "declare-improper-access":
        seal = read_json(args.seal)
        declare_improper_access(open_access_log(args.access_log, seal, _now()), seal, args.actor, args.stage, args.description, _now())
    elif command == "seal-status":
        log = Ledger(args.access_log)
        if args.recorded_head:
            log.require_extends(args.recorded_head)
        print(json.dumps(seal_status(log, read_json(args.seal)), indent=2, sort_keys=True))
    elif command == "report":
        corpus = parse_corpus(read_json(args.corpus))
        partition = read_json(args.partition)
        truth = read_json(args.ground_truth) if args.ground_truth else None
        document = corpus_report(corpus, partition, document_sha256(partition), truth)
        _emit(args.out, document)
        if args.markdown:
            args.markdown.write_text(render_report(document), encoding="utf-8")
    elif command == "check-f1":
        verdict = check_file(args.record, store=args.store)
        print(json.dumps(verdict, indent=2, sort_keys=True))
    elif command == "guide-sha256":
        print(lf_normalised_sha256(args.guide))
    return 0
