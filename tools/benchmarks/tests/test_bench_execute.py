"""``execute``: one MAVI run per prepared sequence through the product API (S3.2d-1 plan §11 step 3).

Driven against the T9 stub API (loopback, never a real MAVI host) and a stub T1 export tool that seals one
trajectory per run, on a prepared directory built from the synthetic adapter's canonical ground truth.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tools.benchmarks import cli, prepare
from tools.benchmarks import execute as execution
from tools.benchmarks.core import descriptor as descriptors
from tools.benchmarks.core._stage3 import ROOT, artefacts
from tools.benchmarks.core.identity import S32Error, canonical_json, document_sha256, sha256_hex
from tools.benchmarks.datasets import synthetic

STAGE3_TESTS = ROOT / "tools" / "stage3" / "tests"
if str(STAGE3_TESTS) not in sys.path:
    sys.path.insert(0, str(STAGE3_TESTS))
import s32fixtures as s32  # noqa: E402
from t9_stub import StubApi  # noqa: E402

HERE = Path(__file__).resolve().parent


def prepared(root: Path) -> Path:
    """A prepared directory as ``prepare`` writes it (synthetic ground truth; stand-in video bytes)."""
    source = synthetic.write_source(root / "source")
    document = descriptors.freeze(synthetic.descriptor(), source)
    entries = descriptors.reconcile(document, source)
    adapter = synthetic.SyntheticAdapter()
    derived = root / "derived"
    rows = []
    for sequence in adapter.discover(source, entries, "val"):
        gt = adapter.ground_truth(source, entries, document, "val", sequence)
        directory = derived / "sequences" / sequence
        directory.mkdir(parents=True)
        (directory / prepare.GROUND_TRUTH).write_bytes(canonical_json(gt))
        video = f"derived video {sequence}".encode()
        (directory / prepare.VIDEO).write_bytes(video)
        rows.append({"sequenceId": sequence, "frameCount": len(gt["instants"]), "sourceFrames": [],
                     "derivedVideoSha256": sha256_hex(video), "derivedVideoSizeBytes": len(video),
                     "groundTruthSha256": document_sha256(gt)})
    manifest = {"kind": prepare.KIND, "descriptorSha256": sha256_hex(canonical_json(document)),
                "datasetId": document["datasetId"], "release": document["release"], "split": "val",
                "adapter": {"id": "synthetic", "version": "1"}, "sequences": rows}
    (derived / prepare.MANIFEST).write_bytes(canonical_json(manifest))
    return derived


class Bench:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.derived = prepared(root)
        self.profile = root / "profile.json"
        self.profile.write_bytes(json.dumps(s32.PROFILE).encode())
        self.exports, self.evidence = root / "exports", root / "evidence"
        self.exports.mkdir()
        self.evidence.mkdir()
        self.journal = root / "journal.json"
        self.api = StubApi(root / "stub")
        self.tamper = ""

    def command(self) -> list[str]:
        return [sys.executable, str(HERE / "bench_stub_export.py"), "--state",
                str(self.api.state.root / "export-state.json"), "--evidence", str(self.evidence),
                f"--tamper={self.tamper}"]

    def run(self, **over):
        values = dict(derived=self.derived, profile_path=self.profile, api_url=self.api.url,
                      journal_path=self.journal, export_root=self.exports, export_command=self.command(),
                      evidence_root=self.evidence, poll_seconds=0, timeout_seconds=30)
        values.update(over)
        return execution.execute(**values)


@pytest.fixture
def bench(tmp_path):
    b = Bench(tmp_path)
    yield b
    b.api.close()


def test_one_run_per_sequence_exported_and_verified(bench):
    rows = bench.run()
    manifest = json.loads((bench.derived / prepare.MANIFEST).read_bytes())
    assert [row["sequenceId"] for row in rows] == [row["sequenceId"] for row in manifest["sequences"]]
    assert len({row["processingRunId"] for row in rows}) == len(rows)
    for row in rows:
        assert (bench.exports / row["processingRunId"] / artefacts.EXPORT_FILE_NAME).is_file()
    assert sorted(c["code"] for c in bench.api.state.cameras) == ["BDD-SEQ-A", "BDD-SEQ-B"]
    imports = [call for call in bench.api.state.calls if call == ("POST", "/api/videos/import")]
    assert len(imports) == 2


def test_resume_from_the_journal_reimports_and_requeues_nothing(bench):
    first = bench.run()
    calls = len([c for c in bench.api.state.calls if c[0] == "POST"])
    assert bench.run() == first
    assert len([c for c in bench.api.state.calls if c[0] == "POST"]) == calls


def test_a_catalogue_that_is_not_fresh_is_refused(bench):
    bench.api.state.cameras.append({"id": "01a0ffb2-0000-7000-8000-00000000ffff", "code": "OLD", "name": "Old",
                                    "timeZoneId": "UTC"})
    with pytest.raises(S32Error, match="^t9_catalogue_not_fresh:cameras$"):
        bench.run()


def test_inputs_are_verified_before_any_api_call(bench):
    video = next((bench.derived / "sequences").iterdir()) / prepare.VIDEO
    original = video.read_bytes()
    video.write_bytes(original + b"x")
    with pytest.raises(S32Error, match="^derivation_invalid:video:"):
        bench.run()
    video.write_bytes(original)
    bench.profile.write_bytes(json.dumps({**s32.PROFILE, "profileVersion": "9.9.9"}).encode())
    with pytest.raises(S32Error, match="^t9_profile_not_s32:profileVersion$"):
        bench.run()
    bench.profile.write_bytes(json.dumps(s32.PROFILE).encode())
    with pytest.raises(S32Error, match="^t9_api_not_local$"):
        Bench.run(bench, api_url="http://example.com:5000")
    assert bench.api.state.calls == []


@pytest.mark.parametrize("tamper, code", [("source", "benchmark_export_mismatch:seq-a"),
                                          ("trajectory", "trajectory_missing")])
def test_exit_checks(bench, tamper, code):
    bench.tamper = tamper
    with pytest.raises(S32Error, match=f"^{code}"):
        bench.run()


def test_camera_codes_are_deterministic_and_within_the_limit():
    assert execution.camera_code("b1c66a42-6f7d68ca") == "BDD-B1C66A42-6F7D68CA"
    with pytest.raises(S32Error, match="^benchmark_camera_code_too_long:"):
        execution.camera_code("x" * 40)


def test_the_cli_prints_one_line_per_sequence(bench, capsys):
    code = cli.main(["execute", "--derived", str(bench.derived), "--pipeline-profile", str(bench.profile),
                     "--api", bench.api.url, "--journal", str(bench.journal), "--exports", str(bench.exports),
                     "--evidence-root", str(bench.evidence), "--export-exe", sys.executable,
                     *[f"--export-arg={arg}" for arg in bench.command()[1:]], "--poll-seconds", "0"])
    out = capsys.readouterr().out.split()
    assert code == 0 and out[0] == "seq-a" and out[3] == "seq-b"
