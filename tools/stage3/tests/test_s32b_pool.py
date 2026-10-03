"""S3.2b-1 T7: the frozen pilot source pool (``freeze_source_pool``); synthetic members and probes."""

from __future__ import annotations

import inspect
import json
import subprocess
from pathlib import Path

import pytest

import artefacts as a
import freeze_source_pool as fp
import s32b_fixtures as f
import s32fixtures as s32


class Pool:
    def __init__(self, root: Path, count: int = 7, det=..., excluded=()) -> None:
        self.root = root
        self.members = {f"cams/c{i % 3}/clip-{i:02d}.mp4": f"synthetic member {i}".encode() * 3 for i in range(count)}
        self.store = f.write_store(root / "store", self.members)
        self.document = f.release_document(self.members, det=det, excluded=excluded)
        self.release = f.write_release(root / "release.json", self.document)
        self.probes = {}
        for path, data in self.members.items():
            probe = root / "probes" / (a.sha256_hex(data) + ".json")
            probe.parent.mkdir(exist_ok=True)
            probe.write_bytes(a.canonical_json(s32.probe_record(data)))
            self.probes[path] = probe
        self.entries = [{"member": path, "sourceCamera": path.split("/")[1], "inclusionReason": "camera diversity"}
                        for path in self.members]

    def selection(self, entries=None) -> Path:
        path = self.root / f"selection-{len(list(self.root.glob('selection-*')))}.json"
        path.write_bytes(json.dumps({"members": self.entries if entries is None else entries}).encode())
        return path

    def freeze(self, entries=None, probes=None, release_root=None) -> bytes:
        return fp.freeze(release_path=self.release, release_root=release_root or self.store,
                         probe_paths=list(self.probes.values()) if probes is None else probes,
                         selection_path=self.selection(entries))


def refused(code, call):
    with pytest.raises(a.S32Error) as raised:
        call()
    assert str(raised.value).startswith(code), str(raised.value)


def test_a_valid_pool_is_schema_valid_sorted_and_deterministic(tmp_path):
    pool = Pool(tmp_path)
    data = pool.freeze()
    assert data == pool.freeze(entries=list(reversed(pool.entries)))
    document = json.loads(data)
    a.validate(document, "vehicle-subclass-source-pool-v1", "unexpected")
    assert document["kind"] == "pilot" and document["selectionProcedure"] == {"id": "s3-2-source-pool-manual-v1"}
    assert document["releaseRecordSha256"] == f.release_sha256(pool.document)
    assert [m["member"] for m in document["members"]] == sorted(pool.members)
    first = document["members"][0]
    assert first["sha256"] == a.sha256_hex(pool.members[first["member"]])
    assert first["probeSha256"] == a.sha256_hex(pool.probes[first["member"]].read_bytes())
    assert str(tmp_path) not in data.decode() and str(tmp_path.as_posix()) not in data.decode()


@pytest.mark.parametrize("count, ok", [(5, False), (6, True), (10, True), (11, False)])
def test_pilot_member_count(tmp_path, count, ok):
    pool = Pool(tmp_path, count=count)
    if ok:
        pool.freeze()
    else:
        refused("source_pool_invalid:member_count", pool.freeze)


def test_release_failures(tmp_path):
    pool = Pool(tmp_path)
    (pool.store / next(iter(pool.members))).write_bytes(b"changed")
    refused("source_pool_invalid:release_files", pool.freeze)
    repository = tmp_path / "repo"
    repository.mkdir()
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    inside = Pool(repository)
    refused("source_pool_invalid:release_root", inside.freeze)
    pool.release.write_bytes(b"{}")
    refused("source_pool_invalid:release", pool.freeze)


def test_member_failures(tmp_path):
    pool = Pool(tmp_path)
    refused("source_pool_invalid:member_not_listed",
            lambda: pool.freeze([*pool.entries[:-1], {**pool.entries[-1], "member": "cams/none.mp4"}]))
    refused("source_pool_invalid:duplicate_member", lambda: pool.freeze([*pool.entries[:-1], pool.entries[0]]))
    refused("source_pool_invalid:selection_entry", lambda: pool.freeze([*pool.entries[:-1],
                                                                         {**pool.entries[-1], "exportSha256": "0" * 64}]))


def test_an_excluded_member_is_refused(tmp_path):
    pool = Pool(tmp_path, count=8)
    excluded = Pool(tmp_path / "ex", count=8, excluded=(next(iter(pool.members)),))
    refused("source_pool_invalid:member_excluded", excluded.freeze)


def test_identical_content_under_two_names_is_refused(tmp_path):
    pool = Pool(tmp_path)
    names = list(pool.members)
    pool.members[names[1]] = pool.members[names[0]]
    pool.store = f.write_store(tmp_path / "store2", pool.members)
    pool.document = f.release_document(pool.members)
    pool.release = f.write_release(tmp_path / "release2.json", pool.document)
    pool.probes.pop(names[1])
    refused("source_pool_invalid:duplicate_content", pool.freeze)


def test_probe_failures(tmp_path):
    pool = Pool(tmp_path)
    names = list(pool.members)
    other = tmp_path / "other-probe.json"
    other.write_bytes(a.canonical_json(s32.probe_record(b"not a member")))
    refused("source_pool_invalid:probe_unmatched", lambda: pool.freeze(probes=[*pool.probes.values(), other]))
    refused("source_pool_invalid:probe_missing", lambda: pool.freeze(probes=list(pool.probes.values())[1:]))
    bad = json.loads(pool.probes[names[0]].read_bytes())
    bad["sourceSizeBytes"] += 1
    pool.probes[names[0]].write_bytes(a.canonical_json(bad))
    refused("source_pool_invalid:probe_mismatch", pool.freeze)
    pool.probes[names[0]].write_bytes(json.dumps(s32.probe_record(pool.members[names[0]]), indent=1).encode())
    refused("source_pool_invalid:probe:not_canonical", pool.freeze)
    pool.probes[names[0]].write_bytes(a.canonical_json({"schemaVersion": "vehicle-subclass-media-probe-v1"}))
    refused("source_pool_invalid:probe:schema", pool.freeze)


@pytest.mark.parametrize("det, code", [
    (None, "source_pool_invalid:not_authorised:determination-missing"),
    (f.determination(purposes=["development"]), "source_pool_invalid:not_authorised"),
])
def test_authorisation_blockers_are_refused(tmp_path, det, code):
    refused(code, Pool(tmp_path, det=det).freeze)


def test_selection_needs_no_derivation_right(tmp_path):
    det = f.determination(inventory={**f.INVENTORY_ALL, "create-derivatives": "not-granted"})
    Pool(tmp_path, det=det).freeze()


@pytest.mark.parametrize("reason", ["", " padded", "two\nlines", "x" * 201, "see C:\\Users\\someone\\clip.mp4",
                                    "from /home/someone/clips"])
def test_inclusion_reason_free_text_rules(tmp_path, reason):
    pool = Pool(tmp_path)
    refused("source_pool_invalid:inclusion_reason",
            lambda: pool.freeze([*pool.entries[:-1], {**pool.entries[-1], "inclusionReason": reason}]))


def test_no_mavi_output_option_exists():
    """Blindness: the tool cannot be given an export, attestation, label, sample or measurement."""
    options = {action.dest for action in fp.parser()._actions}
    assert options == {"help", "release", "release_root", "probe", "selection", "out"}
    assert set(inspect.signature(fp.freeze).parameters) == {"release_path", "release_root", "probe_paths",
                                                            "selection_path"}
    source = Path(fp.__file__).read_text(encoding="utf-8")
    for forbidden in ("load_exports", "Export(", "export-v1", "track-labels-v1", "sample-v1", "measurement-v1"):
        assert forbidden not in source


def test_cli_writes_once(tmp_path, capsys):
    pool = Pool(tmp_path)
    out = tmp_path / "pool.json"
    args = ["--release", str(pool.release), "--release-root", str(pool.store), "--selection", str(pool.selection()),
            "--out", str(out), *[x for p in pool.probes.values() for x in ("--probe", str(p))]]
    assert fp.main(args) == 0
    assert capsys.readouterr().out.strip() == a.sha256_hex(out.read_bytes())
    assert fp.main(args) == 2 and "refused output_exists" in capsys.readouterr().err
