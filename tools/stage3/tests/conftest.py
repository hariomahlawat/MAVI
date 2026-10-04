import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1] / "phase1"))

import pytest  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "real_preregistration: keep the registered S3.2 requirements/guide pin (no synthetic-fixture seam)")


import artefacts  # noqa: E402

REAL_REQUIRE_PREREGISTERED = artefacts.require_preregistered


@pytest.fixture(scope="session", autouse=True)
def _synthetic_preregistration():
    """Fixture worlds commit *synthetic* requirements and guides (s32fixtures), which by design are not the
    registered S3.2 identities, so the suite replaces only the registered-identity check (session-wide, because
    module-scoped worlds sample and pack during setup). Tests marked ``real_preregistration`` get the production
    pin back (below) and exercise it with the real registered files."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(artefacts, "require_preregistered", lambda binding, code: None)
        yield


@pytest.fixture(autouse=True)
def _real_preregistration(request, monkeypatch):
    if request.node.get_closest_marker("real_preregistration") is not None:
        monkeypatch.setattr(artefacts, "require_preregistered", REAL_REQUIRE_PREREGISTERED)


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
