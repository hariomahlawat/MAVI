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
