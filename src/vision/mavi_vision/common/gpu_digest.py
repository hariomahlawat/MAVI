"""The worker's copy of the MAVI GPU identity digest.

A raw GPU UUID identifies one workstation card and never leaves the host;
evidence carries a domain-salted SHA-256 of it instead. The definition that the
host-side tools use lives in `tools/vision/host_gpu_digest.py`, which must stay
standard-library only and importable on a bare host before anything is
installed -- so it cannot import this package, and this package cannot reach
into `tools/`. Two definitions are therefore unavoidable; a test requires them
to be byte-identical, because a salt that drifts is invisible in the output and
would make every digest the worker emits silently stop matching the C4 record.
"""

from __future__ import annotations

import hashlib

GPU_UUID_HASH_DOMAIN = b"mavi-windows-cuda-host-v2\0"


def gpu_uuid_digest(uuid: str) -> str:
    """Digest one raw GPU UUID for inclusion in evidence."""
    return hashlib.sha256(
        GPU_UUID_HASH_DOMAIN + uuid.encode("utf-8")
    ).hexdigest()


__all__ = ["GPU_UUID_HASH_DOMAIN", "gpu_uuid_digest"]
