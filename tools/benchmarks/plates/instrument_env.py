"""Offline packaging of the Stage-4 instrument environment's model payloads (Development benchmark only).

Standard library only, so it runs from any Python before the instrument environment exists.

    fetch-payloads --dest CACHE_DIR
        Connected preparation: download every 'url' payload of instrument-payloads-v1.json into CACHE_DIR, verifying
        SHA-256. Existing verified files are kept; a mismatch is refused and nothing unverified is retained.
    stage-models --cache CACHE_DIR --site-packages SITE_DIR --model-root MODEL_ROOT
        Offline: place every payload under MODEL_ROOT/<instrumentId>/ from CACHE_DIR ('url') or from the installed
        wheel under SITE_DIR ('wheel'), verifying each against the manifest and the instrument specification. No
        network access.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = Path(__file__).with_name("instrument-payloads-v1.json")
SPECS = ROOT / "docs" / "qualification" / "stage4" / "instruments"


class PayloadError(Exception):
    pass


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_manifest(path: Path = MANIFEST, specs: Path = SPECS) -> list[dict]:
    """The manifest's instruments, each checked file-for-file against its instrument specification."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schemaVersion") != "benchmark-plate-instrument-payloads-v1":
        raise PayloadError("payload_manifest_invalid:schema")
    for instrument in document["instruments"]:
        spec = json.loads((specs / f"{instrument['instrumentId']}.json").read_text(encoding="utf-8"))
        declared = {f["path"]: f["sha256"] for f in spec["modelFiles"]}
        listed = {f["path"]: f["sha256"] for f in instrument["files"]}
        if declared != listed:
            raise PayloadError(f"payload_manifest_invalid:spec_mismatch:{instrument['instrumentId']}")
        for item in instrument["files"]:
            if item["source"]["kind"] not in ("url", "wheel"):
                raise PayloadError(f"payload_manifest_invalid:source:{item['path']}")
    return document["instruments"]


def _cache_path(cache: Path, instrument_id: str, item: dict) -> Path:
    return cache / instrument_id / item["path"]


def fetch_payloads(cache: Path, opener=urllib.request.urlopen) -> list[Path]:
    fetched = []
    for instrument in load_manifest():
        for item in instrument["files"]:
            if item["source"]["kind"] != "url":
                continue
            target = _cache_path(cache, instrument["instrumentId"], item)
            if target.is_file() and _sha(target) == item["sha256"]:
                fetched.append(target)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
                partial = Path(handle.name)
                with opener(item["source"]["url"]) as response:
                    shutil.copyfileobj(response, handle)
            if _sha(partial) != item["sha256"]:
                partial.unlink()
                raise PayloadError(f"payload_hash_mismatch:{item['path']}")
            partial.replace(target)
            fetched.append(target)
    return fetched


def stage_models(cache: Path, site_packages: Path, model_root: Path) -> list[Path]:
    staged = []
    for instrument in load_manifest():
        for item in instrument["files"]:
            source = (_cache_path(cache, instrument["instrumentId"], item) if item["source"]["kind"] == "url"
                      else site_packages / item["source"]["member"])
            if not source.is_file():
                raise PayloadError(f"payload_missing:{source}")
            if _sha(source) != item["sha256"]:
                raise PayloadError(f"payload_hash_mismatch:{source}")
            target = model_root / instrument["instrumentId"] / item["path"]
            if target.is_file() and _sha(target) == item["sha256"]:
                staged.append(target)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            if _sha(target) != item["sha256"]:
                raise PayloadError(f"payload_hash_mismatch:{target}")
            staged.append(target)
    return staged


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("fetch-payloads")
    f.add_argument("--dest", type=Path, required=True)
    s = sub.add_parser("stage-models")
    s.add_argument("--cache", type=Path, required=True)
    s.add_argument("--site-packages", type=Path, required=True)
    s.add_argument("--model-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        paths = (fetch_payloads(args.dest) if args.command == "fetch-payloads"
                 else stage_models(args.cache, args.site_packages, args.model_root))
    except PayloadError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
