"""The MAVI API client extracted from T9 into ``mavi_api`` (S3.2d-1 slice 1): same names reachable from
``ingest_source_pool`` and the same HTTP behaviour, pinned against a loopback stub (never a real MAVI host)."""

from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import artefacts as a
import ingest_source_pool as t9
import mavi_api


class Recorder:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.responses: dict[tuple[str, str], tuple[int, dict[str, str], bytes]] = {}


def _handler(recorder: Recorder):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass

        def _serve(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            recorder.requests.append({"method": self.command, "path": self.path, "headers": dict(self.headers),
                                      "body": body})
            status, headers, raw = recorder.responses.get((self.command, self.path), (404, {}, b""))
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        do_GET = do_POST = _serve

    return Handler


@pytest.fixture
def stub():
    recorder = Recorder()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(recorder))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    recorder.url = f"http://127.0.0.1:{server.server_address[1]}"
    yield recorder
    server.shutdown()
    server.server_close()


def test_t9_names_are_the_extracted_client():
    assert t9.Api is mavi_api.Api
    assert t9.Multipart is mavi_api.Multipart
    assert t9._NoRedirect is mavi_api._NoRedirect
    assert t9.LOOPBACK_HOSTS == mavi_api.LOOPBACK_HOSTS == ("127.0.0.1", "::1", "localhost")
    assert t9.HTTP_TIMEOUT_SECONDS == mavi_api.HTTP_TIMEOUT_SECONDS == 600
    assert t9._problem_code is mavi_api.problem_code


@pytest.mark.parametrize("base", ["http://example.com", "http://10.0.0.1:5000", "ftp://127.0.0.1",
                                  "http://user@127.0.0.1", "http://127.0.0.1/?q=1"])
def test_non_local_urls_are_refused(base):
    with pytest.raises(a.S32Error, match="^t9_api_not_local$"):
        mavi_api.Api(base)


@pytest.mark.parametrize("base", ["http://127.0.0.1:5000", "https://localhost/", "http://[::1]:8080"])
def test_loopback_urls_are_accepted(base):
    assert mavi_api.Api(base).base == base.rstrip("/")


def test_json_call_and_proxy_environment_ignored(stub, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://203.0.113.1:9")
    monkeypatch.setenv("http_proxy", "http://203.0.113.1:9")
    stub.responses[("POST", "/api/cameras")] = (201, {"Content-Type": "application/json"}, b'{"id":"c-1"}')
    status, body = mavi_api.Api(stub.url + "/").call("POST", "/api/cameras", json_body={"code": "c0", "n": 1})
    assert (status, body) == (201, {"id": "c-1"})
    request = stub.requests[-1]
    assert request["headers"]["Content-Type"] == "application/json"
    assert request["headers"]["Accept"] == "application/json"
    assert request["body"] == json.dumps({"code": "c0", "n": 1}).encode("utf-8")


def test_multipart_is_streamed_with_exact_framing(stub, tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(bytes(range(256)) * 9000)
    stub.responses[("POST", "/api/videos/import")] = (201, {}, b'{"id":"v-1"}')
    body = mavi_api.Multipart({"cameraId": "c-1", "recordingStartLocal": "2026-01-01T00:00:00"}, "file",
                              "video.mp4", video)
    status, created = mavi_api.Api(stub.url).call("POST", "/api/videos/import", multipart=body)
    assert (status, created) == (201, {"id": "v-1"})
    request = stub.requests[-1]
    assert request["headers"]["Content-Type"] == body.content_type
    assert int(request["headers"]["Content-Length"]) == body.length == len(request["body"])
    assert request["body"] == body.head + video.read_bytes() + body.tail
    assert body.tail == f"\r\n--{body.boundary}--\r\n".encode("ascii")
    assert b'name="cameraId"\r\n\r\nc-1\r\n' in body.head
    assert b'filename="video.mp4"\r\nContent-Type: video/mp4\r\n\r\n' in body.head


def test_redirect_is_refused_and_never_followed(stub):
    stub.responses[("GET", "/api/videos")] = (302, {"Location": "/elsewhere"}, b"")
    with pytest.raises(a.S32Error, match="^t9_api_redirect_refused:302$"):
        mavi_api.Api(stub.url).call("GET", "/api/videos")
    assert [request["path"] for request in stub.requests] == ["/api/videos"]


def test_http_error_status_and_problem_body_are_returned(stub):
    stub.responses[("POST", "/api/videos/import")] = (409, {}, b'{"code":"video_duplicate"}')
    status, body = mavi_api.Api(stub.url).call("POST", "/api/videos/import", json_body={})
    assert status == 409 and mavi_api.problem_code(body) == "video_duplicate"
    assert mavi_api.problem_code(None) == mavi_api.problem_code({"code": ""}) == "unknown"


def test_empty_and_invalid_responses(stub):
    stub.responses[("POST", "/api/videos/x/process")] = (202, {}, b"")
    assert mavi_api.Api(stub.url).call("POST", "/api/videos/x/process") == (202, None)
    stub.responses[("GET", "/api/cameras")] = (200, {}, b"not json")
    with pytest.raises(a.S32Error, match="^t9_api_invalid_response:GET$"):
        mavi_api.Api(stub.url).call("GET", "/api/cameras")


def test_unreachable_host_is_a_refusal():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with pytest.raises(a.S32Error, match="^t9_api_unreachable$"):
        mavi_api.Api(f"http://127.0.0.1:{port}").call("GET", "/api/cameras")


def test_ingest_source_pool_holds_no_second_client():
    source = (Path(t9.__file__)).read_text(encoding="utf-8")
    assert "class Api" not in source and "class Multipart" not in source and "urllib" not in source
