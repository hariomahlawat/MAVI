# S2a.3 record/replay evidence (plan §9, C7)

| | Baseline | S2a.3 head |
|---|---|---|
| Commit | `c176b048e278f7097d49254efc47d89917f687c0` (v1 composition) | `638f9f0ba21fb648c6f04d84960fed7d2e950654` (binding v2) |
| Producer | `tools/vision/dev/measure_evidence_real_clips.py --record-detections` | same |
| Host | Linux x86_64, CPython 3.12.14, `linux-x86_64-cpu`, CPU | same host and interpreter |
| Clips | MOT17-02-FRCNN, MOT17-13-FRCNN (1080p MJPEG; SHA-256 in each summary) | same bytes |

Files:

- `baseline-c176b048.summary.json` and `head.summary.json`: the producer's summaries. They contain no host paths.
- `artifact-hashes.json`: SHA-256 of each run's recorded detection streams and uncompressed evidence candidates. The 22 MB streams themselves are not committed.

**Result.** The results are identical:

- zero differences in the `s1_b1.normalized` sections;
- the detection streams and candidates are byte-identical.

The provenance differs only in the allow-listed component-identity keys, each changed to its reconciled value (`../2026-09-27-detector-identity-reconciliation.md`). Checked by `tools/qualification/tests/test_s2a_provenance_diff.py` (7 passed).

The head run is Development and unpacked (`runtimePackSource: unpacked-environment`, `runtimePackId: null`, `unverified`). It is behaviour evidence only, not qualification evidence.

The run was made at `638f9f0`. Later S2a.3 commits change documentation, tests, tools and the resolver's installed-pack check (`runtime_pack_not_running_environment`, which an unpacked run never reaches). None changes the detector, tracker, evidence or pipeline code path the run exercised, so the evidence stands for the final head.
