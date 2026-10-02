"""UPAR adapter: the pinned UPAR-Challenge-2027 Task-1 ground truth to neutral PA-100K rows.

Pinned revision ``a19ab2fb6470140606d3c1982c303937b58fbd14``. Only
``data/annotations/task1/{train,val}/gt.csv`` are read. Their header is ``# image``
followed by the 40 attributes in ``COLUMNS``; every value is 0 or 1. The top-level
``data/annotations/train.csv`` of that revision omits the ``image`` column (40 names over
41 cells) and is refused.

Only rows keyed ``PA100k/...`` are kept, and the documented rule maps them to PA-100K
member paths: strip the exact prefix ``PA100k/``. PA-100K images absent from UPAR get no
row, so missing truth stays missing. Multiple positive colours are kept as they are,
for the mapping to treat as ambiguous.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from attributes.corpus.canonical import require

PINNED_REVISION = "a19ab2fb6470140606d3c1982c303937b58fbd14"
FILES = {"train": "data/annotations/task1/train/gt.csv", "val": "data/annotations/task1/val/gt.csv"}
# The exact pinned files (plan §2). A release record naming other bytes is not this release.
PINNED_FILES = {
    "data/annotations/task1/train/gt.csv": (12118754, "e42084aa43b31d4074624265b8239437afc6e47a359a8c0129fae4513a77d424"),
    "data/annotations/task1/val/gt.csv": (4131332, "783be600e359052c9dafe856cbfa2aee45bbd4e3eac10309394e2388bcf7c2bc"),
}
PA100K_PREFIX = "PA100k/"
COLUMNS = (
    "Age-Young", "Age-Adult", "Age-Old", "Gender-Female", "Hair-Length-Short", "Hair-Length-Long", "Hair-Length-Bald",
    "UpperBody-Length-Short", "UpperBody-Color-Black", "UpperBody-Color-Blue", "UpperBody-Color-Brown",
    "UpperBody-Color-Green", "UpperBody-Color-Grey", "UpperBody-Color-Orange", "UpperBody-Color-Pink",
    "UpperBody-Color-Purple", "UpperBody-Color-Red", "UpperBody-Color-White", "UpperBody-Color-Yellow",
    "UpperBody-Color-Other", "LowerBody-Length-Short", "LowerBody-Color-Black", "LowerBody-Color-Blue",
    "LowerBody-Color-Brown", "LowerBody-Color-Green", "LowerBody-Color-Grey", "LowerBody-Color-Orange",
    "LowerBody-Color-Pink", "LowerBody-Color-Purple", "LowerBody-Color-Red", "LowerBody-Color-White",
    "LowerBody-Color-Yellow", "LowerBody-Color-Other", "LowerBody-Type-Trousers&Shorts", "LowerBody-Type-Skirt&Dress",
    "Accessory-Backpack", "Accessory-Bag", "Accessory-Glasses-Normal", "Accessory-Glasses-Sun", "Accessory-Hat",
)
HEADER = ("# image",) + COLUMNS


def parse_csv(data: bytes, upar_split: str) -> tuple[dict[str, dict], dict]:
    """PA-100K rows of one Task-1 file, keyed by PA-100K member path, plus row counts by source.

    Refuses a header other than ``HEADER`` (including the misaligned top-level layout and
    unknown or repeated columns), rows of another width, non-binary values, keys without a
    source prefix, and repeated keys."""
    require(upar_split in FILES, f"upar_split:{upar_split}")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("upar_not_utf8") from None
    reader = csv.reader(io.StringIO(text, newline=""))
    header = tuple(next(reader, ()))
    if len(header) == len(COLUMNS) and header and header[0].startswith("# ") and header[0][2:] == COLUMNS[0]:
        require(False, "upar_header_misaligned_top_level_layout")
    require(len(header) == len(set(header)), "upar_header_repeated_column")
    require(header == HEADER, "upar_header_unexpected")
    rows: dict[str, dict] = {}
    counts: dict[str, int] = {}
    for number, row in enumerate(reader, start=2):
        require(len(row) == len(HEADER), f"upar_row_width:{upar_split}:{number}")
        key = row[0]
        require("/" in key, f"upar_row_key:{upar_split}:{number}")
        source = key.split("/", 1)[0]
        counts[source] = counts.get(source, 0) + 1
        values = row[1:]
        require(all(v in ("0", "1") for v in values), f"upar_value_not_binary:{upar_split}:{number}")
        if not key.startswith(PA100K_PREFIX):
            continue
        member = key[len(PA100K_PREFIX):]
        require(member not in rows, f"upar_row_repeated:{member}")
        rows[member] = {"memberPath": member, "uparSplit": upar_split, "labels": dict(zip(COLUMNS, (int(v) for v in values)))}
    return rows, dict(sorted(counts.items()))


def read_rows(root: Path) -> tuple[dict[str, dict], dict]:
    """PA-100K rows from both Task-1 files (verify the release record first)."""
    rows: dict[str, dict] = {}
    counts = {}
    for split, path in FILES.items():
        part, part_counts = parse_csv((Path(root) / path).read_bytes(), split)
        overlap = rows.keys() & part.keys()
        require(not overlap, f"upar_row_in_both_splits:{min(overlap) if overlap else ''}")
        rows.update(part)
        counts[split] = part_counts
    return rows, counts
