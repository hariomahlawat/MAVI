from pathlib import Path

from pydantic import TypeAdapter

from mavi_vision.common.control_plane import StorageKey


# Canonical contract validation
_storage_key_adapter = TypeAdapter(StorageKey)


# Storage errors
class MediaStoreError(RuntimeError):
    """Raised when a logical storage key cannot provide a safe local file."""


# Local media resolution
class LocalMediaStore:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def resolve_file(self, storage_key: str) -> Path:
        canonical_key = _storage_key_adapter.validate_python(storage_key, strict=True)
        candidate = (self._root / Path(*canonical_key.split("/"))).resolve()
        if not candidate.is_relative_to(self._root):
            raise MediaStoreError("logical storage key escapes configured media root")
        if not candidate.exists() or not candidate.is_file():
            raise MediaStoreError("leased source media is unavailable")
        return candidate
