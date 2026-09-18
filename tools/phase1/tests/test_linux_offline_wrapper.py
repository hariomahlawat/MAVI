from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "tools" / "phase1" / "qualify_linux_offline.sh"


def test_linux_wrapper_is_p2_profile_scoped(tmp_path: Path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "python-args.log"
    fake_python = fake_bin / "python"
    fake_python.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" >> \"$MAVI_TEST_ARG_LOG\"\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    work_root = tmp_path / "work"
    output = tmp_path / "offline.json"
    sentinels = [
        "cuda-bundle",
        "a" * 40,
        "b" * 64,
        "acceptance-profile.json",
        "http://mavi.local",
        "media-root",
        "CAM-01",
        "Camera One",
        "Asia/Kolkata",
        "2026-09-15T10:30:00",
        "qualification-video.mp4",
        "linux-host",
        "build-a",
        "corpus.json",
        "ground-truth.json",
        str(work_root),
        str(output),
    ]

    env = dict(os.environ)
    env["PATH"] = str(fake_bin) + os.pathsep + env["PATH"]
    env["MAVI_TEST_ARG_LOG"] = str(log)
    completed = subprocess.run(
        ["bash", str(SCRIPT), *sentinels],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    captured = log.read_text(encoding="utf-8")
    assert "--variant linux-x86_64-cuda" in captured
    assert "--deployment-profile P2" in captured
    assert "--variant " in captured
    for value in sentinels[8:]:
        assert value in captured
