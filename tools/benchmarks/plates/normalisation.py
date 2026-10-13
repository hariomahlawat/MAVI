"""``mavi-plate-normalisation-v1`` (Stage 4 plan §5.2): raw OCR text → searchable normalised plate text.

The rules are the contract written in ``contracts/test-vectors/plate-normalisation-v1.json``; the .NET
``Mavi.Application.Modules.Plates.PlateNormalisation`` implements the same function and is tested against the same
vectors. Raw text is never modified in place: the result carries the normalised text (or none) beside the outcome.

1. Well-formed Unicode in; a two-line reading is its lines joined by LF, top line first.
2. Unicode NFKC.
3. ASCII upper-case only (``a-z`` → ``A-Z``); no other character changes case.
4. Remove exactly TAB, LF, CR, SPACE, ``-``, ``.``, ``/``, ``:`` and U+00B7 MIDDLE DOT.
5. Nothing left → ``rejected``/``empty``; anything outside ``[A-Z0-9]`` left → ``rejected``/``non-alphanumeric``.
6. No confusable substitution, insertion, grammar repair or length rule.
7. ``formatClass`` is advisory (``in-bh``, ``in-standard``, ``other``) and never changes the text.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

NORMALISATION_ID = "mavi-plate-normalisation-v1"
OK = "ok"
REJECTED = "rejected"
EMPTY = "empty"
NON_ALPHANUMERIC = "non-alphanumeric"
SEPARATORS = frozenset("\t\n\r -./:·")
_ALPHANUMERIC = re.compile(r"[A-Z0-9]+")
_IN_BH = re.compile(r"[0-9]{2}BH[0-9]{4}[A-Z]{1,2}")
_IN_STANDARD = re.compile(r"[A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{1,4}")


@dataclass(frozen=True, slots=True)
class NormalisedPlate:
    raw: str
    normalised: str | None
    outcome: str
    reason: str | None
    format_class: str | None


def _ascii_upper(text: str) -> str:
    return "".join(chr(ord(ch) - 32) if "a" <= ch <= "z" else ch for ch in text)


def format_class(normalised: str) -> str:
    if _IN_BH.fullmatch(normalised):
        return "in-bh"
    if _IN_STANDARD.fullmatch(normalised):
        return "in-standard"
    return "other"


def normalise(raw: str) -> NormalisedPlate:
    """The v1 normalisation of one raw reading. Ill-formed input (a lone surrogate) is refused with ``ValueError``."""
    if not isinstance(raw, str):
        raise TypeError("plate_normalisation_input_not_text")
    try:
        raw.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("plate_normalisation_input_ill_formed") from exc
    text = _ascii_upper(unicodedata.normalize("NFKC", raw))
    text = "".join(ch for ch in text if ch not in SEPARATORS)
    if not text:
        return NormalisedPlate(raw, None, REJECTED, EMPTY, None)
    if not _ALPHANUMERIC.fullmatch(text):
        return NormalisedPlate(raw, None, REJECTED, NON_ALPHANUMERIC, None)
    return NormalisedPlate(raw, text, OK, None, format_class(text))
