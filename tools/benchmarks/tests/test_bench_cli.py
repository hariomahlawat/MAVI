"""``tools.benchmarks.cli describe`` (S3.2d-1 slice 1): refusal codes, exit status, write-once freeze."""

from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

from tools.benchmarks import cli
from tools.benchmarks.core import descriptor as d
from tools.benchmarks.core.identity import canonical_json, sha256_hex
from tools.benchmarks.datasets import synthetic as s

ROOT = Path(__file__).resolve().parents[3]


def write(path: Path, document: dict) -> Path:
    path.write_bytes(canonical_json(document))
    return path


def test_describe_prints_status(tmp_path, capsys):
    descriptor = write(tmp_path / "release.json", s.descriptor())
    mapping = write(tmp_path / "mapping.json", s.mapping())
    assert cli.main(["describe", "--descriptor", str(descriptor), "--mapping", str(mapping)]) == 0
    output = capsys.readouterr().out
    assert "research-use RESEARCH-ADMISSIBLE" in output and "(not frozen; prepare will refuse)" in output


def test_describe_refuses_blocked(tmp_path, capsys):
    document = copy.deepcopy(s.descriptor())
    document["researchUse"]["status"] = "BLOCKED"
    assert cli.main(["describe", "--descriptor", str(write(tmp_path / "release.json", document))]) == 2
    assert capsys.readouterr().err.strip() == "refused descriptor_blocked"


def test_describe_refuses_an_incomplete_mapping(tmp_path, capsys):
    mapping = copy.deepcopy(s.mapping())
    mapping["mappings"].pop()
    assert cli.main(["describe", "--descriptor", str(write(tmp_path / "r.json", s.descriptor())),
                     "--mapping", str(write(tmp_path / "m.json", mapping))]) == 2
    assert capsys.readouterr().err.strip() == "refused mapping_incomplete:missing:van"


def test_freeze_writes_once_and_prints_the_hash(tmp_path, capsys):
    source = s.write_source(tmp_path / "source")
    descriptor = write(tmp_path / "release.json", s.descriptor())
    out = tmp_path / "frozen.json"
    args = ["describe", "--descriptor", str(descriptor), "--freeze-manifest", "--source-root", str(source),
            "--out", str(out)]
    assert cli.main(args) == 0
    printed = capsys.readouterr().out.strip()
    assert printed == sha256_hex(out.read_bytes())
    assert out.read_bytes() == canonical_json(d.freeze(s.descriptor(), source))
    assert cli.main(args) == 2
    assert capsys.readouterr().err.strip() == "refused output_exists"


def test_freeze_refuses_atomically(tmp_path, capsys):
    descriptor = write(tmp_path / "release.json", s.descriptor())
    (tmp_path / "empty").mkdir()
    out = tmp_path / "frozen.json"
    assert cli.main(["describe", "--descriptor", str(descriptor), "--freeze-manifest", "--source-root",
                     str(tmp_path / "empty"), "--out", str(out)]) == 2
    assert capsys.readouterr().err.strip() == "refused source_manifest_missing:empty_source"
    assert not out.exists() and not list(tmp_path.glob(".frozen.json*"))


def test_freeze_arguments_are_paired(tmp_path, capsys):
    descriptor = write(tmp_path / "release.json", s.descriptor())
    assert cli.main(["describe", "--descriptor", str(descriptor), "--out", str(tmp_path / "x.json")]) == 2
    assert capsys.readouterr().err.strip() == "refused arguments_invalid:--freeze-manifest"


def test_module_entry_point_runs_from_the_repository_root(tmp_path):
    descriptor = write(tmp_path / "release.json", s.descriptor())
    result = subprocess.run([sys.executable, "-m", "tools.benchmarks.cli", "describe", "--descriptor",
                             str(descriptor)], cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith(f"descriptor {sha256_hex(canonical_json(s.descriptor()))}")
