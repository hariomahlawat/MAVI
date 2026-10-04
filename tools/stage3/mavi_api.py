"""The standard-library client for the local MAVI product API, shared by T9 (``ingest_source_pool``) and the
benchmark harness (S3.2d-1 plan §4: extracted behaviour-preserving from ``ingest_source_pool``; the refusal codes
are T9's, unchanged).

Loopback URLs only, never a system or environment proxy, no redirect ever followed, and multipart uploads
streamed from disk, so neither the calls nor the corpus uploads can leave the host.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Iterator

import artefacts as a

HTTP_TIMEOUT_SECONDS = 600


class Multipart:
    """A streamed ``multipart/form-data`` body: the file is read in blocks, never held in memory."""

    def __init__(self, fields: dict[str, str], file_field: str, file_name: str, file_path: Path) -> None:
        self.boundary = f"mavi-s32-{uuid.uuid4().hex}"
        head = b"".join(
            f'--{self.boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8")
            for name, value in fields.items())
        head += (f'--{self.boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{file_name}"\r\n'
                 f"Content-Type: video/mp4\r\n\r\n").encode("utf-8")
        self.head, self.tail, self.path = head, f"\r\n--{self.boundary}--\r\n".encode("ascii"), Path(file_path)
        self.length = len(head) + self.path.stat().st_size + len(self.tail)

    @property
    def content_type(self) -> str:
        return f"multipart/form-data; boundary={self.boundary}"

    def __iter__(self) -> Iterator[bytes]:
        yield self.head
        with open(self.path, "rb") as stream:
            yield from iter(lambda: stream.read(1 << 20), b"")
        yield self.tail


LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """No MAVI endpoint T9 uses redirects: a 3xx is surfaced as is and never followed."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


class Api:
    """The local MAVI API only: a loopback URL, and never a system or environment proxy, so neither
    the calls nor the corpus uploads can leave the host."""

    def __init__(self, base: str) -> None:
        parsed = urllib.parse.urlsplit(base)
        a.require(parsed.scheme in ("http", "https") and parsed.hostname in LOOPBACK_HOSTS
                  and not parsed.username and not parsed.query, "t9_api_not_local")
        self.base = base.rstrip("/")
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def call(self, method: str, path: str, *, json_body: Any = None, multipart: Multipart | None = None) -> tuple[int, Any]:
        headers = {"Accept": "application/json"}
        data: Any = None
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif multipart is not None:
            data = multipart
            headers["Content-Type"] = multipart.content_type
            headers["Content-Length"] = str(multipart.length)
        request = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with self.opener.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as exc:
            status, raw = exc.code, exc.read()
        except (urllib.error.URLError, OSError) as exc:
            raise a.S32Error("t9_api_unreachable") from exc
        a.require(not 300 <= status < 400, f"t9_api_redirect_refused:{status}")
        try:
            body = json.loads(raw.decode("utf-8")) if raw else None
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise a.S32Error(f"t9_api_invalid_response:{method}") from exc
        return status, body


def problem_code(body: Any) -> str:
    return str(body.get("code")) if isinstance(body, dict) and body.get("code") else "unknown"
