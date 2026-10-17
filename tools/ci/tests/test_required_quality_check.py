"""The required status check M3 verifies (IP-5 Q1) must keep meaning "repository verification passed".

M3's ruleset predicate (``m3_authority.verify_default_branch_protection``) requires the status check ``quality`` of
integration 15368 (GitHub Actions) under the strict policy. That is only worth requiring while the ``quality`` job
needs ``repo-contracts`` (which runs ``tools/verify_repo.py``) and fails unless it succeeded. This is the CI-side
regression of plan rev 4 RQ1; the ``selection_verify`` repository check of the same relationship
(``repo_contracts_not_required_by_quality``) ships with IP-2.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = (ROOT / ".github/workflows/quality-gate.yml").read_text(encoding="utf-8")


def job_block(name: str) -> str:
    match = re.search(rf"^  {re.escape(name)}:\n(?P<body>(?:^(?:    .*|\s*)\n)*)", WORKFLOW, re.MULTILINE)
    assert match, name
    return match.group("body")


def test_m3_requires_the_quality_check_of_github_actions():
    sys.path.insert(0, str(ROOT / "tools" / "qualification"))
    from model_selection import m3_authority as ma
    assert ma.REQUIRED_STATUS_CHECK == {"context": "quality", "integration_id": 15368}
    assert ma.ALLOWED_MERGE_METHODS == ["merge"]


def test_the_quality_job_needs_and_requires_repo_contracts():
    quality = job_block("quality")
    assert re.search(r"^    name: quality$", quality, re.MULTILINE)
    assert re.search(r"^    if: always\(\)$", quality, re.MULTILINE)
    needs = re.search(r"^    needs:\n(?P<items>(?:^      - .*\n)+)", quality, re.MULTILINE)
    assert needs and "      - repo-contracts\n" in needs.group("items")
    assert "require repo-contracts '${{ needs.repo-contracts.result }}' true" in quality
    assert "test '${{ needs.scope.result }}' = 'success'" in quality


def test_repo_contracts_runs_repository_verification():
    contracts = job_block("repo-contracts")
    assert re.search(r"^\s+run: python tools/verify_repo\.py$", contracts, re.MULTILINE)
    assert "if:" not in contracts.split("steps:")[0]  # always applicable: never skipped by the scope decision
