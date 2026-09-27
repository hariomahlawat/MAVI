"""verify_repo keeps completion 3.2 exactly the pinned delta over 3.1 (S2a plan section 4.5)."""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).parents[3]
VERIFY_REPO_PATH = REPOSITORY / "tools" / "verify_repo.py"


def _load_verify_repo():
    spec = importlib.util.spec_from_file_location("verify_repo_completion_v32", VERIFY_REPO_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("verify_repo_module_unloadable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _contracts_root(tmp_path: Path) -> Path:
    shutil.copytree(REPOSITORY / "contracts", tmp_path / "contracts")
    return tmp_path


def _errors(root: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    verifier = _load_verify_repo()
    monkeypatch.setattr(verifier, "ROOT", root)
    errors: list[str] = []
    # Through the repository entry point, so the 3.2 check cannot silently fall out of it.
    verifier.check_contracts(errors)
    return errors


def _edit_json(path: Path, change) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    change(document)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def test_the_published_3_2_contract_is_the_pinned_delta(tmp_path, monkeypatch) -> None:
    assert _errors(_contracts_root(tmp_path), monkeypatch) == []


def test_the_published_3_2_schema_is_byte_for_byte_the_generated_delta() -> None:
    verifier = _load_verify_repo()
    schemas = REPOSITORY / "contracts" / "schemas"
    for stem, build in (
        ("vision-job-complete", verifier.expected_completion_v32_schema),
        ("vision-job-finalization-response", verifier.expected_finalization_response_v32_schema),
    ):
        v31 = json.loads((schemas / f"{stem}-v3.1.schema.json").read_text(encoding="utf-8"))
        text = (schemas / f"{stem}-v3.2.schema.json").read_bytes()
        assert text == (json.dumps(build(v31), indent=2) + "\n").encode("ascii")


def _drop_required(document: dict, field: str) -> None:
    document["$defs"]["provenance"]["required"].remove(field)


@pytest.mark.parametrize(
    ("relative", "change", "expected"),
    [
        # a 3.2 member made optional, or the schema loosened
        ("schemas/vision-job-complete-v3.2.schema.json", lambda d: _drop_required(d, "componentBindingSha256"), "pinned component-identity delta"),
        ("schemas/vision-job-complete-v3.2.schema.json", lambda d: _drop_required(d, "capabilityId"), "pinned component-identity delta"),
        ("schemas/vision-job-complete-v3.2.schema.json", lambda d: d["$defs"]["capabilityId"]["enum"].append("face-recognition"), "pinned component-identity delta"),
        ("schemas/vision-job-complete-v3.2.schema.json", lambda d: d["$defs"]["provenance"]["allOf"].pop(), "pinned component-identity delta"),
        ("schemas/vision-job-complete-v3.2.schema.json", lambda d: d["$defs"]["modelPackId"].pop("maxLength"), "pinned component-identity delta"),
        ("schemas/vision-job-complete-v3.2.schema.json", lambda d: d["$defs"]["provenance"].update(additionalProperties=True), "pinned component-identity delta"),
        # the response drifts from 3.1
        ("schemas/vision-job-finalization-response-v3.2.schema.json", lambda d: d["required"].remove("tracksSubmitted"), "Finalization response v3.2"),
        # an example changes without re-pinning, or stops being valid
        ("examples/vision-job-complete-v3.2.example.json", lambda d: d["provenance"].update(componentBindingSha256="8" * 64), "without re-pinning"),
        ("examples/vision-job-complete-v3.2-unpacked-environment.example.json", lambda d: d["provenance"].update(runtimePackId="mavi-runtime-v2-" + "8" * 64), "is invalid"),
        # the digest vectors stop covering both examples
        ("test-vectors/vision-job-complete-v3.2-digest.json", lambda d: d["vectors"].pop(), "exactly the installed-pack and unpacked-environment"),
        ("test-vectors/vision-job-complete-v3.2-digest.json", lambda d: d["vectors"][0].update(completionDigest="PENDING"), "lower-case SHA-256"),
        # a shared negative case becomes schema-valid
        ("test-vectors/control-plane-v3.2-invalid.json", lambda d: d["cases"].append({"name": "valid", "base": "installed", "code": "provenance_capability_invalid"}), "was accepted by the vision-job-complete-v3.2 schema: valid"),
    ],
)
def test_completion_3_2_drift_fails_closed(tmp_path, monkeypatch, relative, change, expected) -> None:
    root = _contracts_root(tmp_path)
    _edit_json(root / "contracts" / relative, change)
    errors = _errors(root, monkeypatch)
    assert any(expected in error for error in errors), errors
