"""Regression coverage for B0 offline source-integrity verification."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from attributes.corpus.canonical import canonical_json, sha256_hex
from source_acquisition import acquire as acq


def test_verify_rechecks_provider_sha1(tmp_path: Path) -> None:
    store = tmp_path / "controlled-store"
    media = store / "media" / "commons" / "1" / "provider-sha1" / "sample.webm"
    media.parent.mkdir(parents=True)
    payload = b"mavi-source-integrity-fixture"
    media.write_bytes(payload)

    receipt = {
        "fileTitle": "File:sample.webm",
        "acquisition": {
            "storeRelativePath": media.relative_to(store).as_posix(),
            "byteSize": len(payload),
            "sha1": "0" * 40,
            "sha256": hashlib.sha256(payload).hexdigest(),
        },
    }
    blob = canonical_json(receipt)
    receipts = store / "receipts"
    receipts.mkdir()
    (receipts / f"{sha256_hex(blob)}.json").write_bytes(blob)

    problems = acq.verify(store)

    assert any("SHA-1" in problem for problem in problems), problems
