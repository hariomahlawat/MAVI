"""Issue #225 Development pilot Model Packs: fetch (connected) and stage (offline) with SHA-256 verification.

The committed manifests (``models/manifests/plates-*-dev-v1.json``) are the authority: every payload in
``tools/vision/plates-pilot-payloads-v1.json`` must equal its manifest artefact, and staging refuses any byte that does
not hash to it. Model bytes are never written to the repository.

    python tools/vision/plates_pilot_packs.py check
    python tools/vision/plates_pilot_packs.py fetch --dest <cache>/plates-pilot-payloads           (connected)
    python tools/vision/plates_pilot_packs.py collect --source E:/MAVI-Controlled/Benchmarks/plate-candidates \
        --dest <cache>/plates-pilot-payloads    (cache from the controlled store, when a download is refused)
    python tools/vision/plates_pilot_packs.py stage --source <cache>/plates-pilot-payloads --model-root <dir>
    python tools/vision/plates_pilot_packs.py stage --source E:/MAVI-Controlled/Benchmarks/plate-candidates \
        --controlled-store --model-root <dir>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import urllib.request
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
PAYLOADS = ROOT / "tools/vision/plates-pilot-payloads-v1.json"
SCHEMA = "mavi-plates-pilot-payloads-v1"


class PackError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load(root: Path = ROOT) -> list[dict]:
    """The payload list, each checked against its committed manifest artefact (one payload per artefact)."""
    document = json.loads((root / "tools/vision/plates-pilot-payloads-v1.json").read_text(encoding="utf-8"))
    if document.get("schemaVersion") != SCHEMA:
        raise PackError("plates_pilot_payloads_schema")
    payloads = document["payloads"]
    expected: dict[tuple[str, str], str] = {}
    for manifest_path in sorted({item["manifest"] for item in payloads}):
        manifest = json.loads((root / manifest_path).read_text(encoding="utf-8"))
        for artifact in manifest["artifacts"]:
            expected[(manifest_path, artifact["relativePath"])] = artifact["sha256"]
    seen = set()
    for item in payloads:
        name = PurePosixPath(item["packDirectory"]) / item["file"]
        if name.parent.as_posix() != item["packDirectory"] or ".." in name.parts:
            raise PackError(f"plates_pilot_payload_path:{name}")
        key = (item["manifest"], name.as_posix())
        if expected.get(key) != item["sha256"]:
            raise PackError(f"plates_pilot_payload_manifest_mismatch:{name}")
        seen.add(key)
    if seen != set(expected):
        raise PackError("plates_pilot_payloads_incomplete")
    return payloads


def fetch(dest: Path) -> None:
    """Connected cache preparation: download every payload once, verified before it is kept."""
    for item in load():
        target = dest / item["packDirectory"] / item["file"]
        if target.is_file() and _sha256(target) == item["sha256"]:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".partial")
        with urllib.request.urlopen(item["url"], timeout=120) as response, open(partial, "wb") as out:  # noqa: S310
            shutil.copyfileobj(response, out)
        if _sha256(partial) != item["sha256"]:
            partial.unlink()
            raise PackError(f"plates_pilot_payload_hash_mismatch:{item['packDirectory']}/{item['file']}")
        partial.replace(target)


def stage(source: Path, model_root: Path, *, controlled_store: bool) -> list[str]:
    """Copy every payload into ``<model-root>/<packDirectory>/<file>``; refuse any hash mismatch."""
    staged = []
    for item in load():
        origin = source / item["controlledStorePath"] if controlled_store else source / item["packDirectory"] / item["file"]
        if not origin.is_file():
            raise PackError(f"plates_pilot_payload_missing:{item['packDirectory']}/{item['file']}")
        if _sha256(origin) != item["sha256"]:
            raise PackError(f"plates_pilot_payload_hash_mismatch:{item['packDirectory']}/{item['file']}")
        target = model_root / item["packDirectory"] / item["file"]
        if target.is_file() and _sha256(target) == item["sha256"]:
            staged.append(f"{item['packDirectory']}/{item['file']} (present)")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origin, target)
        if _sha256(target) != item["sha256"]:
            raise PackError(f"plates_pilot_payload_copy_mismatch:{item['packDirectory']}/{item['file']}")
        staged.append(f"{item['packDirectory']}/{item['file']}")
    return staged


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check")
    fetch_parser = commands.add_parser("fetch")
    fetch_parser.add_argument("--dest", type=Path, required=True)
    collect_parser = commands.add_parser("collect")
    collect_parser.add_argument("--source", type=Path, required=True)
    collect_parser.add_argument("--dest", type=Path, required=True)
    stage_parser = commands.add_parser("stage")
    stage_parser.add_argument("--source", type=Path, required=True)
    stage_parser.add_argument("--model-root", type=Path, required=True)
    stage_parser.add_argument("--controlled-store", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            print(f"{len(load())} payloads agree with their manifests")
        elif args.command == "fetch":
            fetch(args.dest)
        elif args.command == "collect":
            # The cache layout is the model-store layout, so collecting is staging from the controlled store.
            for line in stage(args.source, args.dest, controlled_store=True):
                print(line)
        else:
            for line in stage(args.source, args.model_root, controlled_store=args.controlled_store):
                print(line)
    except PackError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
