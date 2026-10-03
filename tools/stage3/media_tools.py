"""The approved FFmpeg/ffprobe binaries for S3.2b tooling (S3.2 plan, "Approved media binaries").

One location convention, the platform's own: a MAVI FFmpeg dependency pack laid out as
``vendor/ffmpeg/README.md`` describes and ``NativeMediaToolStartup`` verifies::

    <dir>/manifest.json            schemaVersion "1.0", runtimeId, version, artifacts[{fileName, sha256}]
    <dir>/<runtimeId>/ffprobe(.exe)
    <dir>/<runtimeId>/ffmpeg(.exe)

A tool is usable only when the manifest is valid, its runtime id is this host's, the
executable is listed with a lowercase SHA-256 equal to its bytes, it starts, and its
``-version`` output contains the manifest ``version``. PATH is never searched, and the web
host's Development PATH fallback is never accepted. The pack directory is a runtime-only
input; artefacts record only ``{version, sha256}`` (the manifest's version token, never raw
``-version`` output, which can contain build paths).
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import artefacts as a  # noqa: E402

CODE = "media_tools_invalid"
MANIFEST = "manifest.json"
VERSION_TIMEOUT_SECONDS = 30


def current_runtime_id() -> str:
    """As ``MediaToolPathResolver.CurrentRuntimeId``: x64 on Windows or Linux only."""
    machine = platform.machine().lower()
    a.require(machine in ("amd64", "x86_64"), f"{CODE}:architecture")
    if sys.platform.startswith("win"):
        return "win-x64"
    if sys.platform.startswith("linux"):
        return "linux-x64"
    raise a.S32Error(f"{CODE}:platform")


def executable_name(tool: str) -> str:
    return f"{tool}.exe" if sys.platform.startswith("win") else tool


@dataclass(frozen=True)
class Tool:
    """A verified executable. ``path`` is runtime-only; ``identity`` is what artefacts record."""

    path: Path
    version: str
    sha256: str

    @property
    def identity(self) -> dict[str, str]:
        return {"version": self.version, "sha256": self.sha256}


def _manifest(directory: Path) -> dict:
    data = a.read_bytes(directory / MANIFEST, f"{CODE}:manifest")
    # The staged pack is written by PowerShell and may carry a byte-order mark; the
    # platform's own reader accepts it too.
    try:
        document = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise a.S32Error(f"{CODE}:manifest") from exc
    a.require(isinstance(document, dict), f"{CODE}:manifest")
    # NativeMediaToolStartup reads the manifest case-insensitively.
    return {str(key).lower(): value for key, value in document.items()}


def load(directory: Path, tool: str) -> Tool:
    """The verified ``ffprobe`` or ``ffmpeg`` from the pack at ``directory``."""
    a.require(tool in ("ffprobe", "ffmpeg"), f"{CODE}:tool")
    directory = Path(directory)
    manifest = _manifest(directory)
    a.require(manifest.get("schemaversion") == "1.0", f"{CODE}:schema")
    version = manifest.get("version")
    a.require(isinstance(version, str) and version.strip(), f"{CODE}:version")
    runtime = current_runtime_id()
    a.require(manifest.get("runtimeid") == runtime, f"{CODE}:runtime")
    artifacts = manifest.get("artifacts")
    a.require(isinstance(artifacts, list) and artifacts, f"{CODE}:artifacts")
    name = executable_name(tool)
    entries = [entry for entry in artifacts
               if isinstance(entry, dict)
               and str({k.lower(): v for k, v in entry.items()}.get("filename", "")).lower() == name.lower()]
    a.require(len(entries) == 1, f"{CODE}:not_listed:{name}")
    expected = {k.lower(): v for k, v in entries[0].items()}.get("sha256")
    a.require(isinstance(expected, str) and a.SHA256_RE.fullmatch(expected), f"{CODE}:sha256_invalid:{name}")
    path = directory / runtime / name
    a.require(path.is_file(), f"{CODE}:missing:{name}")
    a.require(a.sha256_hex(path.read_bytes()) == expected, f"{CODE}:sha256_mismatch:{name}")
    try:
        result = subprocess.run([str(path), "-version"], capture_output=True, timeout=VERSION_TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise a.S32Error(f"{CODE}:start:{name}") from exc
    a.require(result.returncode == 0, f"{CODE}:start:{name}")
    output = (result.stdout or result.stderr).decode("utf-8", errors="replace")
    a.require(version in output, f"{CODE}:version_mismatch:{name}")
    return Tool(path=path, version=version, sha256=expected)


def require_unchanged(tool: Tool) -> None:
    """Re-hashes the executable immediately before it runs, so the recorded identity is the binary used."""
    try:
        data = tool.path.read_bytes()
    except OSError as exc:
        raise a.S32Error(f"{CODE}:changed:{tool.path.name}") from exc
    a.require(a.sha256_hex(data) == tool.sha256, f"{CODE}:changed:{tool.path.name}")
