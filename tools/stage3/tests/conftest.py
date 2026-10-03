import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1] / "phase1"))

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def media_pack(tmp_path_factory):
    """A verified media pack (see s32b_fixtures); skipped, or failed in CI, when none is available."""
    import s32b_fixtures

    return s32b_fixtures.build_pack(tmp_path_factory.mktemp("media-pack") / "pack")


@pytest.fixture(scope="session")
def media(media_pack, tmp_path_factory):
    """Tiny synthetic media files made by the pack's FFmpeg: name -> bytes."""
    import s32b_fixtures

    return s32b_fixtures.make_media(media_pack, tmp_path_factory.mktemp("media"))
