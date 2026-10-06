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
        self.attest: dict[str, str] | None = None  # the worker's attested binding and Model Pack (A2 runs)

    def command(self) -> list[str]:
        command = [sys.executable, str(HERE / "bench_stub_export.py"), "--state",
                   str(self.api.state.root / "export-state.json"), "--evidence", str(self.evidence),
                   f"--tamper={self.tamper}"]
        if self.attest is not None:
            command += ["--attest-binding", self.attest["binding"], "--attest-pack", self.attest["pack"]]
        return command

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


def test_a_malformed_derivation_manifest_is_a_refusal_not_a_traceback(bench, capsys):
    path = bench.derived / prepare.MANIFEST
    manifest = json.loads(path.read_bytes())
    del manifest["sequences"][0]["sequenceId"]
    path.write_bytes(canonical_json(manifest))
    with pytest.raises(S32Error, match="^benchmark_input_invalid:KeyError$"):
        bench.run()
    code = cli.main(["execute", "--derived", str(bench.derived), "--pipeline-profile", str(bench.profile),
                     "--api", bench.api.url, "--journal", str(bench.journal), "--exports", str(bench.exports),
                     "--evidence-root", str(bench.evidence), "--export-exe", sys.executable])
    assert code == 2 and "refused benchmark_input_invalid:KeyError" in capsys.readouterr().err
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


# --------------------------------------------------------------------------- Development producers (H4)

import shutil  # noqa: E402
import subprocess  # noqa: E402

from tools.benchmarks.core import producer as producers  # noqa: E402

A2_PROFILE = ROOT / "src" / "vision" / "config" / "pipelines" / "phase1-detection-tracking-a2-v1.json"
IDENTITY = {name: producers.producer_identity(name) for name in ("a2-scale640", "a2-scale1280")}


def a2(bench, requested, attested):
    """An A2 run that asks for ``requested`` while the (stub) worker attests ``attested``."""
    bench.profile.write_bytes(A2_PROFILE.read_bytes())
    identity = IDENTITY[attested]
    bench.attest = {"binding": identity["componentBindingSha256"], "pack": identity["modelPackId"]}
    return bench.run(development_producer=requested)


def exported(bench):
    return sorted(path.name for path in bench.exports.iterdir())


@pytest.mark.parametrize("name", ["a2-scale640", "a2-scale1280"])
def test_the_requested_producer_attested_passes_and_is_bound_and_reported(bench, name):
    rows = a2(bench, name, name)
    assert rows and all(row["developmentProducerId"] == name for row in rows)
    journal = json.loads(bench.journal.read_bytes())
    assert journal["developmentProducer"] == producers.journal_identity(IDENTITY[name])


@pytest.mark.parametrize(("requested", "attested"), [("a2-scale1280", "a2-scale640"), ("a2-scale640", "a2-scale1280")])
def test_another_producer_attested_fails_at_the_first_export(bench, requested, attested):
    with pytest.raises(S32Error, match="^benchmark_producer_mismatch:componentBindingSha256$"):
        a2(bench, requested, attested)
    assert len(exported(bench)) == 1  # refused after the first run, not after the whole domain


@pytest.mark.parametrize(("first", "second"), [("a2-scale640", "a2-scale1280"), ("a2-scale1280", "a2-scale640")])
def test_a_journal_for_one_producer_cannot_resume_as_the_other(bench, first, second):
    a2(bench, first, first)
    calls = len(bench.api.state.calls)
    # Same journal, same catalogue, same benchmark inputs and profile; the other producer requested and attested.
    with pytest.raises(S32Error, match="^benchmark_journal_producer_mismatch$"):
        a2(bench, second, second)
    assert len(bench.api.state.calls) == calls  # refused before any API call
    assert json.loads(bench.journal.read_bytes())["developmentProducer"]["producerId"] == first


def test_the_same_producer_resumes_from_its_own_journal(bench):
    first = a2(bench, "a2-scale1280", "a2-scale1280")
    posts = len([call for call in bench.api.state.calls if call[0] == "POST"])
    assert a2(bench, "a2-scale1280", "a2-scale1280") == first
    assert len([call for call in bench.api.state.calls if call[0] == "POST"]) == posts


def test_s32_execution_is_unchanged(bench):
    rows = bench.run()
    assert all(set(row) == {"sequenceId", "videoAssetId", "processingRunId", "exportSha256"} for row in rows)
    assert "developmentProducer" not in json.loads(bench.journal.read_bytes())
    with pytest.raises(S32Error, match="^benchmark_development_producer_forbidden$"):
        bench.run(development_producer="a2-scale640")


def test_an_s32_journal_cannot_resume_as_a_development_producer(bench):
    bench.run()
    with pytest.raises(S32Error, match="^benchmark_journal_producer_mismatch$"):
        a2(bench, "a2-scale640", "a2-scale640")


def test_an_a2_run_requires_a_producer_and_a_known_one(bench):
    bench.profile.write_bytes(A2_PROFILE.read_bytes())
    with pytest.raises(S32Error, match="^benchmark_development_producer_required$"):
        bench.run()
    with pytest.raises(S32Error, match="^benchmark_development_producer_unknown:a2-scale999$"):
        bench.run(development_producer="a2-scale999")
    assert bench.api.state.calls == [] and not bench.journal.exists()


def test_the_cli_names_the_development_producer(bench, capsys):
    bench.profile.write_bytes(A2_PROFILE.read_bytes())
    identity = IDENTITY["a2-scale640"]
    bench.attest = {"binding": identity["componentBindingSha256"], "pack": identity["modelPackId"]}
    code = cli.main(["execute", "--derived", str(bench.derived), "--pipeline-profile", str(bench.profile),
                     "--api", bench.api.url, "--journal", str(bench.journal), "--exports", str(bench.exports),
                     "--evidence-root", str(bench.evidence), "--export-exe", sys.executable,
                     *[f"--export-arg={arg}" for arg in bench.command()[1:]], "--poll-seconds", "0",
                     "--development-producer", "a2-scale640"])
    out = capsys.readouterr().out.split()
    assert code == 0 and out[:2] == ["developmentProducer", "a2-scale640"]


def test_the_s32_measurement_profile_still_passes_and_its_refusals_are_unchanged():
    assert execution.require_benchmark_profile(json.dumps(s32.PROFILE).encode()) is None
    with pytest.raises(S32Error, match="^t9_profile_not_s32:profileVersion$"):
        execution.require_benchmark_profile(json.dumps({**s32.PROFILE, "profileVersion": "9.9.9"}).encode())


def test_the_tracked_a2_profile_resolves_to_the_requested_frozen_producer():
    for name, identity in IDENTITY.items():
        assert execution.require_benchmark_profile(A2_PROFILE.read_bytes(), name) == identity
    assert IDENTITY["a2-scale640"]["pipelineProfileSha256"] == IDENTITY["a2-scale1280"]["pipelineProfileSha256"]
    assert IDENTITY["a2-scale640"]["componentBindingSha256"] != IDENTITY["a2-scale1280"]["componentBindingSha256"]
    assert IDENTITY["a2-scale640"]["modelPackId"] != IDENTITY["a2-scale1280"]["modelPackId"]


@pytest.mark.parametrize(
    ("key", "value"),
    [("schemaVersion", "1.2"), ("profileVersion", "1.0.1-development"), ("developmentOnly", False),
     ("developmentOnly", "true")],
)
def test_an_a2_profile_with_another_identity_is_refused(key, value):
    document = json.loads(A2_PROFILE.read_bytes())
    document[key] = value
    with pytest.raises(S32Error, match=f"^benchmark_profile_not_development_a2:{key}$"):
        execution.require_benchmark_profile(json.dumps(document).encode(), "a2-scale640")


def test_an_a2_profile_with_another_subclass_vocabulary_is_refused():
    document = json.loads(A2_PROFILE.read_bytes())
    document["vehicleSubclass"]["vocabularyId"] = "other-vocabulary"
    with pytest.raises(S32Error, match="^benchmark_profile_not_development_a2:vehicleSubclass$"):
        execution.require_benchmark_profile(json.dumps(document).encode(), "a2-scale640")


def test_an_altered_a2_profile_with_the_same_identity_is_refused():
    document = json.loads(A2_PROFILE.read_bytes())
    document["tracker"]["trackActivationThreshold"] = 0.62
    with pytest.raises(S32Error, match="^benchmark_profile_not_tracked_a2$"):
        execution.require_benchmark_profile(json.dumps(document).encode(), "a2-scale1280")


# --------------------------------------------------------------------------- frozen producer definition

FROZEN = (
    "src/vision/config/development-producers-v1.json",
    "src/vision/config/components/development-phase1-a2-scale640-v1.json",
    "src/vision/config/components/development-phase1-a2-scale1280-v1.json",
    "src/vision/config/pipelines/phase1-detection-tracking-a2-v1.json",
)


def _git(repo, *args):
    result = subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                             "-c", "core.autocrlf=false", *args], capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    return result


@pytest.fixture
def frozen_repo(tmp_path):
    """A repository holding exactly the committed producer definition."""
    repo = tmp_path / "repo"
    for path in FROZEN:
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, repo / path)
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "producer definition")
    return repo


def test_the_identity_is_read_from_the_committed_definition(frozen_repo):
    for name, expected in IDENTITY.items():
        identity = producers.producer_identity(name, frozen_repo)
        assert producers.journal_identity(identity) == producers.journal_identity(expected)
        assert identity["producerIdentitySha256"] == expected["producerIdentitySha256"]


@pytest.mark.parametrize("path", [FROZEN[0], FROZEN[2], FROZEN[3]], ids=["registry", "binding", "a2-profile"])
def test_a_dirty_producer_definition_is_refused(frozen_repo, path):
    target = frozen_repo / path
    data = target.read_bytes()
    assert data.endswith(b"}\n")
    target.write_bytes(data[:-2] + b" }\n")
    with pytest.raises(S32Error, match=f"^benchmark_producer_dirty:{path}$"):
        producers.producer_identity("a2-scale1280", frozen_repo)


def test_an_uncommitted_producer_definition_is_refused(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README").write_bytes(b"x\n")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "no producer definition")
    for path in FROZEN:
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, repo / path)
    with pytest.raises(S32Error, match=f"^benchmark_producer_dirty:{FROZEN[0]}$"):
        producers.producer_identity("a2-scale640", repo)
