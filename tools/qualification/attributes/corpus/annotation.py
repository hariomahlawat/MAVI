"""Annotation workflow: assignments, independent submission, adjudication, ground truth.

Independence (qualification plan §4; S2c.0 record §4): each annotator receives an
*assignment* that carries units and allowed values but never another person's label.
Every step is written to the annotation ledger, and the ledger refuses:

* a batch from an annotator who has already been shown other labels for any unit of
  that assignment (a reveal packet), so no "independent" label is submitted after seeing
  someone else's;
* a reveal packet (the adjudication view) while any independent assignment covering its
  units is still unsubmitted.

Original labels are never overwritten: ground truth lists every submitted label with its
batch hash and records how the final value was reached (``single``, ``consensus`` or
``adjudicated``). ``unscorable`` stays ``unscorable``; it is never turned into ``absent``.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from dataclasses import dataclass

from .canonical import (
    CorpusError,
    document_sha256,
    refuse_path_leaks,
    require,
    require_datetime,
    require_free_text,
    require_int,
    require_keys,
    require_pseudonym,
    require_sha256,
    require_uuid,
)
from .ledger import Ledger
from .manifest import CorpusManifest
from .partition import partition_of
from .task import OUTCOME_UNSCORABLE, OUTCOME_VALUE, SUBJECT_VALID, Task, require_confirmed_rules

ASSIGNMENT_SCHEMA = "mavi-attribute-annotation-assignment-v1"
BATCH_SCHEMA = "mavi-attribute-annotation-batch-v1"
REVEAL_SCHEMA = "mavi-attribute-reveal-packet-v1"
ADJUDICATION_SCHEMA = "mavi-attribute-adjudication-v1"
GROUND_TRUTH_SCHEMA = "mavi-attribute-ground-truth-v1"
PHASES = ("pilot", "main")
ROUNDS = ("independent", "single")
VALIDITY = "subject-validity"


def unit_key(unit_kind: str, track_id: str, observation_id: str | None) -> str:
    return f"{unit_kind}:{track_id}:{observation_id or '-'}"


@dataclass(frozen=True, slots=True)
class Label:
    unit: str
    attribute_type: str
    outcome: str
    value: str | None
    reason: str | None

    def as_tuple(self) -> tuple[str, str | None, str | None]:
        return (self.outcome, self.value, self.reason)

    @property
    def category(self) -> str:
        """The value used by agreement statistics: a value, or the category ``unscorable``."""
        return self.value if self.outcome == OUTCOME_VALUE else OUTCOME_UNSCORABLE  # type: ignore[return-value]


# ---- assignments -----------------------------------------------------------------------------


def build_assignment(
    assignment_id: str,
    annotator_id: str,
    phase: str,
    round_: str,
    units: list[tuple[str, str, str | None]],
    corpus: CorpusManifest,
    partition: dict,
    partition_sha256: str,
    task: Task,
    guide_sha256: str,
) -> dict:
    require_pseudonym(assignment_id, "assignment_id")
    require_pseudonym(annotator_id, "assignment_annotator")
    require(phase in PHASES and round_ in ROUNDS, "assignment_phase")
    require(task.status == "frozen" or phase == "pilot", "assignment_main_requires_frozen_task")
    if phase == "pilot":
        # The pilot's decision thresholds are fixed before any pilot label exists.
        require_confirmed_rules(task)
    require_sha256(guide_sha256, "assignment_guide")
    parts = partition_of(partition)
    rows = []
    for unit_kind, track_id, observation_id in units:
        require(unit_kind in task.unit_kinds, f"assignment_unit_kind:{unit_kind}")
        require(track_id in corpus.tracks, f"assignment_unknown_track:{track_id}")
        track = corpus.tracks[track_id]
        if unit_kind == "crop":
            require(any(o.observation_id == observation_id for o in track.observations), f"assignment_unknown_observation:{track_id}")
        else:
            require(observation_id is None, "assignment_track_unit_has_observation")
        if phase == "pilot":
            # The pilot drives vocabulary decisions, so it may read training only (plan §10.3).
            require(parts[track_id] == "training", f"pilot_outside_training:{track_id}")
        rows.append(
            {
                "unitKind": unit_kind,
                "trackId": track_id,
                "observationId": observation_id,
                "objectClass": track.object_class,
                "attributeTypes": [VALIDITY] + [s.attribute_type for s in task.attributes_for(track.object_class)],
            }
        )
    rows.sort(key=lambda r: unit_key(r["unitKind"], r["trackId"], r["observationId"]))
    keys = [unit_key(r["unitKind"], r["trackId"], r["observationId"]) for r in rows]
    require(len(keys) == len(set(keys)) and keys, "assignment_units_duplicate_or_empty")
    return {
        "schemaVersion": ASSIGNMENT_SCHEMA,
        "assignmentId": assignment_id,
        "annotatorId": annotator_id,
        "phase": phase,
        "round": round_,
        "corpusManifestSha256": corpus.sha256,
        "partitionManifestSha256": partition_sha256,
        "taskSha256": task.sha256,
        "guideSha256": guide_sha256,
        "units": rows,
    }


# ---- ledger rules ----------------------------------------------------------------------------


class AnnotationLedger(Ledger):
    # Every write is a pure check that returns the payload, then an append. ``replay`` runs
    # the same checks over a retained ledger, so a hand-written entry that the tool would
    # have refused is refused again when the evidence is re-verified (F1).

    def register_annotator(self, annotator_id: str, independent_of_model_selection: bool, at: str) -> None:
        self.append("annotator-registered", self._p_register(annotator_id, independent_of_model_selection), at)

    def _p_register(self, annotator_id: str, independent: bool) -> dict:
        require_pseudonym(annotator_id, "ledger_annotator")
        require(annotator_id not in self.annotators(), f"ledger_annotator_duplicate:{annotator_id}")
        require(isinstance(independent, bool), "ledger_annotator_independence")
        return {"annotatorId": annotator_id, "independentOfModelSelection": independent}

    def annotators(self) -> dict[str, bool]:
        return {e["payload"]["annotatorId"]: e["payload"]["independentOfModelSelection"] for e in self.of_kind("annotator-registered")}

    def issue_assignment(self, assignment: dict, at: str) -> None:
        self.append("assignment-issued", self._p_assignment(assignment), at)

    def _p_assignment(self, assignment: dict) -> dict:
        require(assignment["annotatorId"] in self.annotators(), "ledger_assignment_unregistered_annotator")
        require(assignment["assignmentId"] not in self._assignments(), "ledger_assignment_duplicate")
        units = [unit_key(u["unitKind"], u["trackId"], u["observationId"]) for u in assignment["units"]]
        return {
            "assignmentId": assignment["assignmentId"],
            "assignmentSha256": document_sha256(assignment),
            "annotatorId": assignment["annotatorId"],
            "phase": assignment["phase"],
            "round": assignment["round"],
            "units": sorted(units),
        }

    def _assignments(self) -> dict[str, dict]:
        return {e["payload"]["assignmentId"]: e["payload"] for e in self.of_kind("assignment-issued")}

    def _submitted(self) -> dict[str, dict]:
        return {e["payload"]["assignmentId"]: e["payload"] for e in self.of_kind("batch-submitted")}

    def _revealed_units(self, annotator_id: str) -> set[str]:
        return {u for e in self.of_kind("reveal-issued") if e["payload"]["recipientId"] == annotator_id for u in e["payload"]["units"]}

    def submit_batch(self, batch: dict, assignment: dict, at: str) -> None:
        self.append("batch-submitted", self._p_submit(batch, assignment), at)

    def _p_submit(self, batch: dict, assignment: dict) -> dict:
        issued = self._assignments().get(batch["assignmentId"])
        require(issued is not None, "ledger_batch_unknown_assignment")
        require(issued["assignmentSha256"] == document_sha256(assignment) == batch["assignmentSha256"], "ledger_batch_assignment_mismatch")
        require(issued["annotatorId"] == batch["annotatorId"], "ledger_batch_wrong_annotator")
        require(batch["assignmentId"] not in self._submitted(), "ledger_batch_already_submitted")
        require(batch["assignmentId"] not in self._cancelled(), "ledger_batch_assignment_cancelled")
        if issued["round"] == "independent":
            seen = self._revealed_units(batch["annotatorId"]) & set(issued["units"])
            require(not seen, "ledger_independence_violated:annotator_saw_other_labels")
        return {"assignmentId": batch["assignmentId"], "annotatorId": batch["annotatorId"], "batchSha256": document_sha256(batch)}

    def _cancelled(self) -> dict[str, dict]:
        return {e["payload"]["assignmentId"]: e["payload"] for e in self.of_kind("assignment-cancelled")}

    def cancel_assignment(self, assignment_id: str, actor: str, reason: str, replacement_id: str, at: str) -> None:
        self.append("assignment-cancelled", self._p_cancel(assignment_id, actor, reason, replacement_id), at)

    def _p_cancel(self, assignment_id: str, actor: str, reason: str, replacement_id: str) -> dict:
        """Cancel an issued, unsubmitted assignment, **only** in favour of a *fresh* replacement:
        issued after it, still unsubmitted, with exactly the same phase, round and units, held
        by an annotator with no other assignment of that phase on those units, and not already
        replacing anything. Neither the sample nor its double-labelling can shrink or be chosen
        after the fact. Refused once the assignment's own labels exist or once any reveal has
        shown labels for its units."""
        assignments = self._assignments()
        issued = assignments.get(assignment_id)
        require(issued is not None, "ledger_cancel_unknown_assignment")
        submitted, cancelled = self._submitted(), self._cancelled()
        require(assignment_id not in submitted, "ledger_cancel_after_submission")
        require(assignment_id not in cancelled, "ledger_cancel_duplicate")
        require_pseudonym(actor, "ledger_cancel_actor")
        require_free_text(reason, "ledger_cancel_reason")
        replacement = assignments.get(replacement_id)
        require(replacement is not None and replacement_id != assignment_id and replacement_id not in cancelled, "ledger_cancel_requires_replacement")
        require((replacement["phase"], replacement["round"], replacement["units"]) == (issued["phase"], issued["round"], issued["units"]), "ledger_cancel_replacement_mismatch")
        order = [aid for aid in assignments]
        require(order.index(replacement_id) > order.index(assignment_id), "ledger_cancel_replacement_not_fresh")
        require(replacement_id not in submitted, "ledger_cancel_replacement_already_submitted")
        require(replacement_id not in {c["replacementAssignmentId"] for c in cancelled.values()}, "ledger_cancel_replacement_already_used")
        units = set(issued["units"])
        others = [
            aid for aid, a in assignments.items()
            if aid not in (replacement_id, assignment_id) and aid not in cancelled and a["annotatorId"] == replacement["annotatorId"] and a["phase"] == issued["phase"] and units & set(a["units"])
        ]
        require(not others, "ledger_cancel_replacement_annotator_already_labels_these_units")
        require(not any(units & set(e["payload"]["units"]) for e in self.of_kind("reveal-issued")), "ledger_cancel_after_reveal")
        return {"assignmentId": assignment_id, "actor": actor, "reason": reason, "replacementAssignmentId": replacement_id}

    def require_phase_complete(self, phase: str) -> None:
        """Every issued assignment of ``phase`` has exactly one submitted batch, unless it was
        cancelled in favour of a replacement (which must then be submitted itself). An
        abandoned assignment would let a convenient subset stand for the whole sample."""
        submitted, cancelled = self._submitted(), self._cancelled()
        open_ = sorted(aid for aid, a in self._assignments().items() if a["phase"] == phase and aid not in submitted and aid not in cancelled)
        require(not open_, f"ledger_assignments_unsubmitted:{phase}:{len(open_)}")

    def reveal_batch_hashes(self, phase: str, units: set[str]) -> set[str]:
        """The submitted batches of ``phase`` that cover any of ``units``: what a reveal must show."""
        assignments = self._assignments()
        return {
            e["batchSha256"]
            for e in self._submitted().values()
            if assignments[e["assignmentId"]]["phase"] == phase and units & set(assignments[e["assignmentId"]]["units"])
        }

    def issue_reveal(self, packet: dict, batches: list[dict], at: str) -> None:
        self.append("reveal-issued", self._p_reveal(packet, batches), at)

    def _p_reveal(self, packet: dict, batches: list[dict]) -> dict:
        """Other annotators' labels may be shown only once every independent label is in, and
        the packet must be the canonical one: built from **every** submitted batch of its phase
        that covers its units (``build_reveal_packet``), so no label can be withheld."""
        submitted, cancelled = self._submitted(), self._cancelled()
        units = set(packet["units"])
        for assignment in self._assignments().values():
            if assignment["round"] == "independent" and units & set(assignment["units"]) and assignment["assignmentId"] not in cancelled:
                require(assignment["assignmentId"] in submitted, f"ledger_reveal_before_independent_submission:{assignment['assignmentId']}")
        require(packet["recipientId"] in self.annotators(), "ledger_reveal_unregistered_recipient")
        expected = self.reveal_batch_hashes(packet["phase"], units)
        supplied = {document_sha256(b) for b in batches}
        require(supplied == expected, f"ledger_reveal_batches_incomplete:{len(expected - supplied)}")
        canonical = build_reveal_packet(packet["packetId"], packet["recipientId"], sorted(units), packet["phase"], batches)
        require(canonical == packet, "ledger_reveal_packet_not_canonical")
        return {
            "packetId": packet["packetId"],
            "recipientId": packet["recipientId"],
            "phase": packet["phase"],
            "units": sorted(units),
            "packetSha256": document_sha256(packet),
            "conflictKeys": packet["conflictKeys"],
            "reasonConflictKeys": packet["reasonConflictKeys"],
        }

    def record_adjudication(self, adjudication: dict, at: str) -> None:
        self.append("adjudication-recorded", self._p_adjudication(adjudication), at)

    def _p_adjudication(self, adjudication: dict) -> dict:
        """An adjudication counts only if its reveal packet was issued, through this ledger, to
        this adjudicator, and covers every unit it decides."""
        require(adjudication["adjudicatorId"] in self.annotators(), "ledger_adjudicator_unregistered")
        packet = next((e["payload"] for e in self.of_kind("reveal-issued") if e["payload"]["packetSha256"] == adjudication["revealPacketSha256"]), None)
        require(packet is not None, "ledger_adjudication_packet_not_issued")
        require(packet["recipientId"] == adjudication["adjudicatorId"], "ledger_adjudication_packet_other_recipient")
        require({d["unit"] for d in adjudication["decisions"]} <= set(packet["units"]), "ledger_adjudication_outside_packet")
        require(packet.get("phase") == "main", "ledger_adjudication_requires_main_packet")
        # Only a real disagreement shown in the packet can be adjudicated. Where raters agree
        # the unit is unscorable but name different reasons, only the reason may be decided.
        conflicts, reason_conflicts = set(packet["conflictKeys"]), set(packet["reasonConflictKeys"])
        for decision in adjudication["decisions"]:
            key = f"{decision['unit']}|{decision['attributeType']}"
            require(key in conflicts or key in reason_conflicts, f"ledger_adjudication_without_conflict:{key}")
            if key in reason_conflicts:
                require(decision["outcome"] == OUTCOME_UNSCORABLE, f"ledger_adjudication_overrides_consensus:{key}")
        sha = document_sha256(adjudication)
        require(sha not in self.adjudication_hashes(), "ledger_adjudication_duplicate")
        keys = sorted({f"{d['unit']}|{d['attributeType']}" for d in adjudication["decisions"]})
        require(keys, "ledger_adjudication_empty")  # a withdrawal is not an adjudication
        supersedes = adjudication.get("supersedes")
        effective = self.effective_adjudications()
        if supersedes is not None:
            require(supersedes in effective, "ledger_adjudication_supersedes_unknown_or_superseded")
        # A key already decided may be decided again only by explicitly superseding the
        # adjudication that decided it (a correction); the superseded one stops counting.
        decided = {k: a["adjudicationSha256"] for a in effective.values() for k in a["keys"]}
        for key in keys:
            require(key not in decided or decided[key] == supersedes, f"ledger_adjudication_key_already_decided:{key}")
        return {"adjudicationId": adjudication["adjudicationId"], "adjudicatorId": adjudication["adjudicatorId"], "adjudicationSha256": sha, "keys": keys, "supersedes": supersedes}

    @classmethod
    def replay(cls, entries: list[dict], load) -> "AnnotationLedger":
        """Re-apply every write rule to retained ``entries`` (already chain-verified), loading
        each referenced document with ``load(sha256, what)``. Each entry's payload must equal
        what the rule computes at that point. Seal entries are checked by the caller."""
        view = cls.__new__(cls)
        view.path = None
        view.entries = []
        for entry in entries:
            kind, payload = entry["kind"], entry["payload"]
            if kind == "annotator-registered":
                expected = view._p_register(payload["annotatorId"], payload["independentOfModelSelection"])
            elif kind == "assignment-issued":
                expected = view._p_assignment(load(payload["assignmentSha256"], "assignment"))
            elif kind == "batch-submitted":
                issued = view._assignments().get(payload["assignmentId"])
                require(issued is not None, "ledger_batch_unknown_assignment")
                expected = view._p_submit(load(payload["batchSha256"], "batch"), load(issued["assignmentSha256"], "assignment"))
            elif kind == "assignment-cancelled":
                expected = view._p_cancel(payload["assignmentId"], payload["actor"], payload["reason"], payload["replacementAssignmentId"])
            elif kind == "reveal-issued":
                packet = load(payload["packetSha256"], "reveal packet")
                shown = [load(sha, "batch") for sha in sorted(view.reveal_batch_hashes(packet["phase"], set(packet["units"])))]
                expected = view._p_reveal(packet, shown)
            elif kind == "adjudication-recorded":
                expected = view._p_adjudication(load(payload["adjudicationSha256"], "adjudication"))
            elif kind == "seal-created":
                expected = payload
            else:
                raise CorpusError(f"ledger_replay_unknown_kind:{kind}")
            require(expected == payload, f"ledger_replay_payload_mismatch:{entry['seq']}:{kind}")
            view.entries.append(entry)
        return view

    def record_seal(self, seal: dict, corpus: CorpusManifest, partition: dict, at: str) -> None:
        """The first seal on a ledger is plain; any later one must supersede the latest seal.
        (``frozen.verify_superseding_seal`` proves the old seal compromised; the caller runs
        it, because it needs the old access log.) The frozen Track IDs are recorded so that
        no later seal can reuse a Track of **any** earlier (compromised) frozen set."""
        track_ids = self.check_seal(seal, corpus, partition)
        exposed = sorted(a["trackId"] for a in partition["assignments"])
        self.append(
            "seal-created",
            {
                "sealSha256": document_sha256(seal),
                "membersSha256": seal["frozenMembers"]["membersSha256"],
                "frozenTrackIds": track_ids,
                "exposedTrackIds": exposed,
                "supersedes": None if seal["supersedes"] is None else seal["supersedes"]["sealSha256"],
            },
            at,
        )

    def check_seal(self, seal: dict, corpus: CorpusManifest, partition: dict) -> list[str]:
        from .frozen import frozen_members  # deferred: frozen imports the ledger module

        members = frozen_members(corpus, partition)
        require(document_sha256(members) == seal["frozenMembers"]["membersSha256"] and document_sha256(partition) == seal["partitionManifestSha256"], "ledger_seal_members_not_reproducible")
        track_ids = [m["trackId"] for m in members]
        seals = self.seals()
        require(document_sha256(seal) not in {s["sealSha256"] for s in seals}, "ledger_seal_duplicate")
        if seals:
            require(seal["supersedes"] is not None and seal["supersedes"]["sealSha256"] == seals[-1]["sealSha256"], "ledger_reseal_requires_supersedes")
        else:
            require(seal["supersedes"] is None, "ledger_first_seal_supersedes")
        earlier = {t for s in seals for t in s["frozenTrackIds"]}
        reused = earlier & set(track_ids)
        require(not reused, f"ledger_seal_reuses_earlier_frozen_tracks:{len(reused)}")
        # Every Track of an earlier seal's partition was open to evaluation, so none may be
        # frozen again (R1): a replacement frozen test needs unexposed (new) footage.
        exposed = {t for s in seals for t in s["exposedTrackIds"]}
        previously = exposed & set(track_ids)
        require(not previously, f"ledger_seal_frozen_tracks_previously_exposed:{len(previously)}")
        return track_ids

    def seals(self) -> list[dict]:
        return self.of_kind_payloads("seal-created")

    def adjudication_hashes(self) -> set[str]:
        return {e["payload"]["adjudicationSha256"] for e in self.of_kind("adjudication-recorded")}

    def effective_adjudications(self) -> dict[str, dict]:
        """Recorded adjudications that no later adjudication superseded."""
        entries = self.of_kind_payloads("adjudication-recorded")
        superseded = {e["supersedes"] for e in entries if e.get("supersedes")}
        return {e["adjudicationSha256"]: e for e in entries if e["adjudicationSha256"] not in superseded}

    def batch_hashes(self) -> dict[str, str]:
        return {e["payload"]["batchSha256"]: e["payload"]["annotatorId"] for e in self.of_kind("batch-submitted")}


# ---- batches ---------------------------------------------------------------------------------

CSV_COLUMNS = ("unitKind", "trackId", "observationId", "attributeType", "outcome", "value", "unscorableReason")


def labels_from_csv(text: str) -> list[dict]:
    """The annotator-facing format: one row per unit x attribute (offline spreadsheet)."""
    reader = csv.DictReader(io.StringIO(text))
    require(tuple(reader.fieldnames or ()) == CSV_COLUMNS, "batch_csv_columns")
    return [
        {
            "unitKind": row["unitKind"],
            "trackId": row["trackId"],
            "observationId": row["observationId"] or None,
            "attributeType": row["attributeType"],
            "outcome": row["outcome"],
            "value": row["value"] or None,
            "unscorableReason": row["unscorableReason"] or None,
        }
        for row in reader
    ]


def build_batch(batch_id: str, assignment: dict, submitted_at: str, labels: list[dict], active_seconds: int | None, task: Task) -> dict:
    batch = {
        "schemaVersion": BATCH_SCHEMA,
        "batchId": batch_id,
        "assignmentId": assignment["assignmentId"],
        "assignmentSha256": document_sha256(assignment),
        "annotatorId": assignment["annotatorId"],
        "submittedAt": submitted_at,
        "activeSeconds": active_seconds,
        "labels": sorted(labels, key=lambda l: (unit_key(l["unitKind"], l["trackId"], l["observationId"]), l["attributeType"])),
    }
    parse_batch(batch, assignment, task)
    return batch


def parse_batch(batch: dict, assignment: dict, task: Task) -> list[Label]:
    code = "batch_invalid"
    require_keys(batch, code, ("schemaVersion", "batchId", "assignmentId", "assignmentSha256", "annotatorId", "submittedAt", "activeSeconds", "labels"))
    require(batch["schemaVersion"] == BATCH_SCHEMA, f"{code}:schema")
    refuse_path_leaks(batch, "batch_path_leak")
    require_pseudonym(batch["batchId"], code)
    require_datetime(batch["submittedAt"], code)
    if batch["activeSeconds"] is not None:
        require_int(batch["activeSeconds"], code, 0)
    require(batch["assignmentSha256"] == document_sha256(assignment), "batch_assignment_mismatch")
    expected = {}
    for unit in assignment["units"]:
        key = unit_key(unit["unitKind"], unit["trackId"], unit["observationId"])
        for attribute in unit["attributeTypes"]:
            expected[(key, attribute)] = unit["objectClass"]
    labels: list[Label] = []
    seen = set()
    for row in batch["labels"]:
        require_keys(row, f"{code}:label", CSV_COLUMNS)
        key = unit_key(row["unitKind"], require_uuid(row["trackId"], f"{code}:label"), row["observationId"])
        pair = (key, row["attributeType"])
        require(pair in expected, f"batch_label_not_assigned:{pair[1]}")
        require(pair not in seen, f"batch_label_duplicate:{pair[1]}")
        seen.add(pair)
        task.validate_label(expected[pair], row["attributeType"], row["outcome"], row["value"], row["unscorableReason"])
        labels.append(Label(key, row["attributeType"], row["outcome"], row["value"], row["unscorableReason"]))
    missing = sorted(set(expected) - seen)
    require(not missing, f"batch_incomplete:{len(missing)}")
    by_unit = defaultdict(dict)
    for label in labels:
        by_unit[label.unit][label.attribute_type] = label
    for unit, attributes in by_unit.items():
        validity = attributes[VALIDITY]
        if validity.value == SUBJECT_VALID:
            # "non-subject" is reserved for crops whose subject is not valid (guide §3).
            for name, label in attributes.items():
                require(label.reason != "non-subject", f"batch_valid_subject_marked_non_subject:{unit}")
        else:
            # A non-subject / wrong-class crop cannot carry an attribute value.
            for name, label in attributes.items():
                require(name == VALIDITY or (label.outcome == OUTCOME_UNSCORABLE and label.reason == "non-subject"), f"batch_invalid_subject_has_value:{unit}")
    return labels


# ---- adjudication and ground truth ---------------------------------------------------------


def build_reveal_packet(packet_id: str, recipient_id: str, units: list[str], phase: str, batches: list[dict]) -> dict:
    """The canonical adjudication view: every submitted label for the named units from the
    given batches, with its source batch, plus the keys that actually conflict.

    Built from the raw batch documents, so the ledger (``issue_reveal``) and F1 can rebuild
    it and prove nothing was withheld. ``conflictKeys``: raters differ on outcome or value.
    ``reasonConflictKeys``: all raters say ``unscorable`` but name different reasons."""
    require(phase in PHASES, "reveal_phase")
    wanted = set(units)
    labels = []
    for batch in batches:
        for row in batch["labels"]:
            unit = unit_key(row["unitKind"], row["trackId"], row["observationId"])
            if unit in wanted:
                labels.append({"unit": unit, "attributeType": row["attributeType"], "annotatorId": batch["annotatorId"], "batchSha256": document_sha256(batch), "outcome": row["outcome"], "value": row["value"], "unscorableReason": row["unscorableReason"]})
    by_key: dict[str, list[dict]] = defaultdict(list)
    for label in labels:
        by_key[f"{label['unit']}|{label['attributeType']}"].append(label)
    conflicts = sorted(k for k, ls in by_key.items() if len({(l["outcome"], l["value"]) for l in ls}) > 1)
    reason_conflicts = sorted(k for k, ls in by_key.items() if k not in conflicts and len({l["unscorableReason"] for l in ls}) > 1)
    return {
        "schemaVersion": REVEAL_SCHEMA,
        "packetId": require_pseudonym(packet_id, "reveal_id"),
        "recipientId": require_pseudonym(recipient_id, "reveal_recipient"),
        "phase": phase,
        "units": sorted(wanted),
        "batchSha256s": sorted({document_sha256(b) for b in batches if any(unit_key(r["unitKind"], r["trackId"], r["observationId"]) in wanted for r in b["labels"])}),
        "labels": sorted(labels, key=lambda l: (l["unit"], l["attributeType"], l["annotatorId"], l["batchSha256"])),
        "conflictKeys": conflicts,
        "reasonConflictKeys": reason_conflicts,
    }


def parse_adjudication(document: dict, task: Task, object_class_of: dict[str, str]) -> dict[tuple[str, str], dict]:
    code = "adjudication_invalid"
    require_keys(document, code, ("schemaVersion", "adjudicationId", "adjudicatorId", "revealPacketSha256", "decidedAt", "decisions"), ("supersedes",))
    if document.get("supersedes") is not None:
        require_sha256(document["supersedes"], f"{code}:supersedes")
    require(document["schemaVersion"] == ADJUDICATION_SCHEMA, f"{code}:schema")
    refuse_path_leaks(document, "adjudication_path_leak")
    require_pseudonym(document["adjudicationId"], code)
    require_pseudonym(document["adjudicatorId"], code)
    require_sha256(document["revealPacketSha256"], code)
    require_datetime(document["decidedAt"], code)
    decisions = {}
    for row in document["decisions"]:
        require_keys(row, f"{code}:decision", ("unit", "attributeType", "outcome", "value", "unscorableReason", "rationale"))
        require(row["unit"] in object_class_of, f"adjudication_unknown_unit:{row['unit']}")
        task.validate_label(object_class_of[row["unit"]], row["attributeType"], row["outcome"], row["value"], row["unscorableReason"])
        require_free_text(row["rationale"], f"{code}:rationale")
        key = (row["unit"], row["attributeType"])
        require(key not in decisions, f"adjudication_duplicate:{key}")
        decisions[key] = {**row, "adjudicationSha256": document_sha256(document), "adjudicatorId": document["adjudicatorId"]}
    return decisions


# When raters agree a unit is unscorable but name different reasons, the final reason is the
# first in this order (annotation guide §3): the most fundamental obstacle wins.
REASON_PRECEDENCE = ("non-subject", "not-visible", "truncated", "occluded", "insufficient-area", "achromatic-imagery", "ambiguous")


def build_ground_truth(
    corpus: CorpusManifest,
    partition: dict,
    partition_sha256: str,
    task: Task,
    batches: list[tuple[dict, list[Label]]],
    adjudications: list[dict[tuple[str, str], dict]],
    ledger: AnnotationLedger,
    assignments: dict[str, dict],
) -> dict:
    """Derive final labels from main-phase batches; any unresolved conflict is an error."""
    registered = ledger.batch_hashes()
    recorded_adjudications = set(ledger.effective_adjudications())
    labels: dict[tuple[str, str], list[dict]] = defaultdict(list)
    seen_batches: set[str] = set()
    for batch, parsed in batches:
        batch_sha = document_sha256(batch)
        require(batch_sha not in seen_batches, f"ground_truth_batch_repeated:{batch['batchId']}")
        seen_batches.add(batch_sha)
        require(batch_sha in registered, f"ground_truth_batch_not_in_ledger:{batch['batchId']}")
        assignment = assignments[batch["assignmentId"]]
        require(assignment["phase"] == "main", f"ground_truth_non_main_batch:{batch['batchId']}")
        require(assignment["taskSha256"] == task.sha256, f"ground_truth_task_mismatch:{batch['batchId']}")
        for label in parsed:
            labels[(label.unit, label.attribute_type)].append(
                {"annotatorId": batch["annotatorId"], "batchSha256": batch_sha, "outcome": label.outcome, "value": label.value, "unscorableReason": label.reason}
            )
    supplied = {d["adjudicationSha256"] for a in adjudications for d in a.values()}
    require(supplied <= recorded_adjudications, "ground_truth_adjudication_not_in_ledger")
    # Every effective (recorded, not superseded) adjudication that decides something must be
    # supplied, just as every registered batch must be.
    wanted = {sha for sha, e in ledger.effective_adjudications().items() if e["keys"]}
    require(supplied == wanted, f"ground_truth_adjudications_incomplete:{len(wanted - supplied)}")
    decided: dict[tuple[str, str], dict] = {}
    for adjudication in adjudications:
        for key, decision in adjudication.items():
            require(decision["adjudicationSha256"] in recorded_adjudications, "ground_truth_adjudication_not_in_ledger")
            require(key not in decided, f"ground_truth_adjudicated_twice:{key}")
            decided[key] = decision
    parts = partition_of(partition)
    rows, unresolved = [], []
    for (unit, attribute), submitted in sorted(labels.items()):
        distinct = {(l["outcome"], l["value"]) for l in submitted}
        reasons = sorted({l["unscorableReason"] for l in submitted if l["unscorableReason"]}, key=REASON_PRECEDENCE.index)
        reason_disagreement = len(reasons) > 1
        if (unit, attribute) in decided:
            require(len(distinct) > 1 or reason_disagreement, f"ground_truth_adjudication_without_conflict:{unit}|{attribute}")
            final = decided[(unit, attribute)]
            if len(distinct) == 1:  # a reason-only conflict: the agreed outcome stays
                require((final["outcome"], final["value"]) == next(iter(distinct)), f"ground_truth_adjudication_overrides_consensus:{unit}|{attribute}")
            resolution, source = "adjudicated", final["adjudicationSha256"]
            final_value = (final["outcome"], final["value"], final["unscorableReason"])
        elif len(distinct) == 1:
            # Agreement on outcome and value is consensus; differing unscorable reasons are
            # resolved by the declared precedence and flagged, not sent to adjudication.
            resolution = "single" if len(submitted) == 1 else "consensus"
            outcome, value = next(iter(distinct))
            source, final_value = None, (outcome, value, reasons[0] if reasons else None)
        else:
            unresolved.append(f"{unit}|{attribute}")
            continue
        track_id = unit.split(":")[1]
        rows.append(
            {
                "unit": unit,
                "trackId": track_id,
                "partition": parts[track_id],
                "attributeType": attribute,
                "labels": sorted(submitted, key=lambda l: l["annotatorId"]),
                "resolution": resolution,
                "reasonDisagreement": reason_disagreement,
                "adjudicationSha256": source,
                "final": {"outcome": final_value[0], "value": final_value[1], "unscorableReason": final_value[2]},
            }
        )
    require(not unresolved, f"ground_truth_unresolved_conflicts:{len(unresolved)}")
    # Every main batch the ledger registered must be supplied: dropping one would hide its
    # disagreements (guide §8: conflicts are never resolved silently).
    phases = {a["assignmentId"]: a["phase"] for a in ledger.of_kind_payloads("assignment-issued")}
    registered_main = {e["batchSha256"] for e in ledger.of_kind_payloads("batch-submitted") if phases[e["assignmentId"]] == "main"}
    require(seen_batches == registered_main, f"ground_truth_batches_incomplete:{len(registered_main - seen_batches)}")
    ledger.require_phase_complete("main")
    # Final labels must agree with the final subject validity, including after adjudication.
    finals: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in rows:
        finals[row["unit"]][row["attributeType"]] = row["final"]
    for unit, attributes in sorted(finals.items()):
        valid = attributes.get(VALIDITY, {}).get("value") == SUBJECT_VALID
        for name, final in attributes.items():
            if name == VALIDITY:
                continue
            non_subject = final["outcome"] == OUTCOME_UNSCORABLE and final["unscorableReason"] == "non-subject"
            require(non_subject != valid, f"ground_truth_subject_validity_inconsistent:{unit}|{name}")
    return {
        "schemaVersion": GROUND_TRUTH_SCHEMA,
        "corpusManifestSha256": corpus.sha256,
        "partitionManifestSha256": partition_sha256,
        "taskSha256": task.sha256,
        "annotationLedgerHead": ledger.head,
        "rows": rows,
    }


def split_ground_truth(ground_truth: dict, seal_sha256: str | None) -> tuple[dict, dict]:
    """Separate the evaluation view (training/tuning/selection) from the frozen-test labels."""
    evaluation = {**ground_truth, "view": "evaluation", "frozenExcluded": True, "sealSha256": seal_sha256, "rows": [r for r in ground_truth["rows"] if r["partition"] != "frozen-test"]}
    frozen = {**ground_truth, "view": "frozen-test", "frozenExcluded": False, "sealSha256": seal_sha256, "rows": [r for r in ground_truth["rows"] if r["partition"] == "frozen-test"]}
    return evaluation, frozen


def load_evaluation_view(document: dict, seal: dict) -> list[dict]:
    """The only ground-truth reader model-selection tooling (S2c.3+) may use.

    It refuses a document that carries frozen-test rows, so selection code cannot read
    frozen labels even if handed the wrong file. It also refuses a view that is not the
    one the frozen-test seal committed (``frozen.seal_evaluation_view``).
    """
    require(document.get("schemaVersion") == GROUND_TRUTH_SCHEMA, "evaluation_view_schema")
    require(document.get("view") == "evaluation" and document.get("frozenExcluded") is True, "evaluation_view_not_frozen_excluded")
    for row in document["rows"]:
        if row["partition"] not in ("training", "tuning", "selection"):
            raise CorpusError("frozen_test_labels_refused_in_selection_view")
    require(document.get("sealSha256") == document_sha256(seal), "evaluation_view_not_sealed")
    require(document_sha256({**document, "sealSha256": None}) == seal["evaluationGroundTruthSha256"], "evaluation_view_not_the_sealed_one")
    return document["rows"]
