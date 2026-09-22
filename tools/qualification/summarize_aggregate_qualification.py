"""Print the §T aggregate figures from a ``plan-qualification.json`` — NOT a MAVI runtime component.

The Stage-1 aggregate-materialisation P2 is dispositioned from these figures, and the
authoritative evidence file is held outside the repository. This prints exactly the
rows that decision needs, beside the file's own provenance and SHA-256, as Markdown
an operator can paste into the performance report without retyping a number.

Standard library only::

    python tools/qualification/summarize_aggregate_qualification.py <plan-qualification.json>

Exit code 1 when the file does not describe itself as qualification evidence, so an
engineering observation cannot be transcribed as the authoritative table by mistake.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


def summarize(path: Path) -> tuple[str, bool]:
    raw = path.read_bytes()
    document = json.loads(raw)
    environment = document.get("environment", {})
    verdict = document.get("verdict", {})
    status = verdict.get("status", "unknown — no verdict recorded")
    qualifying = status == "qualification evidence"

    lines = [
        f"- file SHA-256: `{hashlib.sha256(raw).hexdigest()}`",
        f"- status: **{status}**",
        f"- gitSha: `{environment.get('gitSha')}`; working tree clean: `{environment.get('gitWorkingTreeClean')}`; "
        f"commit resolvable: `{environment.get('gitCommitObjectPresent')}`",
        f"- server: {environment.get('postgresVersionFull')}; pgvector {environment.get('pgvector')}; "
        f"cores {environment.get('logicalCores')}; .NET {environment.get('dotnet')}",
        f"- relevant facts: {document.get('relevantFactCount')}",
        "",
        "| Bucket / class | Buckets | Visits | Crossings | Summaries | Intervals | DB ms | App ms | Total ms "
        "| Allocated MiB | GC 0/1/2 | DB queries |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for result in document.get("results", []):
        if result.get("family") != "T":
            continue
        predicate = result["predicate"].removeprefix("aggregate all metrics, ")
        gc = result.get("gcCollections", {})
        lines.append(
            f"| {predicate} | {result.get('buckets')} | {result.get('zoneVisits')} | {result.get('lineCrossings')} "
            f"| {result.get('zoneSummaries')} | {result.get('trackIntervals')} "
            f"| {result.get('databaseMaterialisationMs', 0):,.0f} | {result.get('applicationAggregationMs', 0):,.0f} "
            f"| {result.get('elapsedMs', 0):,.0f} | {result.get('allocatedBytes', 0) / 1048576:,.1f} "
            f"| {gc.get('generation0')}/{gc.get('generation1')}/{gc.get('generation2')} | {result.get('dbQueryCount')} |"
        )
    return "\n".join(lines), qualifying


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    table, qualifying = summarize(Path(argv[0]))
    print(table)
    return 0 if qualifying else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
