"""S2c.1: the offline command line end to end on a synthetic corpus, plus offline/privacy guards."""

from __future__ import annotations

import ast
import json
from pathlib import Path

from attribute_corpus_fixtures import build_corpus, policy

from attributes.corpus.cli import main

PACKAGE = Path(__file__).resolve().parents[1] / "attributes"
NETWORK_MODULES = {"socket", "urllib", "http", "httpx", "requests", "ftplib", "smtplib", "ssl", "aiohttp", "websockets"}


def test_the_corpus_tooling_has_no_network_path() -> None:
    for source in PACKAGE.rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert name.split(".")[0] not in NETWORK_MODULES, f"{source.name} imports {name}"


def test_no_image_or_media_file_is_tracked_in_the_corpus_areas() -> None:
    repo = PACKAGE.parents[2]
    for area in (PACKAGE, repo / "docs" / "qualification" / "stage2-s2c", Path(__file__).parent):
        for path in area.rglob("*"):
            assert path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif", ".tif", ".tiff"}, path


def _write(path: Path, document: dict) -> Path:
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_command_line_workflow_on_a_synthetic_corpus(tmp_path, capsys) -> None:
    corpus = _write(tmp_path / "corpus.json", build_corpus(sites=4, cameras_per_site=3, days=12, tracks_per_source=1))
    policy_path = _write(tmp_path / "policy.json", policy())
    partition = tmp_path / "partition.json"
    assert main(["validate-corpus", "--corpus", str(corpus)]) == 0
    assert main(["partition", "--corpus", str(corpus), "--policy", str(policy_path), "--out", str(partition)]) == 0
    assert main(["verify-partition", "--corpus", str(corpus), "--partition", str(partition)]) == 0
    task = tmp_path / "task.json"
    assert main(["confirm-rules", "--by", "owner-1", "--out", str(task)]) == 0
    ledger = tmp_path / "ledger.jsonl"
    assert main(["register-annotator", "--ledger", str(ledger), "--id", "ann-a"]) == 0
    assert main(["register-annotator", "--ledger", str(ledger), "--id", "ann-b", "--independent"]) == 0
    sample = tmp_path / "sample.json"
    assert main(["pilot-sample", "--corpus", str(corpus), "--partition", str(partition), "--size", "12", "--seed", "s", "--out", str(sample)]) == 0
    guide = Path(__file__).resolve().parents[3] / "docs" / "qualification" / "stage2-s2c" / "annotation-guide.md"
    assignments, batches = [], []
    for annotator in ("ann-a", "ann-b"):
        out = tmp_path / f"assign-{annotator}.json"
        assert main(["assign", "--corpus", str(corpus), "--partition", str(partition), "--task", str(task), "--guide", str(guide), "--ledger", str(ledger), "--id", f"pilot-{annotator}", "--annotator", annotator, "--phase", "pilot", "--round", "independent", "--tracks", str(sample), "--out", str(out)]) == 0
        assignment = json.loads(out.read_text())
        rows = ["unitKind,trackId,observationId,attributeType,outcome,value,unscorableReason"]
        for unit in assignment["units"]:
            for attribute in unit["attributeTypes"]:
                if attribute == "subject-validity":
                    rows.append(f"track,{unit['trackId']},,{attribute},value,valid,")
                elif attribute.endswith("colour"):
                    rows.append(f"track,{unit['trackId']},,{attribute},value,{'grey' if annotator == 'ann-a' else 'white'},")
                else:
                    rows.append(f"track,{unit['trackId']},,{attribute},unscorable,,occluded")
        csv_path = tmp_path / f"{annotator}.csv"
        csv_path.write_text("\n".join(rows) + "\n")
        batch = tmp_path / f"batch-{annotator}.json"
        assert main(["submit", "--ledger", str(ledger), "--assignment", str(out), "--task", str(task), "--labels-csv", str(csv_path), "--batch-id", f"b-{annotator}", "--active-seconds", "300", "--out", str(batch)]) == 0
        assignments.append(str(out))
        batches.append(str(batch))
    report = tmp_path / "pilot-report.json"
    markdown = tmp_path / "pilot-report.md"
    assert main(["pilot-report", "--corpus", str(corpus), "--partition", str(partition), "--task", str(task), "--ledger", str(ledger), "--assignments", *assignments, "--batches", *batches, "--phase", "pilot", "--out", str(report), "--markdown", str(markdown)]) == 0
    document = json.loads(report.read_text())
    assert document["corpusKind"] == "synthetic-fixture"
    assert any(m["recommendMerge"] for m in document["valueMergeRecommendations"] if m["values"] == ["grey", "white"])
    assert str(tmp_path) not in report.read_text() and str(tmp_path) not in partition.read_text()
    committed = Path(__file__).resolve().parents[3] / "docs" / "qualification" / "stage2-s2c" / "corpus" / "f1-evidence-record.json"
    assert main(["check-f1", "--record", str(committed)]) == 0
    assert '"computed": "OPEN"' in capsys.readouterr().out
    # A refusal is reported, never a traceback: a pilot over non-training Tracks.
    parts = json.loads(partition.read_text())
    frozen = [a["trackId"] for a in parts["assignments"] if a["partition"] == "frozen-test"][:1]
    bad = _write(tmp_path / "bad-sample.json", {"trackIds": frozen})
    assert main(["assign", "--corpus", str(corpus), "--partition", str(partition), "--task", str(task), "--guide", str(guide), "--ledger", str(ledger), "--id", "pilot-x", "--annotator", "ann-a", "--phase", "pilot", "--round", "independent", "--tracks", str(bad), "--out", str(tmp_path / "x.json")]) == 2
