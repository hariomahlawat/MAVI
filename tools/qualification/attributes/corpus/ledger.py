"""Append-only, hash-chained JSON-lines ledger (annotation workflow and frozen-test access).

Each line is a canonical JSON entry ``{seq, at, kind, payload, prevSha256, entrySha256}``;
``entrySha256`` is the SHA-256 of the entry without that field, and ``prevSha256`` is
the previous entry's ``entrySha256`` (the genesis entry points at 64 zeros). Editing,
deleting or reordering any line breaks the chain, so the ledger can be audited
independently of the tool that wrote it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .canonical import CorpusError, canonical_json, document_sha256, refuse_path_leaks, require, require_datetime

GENESIS = "0" * 64


def entry_sha256(entry: dict) -> str:
    return document_sha256({k: v for k, v in entry.items() if k != "entrySha256"})


class Ledger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.entries: list[dict] = []
        if path.exists():
            for number, line in enumerate(path.read_text(encoding="ascii").splitlines(), start=1):
                try:
                    self.entries.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise CorpusError(f"ledger_line_unreadable:{number}") from exc
        self.verify()

    def verify(self) -> None:
        previous = GENESIS
        for index, entry in enumerate(self.entries):
            require(entry.get("seq") == index + 1, f"ledger_sequence_broken:{index + 1}")
            require(entry.get("prevSha256") == previous, f"ledger_chain_broken:{index + 1}")
            require(entry.get("entrySha256") == entry_sha256(entry), f"ledger_entry_tampered:{index + 1}")
            previous = entry["entrySha256"]

    @property
    def head(self) -> str:
        return self.entries[-1]["entrySha256"] if self.entries else GENESIS

    def append(self, kind: str, payload: dict, at: str) -> dict:
        require(self.path is not None, "ledger_view_is_read_only")
        require_datetime(at, "ledger_time")
        refuse_path_leaks(payload, "ledger_path_leak")
        entry = {"seq": len(self.entries) + 1, "at": at, "kind": kind, "payload": payload, "prevSha256": self.head}
        entry["entrySha256"] = entry_sha256(entry)
        # All or nothing: a failed write (for example a full disk mid-line) is truncated
        # back to the previous size, so the ledger never keeps a partial entry and a retry
        # starts from a verifiable chain.
        size = self.path.stat().st_size if self.path.exists() else 0
        try:
            with self.path.open("ab") as handle:
                handle.write(canonical_json(entry))
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            with self.path.open("r+b") as handle:
                handle.truncate(size)
            raise
        self.entries.append(entry)
        return entry

    def require_extends(self, recorded_head: str) -> None:
        """A chain alone cannot reveal truncation; a head recorded elsewhere (F1 record, MSR)
        must still be present, so entries after it cannot have been cut away unnoticed."""
        require(recorded_head == GENESIS or any(e["entrySha256"] == recorded_head for e in self.entries), "ledger_truncated_or_forked")

    def of_kind(self, kind: str) -> list[dict]:
        return [e for e in self.entries if e["kind"] == kind]

    def of_kind_payloads(self, kind: str) -> list[dict]:
        return [e["payload"] for e in self.of_kind(kind)]

    def prefix(self, head: str) -> "Ledger":
        """A read-only view of the ledger as it stood at ``head`` (for re-deriving a record
        that was built then). Appending to the view is refused."""
        self.require_extends(head)
        view = self.__class__.__new__(self.__class__)
        view.path = None
        count = 0 if head == GENESIS else next(i for i, e in enumerate(self.entries, start=1) if e["entrySha256"] == head)
        view.entries = self.entries[:count]
        return view
