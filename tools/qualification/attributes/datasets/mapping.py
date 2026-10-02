"""Hash-bound label mappings from a source's labels to MAVI attributes (plan §5).

A mapping record (``mavi-attribute-label-mapping-v1``, committed under
``data/mappings/``) accounts for **every** source label exactly once: either it feeds a
MAVI attribute rule, or it is listed as unmapped with a reason. Nothing is silently
ignored, and a label the adapter does not produce is refused.

Rules:
- ``binary-any``: presence from source binary labels. The outcome is ``source-binary``
  with value ``positive`` (any label 1) or ``negative`` (all 0). A source zero is never
  presented as MAVI ``absent``.
- ``one-hot-colour``: one named column positive → that MAVI colour; the only positive is
  an unmapped column (UPAR ``Other``) → ``unmapped``; several positives →
  ``unscorable:ambiguous``, never a single guessed colour; none → truth missing.

``semantics`` is ``source-native`` (the source's own definition) or ``proxy`` (a
subset/approximation of the MAVI attribute). Results inherit it; neither is a MAVI
operational claim.
"""

from __future__ import annotations

from attributes.corpus.canonical import canonical_json, require, require_free_text, require_keys, require_token, sha256_hex
from attributes.corpus.task import Task, load_task

from .adapters import pa100k, upar

MAPPING_SCHEMA = "mavi-attribute-label-mapping-v1"
ADAPTER_LABELS = {"pa100k": pa100k.ATTRIBUTES, "upar-task1": upar.COLUMNS}
RULES = ("binary-any", "one-hot-colour")
SEMANTICS = ("proxy", "source-native")


def parse_mapping(document: object, task: Task | None = None) -> dict:
    code = "label_mapping_invalid"
    task = task or load_task()
    require(isinstance(document, dict), code)
    require_keys(document, code, ("schemaVersion", "mappingId", "adapter", "sourceLabels", "attributes", "unmapped"))
    require(document["schemaVersion"] == MAPPING_SCHEMA, f"{code}:schema")
    require_token(document["mappingId"], f"{code}:id")
    adapter = document["adapter"]
    require(adapter in ADAPTER_LABELS, f"{code}:adapter")
    require(isinstance(document["sourceLabels"], list) and tuple(document["sourceLabels"]) == ADAPTER_LABELS[adapter], f"{code}:source_labels")
    used: list[str] = []
    attribute_types = []
    require(isinstance(document["attributes"], list) and document["attributes"], f"{code}:attributes")
    for rule in document["attributes"]:
        rcode = f"{code}:rule"
        require(isinstance(rule, dict), rcode)
        kind = rule.get("rule")
        require(kind in RULES, f"{rcode}:kind")
        if kind == "binary-any":
            require_keys(rule, rcode, ("attributeType", "rule", "sourceLabels", "semantics", "coverage"))
            labels = rule["sourceLabels"]
            require(isinstance(labels, list) and labels and all(isinstance(x, str) for x in labels), f"{rcode}:labels")
            used += labels
        else:
            require_keys(rule, rcode, ("attributeType", "rule", "columns", "semantics", "coverage"))
            columns = rule["columns"]
            require(isinstance(columns, dict) and columns and all(isinstance(k, str) for k in columns), f"{rcode}:columns")
            used += list(columns)
        spec = task.attribute(rule["attributeType"])  # refuses an unknown attribute
        require(spec.object_class == "person", f"{rcode}:object_class")
        if kind == "binary-any":
            require(spec.kind == "presence", f"{rcode}:binary_needs_presence")
        else:
            require(spec.kind == "categorical", f"{rcode}:colour_needs_categorical")
            targets = [v for v in rule["columns"].values() if v is not None]
            require(all(v in spec.values for v in targets), f"{rcode}:colour_value_unknown")
            require(len(targets) == len(set(targets)), f"{rcode}:colour_value_repeated")
        require(rule["semantics"] in SEMANTICS, f"{rcode}:semantics")
        require(isinstance(rule["coverage"], str) and rule["coverage"].strip() != "", f"{rcode}:coverage")
        require_free_text(rule["coverage"], f"{rcode}:coverage", 1000)
        attribute_types.append(rule["attributeType"])
    require(len(attribute_types) == len(set(attribute_types)), f"{code}:attribute_repeated")
    require(isinstance(document["unmapped"], list), f"{code}:unmapped")
    for entry in document["unmapped"]:
        require(isinstance(entry, dict), f"{code}:unmapped")
        require_keys(entry, f"{code}:unmapped", ("label", "reason"))
        require(isinstance(entry["label"], str) and isinstance(entry["reason"], str) and entry["reason"].strip() != "", f"{code}:unmapped")
        used.append(entry["label"])
    unknown = sorted(set(used) - set(ADAPTER_LABELS[adapter]))
    require(not unknown, f"{code}:label_unknown:{','.join(unknown)}")
    repeated = sorted({x for x in used if used.count(x) > 1})
    require(not repeated, f"{code}:label_repeated:{','.join(repeated)}")
    missing = sorted(set(ADAPTER_LABELS[adapter]) - set(used))
    require(not missing, f"{code}:label_unaccounted:{','.join(missing)}")
    return document


def mapping_sha256(mapping: dict) -> str:
    return sha256_hex(canonical_json(mapping))


def apply_mapping(mapping: dict, labels: dict[str, int]) -> dict[str, dict | None]:
    """Per MAVI attribute: ``{outcome, value, semantics}``, or None when truth is missing."""
    require(set(labels) == set(mapping["sourceLabels"]), "label_mapping_source_labels_differ")
    out: dict[str, dict | None] = {}
    for rule in mapping["attributes"]:
        semantics = rule["semantics"]
        if rule["rule"] == "binary-any":
            positive = any(labels[x] == 1 for x in rule["sourceLabels"])
            out[rule["attributeType"]] = {"outcome": "source-binary", "value": "positive" if positive else "negative", "semantics": semantics}
            continue
        positives = sorted(c for c in rule["columns"] if labels[c] == 1)
        if not positives:
            out[rule["attributeType"]] = None
        elif len(positives) > 1:
            out[rule["attributeType"]] = {"outcome": "unscorable", "value": "ambiguous", "semantics": semantics}
        elif rule["columns"][positives[0]] is None:
            out[rule["attributeType"]] = {"outcome": "unmapped", "value": None, "semantics": semantics}
        else:
            out[rule["attributeType"]] = {"outcome": "value", "value": rule["columns"][positives[0]], "semantics": semantics}
    return out
