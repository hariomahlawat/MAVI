"""``mavi-plate-normalisation-v1`` for the ``plates`` role (Stage 4 plan §5.2).

The function body is identical to the benchmark tooling's ``tools/benchmarks/plates/normalisation.py``
(Stage 4 PR-1) and to .NET ``Mavi.Application.Modules.Plates.PlateNormalisation``; all three are held to
``contracts/test-vectors/plate-normalisation-v1.json``. The worker keeps its own copy because the role
runs from its own Runtime Pack and never imports repository tooling. It uses normalisation only to
derive the Track-text summary; the platform derives the persisted normalised text itself (ADR-013
implementation amendment 2026-10-13, item 13) and refuses a completion whose texts disagree.
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
