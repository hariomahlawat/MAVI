"""PoC S10 (register C9.2, C9.3): end-to-end evidence of Ask MAVI on the demo corpus.

Development tooling only, standard library only, loopback API only. It asks every question of the frozen corpus
(``contracts/test-vectors/ask-mavi-questions-v1.json``) through ``POST /api/ask`` of a running platform whose language
role is bound, one at a time, and for each question records:

1. **Translation**: the outcome against the corpus expectation. An expected query is canonicalised by the server
   itself (``POST /api/query``), so the comparison uses the platform's own canonical form; an expected refusal must be
   a model refusal with the same reason.
2. **Grounding**: for an answered question, the Ask envelope must equal a direct ``POST /api/query`` of the
   interpreted query (result, coverage, identity; the snapshot block aside): the answer is the deterministic query
   result and nothing else.
3. **Prompt binding**: the prompt hash the API reports must equal the one in the CI recording set named, so the live
   run and the replayed recordings were given the same prompt.
4. **Latency**: client wall time and the server's translation/evaluation split.

    python tools/poc/ask_e2e_evidence.py run --api http://127.0.0.1:62210 --recordings <recordings.json> --out <dir>
        [--questions contracts/test-vectors/ask-mavi-questions-v2.json]

Prompt v2 (ADR-026 amendment D-S10-9) refuses a question naming a place the site lacks before the model, at stage
``question``; that refusal matches an expected ``unknown_reference`` as the model's own does, and has no prompt to bind.

Entities are shown to operators only (ADR-023, #253) and this client is anonymous. For an Entity question the
platform refuses the direct ``POST /api/query`` (401), so the expected canonical query is the one the bound recording
holds (the strict parser's canonical form), and grounding means the Ask answer withholds Entity data
(``empty`` with reason ``operator_required``) exactly as the direct call refuses it.

Every number is pipeline output, not ground truth; the held split's exact-match rate is the measured claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QUESTIONS = ROOT / "contracts/test-vectors/ask-mavi-questions-v1.json"
CATALOGUE = ROOT / "contracts/test-vectors/ask-mavi-site-catalogue-v1.json"


def _opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _check(api: str) -> None:
    if urllib.parse.urlparse(api).hostname not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("REFUSED: the API must be loopback")


def get(api: str, path: str):
    _check(api)
    with _opener().open(api.rstrip("/") + path, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def post(api: str, path: str, body: dict, timeout: float = 1800):
    _check(api)
    request = urllib.request.Request(
        api.rstrip("/") + path, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with _opener().open(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8") or "{}")


def resolve(value, cameras: dict):
    """The corpus placeholders {camera:CODE}, {zone:CODE/Name}, {line:CODE/Name} against the catalogue fixture."""
    if isinstance(value, dict):
        return {key: resolve(item, cameras) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve(item, cameras) for item in value]
    if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
        kind, reference = value[1:-1].split(":", 1)
        if kind == "camera":
            return cameras[reference]["cameraId"]
        code, name = reference.split("/", 1)
        items = cameras[code]["zones" if kind == "zone" else "lines"]
        return next(item["zoneId" if kind == "zone" else "lineId"] for item in items if item["name"] == name)
    return value


def comparable(envelope: dict) -> dict:
    """The envelope without what legitimately differs between two evaluations of one query (the snapshot block)."""
    return {key: value for key, value in envelope.items() if key != "snapshot"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# The stages whose refusal is the expected refusal: the model's, and (v2) the platform's own unknown-place refusal.
REFUSAL_STAGES = {"outside_contract": ("model",), "unknown_reference": ("model", "question")}


def run(api: str, recordings_path: Path | None, out: Path, questions_path: Path = QUESTIONS) -> int:
    out.mkdir(parents=True, exist_ok=False)
    corpus = json.loads(questions_path.read_text(encoding="utf-8"))
    cameras = {camera["code"]: camera for camera in json.loads(CATALOGUE.read_text(encoding="utf-8"))["cameras"]}
    recorded = {}
    if recordings_path:
        recorded = {item["id"]: item for item in json.loads(recordings_path.read_text(encoding="utf-8"))["results"]}

    status = get(api, "/api/ask/status")
    if not status["answering"]:
        raise SystemExit(f"REFUSED: the language role is not answering ({status['reason']})")
    results = []
    for question in corpus["questions"]:
        expect = question["expect"]
        operator_gated = False
        if expect["answer"] == "query":
            code, envelope = post(api, "/api/query", resolve(expect["query"], cameras), timeout=120)
            if code == 401 and expect["query"]["unit"] == "entity" and question["id"] in recorded:
                operator_gated = True
                expected = {"kind": "query", "resolvedQuery": json.loads(recorded[question["id"]]["expected"]), "fingerprint": None}
            elif code != 200:
                raise SystemExit(f"the expected query of {question['id']} is refused by the platform: {envelope}")
            else:
                expected = {"kind": "query", "resolvedQuery": envelope["resolvedQuery"], "fingerprint": envelope["queryFingerprint"]}
        else:
            expected = {"kind": "refusal", "code": expect["reason"]}

        started = time.perf_counter()
        code, response = post(api, "/api/ask", {"question": question["question"], "referenceDate": corpus["site"]["referenceDate"]})
        wall_ms = (time.perf_counter() - started) * 1000
        if code != 200:
            raise SystemExit(f"/api/ask answered {code} for {question['id']}: {response}")

        if response["outcome"] == "answered":
            got = {"kind": "query", "resolvedQuery": response["interpretation"]["resolvedQuery"], "fingerprint": response["interpretation"]["queryFingerprint"]}
            if operator_gated:
                passed = got["resolvedQuery"] == expected["resolvedQuery"]
            else:
                passed = expected["kind"] == "query" and got["fingerprint"] == expected["fingerprint"]
            direct_code, direct = post(api, "/api/query", response["interpretation"]["resolvedQuery"], timeout=120)
            if direct_code == 401 and response["interpretation"]["resolvedQuery"]["unit"] == "entity":
                result = response["envelope"]["result"]
                grounded = result["kind"] == "empty" and result["reason"] == "operator_required"
            else:
                grounded = direct_code == 200 and comparable(direct) == comparable(response["envelope"])
        else:
            refusal = response["refusal"]
            got = {"kind": "refusal", "stage": refusal["stage"], "code": refusal["code"], "path": refusal["path"]}
            passed = (expected["kind"] == "refusal" and refusal["code"] == expected["code"]
                      and refusal["stage"] in REFUSAL_STAGES.get(expected["code"], ()))
            grounded = response["envelope"] is None and response["interpretation"] is None

        prompt_bound = None
        if question["id"] in recorded and recorded[question["id"]].get("stage") != "question":
            prompt_bound = recorded[question["id"]]["promptSha256"] == response["model"]["promptSha256"]
        results.append({
            "id": question["id"],
            "split": question["split"],
            "question": question["question"],
            "pass": passed,
            "grounded": grounded,
            "promptMatchesRecording": prompt_bound,
            "operatorGated": operator_gated,
            "expected": expected,
            "got": got,
            "resultKind": response["envelope"]["result"]["kind"] if response["envelope"] else None,
            "wallMs": round(wall_ms, 1),
            "timings": response["timings"],
            "promptSha256": response["model"]["promptSha256"],
            "promptTokens": response["model"]["promptTokens"],
            "generatedTokens": response["model"]["generatedTokens"],
        })
        mark = "PASS" if passed else "FAIL"
        print(f"{mark} {question['id']} {wall_ms / 1000:6.1f}s grounded={grounded} prompt={prompt_bound}", flush=True)

    def split_summary(split: str) -> dict:
        items = [item for item in results if item["split"] == split]
        return {"passed": sum(item["pass"] for item in items), "total": len(items)}

    walls = sorted(item["wallMs"] for item in results)
    summary = {
        "schemaVersion": "mavi-ask-e2e-v1",
        "recordedAtUtc": datetime.now(timezone.utc).isoformat(),
        "api": api,
        "host": {"platform": platform.platform(), "machine": platform.machine()},
        "status": status,
        "questions": questions_path.name,
        "questionsSha256": sha256(questions_path),
        "catalogueSha256": sha256(CATALOGUE),
        "recordings": recordings_path.name if recordings_path else None,
        "translation": {"development": split_summary("development"), "held": split_summary("held")},
        "grounded": {"passed": sum(item["grounded"] for item in results), "total": len(results),
                     "operatorGated": sum(item["operatorGated"] for item in results)},
        "promptMatchesRecording": {
            "passed": sum(item["promptMatchesRecording"] is True for item in results),
            "compared": sum(item["promptMatchesRecording"] is not None for item in results),
        },
        "latencyMs": {
            "median": statistics.median(walls),
            "p95": walls[min(len(walls) - 1, int(round(0.95 * (len(walls) - 1))))],
            "max": walls[-1],
        },
    }
    (out / "results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    sums = "".join(f"{sha256(path)}  {path.name}\n" for path in sorted(out.iterdir()) if path.name != "SHA256SUMS")
    (out / "SHA256SUMS").write_text(sums, encoding="utf-8")
    print(json.dumps({key: summary[key] for key in ("translation", "grounded", "promptMatchesRecording", "latencyMs")}, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run")
    run_parser.add_argument("--api", required=True)
    run_parser.add_argument("--recordings", type=Path)
    run_parser.add_argument("--out", type=Path, required=True)
    run_parser.add_argument("--questions", type=Path, default=QUESTIONS)
    args = parser.parse_args(argv)
    return run(args.api, args.recordings, args.out, args.questions)


if __name__ == "__main__":
    sys.exit(main())
