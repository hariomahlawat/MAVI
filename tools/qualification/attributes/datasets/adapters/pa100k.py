"""PA-100K adapter: the pinned ``annotation.mat`` (MATLAB 5.0) to neutral rows.

The pinned release (record ``pa-100k-2017``) defines the official split by its own name
lists, ``train_images_name``, ``val_images_name`` and ``test_images_name``, with
``*_label`` matrices of 26 binary attributes in the order of ``attributes``. Everything is
checked against that exact structure, and anything else is refused. PA-100K publishes no
identity or tracklet ids, so a row's group is a **synthetic allocation group** of 500
consecutive image numbers. It is not identity- or tracklet-disjoint.
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

from attributes.corpus.canonical import CorpusError, require

ANNOTATION_ARCHIVE = "annotation.zip"
ANNOTATION_MEMBER = "annotation.mat"
IMAGE_ARCHIVE = "data.zip"
IMAGE_PREFIX = "release_data/release_data/"
SPLITS = ("train", "val", "test")
SPLIT_ROWS = {"train": 80000, "val": 10000, "test": 10000}
BLOCK_SIZE = 500
ATTRIBUTES = (
    "Female", "AgeOver60", "Age18-60", "AgeLess18", "Front", "Side", "Back", "Hat", "Glasses", "HandBag", "ShoulderBag",
    "Backpack", "HoldObjectsInFront", "ShortSleeve", "LongSleeve", "UpperStride", "UpperLogo", "UpperPlaid", "UpperSplice",
    "LowerStripe", "LowerPattern", "LongCoat", "Trousers", "Shorts", "Skirt&Dress", "boots",
)
VARIABLES = frozenset({"attributes"} | {f"{s}_images_name" for s in SPLITS} | {f"{s}_label" for s in SPLITS})
_NAME_RE = re.compile(r"^(\d{6})\.jpg$")


def _cell_strings(value, code: str) -> list[str]:
    """A MATLAB n x 1 cell array of character arrays, as loaded by scipy, to Python strings."""
    require(getattr(value, "ndim", None) == 2 and value.shape[1] == 1, f"{code}:shape")
    out = []
    for item in value[:, 0]:
        require(getattr(item, "size", 0) == 1, f"{code}:cell")
        text = item.ravel()[0]
        require(isinstance(text, str), f"{code}:cell_type")
        out.append(text)
    return out


def group_of(image_number: int) -> dict:
    return {"id": f"pa100k-block-{(image_number - 1) // BLOCK_SIZE:04d}", "kind": "synthetic-allocation"}


def parse_annotation(mat_bytes: bytes) -> list[dict]:
    """Neutral rows ``{memberPath, sourceSplit, imageNumber, group, labels}`` in file order.

    Refuses missing or unexpected variables, wrong row counts, wrong shapes, an attribute
    list differing from the pinned one, non-binary labels, malformed or repeated names."""
    from scipy.io import loadmat  # tools/requirements.txt pin

    require(mat_bytes[:19] == b"MATLAB 5.0 MAT-file", "pa100k_annotation_not_matlab5")
    try:
        mat = loadmat(io.BytesIO(mat_bytes))
    except Exception as exc:  # scipy raises several types for corrupt files
        raise CorpusError(f"pa100k_annotation_unreadable:{type(exc).__name__}") from exc
    names = {k for k in mat if not k.startswith("__")}
    require(names == VARIABLES, f"pa100k_annotation_variables:{','.join(sorted(names ^ VARIABLES))}")
    require(tuple(_cell_strings(mat["attributes"], "pa100k_attributes")) == ATTRIBUTES, "pa100k_attributes_differ")
    rows, seen = [], set()
    for split in SPLITS:
        images = _cell_strings(mat[f"{split}_images_name"], f"pa100k_{split}_names")
        labels = mat[f"{split}_label"]
        require(len(images) == SPLIT_ROWS[split], f"pa100k_{split}_row_count:{len(images)}")
        require(getattr(labels, "shape", None) == (SPLIT_ROWS[split], len(ATTRIBUTES)), f"pa100k_{split}_label_shape")
        values = labels.tolist()
        for name, row in zip(images, values):
            match = _NAME_RE.fullmatch(name)
            require(match is not None, f"pa100k_image_name:{name}")
            require(name not in seen, f"pa100k_image_repeated:{name}")
            seen.add(name)
            require(all(v in (0, 1) and v == int(v) for v in row), f"pa100k_label_not_binary:{name}")
            number = int(match.group(1))
            rows.append({"memberPath": IMAGE_PREFIX + name, "sourceSplit": split, "imageNumber": number,
                         "group": group_of(number), "labels": dict(zip(ATTRIBUTES, (int(v) for v in row)))})
    return rows


def read_rows(root: Path) -> list[dict]:
    """Rows from the operator-placed release files (verify the release record first)."""
    with zipfile.ZipFile(Path(root) / ANNOTATION_ARCHIVE) as archive:
        members = archive.namelist()
        require(ANNOTATION_MEMBER in members, "pa100k_annotation_member_missing")
        return parse_annotation(archive.read(ANNOTATION_MEMBER))
