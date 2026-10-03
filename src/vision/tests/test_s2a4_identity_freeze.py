"""S2a.4 changes Setup, not components: the identities it consumes are those S2a.3 froze.

Values from docs/qualification/stage2-s2a/2026-09-27-detector-identity-reconciliation.md.
S2a.4 plan §8 test 12; parent plan §20.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[3]

# Re-issued deliberately by Stage 3 (ADR-016), and only for these two files: the binding
# now declares completion 3.3 (was 081c0c89...), and the qualification record binds the
# 1.3.0-candidate pipeline profile (was 100b8f10...). The manifest and the runtime profile
# are unchanged, and so are the Model Pack and Runtime Pack ids below.
FROZEN_SHA256 = {
    "src/vision/config/components/phase1-bindings-v2.json": "7ef226193232b90b0a20f8648a95f21e0bbc9416b353605c9be6d81262abe205",
    "models/manifests/rtmdet-m-coco-phase1-v2.json": "bc8127c1c00513a90f1b00325dcae3d4f31243ef1ce04ebe38350f945cb79c90",
    "models/qualifications/rtmdet-m-coco-phase1-v2.json": "2c2ba3d674cebf18955af1b224ef41c8c1a1fbc189cc28a6d605436c46c2a224",
    "src/vision/runtime/mmdetection-phase1-v1/runtime.json": "296b034d5f80ee13ab3f3bf86ed41b84109abd47d0103600b15b24078412acfb",
}
MODEL_PACK_ID = "mavi-model-v2-86754e364c7560c407b531900de58eb5e66fd365685677f8f24a5a61b3186700"
RUNTIME_PACK_IDS = {
    "linux-x86_64-cpu": "mavi-runtime-v2-bd94fded938183dce8dc50390d48e97d913d9dad9dc98b528a962ad32314ff61",
    "windows-x86_64-cpu": "mavi-runtime-v2-5d6229da58554bc951ddc8bd719574c1b33109a7916afdf717339d8847e39e61",
    "windows-x86_64-cuda": "mavi-runtime-v2-89fd8bfcc32fb1bd8ab77f0deb9f33675ae228c75ffd11f13e6838e990003a1d",
}


@pytest.mark.parametrize("relative", sorted(FROZEN_SHA256))
def test_the_identities_s2a4_consumes_are_frozen(relative: str) -> None:
    assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == FROZEN_SHA256[relative]


def test_the_bound_pack_ids_and_qualification_state_are_unchanged() -> None:
    binding = json.loads((ROOT / "src/vision/config/components/phase1-bindings-v2.json").read_text(encoding="utf-8"))
    assert [item["modelPackId"] for item in binding["capabilityBindings"]] == [MODEL_PACK_ID]
    assert {name: entry["runtimePackId"] for name, entry in binding["runtimePacks"][0]["variants"].items()} == RUNTIME_PACK_IDS
    manifest = json.loads((ROOT / "models/manifests/rtmdet-m-coco-phase1-v2.json").read_text(encoding="utf-8"))
    assert manifest["verificationStatus"] == "unverified" and manifest["qualificationId"] is None
    record = json.loads((ROOT / "models/qualifications/rtmdet-m-coco-phase1-v2.json").read_text(encoding="utf-8"))
    assert record["overallResult"] == "pending"
    assert all(variant["status"] == "pending" for variant in record["variants"].values())
