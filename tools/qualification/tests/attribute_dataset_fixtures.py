"""Synthetic PA-100K and UPAR releases in the real file formats (MATLAB 5.0, Task-1 CSV).

They prove the tooling and are never dataset evidence. Row counts are smaller than the
pinned release; tests shrink ``pa100k.SPLIT_ROWS`` (and the smoke sizes) to match.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import numpy as np

from attributes.datasets.adapters import pa100k, upar

SMALL_ROWS = {"train": 1200, "val": 100, "test": 100}
INVENTORY_ALL = {op: "granted" for op in ("create-derivatives", "evaluate", "redistribute-derived-weights", "run-operationally", "train")}


def jpeg(colour: tuple[int, int, int], pattern: int = 0) -> bytes:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (48, 96), colour)
    if pattern:
        draw = ImageDraw.Draw(image)
        for i in range(pattern):
            draw.rectangle((i * 5 % 40, i * 9 % 80, i * 5 % 40 + 6, i * 9 % 80 + 12), fill=(255 - colour[0], (i * 37) % 256, colour[2]))
    out = io.BytesIO()
    image.save(out, "JPEG", quality=90)
    return out.getvalue()


def image_for(number: int) -> bytes:
    """A distinct textured crop: a deterministic 9 x 8 luminance grid, upscaled and tinted,
    so dHashes differ as they do for real crops."""
    from PIL import Image

    seed = hashlib.sha256(f"fixture-image-{number}".encode()).digest() * 3
    grid = Image.frombytes("L", (9, 8), seed[:72]).resize((48, 96), Image.Resampling.NEAREST)
    tint = Image.new("RGB", (48, 96), ((number * 53) % 256, (number * 97) % 256, (number * 31) % 256))
    image = Image.blend(grid.convert("RGB"), tint, 0.3)
    out = io.BytesIO()
    image.save(out, "JPEG", quality=95)
    return out.getvalue()


def label_row(number: int) -> list[int]:
    row = [((number >> (i % 13)) + i) % 2 for i in range(len(pa100k.ATTRIBUTES))]
    return row


def cell(strings: list[str]) -> np.ndarray:
    """A MATLAB n x 1 cell array of character arrays, as the pinned release stores names."""
    out = np.empty((len(strings), 1), dtype=object)
    for i, text in enumerate(strings):
        out[i, 0] = text
    return out


def annotation_mat(rows: dict[str, int] = SMALL_ROWS, edit=None) -> bytes:
    from scipy.io import savemat

    numbers, start = {}, 1
    for split in pa100k.SPLITS:
        numbers[split] = list(range(start, start + rows[split]))
        start += rows[split]
    content = {"attributes": cell(list(pa100k.ATTRIBUTES))}
    for split in pa100k.SPLITS:
        content[f"{split}_images_name"] = cell([f"{n:06d}.jpg" for n in numbers[split]])
        content[f"{split}_label"] = np.array([label_row(n) for n in numbers[split]], dtype=np.uint8)
    if edit:
        edit(content)
    out = io.BytesIO()
    savemat(out, content, format="5")
    return out.getvalue()


def write_pa100k(root: Path, rows: dict[str, int] = SMALL_ROWS, images: dict[int, bytes] | None = None, mat: bytes | None = None) -> None:
    root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(root / pa100k.ANNOTATION_ARCHIVE, "w") as z:
        z.writestr(pa100k.ANNOTATION_MEMBER, mat if mat is not None else annotation_mat(rows))
    total = sum(rows.values())
    with zipfile.ZipFile(root / pa100k.IMAGE_ARCHIVE, "w", compression=zipfile.ZIP_STORED) as z:
        for n in range(1, total + 1):
            z.writestr(f"{pa100k.IMAGE_PREFIX}{n:06d}.jpg", (images or {}).get(n, image_for(n)))
    (root / "README.txt").write_bytes(b"synthetic PA-100K fixture\r\n")


def upar_csv(entries: list[tuple[str, list[int]]], header: tuple[str, ...] = upar.HEADER) -> bytes:
    lines = [",".join(header)] + [",".join([key] + [str(v) for v in values]) for key, values in entries]
    return ("\n".join(lines) + "\n").encode("utf-8")


def colour_values(upper: str | tuple[str, ...] | None, lower: str | tuple[str, ...] | None) -> list[int]:
    labels = dict.fromkeys(upar.COLUMNS, 0)
    for region, colours in (("UpperBody", upper), ("LowerBody", lower)):
        for colour in ((colours,) if isinstance(colours, str) else colours or ()):
            labels[f"{region}-Color-{colour}"] = 1
    return [labels[c] for c in upar.COLUMNS]


def write_upar(root: Path, train: list[tuple[str, list[int]]], val: list[tuple[str, list[int]]]) -> None:
    for split, entries in (("train", train), ("val", val)):
        path = root / upar.FILES[split]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(upar_csv(entries + [("Market1501/bounding_box_train/0002_c1s1_000451_03.jpg", colour_values("Black", "Blue"))]))


def files_of(root: Path) -> list[dict]:
    out = []
    for path in sorted((p for p in root.rglob("*") if p.is_file()), key=lambda p: p.relative_to(root).as_posix()):
        data = path.read_bytes()
        out.append({"path": path.relative_to(root).as_posix(), "sizeBytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    return out


def determination(licence: str, purposes=None, **over) -> dict:
    record = {
        "determinationId": "fixture", "reviewedOn": "2026-10-03",
        "purposes": purposes or ["benchmarking", "development", "regression-challenge", "selection", "training", "tuning"],
        "licenceCodes": [licence],
        "rights": {"reviewedBy": "fixture reviewer", "determination": "PERMITTED_FOR_ENGINEERING_USE", "evidence": "fixture", "inventory": dict(INVENTORY_ALL)},
        "privacy": {"reviewedBy": "fixture reviewer", "disposition": "PERMITTED", "basis": "fixture"},
        "r5Ruling": {"ruledBy": "R-5", "ruling": "PERMITTED", "reference": "fixture ruling"},
    }
    record.update(over)
    return record


def release_record(release_id: str, root: Path, licence: str, det=..., excluded=(), pinned: str = "fixture") -> dict:
    from attributes.datasets.release import parse_release

    return parse_release({
        "schemaVersion": "mavi-attribute-dataset-release-v1", "releaseId": release_id, "name": release_id, "version": "fixture",
        "origin": "public", "officialUrl": "https://example.org/fixture",
        "pinnedSource": {"kind": "fixture", "reference": f"fixture@{pinned}", "retrievedOn": "2026-10-02"},
        "licence": {"codes": [licence], "url": None, "textSha256": "a" * 64},
        "files": files_of(root), "excludedMembers": [{"path": p, "reason": "fixture exclusion"} for p in sorted(excluded)],
        "determination": determination(licence) if det is ... else det, "knownExposure": [],
    })
