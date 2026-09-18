#!/usr/bin/env python3
"""Assemble complete Task-17 CCTV corpus qualification evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PHASE1_ROOT = Path(__file__).resolve().parent
if str(PHASE1_ROOT) not in sys.path:
    sys.path.insert(0, str(PHASE1_ROOT))

import evaluate_ground_truth as evaluator  # noqa: E402
import quality_corpus  # noqa: E402
from policy_identity import (  # noqa: E402
    PolicyIdentityError,
    canonical_acceptance_profile,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--mavi-build", required=True)
    parser.add_argument("--target-verified-manifest-sha256", required=True)
    parser.add_argument("--acceptance-profile", type=Path, required=True)
    parser.add_argument("--corpus-manifest", type=Path, required=True)
    parser.add_argument("--case-evidence", action="append", default=[])
    parser.add_argument("--ground-truth", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        if args.output.exists():
            raise quality_corpus.QualityCorpusError(
                "quality_corpus_output_exists"
            )
        canonical, profile_sha = canonical_acceptance_profile(
            args.acceptance_profile
        )
        profile = quality_corpus.load_json(
            canonical,
            "quality_acceptance_profile_invalid",
        )
        evaluator.validate_profile(profile)
        if profile.get("mode") != "qualification":
            raise quality_corpus.QualityCorpusError(
                "quality_acceptance_profile_not_qualification"
            )
        cases = quality_corpus.parse_named_paths(
            args.case_evidence,
            "quality_case_argument_invalid",
        )
        ground_truth = quality_corpus.parse_named_paths(
            args.ground_truth,
            "quality_ground_truth_argument_invalid",
        )
        value = quality_corpus.build_expected_evidence(
            source_commit=args.source_commit,
            mavi_build=args.mavi_build,
            target_verified_manifest_sha256=args.target_verified_manifest_sha256,
            acceptance_profile_sha256=profile_sha,
            corpus_manifest=args.corpus_manifest,
            profile=profile,
            case_evidence=cases,
            ground_truth=ground_truth,
        )
        quality_corpus.validate_schema(
            value,
            PHASE1_ROOT / "cctv-quality-corpus-evidence.schema.json",
            "quality_corpus_evidence",
        )
        args.output.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except (
        OSError,
        PolicyIdentityError,
        evaluator.EvaluationError,
        quality_corpus.QualityCorpusError,
    ) as exc:
        code = getattr(exc, "code", str(exc))
        print(json.dumps({"ok": False, "code": code}, sort_keys=True))
        return 2

    print(json.dumps({
        "ok": True,
        "passed": value["aggregate"]["qualification"]["passed"],
        "sha256": quality_corpus.sha256_file(args.output),
    }, sort_keys=True))
    return 0 if value["aggregate"]["qualification"]["passed"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
