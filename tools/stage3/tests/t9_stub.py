"""A stubbed MAVI API for T9 tests: the camera, import, process and processing endpoints T9 uses,
with switches for the misbehaviour T9 must refuse. Loopback only; never a real MAVI host."""

from __future__ import annotations

import email.parser
import email.policy
import hashlib
import json
import threading
import uuid
import zoneinfo
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


class StubState:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.uploads = root / "uploads"
        self.uploads.mkdir(parents=True, exist_ok=True)
        self.calls: list[tuple[str, str]] = []
        self.cameras: list[dict[str, Any]] = []
        self.videos: list[dict[str, Any]] = []
        self.runs: dict[str, dict[str, Any]] = {}  # videoAssetId -> latest run
        self.counter = 0
        # Switches
        self.hide_videos = False
        self.process_conflict = False
        self.substitute_run = False
        self.fail_run_for: set[str] = set()  # upload sha256s whose runs fail
        self.running_polls = 1  # polls answering Running before Completed
        self.shift_start = False  # import answers a recording start other than the one sent
        self.lock = threading.Lock()

    def next_id(self) -> str:
        self.counter += 1
        return str(uuid.UUID(int=0x01A0FFB2_0000_7000_8000_000000000000 + self.counter))

    def write_export_state(self) -> None:
        state = {"runs": {}}
        for video in self.videos:
            run = self.runs.get(video["id"])
            if run:
                camera = next(c for c in self.cameras if c["id"] == video["cameraId"])
                state["runs"][run["processingRunId"]] = {"videoAssetId": video["id"], "upload": video["upload"],
                                                         "cameraCode": camera["code"]}
        (self.root / "export-state.json").write_text(json.dumps(state), encoding="utf-8")


def make_handler(state: StubState):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # quiet
            pass

        def _send(self, status: int, body: Any) -> None:
            data = json.dumps(body).encode("utf-8") if body is not None else b""
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> bytes:
            return self.rfile.read(int(self.headers.get("Content-Length", "0")))

        def do_GET(self):
            with state.lock:
                state.calls.append(("GET", self.path))
                if self.path == "/api/cameras":
                    return self._send(200, state.cameras)
                if self.path == "/api/videos":
                    return self._send(200, [] if state.hide_videos else [{k: v for k, v in video.items() if k != "upload"}
                                                                         for video in state.videos])
                parts = self.path.strip("/").split("/")
                if len(parts) == 4 and parts[:2] == ["api", "videos"] and parts[3] == "processing":
                    run = state.runs.get(parts[2])
                    if run is None:
                        return self._send(200, {"videoStatus": "Imported", "latestRun": None})
                    if run["polls"] < state.running_polls:
                        run["polls"] += 1
                        status = "Running"
                    else:
                        status = run["final"]
                    run_id = str(uuid.uuid4()) if state.substitute_run else run["processingRunId"]
                    return self._send(200, {"videoStatus": status, "latestRun": {"processingRunId": run_id,
                                                                                 "status": status}})
                return self._send(404, {"code": "not_found"})

        def do_POST(self):
            with state.lock:
                state.calls.append(("POST", self.path))
                if self.path == "/api/cameras":
                    request = json.loads(self._body())
                    code = request["code"].upper()
                    if any(c["code"] == code for c in state.cameras):
                        return self._send(409, {"code": "camera_code_duplicate"})
                    camera = {"id": state.next_id(), "code": code, "name": request["name"], "description": None,
                              "locationName": None, "timeZoneId": request["timeZoneId"], "isActive": True}
                    state.cameras.append(camera)
                    return self._send(201, camera)
                if self.path == "/api/videos/import":
                    raw = self._body()
                    message = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
                        f"Content-Type: {self.headers['Content-Type']}\r\n\r\n".encode() + raw)
                    fields, data = {}, b""
                    for part in message.iter_parts():
                        name = part.get_param("name", header="content-disposition")
                        if part.get_filename():
                            data = part.get_payload(decode=True)
                        else:
                            fields[name] = part.get_content().strip()
                    sha = hashlib.sha256(data).hexdigest()
                    for video in state.videos:
                        if video["sha"] == sha:
                            return self._send(409, {"code": "video_duplicate", "videoAssetId": video["id"]})
                    camera = next(c for c in state.cameras if c["id"] == fields["cameraId"])
                    zone = camera["timeZoneId"]
                    start = datetime.fromisoformat(fields["recordingStartLocal"]).replace(
                        tzinfo=zoneinfo.ZoneInfo(zone)).astimezone(timezone.utc)
                    if state.shift_start:
                        start = start.replace(hour=(start.hour + 1) % 24)
                    upload = state.uploads / sha
                    upload.write_bytes(data)
                    video = {"id": state.next_id(), "cameraId": fields["cameraId"], "originalFileName": "video.mp4",
                             "recordingStartUtc": start.isoformat(), "recordingTimeZoneId": zone,
                             "sha": sha, "upload": str(upload)}
                    state.videos.append(video)
                    return self._send(201, {k: v for k, v in video.items() if k != "upload"})
                parts = self.path.strip("/").split("/")
                if len(parts) == 4 and parts[:2] == ["api", "videos"] and parts[3] == "process":
                    if state.process_conflict:
                        return self._send(409, {"code": "processing_run_active"})
                    video = next(v for v in state.videos if v["id"] == parts[2])
                    final = "Failed" if video["sha"] in state.fail_run_for else "Completed"
                    state.runs[parts[2]] = {"processingRunId": state.next_id(), "polls": 0, "final": final}
                    state.write_export_state()
                    return self._send(202, {"processingRunId": state.runs[parts[2]]["processingRunId"]})
                return self._send(404, {"code": "not_found"})

    return Handler


class StubApi:
    def __init__(self, root: Path) -> None:
        self.state = StubState(root)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.state))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
