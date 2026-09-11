from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest


RESOLVER_PATH = (
    Path(__file__).parents[3] / "tools" / "vision" / "resolve_mmdet_config.py"
)


def _load_resolver():
    spec = importlib.util.spec_from_file_location("resolve_mmdet_config", RESOLVER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("resolver_module_unloadable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_local_path_rejects_remote_config() -> None:
    resolver = _load_resolver()

    with pytest.raises(resolver.ConfigResolutionError, match="config_url_forbidden"):
        resolver.parse_local_path("https://example.invalid/rtmdet.py")


@pytest.mark.parametrize(
    ("content", "error"),
    [
        ("_base_ = ['../base.py']\nmodel = {}\n", "base_reference"),
        ("model = dict(init_cfg='https://example.invalid/x')\n", "remote_url"),
        ("model = dict(path='{{ fileDirname }}/x')\n", "template_reference"),
        ("model = dict(path='" + "$" + "{MODEL_ROOT}/x')\n", "environment_reference"),
    ],
)
def test_resolved_text_rejects_external_resolution_syntax(
    content: str,
    error: str,
) -> None:
    resolver = _load_resolver()

    with pytest.raises(resolver.ConfigResolutionError, match=error):
        resolver.validate_resolved_text(content)


def test_normalized_python_bytes_is_utf8_lf_without_bom() -> None:
    resolver = _load_resolver()

    payload = resolver.normalized_python_bytes("\ufeffmodel = {}\r\n\r\n")

    assert payload == b"model = {}\n"
    assert not payload.startswith(b"\xef\xbb\xbf")


def test_relevant_equivalence_ignores_non_deployment_metadata() -> None:
    resolver = _load_resolver()

    class FakeConfig:
        def __init__(self, data):
            self._data = data

        def to_dict(self):
            return self._data

    resolver.assert_relevant_equivalence(
        FakeConfig({"model": {"type": "RTMDet"}, "work_dir": "source"}),
        FakeConfig({"model": {"type": "RTMDet"}, "work_dir": "resolved"}),
    )


def test_relevant_equivalence_rejects_model_change() -> None:
    resolver = _load_resolver()

    class FakeConfig:
        def __init__(self, data):
            self._data = data

        def to_dict(self):
            return self._data

    with pytest.raises(
        resolver.ConfigResolutionError,
        match="resolved_config_semantics_mismatch",
    ):
        resolver.assert_relevant_equivalence(
            FakeConfig({"model": {"type": "RTMDet"}}),
            FakeConfig({"model": {"type": "FasterRCNN"}}),
        )


def test_resolve_config_uses_mmengine_dump_reloads_and_normalizes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = _load_resolver()
    source = tmp_path / "source.py"
    output = tmp_path / "resolved.py"
    source.write_text("_base_ = ['base.py']\n", encoding="utf-8")

    class FakeConfig:
        def __init__(self, data):
            self._data = data

        @classmethod
        def fromfile(cls, path: str):
            if Path(path) == source:
                return cls(
                    {
                        "default_scope": "mmdet",
                        "model": {"type": "RTMDet"},
                        "test_dataloader": {
                            "dataset": {"pipeline": [{"type": "LoadImageFromFile"}]}
                        },
                    }
                )
            text = Path(path).read_text(encoding="utf-8")
            assert "_base_" not in text
            return cls(
                {
                    "default_scope": "mmdet",
                    "model": {"type": "RTMDet"},
                    "test_dataloader": {
                        "dataset": {"pipeline": [{"type": "LoadImageFromFile"}]}
                    },
                }
            )

        def dump(self, path: str) -> None:
            Path(path).write_bytes(
                b"default_scope = 'mmdet'\r\n"
                b"model = dict(type='RTMDet')\r\n"
                b"test_dataloader = dict(dataset=dict("
                b"pipeline=[dict(type='LoadImageFromFile')]))\r\n"
            )

        def to_dict(self):
            return self._data

    monkeypatch.setitem(sys.modules, "mmengine", types.SimpleNamespace(Config=FakeConfig))

    result = resolver.resolve_config(source, output)

    assert result["status"] == "passed"
    assert result["selfContained"] is True
    assert output.read_bytes().endswith(b"\n")
    assert b"\r" not in output.read_bytes()
    assert "_base_" not in output.read_text(encoding="utf-8")
