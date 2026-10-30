"""PoC S10 (ADR-026): the Language Runtime Pack and Language Model Packs, acquired, staged and verified by SHA-256.

``tools/language/language-payloads-v1.json`` is the acquisition record and the staging authority; each model file must
equal its source manifest's artefact (``models/language/*.json``). Downloads happen only in ``acquire``, on the
Development machine; everything after that is offline and refuses any byte that is not recorded. Bytes never enter Git.

    python tools/language/language_packs.py check
    python tools/language/language_packs.py acquire --dest <controlled store>                     (connected)
    python tools/language/language_packs.py collect --source <controlled store> --dest <cache>/language-payloads
    python tools/language/language_packs.py stage --source <cache>/language-payloads --runtime-root <dir> --model-root <dir>
    python tools/language/language_packs.py verify --runtime-root <dir> --variant cuda --model-root <dir> --pack <packDirectory>
    python tools/language/language_packs.py identity --pack <packDirectory>

Store layout (controlled store, cache and bundle alike): ``runtime/<archive>``, ``runtime/LICENSE``,
``runtime/cuda-eula-12.4.html`` and ``models/<packDirectory>/<file>``. Staged layout: ``<runtime-root>/<variant
directory>/`` holds exactly the archive contents, ``<runtime-root>/LICENSE`` the llama.cpp licence, and
``<model-root>/<packDirectory>/`` the model files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
PAYLOADS = "tools/language/language-payloads-v1.json"
SCHEMA = "mavi-language-payloads-v1"
MANIFEST_SCHEMA = "mavi-language-model-manifest-v1"
PACK_IDENTITY_SCHEMA = "mavi-language-model-pack-v1"


class PackError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_name(name: str) -> str:
    path = PurePosixPath(name)
    if path.is_absolute() or len(path.parts) != 1 or name in {"", ".", ".."} or "\\" in name:
        raise PackError(f"language_payload_name:{name}")
    return name


def load(root: Path = ROOT) -> dict:
    """The payload record, each model file checked against its source manifest artefact."""
    document = json.loads((root / PAYLOADS).read_text(encoding="utf-8"))
    if document.get("schemaVersion") != SCHEMA:
        raise PackError("language_payloads_schema")
    runtime = document["runtime"]
    _safe_name(runtime["licence"]["file"])
    for variant in runtime["variants"]:
        _safe_name(variant["directory"])
        for archive in variant["archives"]:
            _safe_name(archive["file"])
        for name in variant["files"]:
            _safe_name(name)
        if "nvidiaEula" in variant:
            _safe_name(variant["nvidiaEula"]["file"])
    for model in document["models"]:
        manifest = load_manifest(model["manifest"], root)
        if manifest["packDirectory"] != model["packDirectory"]:
            raise PackError(f"language_pack_directory_mismatch:{model['packDirectory']}")
        expected = {artifact["relativePath"]: artifact["sha256"] for artifact in manifest["artifacts"]}
        recorded = {f"{model['packDirectory']}/{_safe_name(item['file'])}": item["sha256"] for item in model["files"]}
        if expected != recorded:
            raise PackError(f"language_payload_manifest_mismatch:{model['packDirectory']}")
    return document


def load_manifest(relative: str, root: Path = ROOT) -> dict:
    manifest = json.loads((root / relative).read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != MANIFEST_SCHEMA or manifest.get("capabilityIds") != ["query-translation"]:
        raise PackError(f"language_manifest_unexpected:{relative}")
    if manifest.get("verificationStatus") != "unverified" or manifest["licence"]["spdxId"] != "Apache-2.0":
        raise PackError(f"language_manifest_unexpected:{relative}")
    roles = [artifact["artifactRole"] for artifact in manifest["artifacts"]]
    if "licence-notice" not in roles or len(set(roles)) != len(roles):
        raise PackError(f"language_manifest_roles:{relative}")
    for artifact in manifest["artifacts"]:
        path = PurePosixPath(artifact["relativePath"])
        if len(path.parts) != 2 or path.parts[0] != manifest["packDirectory"]:
            raise PackError(f"language_manifest_path:{artifact['relativePath']}")
        _safe_name(path.parts[1])
    if "3b" in manifest["modelId"].split("-") or "72b" in manifest["modelId"].split("-"):
        raise PackError("language_manifest_research_licensed_size")  # plan D7: never the 3B or 72B sizes
    return manifest


def pack_identity(manifest: dict) -> str:
    """``mavi-language-v1-`` + SHA-256 of the material inputs (the ADR-014 §3 derivation, its own schema name)."""
    payload = {
        "schemaVersion": PACK_IDENTITY_SCHEMA,
        "modelId": manifest["modelId"],
        "modelVersion": manifest["modelVersion"],
        "capabilityIds": sorted(manifest["capabilityIds"]),
        "artifacts": sorted(
            ({"artifactRole": item["artifactRole"], "sha256": item["sha256"]} for item in manifest["artifacts"]),
            key=lambda item: item["artifactRole"],
        ),
    }
    text = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    return "mavi-language-v1-" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _store_items(document: dict) -> list[tuple[str, str, str]]:
    """(store-relative path, sha256, url) for every payload byte."""
    runtime = document["runtime"]
    items = [(f"runtime/{runtime['licence']['file']}", runtime["licence"]["sha256"], runtime["licence"]["url"])]
    for variant in runtime["variants"]:
        items += [(f"runtime/{archive['file']}", archive["sha256"], archive["url"]) for archive in variant["archives"]]
        if "nvidiaEula" in variant:
            eula = variant["nvidiaEula"]
            items.append((f"runtime/{eula['file']}", eula["sha256"], eula["url"]))
    for model in document["models"]:
        items += [(f"models/{model['packDirectory']}/{item['file']}", item["sha256"], item["url"]) for item in model["files"]]
    return items


def _copy_verified(source: Path, target: Path, sha256: str) -> None:
    if target.is_file() and sha256_file(target) == sha256:
        return
    if not source.is_file():
        raise PackError(f"language_payload_missing:{source.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".partial")
    shutil.copyfile(source, partial)
    if sha256_file(partial) != sha256:
        partial.unlink()
        raise PackError(f"language_payload_hash_mismatch:{source.name}")
    partial.replace(target)


def acquire(dest: Path) -> None:
    """Connected, Development machine only: download each payload once, kept only when its SHA-256 matches the record."""
    for relative, sha256, url in _store_items(load()):
        target = dest / relative
        if target.is_file() and sha256_file(target) == sha256:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".partial")
        with urllib.request.urlopen(url, timeout=300) as response, open(partial, "wb") as out:  # noqa: S310
            shutil.copyfileobj(response, out, 1 << 20)
        if sha256_file(partial) != sha256:
            partial.unlink()
            raise PackError(f"language_payload_hash_mismatch:{relative}")
        partial.replace(target)


def collect(source: Path, dest: Path) -> None:
    """Controlled store to developer offline cache, verified."""
    for relative, sha256, _ in _store_items(load()):
        _copy_verified(source / relative, dest / relative, sha256)


def stage(source: Path, runtime_root: Path, model_root: Path) -> list[str]:
    """Offline staging: verify every archive, extract each variant, verify every extracted file; copy the model files."""
    document = load()
    for relative, sha256, _ in _store_items(document):
        if not (source / relative).is_file() or sha256_file(source / relative) != sha256:
            raise PackError(f"language_payload_missing_or_mismatched:{relative}")
    staged = []
    runtime = document["runtime"]
    _copy_verified(source / "runtime" / runtime["licence"]["file"], runtime_root / runtime["licence"]["file"], runtime["licence"]["sha256"])
    for variant in runtime["variants"]:
        target = runtime_root / variant["directory"]
        if target.exists() and _variant_problems(target, variant) == []:
            staged.append(f"runtime/{variant['directory']} (present)")
            continue
        partial = runtime_root / (variant["directory"] + ".partial")
        shutil.rmtree(partial, ignore_errors=True)
        partial.mkdir(parents=True)
        for archive in variant["archives"]:
            with zipfile.ZipFile(source / "runtime" / archive["file"]) as bundle:
                for member in bundle.infolist():
                    if member.is_dir():
                        continue
                    name = _safe_name(member.filename)
                    if name not in variant["files"]:
                        raise PackError(f"language_runtime_unrecorded_member:{name}")
                    with bundle.open(member) as stream, open(partial / name, "wb") as out:
                        shutil.copyfileobj(stream, out, 1 << 20)
        if "nvidiaEula" in variant:
            shutil.copyfile(source / "runtime" / variant["nvidiaEula"]["file"], partial / variant["nvidiaEula"]["file"])
        problems = _variant_problems(partial, variant)
        if problems:
            shutil.rmtree(partial, ignore_errors=True)
            raise PackError("language_runtime_extract_mismatch:" + ",".join(problems[:5]))
        shutil.rmtree(target, ignore_errors=True)
        partial.replace(target)
        staged.append(f"runtime/{variant['directory']}")
    for model in document["models"]:
        for item in model["files"]:
            _copy_verified(source / "models" / model["packDirectory"] / item["file"], model_root / model["packDirectory"] / item["file"], item["sha256"])
        staged.append(f"models/{model['packDirectory']}")
    return staged


def _variant_problems(directory: Path, variant: dict) -> list[str]:
    """Every recorded file present with its hash, and nothing else (the EULA notice included for CUDA)."""
    expected = dict(variant["files"])
    if "nvidiaEula" in variant:
        expected[variant["nvidiaEula"]["file"]] = variant["nvidiaEula"]["sha256"]
    present = {path.name for path in directory.iterdir()} if directory.is_dir() else set()
    problems = [f"missing:{name}" for name in sorted(set(expected) - present)]
    problems += [f"unrecorded:{name}" for name in sorted(present - set(expected))]
    problems += [
        f"hash:{name}" for name in sorted(set(expected) & present) if sha256_file(directory / name) != expected[name]
    ]
    return problems


def verify(runtime_root: Path, variant_directory: str, model_root: Path, pack_directory: str) -> dict:
    """What the launcher runs before every start: the variant directory and the bound pack are exactly as recorded."""
    document = load()
    runtime = document["runtime"]
    variant = next((item for item in runtime["variants"] if item["directory"] == variant_directory), None)
    if variant is None:
        raise PackError(f"language_runtime_variant_unknown:{variant_directory}")
    problems = _variant_problems(runtime_root / variant["directory"], variant)
    if problems:
        raise PackError("language_runtime_mismatch:" + ",".join(problems[:5]))
    if sha256_file(runtime_root / runtime["licence"]["file"]) != runtime["licence"]["sha256"]:
        raise PackError("language_runtime_licence_mismatch")
    model = next((item for item in document["models"] if item["packDirectory"] == pack_directory), None)
    if model is None:
        raise PackError(f"language_pack_unknown:{pack_directory}")
    for item in model["files"]:
        path = model_root / pack_directory / item["file"]
        if not path.is_file() or sha256_file(path) != item["sha256"]:
            raise PackError(f"language_pack_mismatch:{item['file']}")
    manifest = load_manifest(model["manifest"])
    weights = sorted(item["file"] for item in model["files"] if item["file"].endswith(".gguf"))
    return {
        "runtimeId": runtime["runtimeId"],
        "variant": variant["variant"],
        "modelPackId": pack_identity(manifest),
        "modelId": manifest["modelId"],
        "quantisation": manifest["quantisation"]["type"],
        "modelPath": str(model_root / pack_directory / weights[0]),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check")
    acquire_parser = commands.add_parser("acquire")
    acquire_parser.add_argument("--dest", type=Path, required=True)
    collect_parser = commands.add_parser("collect")
    collect_parser.add_argument("--source", type=Path, required=True)
    collect_parser.add_argument("--dest", type=Path, required=True)
    stage_parser = commands.add_parser("stage")
    stage_parser.add_argument("--source", type=Path, required=True)
    stage_parser.add_argument("--runtime-root", type=Path, required=True)
    stage_parser.add_argument("--model-root", type=Path, required=True)
    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("--runtime-root", type=Path, required=True)
    verify_parser.add_argument("--variant", required=True)
    verify_parser.add_argument("--model-root", type=Path, required=True)
    verify_parser.add_argument("--pack", required=True)
    identity_parser = commands.add_parser("identity")
    identity_parser.add_argument("--pack", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            document = load()
            for model in document["models"]:
                print(f"{model['packDirectory']}: {pack_identity(load_manifest(model['manifest']))}")
            print(f"{len(_store_items(document))} language payloads agree with their manifests")
        elif args.command == "acquire":
            acquire(args.dest)
        elif args.command == "collect":
            collect(args.source, args.dest)
        elif args.command == "stage":
            for line in stage(args.source, args.runtime_root, args.model_root):
                print(line)
        elif args.command == "verify":
            print(json.dumps(verify(args.runtime_root, args.variant, args.model_root, args.pack), sort_keys=True))
        else:
            model = next(item for item in load()["models"] if item["packDirectory"] == args.pack)
            print(pack_identity(load_manifest(model["manifest"])))
    except PackError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
