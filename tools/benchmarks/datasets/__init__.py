"""Dataset adapters: one per dataset family, turning a reconciled source tree into canonical ground truth.

An adapter reads only manifest members, through ``descriptor.read_verified`` (every byte re-verified on read),
and only after ``descriptor.reconcile`` has accepted the whole frozen manifest. Discovery must find exactly the
sequences the manifest's members describe (plan §11 ``prepare``): a sequence whose annotation or frames were
removed before freezing cannot leave a half-described sequence behind.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Protocol

from tools.benchmarks.core.identity import require


class DatasetAdapter(Protocol):
    adapter_id: str
    adapter_version: str

    def native_classes(self) -> set[str]:
        """The native classes this adapter can emit (the mapping must name exactly these)."""

    def sequences_described(self, manifest_paths: Iterable[str], split: str) -> list[str]:
        """Sequence ids the manifest's members describe for ``split`` (from paths alone)."""

    def discover(self, source_root: Path, entries: dict[str, dict[str, Any]], split: str) -> list[str]:
        """Sequence ids found complete in the reconciled source for ``split``."""

    def ground_truth(self, source_root: Path, entries: dict[str, dict[str, Any]], descriptor: dict[str, Any],
                     split: str, sequence_id: str) -> dict[str, Any]:
        """The canonical ground-truth document of one sequence."""


def require_discovery_matches(described: Iterable[str], discovered: Iterable[str]) -> list[str]:
    described, discovered = sorted(set(described)), sorted(set(discovered))
    missing = sorted(set(described) ^ set(discovered))
    require(not missing, f"source_manifest_incomplete:sequence:{missing[0] if missing else ''}")
    require(discovered, "source_manifest_incomplete:no_sequences")
    return discovered


def discover(adapter: DatasetAdapter, source_root: Path, entries: dict[str, dict[str, Any]], split: str) -> list[str]:
    return require_discovery_matches(adapter.sequences_described(entries, split),
                                     adapter.discover(source_root, entries, split))
