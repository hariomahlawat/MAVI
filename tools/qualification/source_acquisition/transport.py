"""Narrow HTTPS transport for the B0 source-acquisition pilot.

Only HTTPS to allow-listed hosts; every redirect hop is re-validated; at most five
redirects; no credentials, cookies or authorization headers; bounded timeout. The raw
fetch is injectable so tests never touch the network.
"""

from __future__ import annotations

import hashlib
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Iterable

MAX_REDIRECTS = 5
TIMEOUT_SECONDS = 60
CHUNK = 1024 * 1024


class TransportError(Exception):
    """A refused or failed transfer. The message never contains header values."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401 - urllib signature
        return None


def _default_fetch(url: str, headers: dict[str, str]):
    """One GET without following redirects; returns (status, headers, stream)."""
    opener = urllib.request.build_opener(_NoRedirect())
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        response = opener.open(request, timeout=TIMEOUT_SECONDS)
        return response.status, dict(response.headers.items()), response
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers.items()) if exc.headers else {}, exc


class Transport:
    def __init__(self, allowed_hosts: Iterable[str], user_agent: str,
                 fetch: Callable[[str, dict[str, str]], tuple] | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.allowed_hosts = frozenset(h.lower() for h in allowed_hosts)
        if not user_agent or any(c in user_agent for c in "\r\n"):
            raise TransportError("user agent required")
        self.headers = {"User-Agent": user_agent, "Accept": "*/*"}
        self._fetch = fetch or _default_fetch
        self._sleep = sleep

    def check_url(self, url: str) -> urllib.parse.SplitResult:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https":
            raise TransportError(f"refusing non-HTTPS url scheme {parts.scheme!r}")
        if parts.username is not None or parts.password is not None or "@" in parts.netloc:
            raise TransportError("refusing url with embedded credentials")
        if (parts.hostname or "").lower() not in self.allowed_hosts:
            raise TransportError(f"refusing host {parts.hostname!r} (not allow-listed)")
        if parts.port not in (None, 443):
            raise TransportError("refusing non-default port")
        return parts

    def open(self, url: str):
        """Follow at most MAX_REDIRECTS, re-validating each hop; returns (final_url, stream)."""
        current = url
        for attempt in range(3):
            for _hop in range(MAX_REDIRECTS + 1):
                self.check_url(current)
                status, headers, stream = self._fetch(current, dict(self.headers))
                if status in (301, 302, 303, 307, 308):
                    location = {k.lower(): v for k, v in headers.items()}.get("location")
                    _close(stream)
                    if not location:
                        raise TransportError(f"redirect without location (HTTP {status})")
                    current = urllib.parse.urljoin(current, location)
                    continue
                if status in (429, 503) and attempt < 2:
                    _close(stream)
                    self._sleep(30 * (attempt + 1))
                    current = url
                    break
                if status != 200:
                    _close(stream)
                    raise TransportError(f"HTTP {status} from {urllib.parse.urlsplit(current).hostname}")
                return current, stream
            else:
                raise TransportError("too many redirects")
        raise TransportError("rate limited; retry later")

    def get_bytes(self, url: str, limit: int = 16 * 1024 * 1024) -> bytes:
        _final, stream = self.open(url)
        try:
            data = stream.read(limit + 1)
        finally:
            _close(stream)
        if len(data) > limit:
            raise TransportError("response larger than limit")
        return data

    def download(self, url: str, target: Path, expected_size: int, expected_sha1: str) -> dict:
        """Stream to ``<target>.partial``; promote only after size and SHA-1 verify.

        Promotion uses a hard link, which fails instead of overwriting an existing file.
        A failed or rejected transfer removes only its own partial file.
        """
        partial = target.with_name(target.name + ".partial")
        if target.exists():
            raise TransportError("target exists; refusing to overwrite")
        if partial.exists():
            partial.unlink()
        sha1, sha256, size = hashlib.sha1(), hashlib.sha256(), 0
        _final, stream = self.open(url)
        try:
            with open(partial, "xb") as out:
                while True:
                    chunk = stream.read(CHUNK)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > expected_size:
                        raise TransportError("more bytes than the declared size")
                    sha1.update(chunk)
                    sha256.update(chunk)
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
            if size != expected_size:
                raise TransportError(f"size {size} != declared {expected_size}")
            if size == 0:
                raise TransportError("zero-byte transfer")
            if sha1.hexdigest() != expected_sha1:
                raise TransportError("SHA-1 differs from the provider's declared SHA-1")
            os.link(partial, target)
        except BaseException:
            if partial.exists():
                partial.unlink()
            raise
        finally:
            _close(stream)
        partial.unlink()
        return {"byteSize": size, "sha1": sha1.hexdigest(), "sha256": sha256.hexdigest()}


def _close(stream) -> None:
    close = getattr(stream, "close", None)
    if close is not None:
        close()


def file_digests(path: Path) -> dict:
    sha1, sha256, size = hashlib.sha1(), hashlib.sha256(), 0
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            size += len(chunk)
            sha1.update(chunk)
            sha256.update(chunk)
    return {"byteSize": size, "sha1": sha1.hexdigest(), "sha256": sha256.hexdigest()}
