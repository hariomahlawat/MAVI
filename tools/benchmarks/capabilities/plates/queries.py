"""Deterministic plate-search query generation for layer D (plan §4.4; protocol ``plates-2026-01-protocol.md`` §4 D).

Queries are generated from ground-truth texts only, never from predictions or results. Every truth text is
normalised with the frozen ``mavi-plate-normalisation-v1``; a truth that the normalisation rejects is reported and
yields no query.

Classes (plan §4.4):

* ``full`` — every distinct full plate, matched ``exact``;
* ``prefix`` — the first ``prefix_length`` characters (the plan's state+RTO prefix, for example ``KA01``),
  matched ``contains``;
* ``suffix`` — the last ``suffix_length`` characters, matched ``contains``;
* ``interior`` — one ``interior_length``-character substring starting at ``interior_offset``. It must lie strictly
  inside the plate, touching neither end; matched ``contains``;
* ``negative`` — ``negatives_per_plate`` texts at Levenshtein distance 1 or 2 from a real plate that are neither a truth
  nor a substring of any truth, matched ``contains`` (precision only).

Every query is 3–15 characters of ``[A-Z0-9]``, which is the PR-4 ``plateText`` rule. A class that cannot be formed for
a plate (for example a plate too short to have an interior) is skipped and counted, never padded.

Duplicates: one query per distinct ``(class, text)``. A query keeps every source plate it came from, so relevance
is always computed against **all** truths and never against its source alone.

**Open owner decisions are explicit parameters (no defaults):**
- the interior offset and lengths (protocol drafting);
- ``negatives_per_plate`` (N8);
- the seed (D7b and the reproducibility fields).

Negatives are drawn by a counter-mode SHA-256 stream over ``(seed, plate, attempt)``, so the output does not depend
on dict order or the platform.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from mavi_vision.plates.normalisation import OK, normalise

FULL, PREFIX, SUFFIX, INTERIOR, NEGATIVE = "full", "prefix", "suffix", "interior", "negative"
CLASSES = (FULL, PREFIX, SUFFIX, INTERIOR, NEGATIVE)
EXACT, CONTAINS = "exact", "contains"
MATCH_BY_CLASS = {FULL: EXACT, PREFIX: CONTAINS, SUFFIX: CONTAINS, INTERIOR: CONTAINS, NEGATIVE: CONTAINS}
MIN_QUERY, MAX_QUERY = 3, 15
ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
MAX_NEGATIVE_ATTEMPTS = 1000


@dataclass(frozen=True, slots=True)
class QueryParameters:
    prefix_length: int
    suffix_length: int
    interior_length: int
    interior_offset: int
    negatives_per_plate: int
    seed: str

    def __post_init__(self) -> None:
        for name in ("prefix_length", "suffix_length", "interior_length"):
            value = getattr(self, name)
            if not (isinstance(value, int) and MIN_QUERY <= value <= MAX_QUERY):
                raise ValueError(f"query_parameters_invalid:{name}")
        if not (isinstance(self.interior_offset, int) and self.interior_offset >= 1):
            raise ValueError("query_parameters_invalid:interior_offset")
        if not (isinstance(self.negatives_per_plate, int) and self.negatives_per_plate >= 0):
            raise ValueError("query_parameters_invalid:negatives_per_plate")
        if not (isinstance(self.seed, str) and self.seed):
            raise ValueError("query_parameters_invalid:seed")


@dataclass(frozen=True, slots=True)
class Query:
    query_class: str
    text: str
    match: str
    sources: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class QuerySet:
    queries: tuple[Query, ...]
    truths: tuple[str, ...]
    rejected_truths: tuple[str, ...]
    skipped: Mapping[str, int]


def _valid(text: str) -> bool:
    return MIN_QUERY <= len(text) <= MAX_QUERY and all(ch in ALPHABET for ch in text)


def levenshtein(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def _stream(seed: str, plate: str, attempt: int) -> bytes:
    return hashlib.sha256(f"{seed}\x00{plate}\x00{attempt}".encode("utf-8")).digest()


def _mutate(plate: str, entropy: bytes) -> str:
    """One or two single-character edits (substitute, delete, insert), chosen by the entropy bytes."""
    text = list(plate)
    edits = 1 + entropy[0] % 2
    cursor = 1
    for _ in range(edits):
        kind = entropy[cursor] % 3
        position = entropy[cursor + 1] % (len(text) + (1 if kind == 2 else 0))
        character = ALPHABET[entropy[cursor + 2] % len(ALPHABET)]
        cursor += 3
        if kind == 0 and text:
            text[position % len(text)] = character
        elif kind == 1 and len(text) > 1:
            del text[position % len(text)]
        else:
            text.insert(position, character)
    return "".join(text)


def generate(truth_texts: Iterable[str], parameters: QueryParameters) -> QuerySet:
    truths: set[str] = set()
    rejected: list[str] = []
    for raw in truth_texts:
        result = normalise(raw)
        if result.outcome == OK and result.normalised is not None:
            truths.add(result.normalised)
        else:
            rejected.append(raw)
    ordered = tuple(sorted(truths))
    skipped = {name: 0 for name in CLASSES}
    found: dict[tuple[str, str], set[str]] = {}

    def add(query_class: str, text: str, source: str) -> None:
        if not _valid(text):
            skipped[query_class] += 1
            return
        found.setdefault((query_class, text), set()).add(source)

    p = parameters
    for plate in ordered:
        add(FULL, plate, plate)
        if len(plate) > p.prefix_length:
            add(PREFIX, plate[: p.prefix_length], plate)
        else:
            skipped[PREFIX] += 1
        if len(plate) > p.suffix_length:
            add(SUFFIX, plate[-p.suffix_length:], plate)
        else:
            skipped[SUFFIX] += 1
        end = p.interior_offset + p.interior_length
        if end <= len(plate) - 1:
            add(INTERIOR, plate[p.interior_offset:end], plate)
        else:
            skipped[INTERIOR] += 1
        accepted = 0
        attempt = 0
        while accepted < p.negatives_per_plate and attempt < MAX_NEGATIVE_ATTEMPTS:
            candidate = _mutate(plate, _stream(p.seed, plate, attempt))
            attempt += 1
            if not _valid(candidate) or not 1 <= levenshtein(candidate, plate) <= 2:
                continue
            if any(candidate in truth for truth in ordered) or (NEGATIVE, candidate) in found:
                continue
            found[(NEGATIVE, candidate)] = {plate}
            accepted += 1
        if accepted < p.negatives_per_plate:
            skipped[NEGATIVE] += p.negatives_per_plate - accepted
    queries = tuple(Query(c, t, MATCH_BY_CLASS[c], tuple(sorted(s)))
                    for (c, t), s in sorted(found.items(), key=lambda item: (CLASSES.index(item[0][0]), item[0][1])))
    return QuerySet(queries, ordered, tuple(rejected), skipped)


def matches(query: Query, text: str) -> bool:
    """PR-4 literal matching on normalised text: no confusable expansion, no fuzzy distance."""
    return text == query.text if query.match == EXACT else query.text in text
