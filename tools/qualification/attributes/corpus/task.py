"""The attribute task and label vocabulary (S2c plan §6, §7.1; qualification plan §4).

Two kinds of values live here and must not be confused:

* **annotation ground truth**, which this module validates: a colour value, or for a
  presence attribute ``present`` / ``absent``, or ``unscorable`` with a reason;
* the **runtime outcome** a model later emits (Observed ``present`` or Unknown; no
  Absent in v1, ADR-013 §12). Ground truth needs ``absent`` so precision (a false
  discovery) can be measured; it is never exposed as an operator-facing value.

The candidate task is frozen only by the pilot plus an owner decision, and freezing
may only apply the merges and removals declared *before* the pilot.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path

from .canonical import (
    CorpusError,
    document_sha256,
    read_json,
    require,
    require_datetime,
    require_free_text,
    require_keys,
    require_pseudonym,
    require_sha256,
    require_token,
)

TASK_SCHEMA = "mavi-attribute-task-v1"
DECISION_SCHEMA = "mavi-attribute-task-freeze-decision-v1"
CANDIDATE_TASK_PATH = Path(__file__).resolve().parent / "data" / "attribute-task-v1-candidate.json"

OBJECT_CLASSES = ("person", "vehicle")
KINDS = ("categorical", "presence")
PRESENCE_VALUES = ("absent", "present")
OUTCOME_VALUE = "value"
OUTCOME_UNSCORABLE = "unscorable"
SUBJECT_VALID = "valid"

# S2b attribute-schema limits (mavi_vision.attributes.pipeline); duplicated as plain
# numbers so this evaluation-side tool never imports the worker, and checked against it
# in the test suite.
MAXIMUM_TYPES_PER_OBJECT_CLASS = 8
MAXIMUM_VALUES = 32


@dataclass(frozen=True, slots=True)
class AttributeSpec:
    attribute_type: str
    object_class: str
    kind: str
    values: tuple[str, ...]
    conditional_values: tuple[str, ...]
    conditional: bool

    @property
    def allowed_values(self) -> frozenset[str]:
        return frozenset(self.values) | frozenset(self.conditional_values)


@dataclass(frozen=True, slots=True)
class Task:
    document: dict
    sha256: str
    status: str
    attributes: tuple[AttributeSpec, ...]
    unscorable_reasons: frozenset[str]
    subject_validity_values: frozenset[str]
    unit_kinds: frozenset[str]

    def attribute(self, attribute_type: str) -> AttributeSpec:
        for spec in self.attributes:
            if spec.attribute_type == attribute_type:
                return spec
        raise CorpusError(f"task_attribute_unknown:{attribute_type}")

    def attributes_for(self, object_class: str) -> tuple[AttributeSpec, ...]:
        return tuple(spec for spec in self.attributes if spec.object_class == object_class)

    def validate_label(self, object_class: str, attribute_type: str, outcome: str, value: str | None, reason: str | None) -> None:
        """Refuse any label the frozen guide does not allow; ``unscorable`` is never a value."""
        code = f"label_invalid:{attribute_type}"
        if attribute_type == "subject-validity":
            require(outcome == OUTCOME_VALUE and value in self.subject_validity_values and reason is None, code)
            return
        spec = self.attribute(attribute_type)
        require(spec.object_class == object_class, f"label_object_class_mismatch:{attribute_type}")
        if outcome == OUTCOME_VALUE:
            require(value in spec.allowed_values and reason is None, code)
        elif outcome == OUTCOME_UNSCORABLE:
            require(value is None and reason in self.unscorable_reasons, code)
            # Colour cannot be judged in achromatic imagery; presence can (guide §3).
            require(reason != "achromatic-imagery" or spec.kind == "categorical", f"{code}:reason_not_applicable")
        else:
            raise CorpusError(f"label_outcome_invalid:{outcome}")


def _parse_attribute(entry: object, index: int) -> AttributeSpec:
    code = f"task_attribute_invalid:{index}"
    require(isinstance(entry, dict), code)
    require_keys(entry, code, ("attributeType", "objectClass", "kind", "values", "conditionalValues", "conditional"))
    attribute_type = require_token(entry["attributeType"], code)
    require(attribute_type != "subject-validity", code)
    require(entry["objectClass"] in OBJECT_CLASSES and entry["kind"] in KINDS, code)
    require(isinstance(entry["conditional"], bool), code)
    values, conditional = entry["values"], entry["conditionalValues"]
    require(isinstance(values, list) and isinstance(conditional, list) and values, code)
    for value in (*values, *conditional):
        require_token(value, code)
    require(values == sorted(values) and conditional == sorted(conditional), f"{code}:unsorted")
    require(len(set(values) | set(conditional)) == len(values) + len(conditional), f"{code}:duplicate_value")
    require(len(values) + len(conditional) <= MAXIMUM_VALUES, f"{code}:too_many_values")
    if entry["kind"] == "presence":
        require(tuple(values) == PRESENCE_VALUES and not conditional, f"{code}:presence_values")
    else:
        require(not {"present", "absent", "unscorable"} & set(values), f"{code}:reserved_value")
    return AttributeSpec(attribute_type, entry["objectClass"], entry["kind"], tuple(values), tuple(conditional), entry["conditional"])


def parse_task(document: dict) -> Task:
    code = "task_invalid"
    require_keys(
        document,
        code,
        (
            "schemaVersion", "taskId", "version", "status", "derivedFrom", "source", "excludedAttributeKinds",
            "unitKinds", "unscorableReasons", "subjectValidity", "attributes", "valueMergeCandidates",
            "attributeMergeCandidates", "pilotDecisionRules",
        ),
    )
    require(document["schemaVersion"] == TASK_SCHEMA, f"{code}:schema")
    require(document["status"] in ("candidate", "frozen"), f"{code}:status")
    require(isinstance(document["attributes"], list) and document["attributes"], f"{code}:attributes")
    attributes = tuple(_parse_attribute(entry, index) for index, entry in enumerate(document["attributes"]))
    names = [spec.attribute_type for spec in attributes]
    require(len(names) == len(set(names)), f"{code}:duplicate_attribute")
    for object_class in OBJECT_CLASSES:
        require(sum(spec.object_class == object_class for spec in attributes) <= MAXIMUM_TYPES_PER_OBJECT_CLASS, f"{code}:too_many_types")
    excluded = set(document["excludedAttributeKinds"])
    require(not excluded & set(names), f"{code}:excluded_attribute_present")
    reasons = document["unscorableReasons"]
    require(isinstance(reasons, list) and reasons and all(isinstance(r, str) for r in reasons), f"{code}:reasons")
    for reason in reasons:
        require_token(reason, f"{code}:reasons")
    validity = document["subjectValidity"]
    require(isinstance(validity, dict) and validity.get("attributeType") == "subject-validity", f"{code}:validity")
    require(SUBJECT_VALID in validity.get("values", []), f"{code}:validity")
    unit_kinds = document["unitKinds"]
    require(isinstance(unit_kinds, list) and set(unit_kinds) <= {"crop", "track"} and unit_kinds, f"{code}:unit_kinds")
    for merge in document["valueMergeCandidates"]:
        spec = next((s for s in attributes if s.attribute_type == merge.get("attributeType")), None)
        if document["status"] == "candidate":
            require(spec is not None and len(merge.get("values", [])) == 2 and set(merge["values"]) <= spec.allowed_values, f"{code}:merge_candidate")
    rules = document["pilotDecisionRules"]
    require(isinstance(rules, dict) and rules.get("status") in ("proposed", "owner-confirmed"), f"{code}:rules")
    require((rules["status"] == "owner-confirmed") == (rules.get("ownerConfirmation") is not None), f"{code}:rules_confirmation")
    return Task(
        document=document,
        sha256=document_sha256(document),
        status=document["status"],
        attributes=attributes,
        unscorable_reasons=frozenset(reasons),
        subject_validity_values=frozenset(validity["values"]),
        unit_kinds=frozenset(unit_kinds),
    )


def load_task(path: Path = CANDIDATE_TASK_PATH) -> Task:
    return parse_task(read_json(path))


def require_confirmed_rules(task: Task) -> dict:
    """The pilot decision thresholds must be owner-confirmed before any pilot label exists."""
    rules = task.document["pilotDecisionRules"]
    require(rules["status"] == "owner-confirmed", "pilot_rules_not_owner_confirmed")
    return rules


def confirm_rules(task_document: dict, confirmed_by: str, confirmed_at: str, overrides: dict | None = None) -> dict:
    """Owner confirmation of the pilot thresholds; a value may only be raised, never lowered."""
    require_pseudonym(confirmed_by, "rules_confirmation_owner")
    require_datetime(confirmed_at, "rules_confirmation_time")
    document = copy.deepcopy(task_document)
    rules = document["pilotDecisionRules"]
    require(rules["status"] == "proposed", "pilot_rules_already_confirmed")
    for key, value in (overrides or {}).items():
        require(key in ("minimumValueAlpha", "minimumScorabilityAlpha", "minimumDoubleLabelledUnitsPerAttribute"), f"rules_override_unknown:{key}")
        require(isinstance(value, (int, float)) and value >= rules[key], f"rules_override_lowers:{key}")
        rules[key] = value
    rules["status"] = "owner-confirmed"
    rules["ownerConfirmation"] = {"by": confirmed_by, "at": confirmed_at}
    return document


RAISABLE_RULES = ("minimumValueAlpha", "minimumScorabilityAlpha", "minimumDoubleLabelledUnitsPerAttribute")


def verify_confirmed_candidate(committed: dict, confirmed: dict) -> None:
    """``confirmed`` must be the committed candidate task with only an owner confirmation of
    its pilot rules: every other field identical; the raisable thresholds equal or higher;
    every other rule (for example ``mergeConfusionShare``) unchanged. A candidate with
    lowered thresholds, or a different vocabulary, cannot stand behind the pilot."""
    require({k: v for k, v in committed.items() if k != "pilotDecisionRules"} == {k: v for k, v in confirmed.items() if k != "pilotDecisionRules"}, "candidate_differs_from_committed")
    proposed, rules = committed["pilotDecisionRules"], confirmed["pilotDecisionRules"]
    require(proposed["status"] == "proposed" and rules["status"] == "owner-confirmed" and rules.get("ownerConfirmation"), "candidate_rules_not_owner_confirmed")
    require(set(rules) == set(proposed), "candidate_rules_keys_changed")
    for key, value in proposed.items():
        if key in ("status", "ownerConfirmation"):
            continue
        if key in RAISABLE_RULES:
            require(isinstance(rules[key], (int, float)) and rules[key] >= value, f"candidate_rules_lowered:{key}")
        else:
            require(rules[key] == value, f"candidate_rules_changed:{key}")


def attribute_verdicts(task: Task, agreement: dict, rules: dict) -> dict[str, dict]:
    """The pilot's per-attribute verdict under the owner-confirmed rules (deterministic).

    ``keep``: every threshold met. ``insufficient-evidence``: too few double-labelled units
    (or no labels); more pilot labels under the same rules, or removal. ``merge-or-remove``:
    enough support but an agreement threshold failed."""
    by_attribute = {a["attributeType"]: a for a in agreement["attributes"]}
    verdicts = {}
    for spec in task.attributes:
        stats = by_attribute.get(spec.attribute_type)
        if stats is None:
            verdicts[spec.attribute_type] = {"attributeType": spec.attribute_type, "recommendation": "insufficient-evidence", "reasons": ["no_pilot_labels"]}
            continue
        reasons = []
        if stats["doubleLabelledUnits"] < rules["minimumDoubleLabelledUnitsPerAttribute"]:
            reasons.append(f"double_labelled_units_below_minimum:{stats['doubleLabelledUnits']}")
        for facet, key in (("value", "minimumValueAlpha"), ("scorability", "minimumScorabilityAlpha")):
            alpha = stats[facet]["krippendorffAlpha"]
            if alpha is None or alpha < rules[key]:
                reasons.append(f"{facet}_alpha_below_minimum:{alpha}")
        verdict = "keep" if not reasons else ("insufficient-evidence" if reasons[0].startswith("double") else "merge-or-remove")
        verdicts[spec.attribute_type] = {"attributeType": spec.attribute_type, "recommendation": verdict, "reasons": reasons}
    return verdicts


def verify_freeze_consistent_with_pilot(candidate: Task, pilot_report: dict, decision: dict) -> None:
    """The owner decision must resolve every attribute the pilot failed (plan §10.3:
    "if an attribute cannot be labelled reliably, it is removed or merged"):

    * ``keep``: may stay unchanged;
    * ``insufficient-evidence``: must be removed. To keep it, label more pilot units under the
      same rules and produce a new pilot report;
    * ``merge-or-remove``: must be removed, or merged by a pre-declared attribute merge the
      pilot recommended. If only value agreement failed, a pre-declared value merge the
      pilot recommended on that attribute also resolves it. Scorability failure is not
      addressed by merging values.

    The verdicts are recomputed from the report's statistics under the candidate's
    confirmed rules; the report must have been produced under exactly those rules."""
    rules = require_confirmed_rules(candidate)
    require(pilot_report.get("pilotDecisionRules") == rules, "freeze_pilot_rules_differ_from_confirmed")
    verdicts = attribute_verdicts(candidate, pilot_report["agreement"], rules)
    recommended_values = {(m["attributeType"], tuple(sorted(m["values"]))) for m in pilot_report["valueMergeRecommendations"] if m["recommendMerge"]}
    recommended_attributes = {tuple(sorted(m["attributeTypes"])) for m in pilot_report["attributeMergeRecommendations"] if m["recommendMerge"]}
    removed = set(decision["attributeRemovals"])
    merged_by_recommendation = {name for m in decision["attributeMerges"] if tuple(sorted(m["attributeTypes"])) in recommended_attributes for name in m["attributeTypes"]}
    value_merged = {m["attributeType"] for m in decision["valueMerges"] if (m["attributeType"], tuple(sorted(m["values"]))) in recommended_values}
    for name, verdict in sorted(verdicts.items()):
        if verdict["recommendation"] == "keep" or name in removed:
            continue
        if verdict["recommendation"] == "insufficient-evidence":
            raise CorpusError(f"freeze_unresolved_insufficient_evidence:{name}")
        only_value = all(r.startswith("value_alpha") for r in verdict["reasons"])
        require(name in merged_by_recommendation or (only_value and name in value_merged), f"freeze_failing_attribute_retained:{name}")


def freeze_task(candidate: Task, pilot_report: dict, decision: dict) -> dict:
    """Produce the frozen task from the candidate, the pilot report and the owner decision.

    Only pre-declared value merges, pre-declared attribute merges, removals of
    conditional values and removals of whole attributes are possible. Nothing is
    added, so the S2b/v2 artefact bound can only decrease from the candidate's.
    """
    require(candidate.status == "candidate", "freeze_requires_candidate")
    require_confirmed_rules(candidate)
    require(pilot_report.get("schemaVersion") == "mavi-attribute-pilot-report-v1", "freeze_pilot_report_invalid")
    require(pilot_report.get("taskSha256") == candidate.sha256, "freeze_pilot_report_task_mismatch")
    require(
        pilot_report.get("reportSha256") == document_sha256({k: v for k, v in pilot_report.items() if k != "reportSha256"}),
        "freeze_pilot_report_hash_mismatch",
    )
    require_keys(decision, "freeze_decision_invalid", ("schemaVersion", "decidedBy", "decidedAt", "valueMerges", "attributeMerges", "valueRemovals", "attributeRemovals", "rationale"))
    require(decision["schemaVersion"] == DECISION_SCHEMA, "freeze_decision_schema")
    require_pseudonym(decision["decidedBy"], "freeze_decision_owner")
    require_datetime(decision["decidedAt"], "freeze_decision_time")
    require_free_text(decision["rationale"], "freeze_decision_rationale")

    document = copy.deepcopy(candidate.document)
    by_type = {entry["attributeType"]: entry for entry in document["attributes"]}
    allowed_value_merges = {(m["attributeType"], tuple(sorted(m["values"]))) for m in candidate.document["valueMergeCandidates"]}
    for merge in decision["valueMerges"]:
        key = (merge["attributeType"], tuple(sorted(merge["values"])))
        require(key in allowed_value_merges, f"freeze_value_merge_not_predeclared:{key[0]}:{'+'.join(key[1])}")
        entry = by_type.get(key[0])
        require(entry is not None, f"freeze_value_merge_attribute_missing:{key[0]}")
        merged = require_token(merge["mergedValue"], "freeze_value_merge_name")
        require(merged in key[1], "freeze_value_merge_name_must_be_member")  # keep one member's name: no new token
        survivors = [v for v in entry["values"] if v not in key[1]] + [merged]
        entry["values"] = sorted(survivors)
    for removal in decision["valueRemovals"]:
        entry = by_type.get(removal["attributeType"])
        require(entry is not None and removal["value"] in entry["conditionalValues"], f"freeze_value_removal_not_conditional:{removal.get('attributeType')}")
        entry["conditionalValues"] = [v for v in entry["conditionalValues"] if v != removal["value"]]
    allowed_attribute_merges = {tuple(sorted(m["attributeTypes"])): m["mergedAttributeType"] for m in candidate.document["attributeMergeCandidates"]}
    for merge in decision["attributeMerges"]:
        key = tuple(sorted(merge["attributeTypes"]))
        require(key in allowed_attribute_merges, f"freeze_attribute_merge_not_predeclared:{'+'.join(key)}")
        require(all(name in by_type for name in key), f"freeze_attribute_merge_member_missing:{'+'.join(key)}")
        members = [by_type[name] for name in key]
        require(len({(m["objectClass"], m["kind"]) for m in members}) == 1, f"freeze_attribute_merge_incompatible:{'+'.join(key)}")
        merged_name = allowed_attribute_merges[key]
        require(merged_name not in by_type or merged_name in key, f"freeze_attribute_merge_collision:{merged_name}")
        first = by_type.pop(key[0])
        for other in key[1:]:
            by_type.pop(other)
        first["attributeType"] = merged_name
        by_type[first["attributeType"]] = first
    for removal in decision["attributeRemovals"]:
        require(removal in by_type, f"freeze_attribute_removal_unknown:{removal}")
        by_type.pop(removal)
    document["attributes"] = [by_type[name] for name in sorted(by_type)]
    document["valueMergeCandidates"] = []
    document["attributeMergeCandidates"] = []
    document["status"] = "frozen"
    document["version"] = candidate.document["version"].removesuffix("-candidate")
    document["derivedFrom"] = {
        "candidateTaskSha256": candidate.sha256,
        "pilotReportSha256": require_sha256(pilot_report.get("reportSha256"), "freeze_pilot_report_hash"),
        "ownerDecisionSha256": document_sha256(decision),
    }
    frozen = parse_task(document)
    for spec in frozen.attributes:
        original = next((s for s in candidate.attributes if s.attribute_type == spec.attribute_type), None)
        if original is not None:
            require(spec.allowed_values <= original.allowed_values, f"freeze_added_value:{spec.attribute_type}")
    verify_freeze_consistent_with_pilot(candidate, pilot_report, decision)
    return frozen.document
