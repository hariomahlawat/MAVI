#!/usr/bin/env python3
"""Blind labelling pack builder (Stage 3, S3.2 plan T4).

A pack is a directory a reviewer opens from disk (``index.html``, no server, no
network): per selected Track its verified Evidence Set crops and one context frame
per observation with the observation box drawn. Reviewer-visible files carry no
predicted subclass, confidence, run or Track id, or producer detail; the hidden
run/Track mapping lives only in ``pack-manifest.json``.

Identity: ``packSha256`` is the SHA-256 of the canonical manifest bytes. The
manifest's ``files[]`` lists every pack file except itself and ``pack-data.js``;
``pack-data.js`` is derived from the manifest afterwards (it carries ``packSha256``)
and is checked by regenerating it, so neither file hashes itself.

Usage::

    build_labeling_pack.py --sample <file> --export <file>... --source <mp4>...
        --pipeline-profile <file> --labeling-guide <file> --labeling-guide-commit <sha>
        --seed <text> --reviewer-view primary|overlap [--parent-pack <primary-pack-dir>]
        [--repository <git-dir>] --out <new-dir>
"""

from __future__ import annotations

import argparse
import hashlib
import io
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import artefacts as a  # noqa: E402

TEMPLATES = Path(__file__).resolve().parent / "labeling"
TEMPLATE_FILES = ("index.html", "labeling.js", "labeling.css")
MANIFEST = "pack-manifest.json"
PACK_DATA = "pack-data.js"
GUIDE = "labeling-guide.md"
MAX_LONG_EDGE = 1280
RENDER_RULE = "context-v1"
BOX_COLOUR = (255, 0, 0)
ROLE_ORDER = ("Representative", "NearView", "EarlyDiverse", "LateDiverse")


# pack-data.js and pack verification (shared with T5 and T6)


def pack_data(manifest: dict[str, Any], pack_sha256: str) -> bytes:
    """The reviewer-facing payload, a pure function of the manifest: item ids and image paths only."""
    payload = {
        "packSha256": pack_sha256,
        "guide": manifest["labelingGuide"]["path"],
        "items": [
            {"itemId": item["itemId"],
             "views": [{"path": view["path"], "label": f"{view['kind']} {view['evidenceRole']}"} for view in item["views"]]}
            for item in manifest["items"]
        ],
    }
    return b"window.MAVI_PACK = " + a.canonical_json(payload) + b";\n"


def verify_pack(directory: Path) -> tuple[dict[str, Any], str]:
    """A pack exactly as built: canonical manifest, every listed file, nothing extra, and the derived payload."""
    directory = Path(directory)
    manifest, _, pack_sha = a.read_artefact(directory / MANIFEST, "vehicle-subclass-labeling-pack-v1", "pack_manifest_invalid")
    listed = {entry["path"] for entry in manifest["files"]}
    a.require(len(listed) == len(manifest["files"]), "pack_inventory_mismatch:duplicate")
    for entry in manifest["files"]:
        path = a.safe_relative(entry["path"], "pack_inventory_mismatch")
        data = a.read_bytes(directory / path, "pack_inventory_mismatch")
        a.require(a.sha256_hex(data) == entry["sha256"] and len(data) == entry["sizeBytes"], f"pack_file_changed:{path}")
    present = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()}
    a.require(present == listed | {MANIFEST, PACK_DATA}, "pack_inventory_mismatch")
    for item in manifest["items"]:
        for view in item["views"]:
            a.require(view["path"] in listed, "pack_inventory_mismatch:view")
            entry = next(e for e in manifest["files"] if e["path"] == view["path"])
            a.require(entry["sha256"] == view["sha256"] and entry["sizeBytes"] == view["sizeBytes"], "pack_inventory_mismatch:view")
    a.require(a.read_bytes(directory / PACK_DATA, "pack_data_mismatch") == pack_data(manifest, pack_sha), "pack_data_mismatch")
    return manifest, pack_sha


# Inputs


def _profile(path: Path, exports: dict[str, a.Export]) -> tuple[str, str, str]:
    data = a.read_bytes(path, "pack_profile_mismatch")
    sha = a.sha256_hex(data)
    for export in exports.values():
        a.require(export.document["profile"]["pipelineProfileSha256"] == sha, "pack_profile_mismatch")
    document = a.parse_json(data, "pack_profile_invalid")
    evidence = document.get("evidence") if isinstance(document, dict) else None
    a.require(isinstance(evidence, dict), "pack_profile_invalid")
    selector, scorer = evidence.get("selectorVersion"), evidence.get("scorerVersion")
    a.require(isinstance(selector, str) and isinstance(scorer, str), "pack_profile_invalid")
    for export in exports.values():
        a.require(export.document["profile"]["evidenceSelectorVersion"] == selector
                  and export.document["profile"]["evidenceScorerVersion"] == scorer, "pack_profile_mismatch:evidence")
    return sha, selector, scorer


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as stream:
            for block in iter(lambda: stream.read(1 << 20), b""):
                digest.update(block)
    except OSError as exc:
        raise a.S32Error(f"source_unreadable:{Path(path).name}") from exc
    return digest.hexdigest()


def _sources(paths: list[Path], needed: set[str]) -> dict[str, Path]:
    """Source videos mapped by their actual SHA-256, never by argument order. A video no item needs
    (an overlap pack may cover one camera) is simply not read; a missing or duplicated one refuses."""
    by_sha: dict[str, Path] = {}
    for path in paths:
        sha = _file_sha256(path)
        a.require(sha not in by_sha, "source_ambiguous")
        by_sha[sha] = Path(path)
    a.require(needed <= set(by_sha), "source_missing")
    return {sha: path for sha, path in by_sha.items() if sha in needed}


def _template(directory: Path, name: str) -> bytes:
    return a.canonical_text(a.read_bytes(directory / name, "pack_asset_missing"), "pack_asset_not_utf8")


# Rendering


def decoder_identity() -> dict[str, str]:
    import av

    version = av.library_versions.get("libavcodec", ())
    return {"av": av.__version__, "libavcodec": ".".join(str(part) for part in version)}


def render_context(rgb, box: dict[str, float]) -> bytes:
    """A decoded frame, downscaled to at most 1280 px on its long edge, with the box drawn; PNG bytes."""
    from PIL import Image, ImageDraw

    image = Image.fromarray(rgb).convert("RGB")
    width, height = image.size
    scale = min(1.0, MAX_LONG_EDGE / max(width, height))
    if scale < 1.0:
        image = image.resize((max(1, round(width * scale)), max(1, round(height * scale))), Image.Resampling.BILINEAR)
    width, height = image.size
    x0 = min(width - 1, max(0, round(box["x"] * width)))
    y0 = min(height - 1, max(0, round(box["y"] * height)))
    x1 = min(width - 1, max(x0, round((box["x"] + box["width"]) * width) - 1))
    y1 = min(height - 1, max(y0, round((box["y"] + box["height"]) * height) - 1))
    line = max(2, round(min(width, height) / 240))
    ImageDraw.Draw(image).rectangle([x0, y0, x1, y1], outline=BOX_COLOUR, width=line)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", compress_level=6)
    return buffer.getvalue()


def _render_frames(source: Path, requests: dict[int, list[tuple[str, dict[str, float]]]]) -> dict[str, bytes]:
    """Decodes the source once, in order, rendering each requested frame as it is reached."""
    import av

    rendered: dict[str, bytes] = {}
    wanted = dict(requests)
    try:
        with av.open(str(source)) as container:
            stream = container.streams.video[0]
            for index, frame in enumerate(container.decode(stream)):
                if index in wanted:
                    rgb = frame.to_ndarray(format="rgb24")
                    for path, box in wanted.pop(index):
                        rendered[path] = render_context(rgb, box)
                if not wanted:
                    break
    except av.FFmpegError as exc:
        raise a.S32Error(f"source_undecodable:{source.name}") from exc
    a.require(not wanted, "frame_outside_video")
    return rendered


# Build


def _guide(repository: Path, path: Path, commit: str) -> tuple[dict[str, str], bytes]:
    """The labelling guide: committed unchanged at ``commit`` (an ancestor of HEAD), canonical, and the
    owner-approved registered guide (plan §5; register G2)."""
    binding = a.git_binding(repository, path, commit, a.LABELING_GUIDE_GIT_PATH, "labeling_guide_not_committed")
    guide_bytes = a.read_bytes(path, "labeling_guide_not_committed")
    a.require(a.canonical_text(guide_bytes, "labeling_guide_not_canonical") == guide_bytes, "labeling_guide_not_canonical")
    a.require_preregistered(binding, "labeling_guide_not_preregistered")
    guide = {"sha256": binding["sha256"], "gitCommit": binding["gitCommit"], "gitPath": binding["gitPath"], "path": GUIDE}
    return guide, guide_bytes


def build(args: argparse.Namespace, staging: Path) -> tuple[dict[str, Any], str]:
    sample, _, sample_sha = a.read_artefact(args.sample, "vehicle-subclass-sample-v1", "pack_sample_invalid")
    exports = a.load_exports(args.export)
    a.require(sorted(exports) == sorted(sample["exportSha256s"]), "pack_exports_mismatch")
    profile_sha, selector, scorer = _profile(args.pipeline_profile, exports)
    guide, guide_bytes = _guide(args.repository, args.labeling_guide, args.labeling_guide_commit)
    a.require(isinstance(args.seed, str) and args.seed.strip() == args.seed and args.seed, "seed_invalid")

    view_kind = args.reviewer_view
    a.require(view_kind in ("primary", "overlap"), "reviewer_view_invalid")
    parent_sha = None
    if view_kind == "primary":
        a.require(args.parent_pack is None, "parent_pack_invalid:unexpected")
        chosen = sample["selected"]
    else:
        a.require(args.parent_pack is not None, "parent_pack_invalid:missing")
        try:
            parent, parent_sha = verify_pack(args.parent_pack)
        except a.S32Error as exc:
            raise a.S32Error(f"parent_pack_invalid:{exc}") from exc
        a.require(parent["viewKind"] == "primary", "parent_pack_invalid:view")
        a.require(parent["sampleSha256"] == sample_sha, "parent_pack_invalid:sample")
        a.require(parent["exportSha256s"] == sorted(sample["exportSha256s"]), "parent_pack_invalid:exports")
        a.require(parent["labelingGuide"] == guide, "parent_pack_invalid:guide")
        chosen = sample["overlapSelected"]

    by_run = {export.run_id: export for export in exports.values()}
    pack_seed = a.h("pack", args.seed, view_kind)
    items: list[dict[str, Any]] = []
    files: dict[str, bytes] = {}
    requests: dict[str, dict[int, list[tuple[str, dict[str, float]]]]] = {}
    for entry in chosen:
        export = by_run.get(entry["processingRunId"])
        a.require(export is not None, "pack_track_invalid:run")
        track = export.track(entry["trackId"])
        a.require(track is not None and track["objectClass"] == "Vehicle", "pack_track_invalid")
        item_id = a.h(pack_seed, entry["processingRunId"], entry["trackId"])[:16]
        source_sha = export.video["sourceSha256"]
        views = []
        for observation in sorted(track["observations"], key=lambda o: o["evidenceRank"])[:4]:
            try:
                crop = export.require_evidence(observation)
            except a.S32Error as exc:
                raise a.S32Error("pack_evidence_mismatch") from exc
            rank = observation["evidenceRank"]
            crop_path = f"items/{item_id}/crop-{rank}.jpg"
            context_path = f"items/{item_id}/context-{rank}.png"
            files[crop_path] = crop
            requests.setdefault(source_sha, {}).setdefault(observation["sourceFrameNumber"], []).append(
                (context_path, observation["boundingBox"]))
            for kind, path in (("crop", crop_path), ("context", context_path)):
                views.append({"kind": kind, "evidenceRole": observation["evidenceRole"],
                              "sourceFrameNumber": observation["sourceFrameNumber"],
                              "videoOffsetMs": observation["videoOffsetMs"], "path": path})
        a.require(views, "pack_track_invalid:no_evidence")
        items.append({"itemId": item_id, "processingRunId": entry["processingRunId"], "trackId": entry["trackId"],
                      "videoSourceSha256": source_sha, "views": views})
    a.require(len({item["itemId"] for item in items}) == len(items), "pack_item_collision")

    sources = _sources(args.source, set(requests))
    for source_sha, frame_requests in sorted(requests.items()):
        files.update(_render_frames(sources[source_sha], frame_requests))

    for name in TEMPLATE_FILES:
        files[name] = _template(args.templates, name)
    files[GUIDE] = guide_bytes  # canonical, and byte-identical to the committed blob
    for item in items:
        for view in item["views"]:
            view["sha256"] = a.sha256_hex(files[view["path"]])
            view["sizeBytes"] = len(files[view["path"]])

    from PIL import __version__ as pillow_version
    manifest: dict[str, Any] = {
        "schemaVersion": "vehicle-subclass-labeling-pack-v1",
        "viewKind": view_kind,
        "seed": args.seed,
        "sampleSha256": sample_sha,
        "exportSha256s": sorted(exports),
        "pipelineProfileSha256": profile_sha,
        "evidenceSelectorVersion": selector,
        "evidenceScorerVersion": scorer,
        "labelingGuide": guide,
        "extraction": {"decoder": decoder_identity(), "renderer": {"pillow": pillow_version},
                       "renderRuleVersion": RENDER_RULE, "maxLongEdgePx": MAX_LONG_EDGE},
        "items": sorted(items, key=lambda item: item["itemId"]),
        "files": [{"path": path, "sha256": a.sha256_hex(data), "sizeBytes": len(data)} for path, data in sorted(files.items())],
    }
    if parent_sha is not None:
        manifest["parentPackSha256"] = parent_sha
    a.validate(manifest, "vehicle-subclass-labeling-pack-v1", "pack_manifest_invalid")
    manifest_bytes = a.canonical_json(manifest)
    pack_sha = a.sha256_hex(manifest_bytes)
    for path, data in files.items():
        a.write_text_file(staging, path, data)
    (staging / MANIFEST).write_bytes(manifest_bytes)
    (staging / PACK_DATA).write_bytes(pack_data(manifest, pack_sha))
    return manifest, pack_sha


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--sample", type=Path, required=True)
    p.add_argument("--export", type=Path, action="append", required=True)
    p.add_argument("--source", type=Path, action="append", required=True)
    p.add_argument("--pipeline-profile", type=Path, required=True)
    p.add_argument("--labeling-guide", type=Path, required=True)
    p.add_argument("--labeling-guide-commit", required=True)
    p.add_argument("--seed", required=True)
    p.add_argument("--reviewer-view", required=True)
    p.add_argument("--parent-pack", type=Path)
    p.add_argument("--repository", type=Path, default=a.ROOT,
                   help="the git repository holding the committed guide (default: this MAVI checkout)")
    p.add_argument("--templates", type=Path, default=TEMPLATES, help=argparse.SUPPRESS)
    p.add_argument("--out", type=Path, required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        with a.OutputDirectory(args.out) as staging:
            _, pack_sha = build(args, staging)
    except a.S32Error as exc:
        print(f"refused {exc}", file=sys.stderr)
        return 2
    print(pack_sha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
