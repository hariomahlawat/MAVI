"""Task 10 MMCV wheel reuse: identity, provenance and fail-closed verification.

A restored wheel is installed only when it is provably the wheel Task 10 built
for exactly this build identity. These tests use synthetic wheels; they never
need PyTorch or a compiler.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import importlib.util
import json
import sys
import zipfile
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[3] / "tools" / "vision" / "mmcv_wheel_cache.py"


def _load():
    spec = importlib.util.spec_from_file_location("mmcv_wheel_cache", TOOL)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


cache = _load()

IDENTITY = {
    "schema": cache.IDENTITY_SCHEMA,
    "mmcvSourceCommit": "57c4e25e06e2d4f8a9357c84bcd24089a284dc88",
    "buildRecipe": "python -m pip wheel --no-build-isolation --no-deps -w ../.mmcv-wheel .|MMCV_WITH_OPS=1",
    "toolSha256": "0" * 64,
    "python": {"version": "3.12.10", "implementation": "CPython", "build": ["tags/v3.12.10", "Apr 8 2025"],
               "compiler": "MSC v.1943 64 bit (AMD64)", "soabi": "cp312-win_amd64", "cacheTag": "cpython-312"},
    "torch": {"version": "2.6.0+cpu", "gitVersion": "1eba9b3aa3c43f86f4a2c807ac8e12c4a7767340",
              "configSha256": "a" * 64, "cxx11Abi": False},
    "numpy": "2.5.3",
    "platform": {"system": "Windows", "machine": "AMD64", "sysconfigPlatform": "win-amd64", "runnerImage": "win25"},
    "toolchain": {"msvcToolsVersion": "14.44.35207", "windowsSdkVersion": "10.0.26100.0\\",
                  "vsCmdVersion": "17.14.0", "cl": "Microsoft (R) C/C++ Optimizing Compiler Version 19.44.35207 for x64"},
}
TAG = "cp312-cp312-win_amd64"


def _record_line(name: str, data: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
    return f"{name},sha256={digest},{len(data)}"


def make_wheel(directory: Path, *, version: str = "2.1.0", tag: str = TAG, tamper_member: bool = False) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    members = {
        "mmcv/__init__.py": b"__version__ = '2.1.0'\n",
        "mmcv/_ext.pyd": b"\x4d\x5a native ops",
        f"mmcv-{version}.dist-info/METADATA": f"Metadata-Version: 2.1\nName: mmcv\nVersion: {version}\n".encode(),
        f"mmcv-{version}.dist-info/WHEEL": f"Wheel-Version: 1.0\nRoot-Is-Purelib: false\nTag: {tag}\n".encode(),
    }
    record_name = f"mmcv-{version}.dist-info/RECORD"
    record = "\n".join([*(_record_line(n, d) for n, d in members.items()), f"{record_name},,"]) + "\n"
    if tamper_member:
        members["mmcv/_ext.pyd"] = b"\x4d\x5a substituted ops"
    path = directory / f"mmcv-{version}-{tag}.whl"
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
        archive.writestr(record_name, record)
    return path


def built(directory: Path, identity=IDENTITY, **wheel_kwargs) -> Path:
    make_wheel(directory, **wheel_kwargs)
    cache.record_provenance(directory, identity, {"runId": "1", "sourceSha": "b" * 40})
    return directory


def test_a_wheel_built_for_this_identity_verifies(tmp_path: Path) -> None:
    entry = built(tmp_path / "w")
    provenance = cache.verify(entry, IDENTITY)
    assert provenance["identitySha256"] == cache.identity_key(IDENTITY)
    wheel = next(entry.glob("*.whl"))
    assert cache.verify(entry, IDENTITY, expected_sha256=cache.sha256_file(wheel))


@pytest.mark.parametrize(
    "change",
    [
        lambda i: i.update(mmcvSourceCommit="f" * 40),
        lambda i: i.update(buildRecipe=i["buildRecipe"] + "|MMCV_WITH_OPS=0"),
        lambda i: i.update(toolSha256="1" * 64),
        lambda i: i["python"].update(version="3.12.11"),
        lambda i: i["torch"].update(version="2.6.1+cpu"),
        lambda i: i["torch"].update(configSha256="b" * 64),
        lambda i: i.update(numpy="2.5.4"),
        lambda i: i["platform"].update(runnerImage="win22"),
        lambda i: i["toolchain"].update(msvcToolsVersion="14.43.0"),
        lambda i: i["toolchain"].update(windowsSdkVersion="10.0.22621.0\\"),
    ],
)
def test_any_build_input_changes_the_key_and_refuses_reuse(tmp_path: Path, change) -> None:
    entry = built(tmp_path / "w")
    other = copy.deepcopy(IDENTITY)
    change(other)
    assert cache.identity_key(other) != cache.identity_key(IDENTITY)
    with pytest.raises(cache.IntegrityError, match="identity_mismatch"):
        cache.verify(entry, other)


def test_missing_or_unknown_provenance_is_unverifiable_and_rebuilt(tmp_path: Path) -> None:
    entry = tmp_path / "w"
    make_wheel(entry)
    with pytest.raises(cache.Unverifiable, match="provenance_missing"):
        cache.verify(entry, IDENTITY)
    (entry / cache.PROVENANCE_NAME).write_text("{not json", encoding="utf-8")
    with pytest.raises(cache.Unverifiable, match="provenance_unreadable"):
        cache.verify(entry, IDENTITY)
    (entry / cache.PROVENANCE_NAME).write_text(json.dumps({"schema": "other"}), encoding="utf-8")
    with pytest.raises(cache.Unverifiable, match="provenance_schema_unknown"):
        cache.verify(entry, IDENTITY)


def test_a_tampered_wheel_is_an_integrity_violation(tmp_path: Path) -> None:
    entry = built(tmp_path / "w")
    wheel = next(entry.glob("*.whl"))
    wheel.write_bytes(wheel.read_bytes() + b"\0")
    with pytest.raises(cache.IntegrityError, match="wheel_hash_mismatch"):
        cache.verify(entry, IDENTITY)


def test_a_rerecorded_wheel_whose_members_disagree_with_record_is_refused(tmp_path: Path) -> None:
    # Provenance re-written to match the substituted bytes still cannot hide a
    # native member that its own RECORD does not describe.
    entry = built(tmp_path / "w", tamper_member=True)
    with pytest.raises(cache.IntegrityError, match="wheel_record_inconsistent"):
        cache.verify(entry, IDENTITY)


def test_tampered_provenance_hash_is_refused(tmp_path: Path) -> None:
    entry = built(tmp_path / "w")
    provenance = json.loads((entry / cache.PROVENANCE_NAME).read_text(encoding="utf-8"))
    provenance["identitySha256"] = "0" * 64
    (entry / cache.PROVENANCE_NAME).write_text(json.dumps(provenance), encoding="utf-8")
    with pytest.raises(cache.IntegrityError, match="identity_hash_mismatch"):
        cache.verify(entry, IDENTITY)


def test_wrong_distribution_or_tag_is_refused(tmp_path: Path) -> None:
    with pytest.raises(cache.IntegrityError, match="wheel_distribution_unexpected"):
        cache.verify(built(tmp_path / "v", version="2.2.0"), IDENTITY)
    with pytest.raises(cache.IntegrityError, match="wheel_tag_unexpected"):
        cache.verify(built(tmp_path / "t", tag="cp312-cp312-linux_x86_64"), IDENTITY)


def test_a_wheel_other_than_the_producer_s_is_refused(tmp_path: Path) -> None:
    entry = built(tmp_path / "w")
    with pytest.raises(cache.IntegrityError, match="wheel_not_the_expected_artifact"):
        cache.verify(entry, IDENTITY, expected_sha256="0" * 64)


def test_an_ambiguous_entry_is_unverifiable(tmp_path: Path) -> None:
    entry = built(tmp_path / "w")
    make_wheel(entry, version="2.1.0", tag="cp312-cp312-win32")
    with pytest.raises(cache.Unverifiable, match="exactly one wheel"):
        cache.verify(entry, IDENTITY)


def test_the_cli_exit_codes_separate_rebuild_from_integrity_failure(tmp_path: Path) -> None:
    identity_file = tmp_path / "identity.json"
    identity_file.write_text(json.dumps(IDENTITY), encoding="utf-8")
    entry = built(tmp_path / "w")
    assert cache.main(["verify", "--dir", str(entry), "--identity", str(identity_file)]) == cache.EXIT_VERIFIED
    (entry / cache.PROVENANCE_NAME).unlink()
    assert cache.main(["verify", "--dir", str(entry), "--identity", str(identity_file)]) == cache.EXIT_UNVERIFIABLE
    tampered = built(tmp_path / "x")
    wheel = next(tampered.glob("*.whl"))
    wheel.write_bytes(wheel.read_bytes() + b"\0")
    assert cache.main(["verify", "--dir", str(tampered), "--identity", str(identity_file)]) == cache.EXIT_INTEGRITY


def test_the_expected_tag_follows_the_identity() -> None:
    assert cache.expected_wheel_tag(IDENTITY) == "cp312-cp312-win_amd64"
    linux = copy.deepcopy(IDENTITY)
    linux["python"]["version"] = "3.12.14"
    linux["platform"]["sysconfigPlatform"] = "linux-x86_64"
    assert cache.expected_wheel_tag(linux) == "cp312-cp312-linux_x86_64"


def test_a_same_size_substitution_is_an_integrity_violation(tmp_path: Path) -> None:
    entry = built(tmp_path / "w")
    wheel = next(entry.glob("*.whl"))
    data = bytearray(wheel.read_bytes())
    data[-1] ^= 0xFF
    wheel.write_bytes(bytes(data))
    with pytest.raises(cache.IntegrityError, match="wheel_hash_mismatch"):
        cache.verify(entry, IDENTITY)


def test_the_identity_covers_every_declared_build_input(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cache, "torch_identity", lambda: {"version": "torch-sentinel"})
    monkeypatch.setattr(cache, "toolchain_identity", lambda: {"cl": "toolchain-sentinel"})
    monkeypatch.setenv("ImageOS", "image-sentinel")
    identity = cache.environment_identity("c" * 40, "recipe-sentinel")
    assert identity["mmcvSourceCommit"] == "c" * 40
    assert identity["buildRecipe"] == "recipe-sentinel"
    assert identity["toolSha256"] == cache.sha256_file(TOOL)
    assert identity["torch"] == {"version": "torch-sentinel"}
    assert identity["toolchain"] == {"cl": "toolchain-sentinel"}
    assert identity["platform"]["runnerImage"] == "image-sentinel"
    assert {"version", "implementation", "build", "compiler", "soabi", "cacheTag"} <= set(identity["python"])
    assert identity["numpy"]
    assert identity["verifierSha256"] == cache.sha256_file(TOOL.parent / "compare_wheel_reproducibility.py")
    assert set(identity["buildTools"]) == {"setuptools", "wheel", "ninja", "pip"}


def test_build_environment_and_tool_versions_enter_the_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cache, "torch_identity", lambda: {})
    monkeypatch.setattr(cache, "toolchain_identity", lambda: {})
    for name in [n for n in __import__("os").environ if n in cache.BUILD_ENVIRONMENT or n.startswith("MMCV_")]:
        monkeypatch.delenv(name)
    monkeypatch.setenv("MAX_JOBS", "2")
    base = cache.environment_identity("c" * 40, "r")
    assert base["buildEnvironment"] == {}
    monkeypatch.setenv("MAX_JOBS", "1")  # parallelism only: same identity
    assert cache.identity_key(cache.environment_identity("c" * 40, "r")) == cache.identity_key(base)
    for name, value in (("CXXFLAGS", "-O0"), ("MMCV_WITH_OPS", "1"), ("DISTUTILS_USE_SDK", "1")):
        monkeypatch.setenv(name, value)
        changed = cache.environment_identity("c" * 40, "r")
        assert changed["buildEnvironment"][name] == value
        assert cache.identity_key(changed) != cache.identity_key(base)
        monkeypatch.delenv(name)
    monkeypatch.setattr(cache, "build_tools_identity", lambda: {"setuptools": "81.0.0"})
    assert cache.identity_key(cache.environment_identity("c" * 40, "r")) != cache.identity_key(base)


HEAD = "d" * 40
REPO = "owner/MAVI"


def _producer(**overrides):
    run = {"id": 7, "path": cache.TASK10_WORKFLOW_PATH, "event": "push", "head_branch": "main",
           "head_sha": "e" * 40, "repository": {"full_name": REPO}, "head_repository": {"full_name": REPO}}
    run.update(overrides)
    return run


def _attest(provenance, run, record, *, on_default=True):
    records = record if isinstance(record, list) else ([] if record is None else [record])
    return cache.attest(provenance, run, records, expected_head=HEAD, repository=REPO,
                        default_branch="main", variant="windows-x86_64-cpu",
                        producer_on_default_branch=on_default)


def _record_for(provenance, run, **overrides):
    record = {"state": "build", "runtimeVariant": "windows-x86_64-cpu", "headSha": run["head_sha"],
              "provenance": provenance}
    record.update(overrides)
    return record


def _provenance(tmp_path: Path):
    entry = built(tmp_path / "w")
    return json.loads((entry / cache.PROVENANCE_NAME).read_text(encoding="utf-8"))


def test_a_wheel_produced_on_the_default_branch_or_this_head_is_attested(tmp_path: Path) -> None:
    provenance = _provenance(tmp_path)
    for run, trust in ((_producer(), "default-branch"), (_producer(event="workflow_dispatch"), "default-branch"),
                       (_producer(event="pull_request", head_branch="feature", head_sha=HEAD), "same-head")):
        assert _attest(provenance, run, _record_for(provenance, run))["trust"] == trust


@pytest.mark.parametrize(
    "run",
    [
        None,
        # An earlier, unreviewed head of the same pull request.
        _producer(event="pull_request", head_branch="feature"),
        # A pull request from a branch merely named after the default branch.
        _producer(event="pull_request"),
        _producer(head_repository={"full_name": "fork/MAVI"}),
        _producer(repository={"full_name": "other/MAVI"}),
        _producer(head_branch="feature"),
        _producer(path=".github/workflows/other.yml"),
    ],
)
def test_an_untrusted_or_unknown_producer_is_unverifiable_and_rebuilt(tmp_path: Path, run) -> None:
    provenance = _provenance(tmp_path)
    record = _record_for(provenance, run or _producer())
    with pytest.raises(cache.Unverifiable):
        _attest(provenance, run, record)


def test_a_trusted_producer_without_its_record_is_unverifiable(tmp_path: Path) -> None:
    provenance = _provenance(tmp_path)
    with pytest.raises(cache.Unverifiable, match="producer_record_missing"):
        _attest(provenance, _producer(), None)


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (lambda r: r["provenance"]["wheel"].update(sha256="0" * 64), "producer_wheel_mismatch"),
        (lambda r: r["provenance"].update(identitySha256="0" * 64), "producer_identity_mismatch"),
        (lambda r: r.update(state="reuse"), "producer_did_not_build"),
        (lambda r: r.update(runtimeVariant="linux-x86_64-cpu"), "producer_variant_mismatch"),
        (lambda r: r.update(headSha="f" * 40), "producer_head_mismatch"),
    ],
)
def test_a_trusted_producer_that_disagrees_is_an_integrity_violation(tmp_path: Path, change, reason) -> None:
    provenance = _provenance(tmp_path)
    run = _producer()
    record = copy.deepcopy(_record_for(provenance, run))
    change(record)
    with pytest.raises(cache.IntegrityError, match=reason):
        _attest(provenance, run, record)


def test_a_default_branch_name_without_a_default_branch_commit_is_not_trusted(tmp_path: Path) -> None:
    # A tag literally named "main" reports head_branch == "main" too.
    provenance = _provenance(tmp_path)
    run = _producer(event="workflow_dispatch")
    with pytest.raises(cache.Unverifiable, match="producer_not_trusted"):
        _attest(provenance, run, _record_for(provenance, run), on_default=False)


def test_a_rerun_producer_with_several_records_is_attested_by_the_matching_build(tmp_path: Path) -> None:
    provenance = _provenance(tmp_path)
    run = _producer()
    reused = _record_for(provenance, run, state="reuse")
    built_record = _record_for(provenance, run)
    assert _attest(provenance, run, [reused, built_record])["trust"] == "default-branch"
    other = copy.deepcopy(built_record)
    other["provenance"]["wheel"]["sha256"] = "0" * 64
    with pytest.raises(cache.IntegrityError, match="producer_records_disagree"):
        _attest(provenance, run, [reused, other])


def test_the_torch_key_ignores_the_runner_cpu_but_not_the_build() -> None:
    # Measured: runs 36819776216 / 36820941092 had the same PyTorch wheel and
    # different runner CPUs, and their raw configs hashed differently.
    avx2 = "PyTorch built with:\n  - GCC 11.2\n  - CPU capability usage: AVX2\n  - Build settings: BLAS_INFO=mkl\n"
    avx512 = avx2.replace("AVX2", "AVX512")
    assert cache.torch_build_config(avx2) == cache.torch_build_config(avx512)
    assert cache.torch_build_config(avx2) != cache.torch_build_config(avx2.replace("GCC 11.2", "GCC 12.1"))
    assert "Build settings" in cache.torch_build_config(avx2)


def test_the_compiler_banner_is_read_from_stderr_when_asked() -> None:
    import sys as _sys

    command = [_sys.executable, "-c", "import sys; print('usage: cl'); print('Compiler 19.44', file=sys.stderr)"]
    assert cache._first_line(command, stderr_first=True) == "Compiler 19.44"
    assert cache._first_line(command) == "usage: cl"


def test_a_non_numeric_producer_run_is_never_fetched(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    monkeypatch.setenv("GITHUB_TOKEN", "unused")
    monkeypatch.setattr(cache, "_api", lambda *a: (_ for _ in ()).throw(AssertionError("fetched")))
    assert cache.fetch_producer("../../evil", "a", "main") == (None, [], False)
    assert cache.fetch_producer(None, "a", "main") == (None, [], False)


def _fake_github(monkeypatch: pytest.MonkeyPatch, run: dict, artifacts: list[tuple[str, dict | None]], status: str):
    import io as _io

    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    monkeypatch.setenv("GITHUB_TOKEN", "unused")
    archives = {}
    listing = []
    for index, (name, record) in enumerate(artifacts):
        buffer = _io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("junit/x.xml", "<x/>")
            if record is not None:
                archive.writestr(cache.WHEEL_RECORD_NAME, json.dumps(record))
        archives[f"https://dl/{index}"] = buffer.getvalue()
        listing.append({"name": name, "expired": False, "archive_download_url": f"https://dl/{index}"})
    calls = []

    def api(url, token):
        calls.append(url)
        if url in archives:
            return archives[url]
        if "/compare/" in url:
            return json.dumps({"status": status}).encode()
        if url.endswith("/artifacts?name=a&per_page=100"):
            return json.dumps({"artifacts": listing}).encode()
        return json.dumps(run).encode()

    monkeypatch.setattr(cache, "_api", api)
    return calls


def test_fetch_collects_every_attempt_s_record_and_branch_containment(monkeypatch: pytest.MonkeyPatch) -> None:
    run = _producer()
    calls = _fake_github(monkeypatch, run, [("a", {"state": "reuse"}), ("a", {"state": "build"}), ("b", {"state": "x"}),
                                            ("a", None)], "behind")
    fetched, records, on_default = cache.fetch_producer("7", "a", "main")
    assert fetched == run and on_default is True
    assert records == [{"state": "reuse"}, {"state": "build"}]
    assert any(f"/compare/main...{run['head_sha']}" in url for url in calls)
    for status, expected in (("identical", True), ("ahead", False), ("diverged", False)):
        _fake_github(monkeypatch, run, [], status)
        assert cache.fetch_producer("7", "a", "main")[2] is expected


def test_an_unreachable_producer_is_unverifiable(monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.error

    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    monkeypatch.setenv("GITHUB_TOKEN", "unused")

    def fail(*_):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(cache, "_api", fail)
    with pytest.raises(cache.Unverifiable, match="producer_unreachable"):
        cache.fetch_producer("7", "a", "main")


def test_the_token_is_not_forwarded_on_redirect() -> None:
    import urllib.request

    seen = {}

    class Capture(urllib.request.BaseHandler):
        def default_open(self, request):
            seen["redirected"] = request.headers
            seen["unredirected"] = request.unredirected_hdrs
            raise urllib.error.URLError("stop")

    import urllib.error

    opener = urllib.request.build_opener(Capture)
    original = urllib.request.urlopen
    urllib.request.urlopen = lambda request, timeout=None: opener.open(request, timeout=timeout)
    try:
        with pytest.raises(urllib.error.URLError):
            cache._api("https://api.example/x", "secret")
    finally:
        urllib.request.urlopen = original
    assert "Authorization" not in seen["redirected"]
    assert seen["unredirected"]["Authorization"] == "Bearer secret"


def test_torch_identity_keys_the_build_config_not_the_runner_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    import types

    def fake_torch(capability: str):
        module = types.ModuleType("torch")
        module.__version__ = "2.6.0+cpu"
        module.version = types.SimpleNamespace(git_version="g")
        module.__config__ = types.SimpleNamespace(show=lambda: f"PyTorch built with:\n  - CPU capability usage: {capability}\n")
        module._C = types.SimpleNamespace(_GLIBCXX_USE_CXX11_ABI=True)
        return module

    monkeypatch.setitem(sys.modules, "torch", fake_torch("AVX2"))
    avx2 = cache.torch_identity()
    monkeypatch.setitem(sys.modules, "torch", fake_torch("AVX512"))
    assert cache.torch_identity() == avx2
    assert avx2["configSha256"] == cache.sha256_bytes(b"PyTorch built with:")


def test_the_windows_toolchain_reads_the_cl_banner_from_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(cache.platform, "system", lambda: "Windows")
    monkeypatch.setattr(cache, "_first_line", lambda command, **kwargs: calls.append((command, kwargs)) or "banner")
    assert cache.toolchain_identity()["cl"] == "banner"
    assert calls == [(["cl"], {"stderr_first": True})]
