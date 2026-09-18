"""The one definition of a MAVI GPU identity digest.

A raw GPU UUID identifies a specific workstation card, so it is never committed
and never leaves the host. Evidence therefore carries a domain-salted SHA-256 of
it instead, which is stable enough to correlate two artefacts from the same
machine and useless as an identifier anywhere else.

Every tool that emits or compares such a digest imports it from here. Two tools
computing "the same" digest from separately written constants is how an evidence
chain silently stops matching, and the salt in particular is invisible in the
output: a verifier that computed a plain SHA-256 would conclude the evidence was
forged.

This module is standard library only, because the host probe that uses it runs
on a bare Windows host before anything is installed.
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
