"""The existing public-dataset release machinery, used as is by the S3.2b tools.

S3.2b creates no second rights or provenance model: release records are
``mavi-attribute-dataset-release-v1`` and are read, verified and authorised only through
``tools/qualification/attributes/datasets/release.py``. This module only makes that
package importable from ``tools/stage3`` and maps its exceptions to S3.2 refusal codes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

QUALIFICATION = Path(__file__).resolve().parents[1] / "qualification"
if str(QUALIFICATION) not in sys.path:
    sys.path.insert(0, str(QUALIFICATION))

from attributes.corpus.canonical import CorpusError, require_free_text  # noqa: E402
from attributes.datasets import release as release_module  # noqa: E402
from source_acquisition.acquire import git_worktree_ancestor  # noqa: E402,F401
from source_acquisition.admission import refuse_local_paths  # noqa: E402

import artefacts as a  # noqa: E402

PURPOSES = ["benchmarking", "development"]
RELEASE_ERRORS = (CorpusError, release_module.ReleaseError, ValueError, TypeError, KeyError)


def read_release(path: Path, code: str) -> tuple[dict[str, Any], str]:
    """A parsed release record and its canonical identity (``release_sha256``)."""
    try:
        document = json.loads(Path(path).read_bytes().decode("utf-8"))
        release = release_module.parse_release(document)
        return release, release_module.release_sha256(release)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise a.S32Error(f"{code}:unreadable") from exc
    except RELEASE_ERRORS as exc:
        raise a.S32Error(f"{code}:{exc}") from exc


def verify_store(release: dict[str, Any], root: Path, root_code: str, files_code: str) -> None:
    """``verify_release_files``: a store inside a Git worktree, or any problem, refuses."""
    try:
        problems = release_module.verify_release_files(release, Path(root))
    except release_module.ReleaseError as exc:
        # The bare code: the verifier's message names the local worktree path.
        raise a.S32Error(root_code) from exc
    a.require(not problems, f"{files_code}:{len(problems)}")


def member_entry(release: dict[str, Any], member: str, listed_code: str, excluded_code: str) -> dict[str, Any]:
    entries = [entry for entry in release["files"] if entry["path"] == member]
    a.require(len(entries) == 1, listed_code)
    a.require(member not in {entry["path"] for entry in release["excludedMembers"]}, excluded_code)
    return entries[0]


def authorise(release: dict[str, Any], member: str, operations: list[str]) -> list[str]:
    """Member-scoped use authorisation; T8 and the pool tool only consume R-5's determination."""
    try:
        return release_module.authorise_release_use(release, PURPOSES, operations=operations, member=member)
    except RELEASE_ERRORS as exc:
        return [f"authorisation-refused:{exc}"]


def free_text(value: object, code: str, maximum: int) -> str:
    """The repository's free-text and local-path checks, plus one line and a length bound."""
    text = a.text_value(value, code, maximum)
    try:
        require_free_text(text, code, maximum)
        refuse_local_paths(text)
    except (CorpusError, ValueError) as exc:
        raise a.S32Error(f"{code}:path_like") from exc
    return text
