"""The LRLPR-26 adapter (Stage 4; Laroca et al., ICPR 2026): minimal, read-only plate-crop tracks. Development only.

Bound by ``docs/qualification/stage4/lrlpr-26-aggregation-protocol-v1.md`` (FROZEN) and its machine form
``lrlpr-26-aggregation-rules-v1.json``. The data record is ``lrlpr-26-dataset-record-2026-10-18.md``.

Source layout (the Dropbox ``train.zip`` extracted; byte-identical to ``data.zip``'s ``train.tar``)::

    train/<Scenario-A|Scenario-B>/<Brazilian|Mercosur>/track_NNNNN/
        lr-001..005.<png|jpg>   five low-resolution plate crops (the only recognition inputs)
        hr-001..005.<png|jpg>   five high-resolution crops (never read here; hashed only)
        annotations.json        {plate_text, plate_layout, corners?}

Fail-closed: any other scenario, layout, directory, file name or extension; a ``plate_layout`` that differs from
the folder; a plate text that ``normalise()`` does not accept; an image whose bytes differ from the per-file
manifest; an ``annotations.json`` whose bytes differ from the archive member; an archive or manifest SHA-256 that
differs from the record. ``CropTrack.truth`` is MAVI's ``normalise(plate_text)`` with no format-based correction.

The split builders reproduce ``lrlpr-26-split-v1.json`` exactly: plate-identity groups are the union-find
components over a shared normalised text or a shared byte-identical image (LR or HR). No plate text and no text
hash is ever written by this module.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "src" / "vision") not in sys.path:
    sys.path.insert(0, str(ROOT / "src" / "vision"))

from tools.benchmarks.core.identity import S32Error, require  # noqa: E402

ADAPTER_ID = "lrlpr26"
ADAPTER_VERSION = "1"
DATA = Path("E:/MAVI-Controlled/Benchmarks/lrlpr-26")
TRAIN_ROOT = DATA / "extracted" / "train.zip" / "train"
TRAIN_ARCHIVE = DATA / "archives" / "dropbox-mirror" / "train.zip"
TRAIN_MANIFEST = DATA / "manifests" / "dropbox__train.sha256"
TRAIN_MANIFEST_DATAZIP = DATA / "manifests" / "datazip__train.sha256"
EXPECTED = {
    "trainArchiveSha256": "fb95f86dbf5666ce7d2f577605d55516f9ec558d25944f870dfca8b7f7c9fb8f",
    "trainArchiveBytes": 719723859,
    "trainManifestSha256": "efa5bb0885be3af13ff8e79c5f00e91e493d6a449fc333a5e422fbeee0e72b8c",
    "trainManifestRows": 200000,
    "tracks": 20000,
}
SCENARIOS = {"Scenario-A": "png", "Scenario-B": "jpg"}
LAYOUTS = ("Brazilian", "Mercosur")
TRACK_DIR = re.compile(r"track_[0-9]{5}")
FRAMES = tuple(f"{kind}-{n:03d}" for kind in ("lr", "hr") for n in range(1, 6))
SPLIT_ID = "lrlpr26-split-v1"
SPLIT_PREFIX = "lrlpr26-split-v1|"
BLOCK_PREFIX = "lrlpr26-block-v1|"
BLOCK_SIZE = 500
DEV, EVAL = "DEV", "EVAL"


class Lrlpr26Error(S32Error):
    pass


def fail(condition: bool, code: str) -> None:
    if not condition:
        raise Lrlpr26Error(code)


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class Frame:
    name: str
    path: Path
    sha256: str


@dataclass(frozen=True, slots=True)
class CropTrack:
    track_id: str
    scenario: str
    layout: str
    lr_frames: tuple[Frame, ...]
    truth: str

    @property
    def stratum(self) -> str:
        return f"{self.scenario}/{self.layout}"

    @property
    def number(self) -> int:
        return int(self.track_id.split("_")[1])


def normalised_truth(raw: object) -> str:
    from mavi_vision.plates.normalisation import OK, normalise

    fail(isinstance(raw, str), "lrlpr26_annotation_text_invalid")
    result = normalise(raw)
    fail(result.outcome == OK and result.normalised is not None, "lrlpr26_annotation_text_not_normalisable")
    return result.normalised


def read_manifest(path: Path) -> dict[str, tuple[str, int]]:
    """``<sha256>  <bytes>  <relative path>`` per line → {relative path: (sha256, bytes)}."""
    rows: dict[str, tuple[str, int]] = {}
    for line in path.read_bytes().decode("utf-8").splitlines():
        parts = line.split("  ", 2)
        fail(len(parts) == 3 and re.fullmatch(r"[0-9a-f]{64}", parts[0]) is not None and parts[1].isdigit(),
             "lrlpr26_manifest_row_invalid")
        fail(parts[2] not in rows, "lrlpr26_manifest_duplicate_path")
        rows[parts[2]] = (parts[0], int(parts[1]))
    return rows


def discover(root: Path) -> list[tuple[str, str, str, dict[str, str]]]:
    """Every track as (track_id, scenario, layout, {frame name or 'annotations': relative path}); fail closed."""
    fail(root.is_dir(), "lrlpr26_root_missing")
    fail(sorted(p.name for p in root.iterdir()) == sorted(SCENARIOS), "lrlpr26_unexpected_scenarios")
    found = []
    seen: set[str] = set()
    for scenario in sorted(SCENARIOS):
        ext = SCENARIOS[scenario]
        sdir = root / scenario
        fail(sdir.is_dir() and sorted(p.name for p in sdir.iterdir()) == list(LAYOUTS), "lrlpr26_unexpected_layouts")
        for layout in LAYOUTS:
            for tdir in sorted((sdir / layout).iterdir()):
                fail(tdir.is_dir() and TRACK_DIR.fullmatch(tdir.name) is not None, "lrlpr26_unexpected_entry")
                fail(tdir.name not in seen, "lrlpr26_duplicate_track_id")
                seen.add(tdir.name)
                expected = {f"{frame}.{ext}" for frame in FRAMES} | {"annotations.json"}
                present = {p.name for p in tdir.iterdir()}
                fail(present == expected and all((tdir / name).is_file() for name in present),
                     f"lrlpr26_unexpected_track_files:{tdir.name}")
                files = {frame: f"{scenario}/{layout}/{tdir.name}/{frame}.{ext}" for frame in FRAMES}
                files["annotations"] = f"{scenario}/{layout}/{tdir.name}/annotations.json"
                found.append((tdir.name, scenario, layout, files))
    return found


def load_tracks(root: Path = TRAIN_ROOT, manifest: Path = TRAIN_MANIFEST, archive: Path | None = TRAIN_ARCHIVE,
                expected: dict[str, Any] | None = None) -> tuple[list[CropTrack], dict[str, Any]]:
    """The hash-bound tracks and a text-free inventory. ``archive=None`` skips the archive comparison (tests only
    pass synthetic archives; the experiment always binds the real one)."""
    expected = EXPECTED if expected is None else expected
    manifest_sha = sha_file(manifest)
    fail(manifest_sha == expected["trainManifestSha256"], "lrlpr26_manifest_sha_mismatch")
    rows = read_manifest(manifest)
    fail(len(rows) == expected["trainManifestRows"], "lrlpr26_manifest_rowcount")
    archive_doc: dict[str, Any] | None = None
    members: dict[str, bytes] = {}
    if archive is not None:
        archive_sha = sha_file(archive)
        fail(archive_sha == expected["trainArchiveSha256"] and archive.stat().st_size == expected["trainArchiveBytes"],
             "lrlpr26_archive_sha_mismatch")
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                if info.filename.endswith("/annotations.json"):
                    fail(info.filename.startswith("train/"), "lrlpr26_archive_member_outside_train")
                    members[info.filename[len("train/"):]] = zf.read(info)
        archive_doc = {"sha256": archive_sha, "bytes": archive.stat().st_size, "annotationMembers": len(members)}
    discovered = discover(root)
    fail(len(discovered) == expected["tracks"], "lrlpr26_track_count")
    image_paths = {rel for _, _, _, files in discovered for key, rel in files.items() if key != "annotations"}
    fail(image_paths == set(rows), "lrlpr26_manifest_population_differs")
    if archive is not None:
        fail(set(members) == {files["annotations"] for _, _, _, files in discovered},
             "lrlpr26_archive_annotation_population_differs")
    tracks: list[CropTrack] = []
    image_hashes: dict[str, list[str]] = {}
    annotation_digest = hashlib.sha256()
    for track_id, scenario, layout, files in discovered:
        frames = []
        hashes = []
        for frame in FRAMES:
            rel = files[frame]
            path = root / rel
            digest = sha_file(path)
            fail(digest == rows[rel][0] and path.stat().st_size == rows[rel][1], f"lrlpr26_image_mismatch:{rel}")
            hashes.append(digest)
            if frame.startswith("lr"):
                frames.append(Frame(frame, path, digest))
        data = (root / files["annotations"]).read_bytes()
        if archive is not None:
            fail(data == members[files["annotations"]], f"lrlpr26_annotation_differs_from_archive:{track_id}")
        annotation_digest.update(f"{files['annotations']}\0{sha_bytes(data)}\n".encode("utf-8"))
        try:
            annotation = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise Lrlpr26Error(f"lrlpr26_annotation_invalid:{track_id}") from exc
        fail(isinstance(annotation, dict) and annotation.get("plate_layout") == layout,
             f"lrlpr26_annotation_layout:{track_id}")
        tracks.append(CropTrack(track_id, scenario, layout, tuple(frames), normalised_truth(annotation.get("plate_text"))))
        image_hashes[track_id] = hashes
    inventory = {
        "adapter": {"id": ADAPTER_ID, "version": ADAPTER_VERSION},
        "trainManifest": {"sha256": manifest_sha, "rows": len(rows)},
        "trainArchive": archive_doc,
        "annotationsDigest": annotation_digest.hexdigest(),
        "tracks": len(tracks),
        "lrFrames": {t.track_id: [f.sha256 for f in t.lr_frames] for t in tracks},
    }
    return tracks, {"inventory": inventory, "imageHashes": image_hashes}


# split ------------------------------------------------------------------------------------------------------------

def _hash_side(key: str) -> str:
    return EVAL if int(sha_bytes(key.encode("utf-8")), 16) % 2 == 1 else DEV


def plate_groups(tracks: list[CropTrack], image_hashes: dict[str, list[str]]) -> dict[str, list[str]]:
    """Union-find over shared normalised text or shared byte-identical image; {root track id: member ids}."""
    parent: dict[Any, Any] = {}

    def find(x: Any) -> Any:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: Any, b: Any) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb, key=repr)] = min(ra, rb, key=repr)

    for t in tracks:
        union(("t", t.track_id), ("x", t.truth))
        for digest in image_hashes[t.track_id]:
            union(("t", t.track_id), ("i", digest))
    groups: dict[Any, list[str]] = {}
    for t in tracks:
        groups.setdefault(find(("t", t.track_id)), []).append(t.track_id)
    return {min(members): sorted(members) for members in groups.values()}


def build_split(tracks: list[CropTrack], image_hashes: dict[str, list[str]], identities: dict[str, Any]) -> dict[str, Any]:
    by_id = {t.track_id: t for t in tracks}
    groups = plate_groups(tracks, image_hashes)
    ordered = sorted(groups, key=lambda root: by_id[root].number)
    main: dict[str, str] = {}
    group_of: dict[str, int] = {}
    for index, root in enumerate(ordered):
        members = groups[root]
        side = _hash_side(SPLIT_PREFIX + min(by_id[m].truth for m in members))
        for m in members:
            main[m] = side
            group_of[m] = index
    # Secondary block split: 500-ID blocks per scenario; a plate-identity group whose tracks fall on both sides is a
    # conflict group and its EVAL-side tracks are excluded (DEV-side kept).
    block = {t.track_id: _hash_side(f"{BLOCK_PREFIX}{t.scenario}|{t.number // BLOCK_SIZE}") for t in tracks}
    excluded = sorted(m for root in ordered if len({block[x] for x in groups[root]}) > 1
                      for m in groups[root] if block[m] == EVAL)
    excluded_set = set(excluded)
    block_assign = {tid: ("EXCLUDED" if tid in excluded_set else block[tid]) for tid in block}

    def counts(assign: dict[str, str]) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for t in tracks:
            out.setdefault(t.stratum, {}).setdefault(assign[t.track_id], 0)
            out[t.stratum][assign[t.track_id]] += 1
        return {k: dict(sorted(v.items())) for k, v in sorted(out.items())}

    return {
        "id": SPLIT_ID,
        "class": "Development only; text-free (no plate text, no text hash)",
        "identities": identities,
        "rule": {
            "groups": "union-find components over tracks sharing a normalised plate text (MAVI normalise) or any "
                      "byte-identical image (LR or HR, per-file manifest SHA-256)",
            "assignment": "EVAL if int(sha256('lrlpr26-split-v1|' + min normalised text in group), 16) % 2 == 1, else DEV",
            "groupIndex": "groups numbered 0.. in order of their smallest track number",
            "blockSplit": "secondary only: block = (scenario, trackNumber // 500); EVAL if "
                          "int(sha256('lrlpr26-block-v1|' + scenario + '|' + str(block)), 16) % 2 == 1, else DEV; a "
                          "plate-identity group with tracks on both block sides is a conflict group and its EVAL-side "
                          "tracks are EXCLUDED",
        },
        "counts": {"tracks": len(tracks), "groups": len(ordered),
                   "groupsBySide": {side: len({group_of[t] for t in main if main[t] == side}) for side in (DEV, EVAL)},
                   "byStratum": counts(main)},
        "blockSplitCounts": {"excluded": len(excluded), "byStratum": counts(block_assign),
                             "conflictGroups": sum(1 for root in ordered if len({block[x] for x in groups[root]}) > 1)},
        "tracks": {tid: [main[tid], group_of[tid], block_assign[tid]] for tid in sorted(main, key=lambda x: by_id[x].number)},
    }


def read_truths(wanted: set[str], expected_digest: str, root: Path = TRAIN_ROOT) -> dict[str, str]:
    """Truth for the ``wanted`` track ids only. Every annotation is read so that the aggregate annotation digest
    (bound in the inventory) is re-verified; only the wanted texts are normalised and returned."""
    digest = hashlib.sha256()
    truths: dict[str, str] = {}
    discovered = discover(root)
    for track_id, _, layout, files in discovered:
        data = (root / files["annotations"]).read_bytes()
        digest.update(f"{files['annotations']}\0{sha_bytes(data)}\n".encode("utf-8"))
        if track_id in wanted:
            annotation = json.loads(data.decode("utf-8"))
            fail(isinstance(annotation, dict) and annotation.get("plate_layout") == layout,
                 f"lrlpr26_annotation_layout:{track_id}")
            truths[track_id] = normalised_truth(annotation.get("plate_text"))
    fail(digest.hexdigest() == expected_digest, "lrlpr26_annotations_digest_mismatch")
    fail(set(truths) == wanted, "lrlpr26_truth_population")
    return truths


def split_identities(inventory: dict[str, Any]) -> dict[str, Any]:
    """The text-free data identities a split file binds (from ``load_tracks``'s inventory)."""
    fail(inventory.get("trainArchive") is not None, "lrlpr26_split_needs_archive_binding")
    return {
        "datasetRecord": "docs/qualification/stage4/lrlpr-26-dataset-record-2026-10-18.md",
        "trainArchive": {"name": "train.zip (Dropbox mirror)", "sha256": inventory["trainArchive"]["sha256"],
                         "bytes": inventory["trainArchive"]["bytes"]},
        "trainManifest": {"name": "manifests/dropbox__train.sha256", "sha256": inventory["trainManifest"]["sha256"],
                          "rows": inventory["trainManifest"]["rows"],
                          "equalTo": "manifests/datazip__train.sha256 (same SHA-256)"},
        "annotationsDigest": {"sha256": inventory["annotationsDigest"],
                              "rule": "sha256 over sorted lines '<relative path>\\0<sha256(annotations.json bytes)>\\n' "
                                      "(aggregate only; per-file annotation hashes are not recorded)"},
        "normalisation": "mavi-plate-normalisation-v1 (src/vision/mavi_vision/plates/normalisation.py)",
    }


def load_split(path: Path, expected_sha: str) -> dict[str, Any]:
    data = path.read_bytes()
    fail(sha_bytes(data) == expected_sha, "lrlpr26_split_sha_mismatch")
    document = json.loads(data)
    fail(document.get("id") == SPLIT_ID, "lrlpr26_split_id")
    return document
