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
