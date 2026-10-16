"""Stage-4 plate selection: the freeze-construction tool (run ONCE, at PROTOCOL_FROZEN, before any candidate executes).

It is the only harness code that reads BOTH partitions together outside the protected-D stages (owner point 2). It
reads the four corpus documents, parses each strictly, validates each partition against the partition plan, checks
cross-partition disjointness (R2), and returns the canonical freeze-record bytes. The record names the four document
SHA-256s and the disjointness result with its hash (``selection_bundle.disjointness_attestation``).

The selection process never runs this tool: it loads only the committed record and the A/B documents, so Layer A
neither parses nor needs D metadata. The D stages re-run the disjointness check on the real D index when they open it.

Because the tool reads the protected-D truth, it marks this process as holding protected truth: no candidate can be
executed in the same process afterwards (``selection_bundle._candidate_execution``). It records no Stage-2 or D state
for the record; freeze construction is a curator step that precedes Layer A by design.

The caller commits the returned bytes at ``FREEZE_RECORD_PATH`` once; the loader refuses any later modification of that
path in the reachable history (add-only).
"""

from __future__ import annotations

import os
from pathlib import Path

from tools.benchmarks.capabilities.plates import selection_bundle as sb


def construct_freeze_record(corpus_dir, *, protocol: dict, roster: dict, partition_plan: dict) -> bytes:
    """The canonical freeze-record bytes for the corpus in ``corpus_dir``, or a refusal (``ValueError`` with the same
    stable codes the loader uses). Nothing is written."""
    if not isinstance(corpus_dir, (str, os.PathLike)):
        raise ValueError("corpus_directory_malformed")
    directory = Path(os.fspath(corpus_dir))
    data = {}
    for key, name in sb.DOCUMENT_FILES.items():
        path = directory / name
        if not path.is_file():
            raise ValueError(f"corpus_document_absent:{key}")
        data[key] = path.read_bytes()
    sb._D_TRUTH_LOADED.add("freeze-construction")   # this process now holds protected truth: no candidate may run
    documents = {key: sb.document_sha256(value) for key, value in data.items()}
    record = {"disjointness": sb.disjointness_attestation(documents), "documents": documents,
              "partitionPlan": partition_plan, "protocol": protocol, "roster": roster, "schema": sb.RECORD_SCHEMA}
    record_bytes = sb.canonical_bytes(record)
    _, _, sites, _, _ = sb._parse_record(record_bytes)   # the record itself must be a valid record
    parsed = {key: sb.parse_canonical(value, f"corpus_document_{key}") for key, value in data.items()}
    ab_index = sb._index(parsed["abIndex"], sb.Partition.AB_SELECTION, sites)
    d_index = sb._index(parsed["dIndex"], sb.Partition.PROTECTED_D, sites)
    ab_truth = sb._truth(parsed["abTruth"], sb.Partition.AB_SELECTION, ab_index)
    sb._truth(parsed["dTruth"], sb.Partition.PROTECTED_D, d_index)
    sb.check_disjoint(ab_index, ab_truth[2], d_index)
    return record_bytes
