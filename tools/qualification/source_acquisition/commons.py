"""Wikimedia Commons metadata client for the B0 pilot (the only provider implemented).

Uses the official MediaWiki Action API on commons.wikimedia.org. Only one exact file
revision is ever described; discovery lists candidate titles for human review and admits
nothing. The media licence comes from the file's own description page (extmetadata),
never from the site's text licence or from category membership.
"""

from __future__ import annotations

import html
import json
import re
import urllib.parse

from .admission import require_file_title, normalise_licence
from .transport import Transport

API = "https://commons.wikimedia.org/w/api.php"
ALLOWED_HOSTS = ("commons.wikimedia.org", "upload.wikimedia.org")
PROVIDER = "wikimedia-commons"
_ORIGINAL_PATH_RE = re.compile(r"^/wikipedia/commons/[0-9a-f]/[0-9a-f]{2}/[^/]+$")
_TAG_RE = re.compile(r"<[^>]+>")


def _text(ext: dict, key: str) -> str | None:
    value = (ext.get(key) or {}).get("value")
    if not isinstance(value, str):
        return None
    cleaned = " ".join(html.unescape(_TAG_RE.sub(" ", value)).split())
    return cleaned or None


def metadata_query_url(title: str) -> str:
    require_file_title(title)
    params = {
        "action": "query", "format": "json", "formatversion": "2", "maxlag": "5",
        "titles": title, "prop": "imageinfo|revisions", "rvprop": "ids|timestamp",
        "iiprop": "timestamp|user|url|size|sha1|mime|mediatype|extmetadata|metadata",
        "iiextmetadatalanguage": "en",
    }
    return API + "?" + urllib.parse.urlencode(params)


def search_query_url(search: str, limit: int) -> str:
    if not (1 <= limit <= 100):
        raise ValueError("limit must be 1..100")
    params = {"action": "query", "format": "json", "formatversion": "2", "maxlag": "5", "list": "search",
              "srnamespace": "6", "srsearch": f"filetype:video {search}", "srlimit": str(limit)}
    return API + "?" + urllib.parse.urlencode(params)


def category_query_url(category: str, limit: int) -> str:
    if not (isinstance(category, str) and category.startswith("Category:") and 1 <= limit <= 100):
        raise ValueError("an explicit Category: title and a limit of 1..100 are required")
    params = {"action": "query", "format": "json", "formatversion": "2", "maxlag": "5", "list": "categorymembers",
              "cmtitle": category, "cmtype": "file", "cmlimit": str(limit)}
    return API + "?" + urllib.parse.urlencode(params)


def parse_file_metadata(response: dict) -> dict:
    """One exact file revision from an API response; raises ValueError when incomplete."""
    pages = (response.get("query") or {}).get("pages") or []
    if len(pages) != 1 or pages[0].get("missing") or pages[0].get("invalid"):
        raise ValueError("expected exactly one existing file page")
    page = pages[0]
    title = require_file_title(page.get("title"))
    infos = page.get("imageinfo") or []
    revisions = page.get("revisions") or []
    if len(infos) != 1 or len(revisions) != 1:
        raise ValueError("expected exactly one current file version and page revision")
    info, revision = infos[0], revisions[0]
    ext = info.get("extmetadata") or {}
    url = info.get("url")
    parts = urllib.parse.urlsplit(url or "")
    if parts.scheme != "https" or parts.hostname != "upload.wikimedia.org" or not _ORIGINAL_PATH_RE.match(parts.path):
        raise ValueError("original file url is not an upload.wikimedia.org original (transcodes and thumbnails are refused)")
    duration = info.get("duration")
    return {
        "provider": PROVIDER,
        "fileTitle": title,
        "pageId": int(page["pageid"]),
        "pageRevisionId": int(revision["revid"]),
        "canonicalPageUrl": info.get("descriptionurl") or ("https://commons.wikimedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))),
        "originalFileUrl": url,
        "fileUploadTimestampUtc": info.get("timestamp"),
        "uploader": info.get("user"),
        "author": _text(ext, "Artist"),
        "attribution": _text(ext, "Attribution") or _text(ext, "Credit"),
        "licenceCode": normalise_licence(_text(ext, "License")),
        "licenceShortName": _text(ext, "LicenseShortName"),
        "licenceUrl": _text(ext, "LicenseUrl"),
        "declaredCaptureDate": _text(ext, "DateTimeOriginal"),
        "mime": info.get("mime"),
        "mediaType": info.get("mediatype"),
        "declaredByteSize": info.get("size"),
        "fileSha1": (info.get("sha1") or "").lower() or None,
        "width": info.get("width"),
        "height": info.get("height"),
        "durationSeconds": None if duration is None else str(duration),
    }


def fetch_file_metadata(transport: Transport, title: str) -> tuple[dict, bytes]:
    """Parsed metadata and the exact API response bytes (retained as evidence)."""
    raw = transport.get_bytes(metadata_query_url(title))
    return parse_file_metadata(json.loads(raw.decode("utf-8"))), raw


def discovered_titles(response: dict) -> list[str]:
    query = response.get("query") or {}
    rows = query.get("search") or query.get("categorymembers") or []
    titles = []
    for row in rows:
        title = row.get("title")
        try:
            titles.append(require_file_title(title))
        except Exception:  # noqa: BLE001 - non-video or malformed titles are simply not candidates
            continue
    return sorted(set(titles))
