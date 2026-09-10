from pathlib import Path

import pytest

from mavi_vision.storage.local_media_store import LocalMediaStore, MediaStoreError


# Safe resolution
def test_resolve_file_maps_logical_key_under_root(tmp_path: Path) -> None:
    target = tmp_path / "videos" / "camera-01" / "clip.mp4"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"video")
    store = LocalMediaStore(tmp_path)
    assert store.resolve_file("videos/camera-01/clip.mp4") == target.resolve()


@pytest.mark.parametrize(
    "key",
    [
        "../outside.mp4",
        "/outside.mp4",
        "videos\\clip.mp4",
        "C:/outside.mp4",
        "videos//clip.mp4",
        "videos/./clip.mp4",
        "videos/../clip.mp4",
    ],
)
def test_resolve_file_rejects_unsafe_keys(tmp_path: Path, key: str) -> None:
    store = LocalMediaStore(tmp_path)
    with pytest.raises((ValueError, MediaStoreError)):
        store.resolve_file(key)


# Unavailable media
@pytest.mark.parametrize("key", ["videos", "videos/missing.mp4"])
def test_resolve_file_rejects_missing_or_directory(tmp_path: Path, key: str) -> None:
    (tmp_path / "videos").mkdir()
    store = LocalMediaStore(tmp_path)
    with pytest.raises(MediaStoreError, match="unavailable"):
        store.resolve_file(key)


def test_resolve_file_rejects_symlink_escape(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"video")
    link = media_root / "linked.mp4"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    with pytest.raises(MediaStoreError, match="escapes"):
        LocalMediaStore(media_root).resolve_file("linked.mp4")
