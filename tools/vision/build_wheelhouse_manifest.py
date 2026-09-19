#!/usr/bin/env python3
"""Record the exact identity and origin of every wheel in a C2 wheelhouse.

The offline lock proves *what* is installed (`name==version --hash=`), but it
records neither the artefact's filename and wheel tags nor where it came from.
C2 mixes three acquisition sources -- the PyTorch CUDA index, ordinary PyPI, and
a locally compiled MMCV -- and a supply chain that cannot say which wheel came
from which source is not auditable.

This tool is offline. It reads a prepared wheelhouse and an explicit origin
declaration, and fails closed when they do not account for each other exactly.
Wheel inspection is delegated to freeze_offline_lock so there is one
implementation of what a wheel is.

Scope: this records identity and origin. The transitive dependency closure is
deliberately not checked here -- `freeze_offline_lock` owns that, and duplicating
it would create a second opinion about what a complete wheelhouse is.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VISION_ROOT = ROOT / "src" / "vision"
TOOLS_ROOT = Path(__file__).resolve().parent
for candidate in (VISION_ROOT, TOOLS_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from freeze_offline_lock import (  # noqa: E402
    FreezeOfflineLockError,
    inspect_wheel,
    validate_wheel_record_for_target,
)

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from vision_package_bootstrap import (  # noqa: E402
    install_lightweight_vision_package,
)

# Must run before the first `mavi_vision` import: the package's eager
# re-exports would otherwise pull in NumPy and Torch, which this tool
# exists to help acquire.
install_lightweight_vision_package()

from mavi_vision.runtime.offline_lock import (  # noqa: E402
    SUPPORTED_PLATFORM_VARIANTS,
    canonicalize_distribution_name,
)

from packaging.version import InvalidVersion, Version  # noqa: E402

SCHEMA_VERSION = "mavi-wheelhouse-manifest-v1"

_ACCELERATOR_DISTRIBUTIONS = ("torch", "torchvision")
_CUDA_LOCAL_VERSION = re.compile(r"^cu\d+$", re.ASCII)


class WheelhouseManifestError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _origin_for(filename: str, origins: dict[str, object]) -> dict[str, object]:
    """Return the declared origin of one wheel, or fail closed."""
    declared = origins.get(filename)
    if not isinstance(declared, dict):
        raise WheelhouseManifestError("wheelhouse_origin_missing:" + filename)

    kind = declared.get("kind")
    if kind == "index":
        url = declared.get("indexUrl")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise WheelhouseManifestError(
                "wheelhouse_origin_index_url_invalid:" + filename
            )
        return {"kind": "index", "indexUrl": url}
    if kind == "local-build":
        repository = declared.get("sourceRepository")
        commit = declared.get("sourceCommit")
        toolchain = declared.get("buildToolchain")
        if not isinstance(repository, str) or not repository.startswith("https://"):
            raise WheelhouseManifestError(
                "wheelhouse_origin_source_repository_invalid:" + filename
            )
        if not isinstance(commit, str) or re.fullmatch(
            r"[0-9a-f]{40}", commit
        ) is None:
            raise WheelhouseManifestError(
                "wheelhouse_origin_source_commit_invalid:" + filename
            )
        if not isinstance(toolchain, str) or not toolchain.strip():
            raise WheelhouseManifestError(
                "wheelhouse_origin_build_toolchain_invalid:" + filename
            )
        return {
            "kind": "local-build",
            "sourceRepository": repository,
            "sourceCommit": commit,
            "buildToolchain": toolchain,
        }
    raise WheelhouseManifestError("wheelhouse_origin_kind_invalid:" + filename)


def _validate_accelerator_identity(name: str, version: str, variant: str) -> None:
    """A CUDA wheelhouse must carry CUDA accelerator builds, and vice versa."""
    if name not in _ACCELERATOR_DISTRIBUTIONS:
        return
    try:
        # PEP 440 normalisation, so `+CU124` is the CUDA build it claims to be.
        local = Version(version).local or ""
    except InvalidVersion as exc:
        raise WheelhouseManifestError(
            "wheelhouse_version_invalid:" + name
        ) from exc
    if variant.endswith("-cuda"):
        if _CUDA_LOCAL_VERSION.fullmatch(local) is None:
            raise WheelhouseManifestError(
                "wheelhouse_cuda_binary_build_required:" + name
            )
    elif variant.endswith("-cpu"):
        if local != "cpu":
            raise WheelhouseManifestError(
                "wheelhouse_cpu_binary_build_required:" + name
            )
    else:
        # A variant that is neither must never silently skip the check.
        raise WheelhouseManifestError(
            "wheelhouse_platform_variant_unsupported:" + variant
        )


def build_manifest(
    *,
    wheelhouse: Path,
    platform_variant: str,
    python_version: str,
    origins: dict[str, object],
) -> dict[str, object]:
    if platform_variant not in SUPPORTED_PLATFORM_VARIANTS:
        # Checked before anything is read: an unrecognised variant would let the
        # accelerator rule below decide nothing at all.
        raise WheelhouseManifestError(
            "wheelhouse_platform_variant_unsupported:" + platform_variant
        )
    if not wheelhouse.is_dir():
        raise WheelhouseManifestError("wheelhouse_missing")

    # Enumerate without filtering: a directory or a symlink filtered out before
    # the stray check is a payload nobody inspected, shipped anyway.
    entries = sorted(wheelhouse.iterdir())
    for item in entries:
        if item.is_symlink():
            # An offline supply-chain artefact must be a real file: an archive
            # taken without dereferencing would ship a dangling link.
            raise WheelhouseManifestError("wheelhouse_symlink_entry:" + item.name)
        if not item.is_file() or item.suffix.casefold() != ".whl":
            raise WheelhouseManifestError("wheelhouse_unexpected_file:" + item.name)
    if not entries:
        raise WheelhouseManifestError("wheelhouse_empty")

    declared = set(origins)
    present = {item.name for item in entries}
    undeclared = sorted(present - declared)
    unmatched = sorted(declared - present)
    if undeclared:
        raise WheelhouseManifestError("wheelhouse_origin_missing:" + undeclared[0])
    if unmatched:
        # An origin naming a wheel that is not here means the declaration and
        # the wheelhouse describe different things.
        raise WheelhouseManifestError("wheelhouse_origin_unmatched:" + unmatched[0])

    wheels: list[dict[str, object]] = []
    seen: dict[str, str] = {}
    for path in entries:
        try:
            record = inspect_wheel(path)
            validate_wheel_record_for_target(
                record,
                platform_variant=platform_variant,
                python_version=python_version,
            )
        except FreezeOfflineLockError as exc:
            raise WheelhouseManifestError(
                f"wheelhouse_wheel_invalid:{path.name}:{exc}"
            ) from exc

        canonical = canonicalize_distribution_name(record.name)
        if canonical in seen:
            raise WheelhouseManifestError(
                "wheelhouse_duplicate_distribution:" + canonical
            )
        seen[canonical] = record.version
        _validate_accelerator_identity(canonical, record.version, platform_variant)

        wheels.append(
            {
                "filename": path.name,
                "package": canonical,
                "version": record.version,
                "wheelTags": sorted(
                    "-".join(tag) for tag in record.tags
                ),
                "sizeBytes": path.stat().st_size,
                "sha256": record.sha256,
                "origin": _origin_for(path.name, origins),
            }
        )

    wheels.sort(key=lambda item: (item["package"], item["version"], item["filename"]))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "platformVariant": platform_variant,
        "pythonVersion": python_version,
        "wheelCount": len(wheels),
        "wheels": wheels,
        "note": (
            "Inventory and origin of a prepared wheelhouse. This records what "
            "the artefacts are and where they came from; the transitive "
            "dependency closure is validated by the offline lock, not here. It "
            "is not a runtime, hardware or Production qualification."
        ),
    }


def _load_origins(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WheelhouseManifestError("wheelhouse_origins_invalid") from exc
    if not isinstance(value, dict):
        raise WheelhouseManifestError("wheelhouse_origins_invalid")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--platform-variant", required=True)
    parser.add_argument("--python-version", required=True)
    parser.add_argument(
        "--origins",
        type=Path,
        required=True,
        help="JSON mapping each wheel filename to its acquisition origin.",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        manifest = build_manifest(
            wheelhouse=args.wheelhouse,
            platform_variant=args.platform_variant,
            python_version=args.python_version,
            origins=_load_origins(args.origins),
        )
    except WheelhouseManifestError as exc:
        print(json.dumps({"ok": False, "code": exc.code}, sort_keys=True))
        return 2

    if args.output is not None:
        if args.output.exists():
            print(
                json.dumps(
                    {"ok": False, "code": "wheelhouse_manifest_output_exists"},
                    sort_keys=True,
                )
            )
            return 2
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    print(json.dumps({"ok": True, "manifest": manifest}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
