"""Corpus diversity report (S2c plan §10.2 "Coverage"; qualification plan §3.2–§3.3).

Distributions only: sites, cameras, sources, date blocks, lighting, setting, frame
resolution, source class, Track and crop counts, evidence roles, subject-size bands and,
when ground truth is supplied, annotated difficulty (unscorable reasons). This is the
foundation for later generalisation analysis. It is **not** a 500-camera or load claim:
scale and workload are S2c.2/S2c.3/S2c.9 (plan §14.1).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from statistics import median

from .canonical import document_sha256, require
from .manifest import CorpusManifest
from .partition import PARTITIONS, partition_of

REPORT_SCHEMA = "mavi-attribute-corpus-report-v1"


def _band(value: int | None, edges: tuple[int, ...], labels: tuple[str, ...]) -> str:
    if value is None:
        return "unknown"
    for edge, label in zip(edges, labels):
        if value < edge:
            return label
    return labels[-1]


def corpus_report(corpus: CorpusManifest, partition: dict, partition_sha256: str, ground_truth: dict | None = None) -> dict:
    parts = partition_of(partition)
    groups: dict[str, dict] = {}
    for scope in ("all", *PARTITIONS):
        tracks = [t for t in corpus.tracks.values() if scope == "all" or parts[t.track_id] == scope]
        sources = {t.source_id for t in tracks}
        per_camera = Counter(corpus.sources[t.source_id].camera_id for t in tracks)
        clusters = {a["clusterId"] for a in partition["assignments"] if scope == "all" or a["partition"] == scope}
        observations = [o for t in tracks for o in t.observations]
        groups[scope] = {
            "sites": len({corpus.sources[s].site_id for s in sources}),
            "cameras": len(per_camera),
            "sources": len(sources),
            "siteDateClusters": len(clusters),
            "recordingDates": len({corpus.sources[s].recording_date for s in sources}),
            "tracksByClass": dict(sorted(Counter(t.object_class for t in tracks).items())),
            "tracksPerCamera": {"min": min(per_camera.values(), default=0), "median": median(per_camera.values()) if per_camera else 0, "max": max(per_camera.values(), default=0)},
            "lighting": dict(sorted(Counter(corpus.sources[s].lighting for s in sources).items())),
            "setting": dict(sorted(Counter(corpus.sources[s].setting for s in sources).items())),
            "frameHeightBand": dict(sorted(Counter(_band(corpus.sources[s].frame_height, (720, 1080), ("<720", "720-1079", ">=1080")) for s in sources).items())),
            "sourceClass": dict(sorted(Counter(corpus.sources[s].source_class for s in sources).items())),
            "cropsByRole": dict(sorted(Counter(o.role for o in observations).items())),
            "cropHeightBand": dict(sorted(Counter(_band(o.height, (64, 128, 256), ("<64", "64-127", "128-255", ">=256")) for o in observations).items())),
        }
    difficulty: dict[str, dict] = {}
    if ground_truth is not None:
        # Annotated difficulty comes from the evaluation view only: frozen-test label
        # distributions never enter a Git-tracked or evaluation-side report.
        require(ground_truth.get("view") == "evaluation", "corpus_report_requires_evaluation_view")
        counts: dict[str, Counter] = defaultdict(Counter)
        for row in ground_truth["rows"]:
            if row["partition"] == "frozen-test":
                continue
            final = row["final"]
            key = final["unscorableReason"] if final["outcome"] == "unscorable" else "scorable"
            counts[row["partition"]][f"{row['attributeType']}:{key}"] += 1
        difficulty = {p: dict(sorted(c.items())) for p, c in sorted(counts.items())}
    document = {
        "schemaVersion": REPORT_SCHEMA,
        "corpusKind": corpus.corpus_kind,
        "corpusManifestSha256": corpus.sha256,
        "partitionManifestSha256": partition_sha256,
        "groundTruthSha256": None if ground_truth is None else document_sha256(ground_truth),
        "scope": "diversity and generalisation foundation only; not a scale, load or 500-camera claim",
        "distributions": groups,
        "annotatedDifficulty": difficulty,
        "limitations": partition["checks"]["limitations"],
    }
    document["reportSha256"] = document_sha256(document)
    return document


def render_markdown(report: dict) -> str:
    lines = [
        "# Corpus diversity report",
        "",
        f"- Corpus kind: `{report['corpusKind']}`" + ("  **(synthetic fixture: not corpus evidence)**" if report["corpusKind"] != "operational" else ""),
        f"- Corpus manifest `{report['corpusManifestSha256']}`; partition manifest `{report['partitionManifestSha256']}`",
        f"- Scope: {report['scope']}",
        f"- Limitations: {', '.join(report['limitations']) or 'none recorded'}",
        "",
        "| Scope | Sites | Cameras | Site-date clusters | Dates | Tracks (person / vehicle) | Tracks per camera (min / median / max) | Lighting |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for scope, g in report["distributions"].items():
        classes = g["tracksByClass"]
        tpc = g["tracksPerCamera"]
        lighting = ", ".join(f"{k} {v}" for k, v in g["lighting"].items())
        lines.append(f"| {scope} | {g['sites']} | {g['cameras']} | {g['siteDateClusters']} | {g['recordingDates']} | {classes.get('person', 0)} / {classes.get('vehicle', 0)} | {tpc['min']} / {tpc['median']} / {tpc['max']} | {lighting} |")
    return "\n".join(lines) + "\n"
