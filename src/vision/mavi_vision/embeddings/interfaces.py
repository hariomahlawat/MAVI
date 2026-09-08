from __future__ import annotations

from typing import Protocol


class EmbeddingExtractor(Protocol):
    @property
    def dimensions(self) -> int: ...

    def extract(self, crop: object) -> tuple[float, ...]: ...
