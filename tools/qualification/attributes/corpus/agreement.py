"""Inter-annotator agreement (qualification plan §4; S2c plan §10.3).

Agreement is computed over *independent* labels only (never adjudication) and reported
three ways per attribute, because ``unscorable`` is an outcome, not a value:

* **full** — the category is the value, or ``unscorable``;
* **scorability** — the binary question "is this unit scorable at all?";
* **value** — among raters who scored the unit, do they agree on the value?

Statistics: raw (pairwise) agreement, Cohen's kappa (exactly two raters on every unit)
and Krippendorff's alpha for nominal data (any number of raters, missing values
allowed). A statistic that is undefined — no variation, or no unit with two ratings —
is reported as ``null`` with the reason, never as a number.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from itertools import combinations

from .annotation import VALIDITY, Label, unit_key
from .canonical import document_sha256, require
from .manifest import CorpusManifest
from .partition import partition_of

REPORT_SCHEMA = "mavi-attribute-agreement-report-v1"


def krippendorff_alpha_nominal(units: list[list[str]]) -> float | None:
    """Alpha for nominal data from the coincidence matrix (Krippendorff 2011, §B)."""
    coincidence: Counter[tuple[str, str]] = Counter()
    for values in units:
        m = len(values)
        if m < 2:
            continue
        for i, a in enumerate(values):
            for j, b in enumerate(values):
                if i != j:
                    coincidence[(a, b)] += 1 / (m - 1)
    n_c: Counter[str] = Counter()
    for (a, _b), weight in coincidence.items():
        n_c[a] += weight
    n = sum(n_c.values())
    if n <= 1:
        return None
    observed = sum(w for (a, b), w in coincidence.items() if a != b) / n
    expected = sum(n_c[a] * n_c[b] for a in n_c for b in n_c if a != b) / (n * (n - 1))
    if expected == 0:
        return None
    return 1 - observed / expected


def cohen_kappa(pairs: list[tuple[str, str]]) -> float | None:
    if not pairs:
        return None
    n = len(pairs)
    observed = sum(a == b for a, b in pairs) / n
    first, second = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    expected = sum(first[c] * second[c] for c in set(first) | set(second)) / (n * n)
    if expected == 1:
        return None
    return (observed - expected) / (1 - expected)


def raw_agreement(units: list[list[str]]) -> float | None:
    agreeing = total = 0
    for values in units:
        for a, b in combinations(values, 2):
            agreeing += a == b
            total += 1
    return None if total == 0 else agreeing / total


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


def _statistics(units: list[list[str]], rater_lists: list[list[str]]) -> dict:
    pairs = [(u[0], u[1]) for u, r in zip(units, rater_lists) if len(u) == 2]
    two_raters = bool(units) and all(len(u) == 2 for u in units) and len({tuple(sorted(r)) for r in rater_lists}) == 1
    alpha = krippendorff_alpha_nominal(units)
    return {
        "units": len(units),
        "rawAgreement": _round(raw_agreement(units)),
        "cohenKappa": _round(cohen_kappa(pairs)) if two_raters else None,
        "krippendorffAlpha": _round(alpha),
        "undefinedReason": None if alpha is not None else ("no_double_labelled_units" if not units else "no_variation"),
    }


def independent_labels(batches: list[tuple[dict, list[Label]]], assignments: dict[str, dict]) -> dict[tuple[str, str], list[tuple[str, Label]]]:
    grouped: dict[tuple[str, str], list[tuple[str, Label]]] = defaultdict(list)
    for batch, labels in batches:
        assignment = assignments[batch["assignmentId"]]
        if assignment["round"] != "independent":
            continue
        for label in labels:
            grouped[(label.unit, label.attribute_type)].append((batch["annotatorId"], label))
    for key, entries in grouped.items():
        annotators = [a for a, _ in entries]
        require(len(annotators) == len(set(annotators)), f"agreement_annotator_labelled_unit_twice:{key[0]}")
    return grouped


def agreement_report(
    phase: str,
    corpus: CorpusManifest,
    partition: dict,
    partition_sha256: str,
    task_sha256: str,
    batches: list[tuple[dict, list[Label]]],
    assignments: dict[str, dict],
    annotators: dict[str, bool],
    adjudicated: set[tuple[str, str]],
    registered_batches: set[str],
) -> dict:
    for batch, _ in batches:
        # Only ledger-registered batches count: a label that bypassed the independence rules cannot enter a statistic.
        require(document_sha256(batch) in registered_batches, f"agreement_batch_not_in_ledger:{batch['batchId']}")
        require(assignments[batch["assignmentId"]]["phase"] == phase, "agreement_phase_mismatch")
        require(assignments[batch["assignmentId"]]["taskSha256"] == task_sha256, "agreement_task_mismatch")
    grouped = independent_labels(batches, assignments)
    parts = partition_of(partition)
    attributes: dict[str, dict] = defaultdict(lambda: {"all": [], "double": []})
    for (unit, attribute), entries in sorted(grouped.items()):
        attributes[attribute]["all"].append((unit, entries))
        if len(entries) >= 2:
            attributes[attribute]["double"].append((unit, entries))
    report_attributes = []
    for attribute in sorted(attributes):
        everything, double = attributes[attribute]["all"], attributes[attribute]["double"]
        full_units = [[label.category for _, label in sorted(e, key=lambda x: x[0])] for _, e in double]
        raters = [[a for a, _ in sorted(e, key=lambda x: x[0])] for _, e in double]
        scorability = [["scorable" if c != "unscorable" else "unscorable" for c in u] for u in full_units]
        value_units, value_raters = [], []
        for units_values, unit_raters in zip(full_units, raters):
            kept = [(v, r) for v, r in zip(units_values, unit_raters) if v != "unscorable"]
            if len(kept) >= 2:
                value_units.append([v for v, _ in kept])
                value_raters.append([r for _, r in kept])
        confusion: Counter[str] = Counter()
        for values in full_units:
            for a, b in combinations(values, 2):
                if a != b:
                    confusion["|".join(sorted((a, b)))] += 1
        labels_all = [label for _, entries in everything for _, label in entries]
        support: dict[str, Counter[str]] = {"partition": Counter(), "camera": Counter(), "site": Counter()}
        independent_covered = 0
        for unit, entries in double:
            track_id = unit.split(":")[1]
            source = corpus.source_of(track_id)
            support["partition"][parts[track_id]] += 1
            support["camera"][source.camera_id] += 1
            support["site"][source.site_id] += 1
            independent_covered += any(annotators.get(a, False) for a, _ in entries)
        report_attributes.append(
            {
                "attributeType": attribute,
                "labelledUnits": len(everything),
                "doubleLabelledUnits": len(double),
                "full": _statistics(full_units, raters),
                "scorability": _statistics(scorability, raters),
                "value": _statistics(value_units, value_raters),
                "confusion": dict(sorted(confusion.items())),
                "categoryCounts": dict(sorted(Counter(l.category for l in labels_all).items())),
                "unscorableRate": _round(sum(l.category == "unscorable" for l in labels_all) / len(labels_all)) if labels_all else None,
                "adjudicatedUnits": sum((u, attribute) in adjudicated for u, _ in everything),
                "doubleLabelledWithIndependentAnnotator": independent_covered,
                "support": {k: dict(sorted(v.items())) for k, v in support.items()},
            }
        )
    document = {
        "schemaVersion": REPORT_SCHEMA,
        "phase": phase,
        "corpusKind": corpus.corpus_kind,
        "corpusManifestSha256": corpus.sha256,
        "partitionManifestSha256": partition_sha256,
        "taskSha256": task_sha256,
        "batchSha256s": sorted(document_sha256(b) for b, _ in batches),
        "annotators": {"count": len({b["annotatorId"] for b, _ in batches}), "independent": sorted(a for a in {b["annotatorId"] for b, _ in batches} if annotators.get(a))},
        "totals": {
            "labels": sum(len(labels) for _, labels in batches),
            "units": len({unit for (unit, _a) in grouped}),
            "doubleLabelledUnits": len({unit for (unit, _a), e in grouped.items() if len(e) >= 2}),
        },
        "attributes": report_attributes,
    }
    document["reportSha256"] = document_sha256(document)
    return document


def verify_report_hash(document: dict) -> None:
    require(document.get("reportSha256") == document_sha256({k: v for k, v in document.items() if k != "reportSha256"}), "report_hash_mismatch")


def render_markdown(report: dict) -> str:
    lines = [
        f"# Annotation agreement report — {report['phase']}",
        "",
        f"- Corpus kind: `{report['corpusKind']}`" + ("  **(synthetic fixture: not corpus evidence)**" if report["corpusKind"] != "operational" else ""),
        f"- Corpus manifest: `{report['corpusManifestSha256']}`",
        f"- Partition manifest: `{report['partitionManifestSha256']}`",
        f"- Task: `{report['taskSha256']}`",
        f"- Report SHA-256: `{report['reportSha256']}`",
        f"- Annotators: {report['annotators']['count']} (independent: {', '.join(report['annotators']['independent']) or 'none'})",
        f"- Labels {report['totals']['labels']}; units {report['totals']['units']}; double-labelled units {report['totals']['doubleLabelledUnits']}",
        "",
        "| Attribute | Units | Double | Full α | Full κ | Scorability α | Value α | Raw (full) | Unscorable rate | Adjudicated |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for a in report["attributes"]:
        def fmt(v):
            return "—" if v is None else f"{v:.3f}"

        lines.append(
            f"| `{a['attributeType']}` | {a['labelledUnits']} | {a['doubleLabelledUnits']} | {fmt(a['full']['krippendorffAlpha'])} | {fmt(a['full']['cohenKappa'])} | "
            f"{fmt(a['scorability']['krippendorffAlpha'])} | {fmt(a['value']['krippendorffAlpha'])} | {fmt(a['full']['rawAgreement'])} | {fmt(a['unscorableRate'])} | {a['adjudicatedUnits']} |"
        )
    return "\n".join(lines) + "\n"


__all__ = ["VALIDITY", "agreement_report", "cohen_kappa", "krippendorff_alpha_nominal", "raw_agreement", "render_markdown", "unit_key", "verify_report_hash"]
