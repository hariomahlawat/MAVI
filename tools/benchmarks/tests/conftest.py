import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
for path in (ROOT, HERE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import pytest  # noqa: E402

from tools.benchmarks.core import descriptor as descriptors  # noqa: E402
from tools.benchmarks.datasets import synthetic  # noqa: E402


@pytest.fixture
def source(tmp_path) -> Path:
    """A fresh synthetic source tree."""
    return synthetic.write_source(tmp_path / "source")


@pytest.fixture
def frozen(source) -> dict:
    return descriptors.freeze(synthetic.descriptor(), source)


@pytest.fixture(scope="session")
def media_pack(tmp_path_factory):
    """A verified MAVI FFmpeg pack, built as the Stage-3 media tests build it (``MAVI_TEST_MEDIA_TOOLS`` or the
    environment's ffmpeg/ffprobe); skipped without one, failed in CI (``MAVI_REQUIRE_MEDIA_TESTS=1``)."""
    stage3_tests = ROOT / "tools" / "stage3" / "tests"
    if str(stage3_tests) not in sys.path:
        sys.path.insert(0, str(stage3_tests))
    import s32b_fixtures

    return s32b_fixtures.build_pack(tmp_path_factory.mktemp("media-pack") / "pack")
