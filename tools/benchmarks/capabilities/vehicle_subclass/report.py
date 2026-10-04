"""A deterministic Markdown report of one ``benchmark-vehicle-subclass-result-v1`` (plan §8, §13).

Rendered from the result alone (regenerable, no clock, LF, UTF-8): identity and provenance, the exposure sentence,
scope A with the coverage-limited warning, scope B with exact confusion, precision availability, subset and
excluded blocks, per-class support and requirement status, and the macro class list. Wording is descriptive: no
pass or fail is claimed beyond the registered statuses.
"""

from __future__ import annotations

from typing import Any

from tools.benchmarks.capabilities.vehicle_subclass import evaluate as evaluation

DEVELOPMENT = "Development/reference evidence; not independent generalisation evidence."


def _f(fraction: dict[str, Any] | None) -> str:
    if fraction is None:
        return "n/a"
    numerator, denominator = fraction["numerator"], fraction["denominator"]
    if denominator == 0:
        return f"undefined ({numerator}/0)"
    return f"{numerator}/{denominator} = {numerator / denominator:.4f}"


def _table(header: list[str], rows: list[list[Any]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return lines


def render(result: dict[str, Any]) -> bytes:
    evaluation.check(result)
    envelope, a, b = result["envelope"], result["scopeA"], result["scopeB"]
    dataset, exposure = envelope["dataset"], envelope["exposure"]
    lines = [
        f"# Vehicle-subclass benchmark — {dataset['datasetId']} {dataset['release']} ({dataset['split']})",
        "",
        f"- Run: `{envelope['benchmarkRunId']}`",
        f"- Descriptor: `{dataset['descriptorSha256']}`; mapping: `{result['mappingSha256']}`",
        f"- Association: `{result['associationSha256']}`; policy: `{envelope['tooling']['associationPolicySha256']}`",
        f"- Requirements: `{result['requirements']['sha256']}` (support floor {result['requirements']['supportFloor']})",
        f"- MAVI: commit `{envelope['mavi']['maviCommit']}`, profile `{envelope['mavi']['pipelineProfileSha256']}`, "
        f"{len(envelope['mavi']['exportSha256s'])} export(s)",
        f"- Tooling: commit `{envelope['tooling']['toolingCommit']}`, `{envelope['tooling']['toolingSha256']}`",
        f"- Exposure: {exposure['status']} — {exposure['basis']}",
        f"- {DEVELOPMENT}",
        "",
        "## Scope A — association coverage (detection and tracking; not subclass accuracy)",
        "",
        a["scope"],
        "",
    ]
    gt = a["expectedVehicleGt"]
    lines += _table(["Expected-vehicle GT", "total", "assigned", "ambiguous", "fragmented", "merged", "unverified",
                     "unmatched"],
                    [["all sequences", *(gt[key] for key in ("total", "assigned", "ambiguous", "fragmented", "merged",
                                                              "unverified", "unmatched"))]]
                    + [[item["sequenceId"], *(item["expectedVehicleGt"][key] for key in (
                        "total", "assigned", "ambiguous", "fragmented", "merged", "unverified", "unmatched"))]
                       for item in a["sequences"]])
    lines += ["",
              f"- Association rate: {_f(a['associationRate'])}",
              f"- Coverage-limited GT rate: {_f(a['coverageLimitedGtRate'])} (threshold "
              f"{a['escalationThreshold']['numerator']}/{a['escalationThreshold']['denominator']})",
              f"- Outside-capability GT: {a['outsideCapabilityGt']['total']}; Vehicle Tracks assigned to them: "
              f"{a['outsideCapabilityGt']['vehicleTracksOnOutsideCapabilityGt']}",
              f"- Ignored GT (in no population): {a['ignoredGt']}",
              "- MAVI Vehicle Tracks: " + ", ".join(  # fixed order: the report depends only on the result's values
                  f"{key} {a['maviTracks'][key]}"
                  for key in ("total", "assigned", "fragment", "ignored", "unverified", "unmatched"))
              + f"; MAVI-side unverified rate {_f(a['maviUnverifiedRate'])}",
              f"- Alignment: source {a['alignment']['sourceRate']['numerator']}/"
              f"{a['alignment']['sourceRate']['denominator']} fps, labelled "
              f"{a['alignment']['labelledRate']['numerator']}/{a['alignment']['labelledRate']['denominator']} fps, "
              f"{a['alignment']['evaluablePointsTotal']} evaluable of {a['alignment']['maviPointsTotal']} points",
              ""]
    if a["coverageLimited"]:
        lines += ["**Coverage-limited.** The coverage-limited GT rate exceeds the declared threshold. The association "
                  "is unchanged; the owner decides, before H3 relies on this result, whether to add per-point boxes "
                  "(trajectory v2) or accept the limitation (plan §7.7).", ""]
    lines += _table(["Native class", "mapping", "GT", "assigned", "ambiguous", "fragmented", "merged", "unverified",
                     "unmatched"],
                    [[item["nativeClass"], item["kind"] + (f" ({item['unsupportedKind']})"
                                                           if "unsupportedKind" in item else ""),
                      *(item["gt"][key] for key in ("total", "assigned", "ambiguous", "fragmented", "merged",
                                                    "unverified", "unmatched"))] for item in a["perNativeClass"]])
    lines += ["", "## Scope B — Track-conditional subclass quality (assigned pairs only)", "", b["scope"], ""]
    lines += _table(["MAVI class", "support", "recall", "precision", "precision among judged", "unjudgeable",
                     "undetermined share", "requirement status (precision / recall)"],
                    [[item["maviClass"], f"{item['support']} ({item['supportStatus']})",
                      item["recall"]["status"] if item["recall"]["value"] is None
                      else _f(item["recall"]["value"]),
                      item["precision"]["status"] if item["precision"]["value"] is None
                      else _f(item["precision"]["value"]),
                      _f(item["precision"]["precisionAmongJudgedTracks"]), item["precision"]["unjudgeablePredictions"],
                      _f(item["undeterminedShare"]),
                      f"{item['requirementStatus']['precision']} / {item['requirementStatus']['recall']}"]
                     for item in b["classes"]])
    lines += ["", "Precision is judged over exact, subset and outside-capability truths ("
              + ", ".join(b["classes"][0]["precision"]["judgeableNativeClasses"]) + "); it is `not-available` "
              "whenever a prediction of the class landed on a vehicle-unresolved track.", ""]
    overall = b["overall"]
    lines += [f"- Assigned exact-GT pairs: {overall['assignedExact']}; correct {overall['correct']}; "
              f"undetermined {overall['undetermined']} ({_f(overall['undeterminedShare'])})",
              f"- Accuracy over evaluable: {_f(overall['accuracyOverEvaluable'])}; over resolved: "
              f"{_f(overall['accuracyOverResolved'])}",
              f"- Macro (classes with exact GT and support ≥ floor: {', '.join(b['macro']['classes']) or 'none'}): "
              f"recall {_f(b['macro']['recall'])}, accuracy over resolved {_f(b['macro']['accuracyOverResolved'])}",
              f"- Taxonomy coverage (exact native classes for the four MAVI classes): {b['taxonomyCoverage']}",
              "", "### Exact-class confusion (rows: native class → truth; columns: MAVI outcome)", ""]
    natives = sorted({item["nativeClass"] for item in b["confusion"]})
    rows = []
    for native in natives:
        cells = {item["outcome"]: item["count"] for item in b["confusion"] if item["nativeClass"] == native}
        truth = next(item["truth"] for item in b["confusion"] if item["nativeClass"] == native)
        rows.append([f"{native} → {truth}", *(cells[value] for value in evaluation.OUTCOMES)])
    lines += _table(["truth", *evaluation.OUTCOMES], rows) if rows else ["(no exact native class)"]
    for title, blocks in (("Subset classes (precision only; never recall or confusion)", b["subsetBlocks"]),
                          ("Unsupported classes (excluded from scoring)", b["excluded"])):
        lines += ["", f"### {title}", ""]
        if not blocks:
            lines.append("(none)")
            continue
        for block in blocks:
            label = block["nativeClass"] + (f" → {block['maviClass']}" if "maviClass" in block
                                            else f" ({block['unsupportedKind']})")
            outcome_text = ", ".join(f"{item['outcome']} {item['count']}" for item in block["outcomes"])
            extra = (f"; resolved to mapped {_f(block['resolvedToMapped'])}, undetermined "
                     f"{_f(block['undeterminedShare'])}" if "resolvedToMapped" in block else "")
            lines.append(f"- {label}: assigned {block['assigned']}; outcomes {outcome_text}{extra}")
    lines += ["", "## Limitations", "",
              "- Centre-only trajectories: per-frame IoU exists only at MAVI observation frames (plan §7.7).",
              "- Scope B is conditional on association; scope A misses are never counted as subclass errors.",
              f"- {DEVELOPMENT}", ""]
    return "\n".join(lines).encode("utf-8")
