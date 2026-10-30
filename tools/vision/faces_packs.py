"""PoC S6 (ADR-022): the face Model Pack payloads, collected and staged with SHA-256 verification.

The committed manifest (``models/manifests/faces-yunet-adaface-ir50-dev-v1.json``) is the authority. The AdaFace
embedder is exported by ``tools/vision/build_face_packs.py`` from the pinned upstream checkpoint and YuNet is copied
from opencv_zoo, so there is no upstream URL for the pack. The verified bytes live in the PoC controlled store
(``E:\\MAVI-Controlled\\PoC\\S6\\pack`` on the Development host), are collected into the developer offline cache and
staged from there. Every byte is checked against the manifest; nothing is downloaded. Model bytes and biometric
derivatives are never written to the repository or the kit's media.

    python tools/vision/faces_packs.py check
    python tools/vision/faces_packs.py collect --source <controlled store> --dest <cache>/faces-payloads
    python tools/vision/faces_packs.py stage --source <cache>/faces-payloads --model-root <dir>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = "models/manifests/faces-yunet-adaface-ir50-dev-v1.json"


class PackError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load(root: Path = ROOT) -> list[tuple[str, str]]:
    """The (relative path, SHA-256) list of the manifest; paths stay inside the pack directory."""
    manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    if manifest.get("verificationStatus") != "unverified" or manifest.get("capabilityIds") != ["embedding"]:
        raise PackError("faces_manifest_unexpected")
    items = []
    for artifact in manifest["artifacts"]:
        path = PurePosixPath(artifact["relativePath"])
        if path.is_absolute() or ".." in path.parts or len(path.parts) != 2:
            raise PackError(f"faces_artifact_path:{path}")
        items.append((path.as_posix(), artifact["sha256"]))
    if len({path.parts[0] for path in map(PurePosixPath, (item[0] for item in items))}) != 1:
        raise PackError("faces_pack_directory_ambiguous")
    return items


def _copy_verified(source: Path, target: Path, sha256: str) -> None:
    if target.is_file() and _sha256(target) == sha256:
        return
    if not source.is_file():
        raise PackError(f"faces_payload_missing:{source.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".partial")
    shutil.copyfile(source, partial)
    if _sha256(partial) != sha256:
        partial.unlink()
        raise PackError(f"faces_payload_hash_mismatch:{source.name}")
    partial.replace(target)


def collect(source: Path, dest: Path) -> None:
    """Connected cache preparation: copy every payload from the controlled store, verified before it is kept."""
    for relative, sha256 in load():
        _copy_verified(source / relative, dest / relative, sha256)


def stage(source: Path, model_root: Path) -> None:
    """Offline staging into the model store the faces worker reads; refuses any byte not in the manifest."""
    for relative, sha256 in load():
        _copy_verified(source / relative, model_root / relative, sha256)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check")
    collect_parser = commands.add_parser("collect")
    collect_parser.add_argument("--source", type=Path, required=True)
    collect_parser.add_argument("--dest", type=Path, required=True)
    stage_parser = commands.add_parser("stage")
    stage_parser.add_argument("--source", type=Path, required=True)
    stage_parser.add_argument("--model-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            print(f"{len(load())} face payloads pinned by {MANIFEST}")
        elif args.command == "collect":
            collect(args.source, args.dest)
        else:
            stage(args.source, args.model_root)
    except PackError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
