"""Deterministic plate-search query generation for layer D (plan §4.4; PR-2 protocol ``plates-2026-01`` §4).

Queries are generated from ground-truth texts only, never from predictions or results. Every truth is normalised
with the frozen ``mavi-plate-normalisation-v1``. A truth the normalisation rejects is reported and yields no query.

**Classes, fixed by plan §4.4 (constants, not parameters):**

* ``full`` — every distinct full plate, matched ``exact``;
* ``prefix`` — the first ``PREFIX_LENGTH`` = 4 characters (the plan's state+RTO prefix, for example ``KA01``),
  matched ``contains``. Formed only when the plate is longer than 4;
* ``suffix`` — the plan's "last-4-digit suffix": the last ``SUFFIX_DIGITS`` = 4 characters of the plate's **final
  maximal run of digits** (``KA01AB1234`` → ``1234``; ``22BH1234AA`` → ``1234``), matched ``contains``. If that run has
  fewer than 4 digits, the class is skipped for that plate and counted;
* ``interior`` — one ``INTERIOR_LENGTH`` = 5 character substring starting at ``interior_offset``, lying strictly inside
  the plate (touching neither end), matched ``contains``;
* ``negative`` — ``negatives_per_plate`` texts at Levenshtein distance 1 or 2 from a real plate that are neither a
  truth nor a substring of any truth, matched ``contains``. They contribute to precision only.

Every query is 3–15 characters of ``[A-Z0-9]`` (the PR-4 ``plateText`` rule). A class that cannot be formed is skipped
and counted, never padded.

**De-duplication:** ``queries`` keeps one entry per ``(class, text)`` with every source plate, as labels.
``metric_queries`` keeps **one entry per (match, text)**: the same text under two ``contains`` classes (for example a
prefix that equals another plate's interior) is counted once in the metrics. Its ``classes`` lists every class as
labels. Relevance is always computed against **all** truths, never against the source alone.

**Identity (owner item 12).** A query set is bound to the exact frozen population. ``generate`` requires the
partition/corpus manifest SHA-256 and records:
- ``population_manifest_sha256``;
- ``generator_config_sha256``: canonical JSON of the generator version, the fixed class constants and the parameters;
- ``query_set_sha256``: canonical JSON of every query and the truth list.

The evaluator refuses a query set whose population manifest SHA differs from the population it scores.

**Open protocol values (required parameters, no defaults):** the interior offset, negatives per plate and the seed.
Negatives are drawn from a SHA-256 counter-mode stream over ``(seed, plate, attempt)``, so the output does not depend on
dict order or the platform.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from mavi_vision.plates.normalisation import OK, normalise

FULL, PREFIX, SUFFIX, INTERIOR, NEGATIVE = "full", "prefix", "suffix", "interior", "negative"
CLASSES = (FULL, PREFIX, SUFFIX, INTERIOR, NEGATIVE)
EXACT, CONTAINS = "exact", "contains"
MATCH_BY_CLASS = {FULL: EXACT, PREFIX: CONTAINS, SUFFIX: CONTAINS, INTERIOR: CONTAINS, NEGATIVE: CONTAINS}
MIN_QUERY, MAX_QUERY = 3, 15
ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
MAX_NEGATIVE_ATTEMPTS = 1000
PREFIX_LENGTH = 4    # plan §4.4: state + RTO prefix
SUFFIX_DIGITS = 4    # plan §4.4: last-4-digit suffix
INTERIOR_LENGTH = 5  # plan §4.4: a 5-character interior substring
_FINAL_DIGITS = re.compile(r"([0-9]+)[^0-9]*$")


@dataclass(frozen=True, slots=True)
class QueryParameters:
    interior_offset: int
    negatives_per_plate: int
    seed: str

    def __post_init__(self) -> None:
        if not (isinstance(self.interior_offset, int) and not isinstance(self.interior_offset, bool)
                and self.interior_offset >= 1):
            raise ValueError("query_parameters_invalid:interior_offset")
        if not (isinstance(self.negatives_per_plate, int) and not isinstance(self.negatives_per_plate, bool)
                and self.negatives_per_plate >= 0):
            raise ValueError("query_parameters_invalid:negatives_per_plate")
        if not (isinstance(self.seed, str) and self.seed):
            raise ValueError("query_parameters_invalid:seed")


@dataclass(frozen=True, slots=True)
class Query:
    query_class: str
    text: str
    match: str
    sources: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MetricQuery:
    """One query as the metrics count it: unique by (match, text); ``classes`` are labels only."""

    text: str
    match: str
    classes: tuple[str, ...]

    @property
    def negative_only(self) -> bool:
        return self.classes == (NEGATIVE,)


GENERATOR_VERSION = "mavi-plate-query-generator-v1"


@dataclass(frozen=True, slots=True)
class QuerySet:
    queries: tuple[Query, ...]
    metric_queries: tuple[MetricQuery, ...]
    truths: tuple[str, ...]
    rejected_truths: tuple[str, ...]
    skipped: Mapping[str, int]
    population_manifest_sha256: str
    generator_config_sha256: str
    query_set_sha256: str


def _sha(document: object) -> str:
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def queryable(text: str) -> bool:
    """The PR-4 ``plateText`` rule: 3–15 characters of [A-Z0-9] after normalisation."""
    return MIN_QUERY <= len(text) <= MAX_QUERY and all(ch in ALPHABET for ch in text)


def levenshtein(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def last_digit_suffix(plate: str) -> str | None:
    match = _FINAL_DIGITS.search(plate)
    if match is None or len(match.group(1)) < SUFFIX_DIGITS:
        return None
    return match.group(1)[-SUFFIX_DIGITS:]


def _stream(seed: str, plate: str, attempt: int) -> bytes:
    return hashlib.sha256(f"{seed}\x00{plate}\x00{attempt}".encode("utf-8")).digest()


def _mutate(plate: str, entropy: bytes) -> str:
    """One or two single-character edits (substitute, delete, insert), chosen by the entropy bytes."""
    text = list(plate)
    cursor = 1
    for _ in range(1 + entropy[0] % 2):
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


def generate(truth_texts: Iterable[str], parameters: QueryParameters, population_manifest_sha256: str) -> QuerySet:
    if not (isinstance(population_manifest_sha256, str) and re.fullmatch(r"[0-9a-f]{64}", population_manifest_sha256)):
        raise ValueError("population_manifest_sha256_required")
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

    def add(query_class: str, text: str | None, source: str) -> None:
        if text is None or not queryable(text):
            skipped[query_class] += 1
            return
        found.setdefault((query_class, text), set()).add(source)

    p = parameters
    for plate in ordered:
        add(FULL, plate, plate)
        add(PREFIX, plate[:PREFIX_LENGTH] if len(plate) > PREFIX_LENGTH else None, plate)
        add(SUFFIX, last_digit_suffix(plate), plate)
        end = p.interior_offset + INTERIOR_LENGTH
        add(INTERIOR, plate[p.interior_offset:end] if end <= len(plate) - 1 else None, plate)
        accepted = attempt = 0
        while accepted < p.negatives_per_plate and attempt < MAX_NEGATIVE_ATTEMPTS:
            candidate = _mutate(plate, _stream(p.seed, plate, attempt))
            attempt += 1
            if not queryable(candidate) or not 1 <= levenshtein(candidate, plate) <= 2:
                continue
            if any(candidate in truth for truth in ordered) or (NEGATIVE, candidate) in found:
                continue
            found[(NEGATIVE, candidate)] = {plate}
            accepted += 1
        skipped[NEGATIVE] += p.negatives_per_plate - accepted
    queries = tuple(Query(c, t, MATCH_BY_CLASS[c], tuple(sorted(s)))
                    for (c, t), s in sorted(found.items(), key=lambda item: (CLASSES.index(item[0][0]), item[0][1])))
    labels: dict[tuple[str, str], set[str]] = {}
    for query in queries:
        labels.setdefault((query.match, query.text), set()).add(query.query_class)
    metric = tuple(MetricQuery(text, match, tuple(sorted(classes, key=CLASSES.index)))
                   for (match, text), classes in sorted(labels.items()))
    config = {"generator": GENERATOR_VERSION, "prefixLength": PREFIX_LENGTH, "suffixDigits": SUFFIX_DIGITS,
              "interiorLength": INTERIOR_LENGTH, "interiorOffset": p.interior_offset,
              "negativesPerPlate": p.negatives_per_plate, "seed": p.seed}
    body = {"truths": list(ordered), "queries": [[x.query_class, x.text, x.match, list(x.sources)] for x in queries]}
    return QuerySet(queries, metric, ordered, tuple(rejected), skipped, population_manifest_sha256, _sha(config),
                    _sha({"population": population_manifest_sha256, "config": _sha(config), **body}))


def matches(match: str, query_text: str, text: str) -> bool:
    """PR-4 literal matching on normalised text: no confusable expansion, no fuzzy distance."""
    return text == query_text if match == EXACT else query_text in text
