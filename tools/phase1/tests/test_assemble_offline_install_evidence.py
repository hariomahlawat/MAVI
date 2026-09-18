from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "assemble_offline_install_evidence.py"
SPEC = importlib.util.spec_from_file_location("offline_assembler", MODULE_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def variant(name: str, commit: str) -> dict:
    return {
        "schemaVersion": "mavi-offline-variant-evidence-v1",
        "sourceCommit": commit,
        "targetVerifiedManifestSha256": "e" * 64,
        "acceptanceProfileSha256": "d" * 64,
        "maviBuild": "build-a",
        "variant": name,
        "bundleMode": "qualification-candidate",
        "bundleManifestSha256": "a" * 64,
        "releaseLockSha256": "b" * 64,
        "expectedHostCompatibility": {"osFamily": name.split("-")[0]},
        "observedHostCompatibility": {"osFamily": name.split("-")[0]},
        "installCommand": "pip --no-index --only-binary=:all: --require-hashes --find-links wheels",
        "installExitCode": 0,
        "pipCheckPassed": True,
        "runtimeStarted": True,
        "realInferencePassed": True,
        "workerFlowPassed": True,
        "workerFlowEvidenceSha256": "f" * 64,
        "workerPythonSha256": "1" * 64,
        "workerEnvironmentSha256": "4" * 64,
        "workerVenvRootSha256": "5" * 64,
        "workerResolvedPythonSha256": "6" * 64,
        "hostIdentitySha256": "7" * 64,
        "workerCommandSha256": "2" * 64,
        "workerLogSha256": "3" * 64,
        "actualDevice": "cuda:0" if name.endswith("cuda") else "cpu",
        "outboundNetworkUnavailable": True,
        "networkIsolation": {
            "proxyEnvironmentAbsent": True,
            "probes": [{"host": f"h{i}", "port": 443, "reachable": False} for i in range(5)],
            "passed": True,
        },
        "firstRunDownloadObserved": False,
        "result": "passed",
    }


def test_load_hashes_exact_bytes(tmp_path: Path):
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(variant("linux-x86_64-cpu", "a" * 40)), encoding="utf-8")
    value, digest = mod.load(path)
    assert value["variant"] == "linux-x86_64-cpu"
    assert len(digest) == 64


def test_variant_evidence_hash_is_profile_scoped(tmp_path: Path, monkeypatch):
    cuda = tmp_path / "cuda.json"
    output = tmp_path / "offline.json"
    cuda.write_text(
        json.dumps(variant("linux-x86_64-cuda", "a" * 40)),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(MODULE_PATH),
            "--deployment-profile",
            "P2",
            "--variant",
            str(cuda),
            "--isolation-method",
            "air-gapped",
            "--output",
            str(output),
        ],
    )
    assert mod.main() == 0
    value = json.loads(output.read_text(encoding="utf-8"))
    assert value["schemaVersion"] == "mavi-offline-install-evidence-v2"
    assert value["deploymentProfile"] == "P2"
    assert value["os"] == "linux"
    assert value["variantEvidenceSha256"] == {
        "linux-x86_64-cuda": __import__("hashlib").sha256(
            cuda.read_bytes()
        ).hexdigest()
    }
    assert len(value["variants"]) == 1


def test_profile_rejects_wrong_runtime_variant(tmp_path: Path):
    cpu = tmp_path / "cpu.json"
    cpu.write_text(
        json.dumps(variant("linux-x86_64-cpu", "a" * 40)),
        encoding="utf-8",
    )
    args = __import__("argparse").Namespace(
        deployment_profile="P2",
        deployment_profile_policy=mod.deployment_profiles.CANONICAL_DEPLOYMENT_PROFILES,
        variant=cpu,
        isolation_method="air-gapped",
    )
    with __import__("pytest").raises(
        mod.AssembleError,
        match="offline_variant_not_passed",
    ):
        mod.assemble(args)
