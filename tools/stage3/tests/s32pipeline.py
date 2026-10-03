"""Drives the S3.2a-2 tools through their command lines for tests: sample → packs →
scripted blind decisions → freeze → adjudicate → measure."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import s32fixtures as f

import build_labeling_pack
import freeze_labels
import run_subclass_measurement
import sample_tracks

a = f.a


def run(main: Callable[[list[str]], int], args: list[str]) -> None:
    import contextlib
    import io

    errors = io.StringIO()
    with contextlib.redirect_stderr(errors):
        code = main(args)
    assert code == 0, f"{main.__module__}: {errors.getvalue().strip()}"


def repeat(flag: str, paths: list[Path]) -> list[str]:
    return [item for path in paths for item in (flag, str(path))]


def sample(world: f.World, out: Path, *, target: int, seed: str = "s32-seed", design: str = "continuation",
           reason: str | None = None, exclude: list[Path] = (), exports: list[Path] | None = None,
           derivations: list[Path] | None = None, overlap: str = "0.2") -> list[str]:
    args = [*repeat("--export", exports or world.exports()), *repeat("--derivation", derivations or world.derivations()),
            "--requirements", str(world.requirements), "--requirements-commit", world.commit,
            "--target", str(target), "--overlap-fraction", overlap, "--seed", seed, "--design", design,
            *repeat("--exclude-sample", list(exclude)), "--repository", str(world.repository), "--out", str(out)]
    if reason is not None:
        args += ["--reason", reason]
    return args


def pack(world: f.World, sample_path: Path, out: Path, *, view: str = "primary", parent: Path | None = None,
         seed: str = "pack-seed", exports: list[Path] | None = None, templates: Path | None = None) -> list[str]:
    args = ["--sample", str(sample_path), *repeat("--export", exports or world.exports()),
            *repeat("--source", world.sources()), "--pipeline-profile", str(world.profile_path),
            "--labeling-guide", str(world.guide), "--labeling-guide-commit", world.commit, "--seed", seed,
            "--reviewer-view", view, "--repository", str(world.repository), "--out", str(out)]
    if parent is not None:
        args += ["--parent-pack", str(parent)]
    if templates is not None:
        args += ["--templates", str(templates)]
    return args


def draft(pack_dir: Path, decide: Callable[[dict[str, Any]], dict[str, Any]], reviewer: str, out: Path) -> Path:
    """Scripted reviewer: decides each pack item from the hidden manifest's Track id (the script, not the page)."""
    manifest = json.loads((pack_dir / build_labeling_pack.MANIFEST).read_text(encoding="utf-8"))
    pack_sha = a.sha256_hex((pack_dir / build_labeling_pack.MANIFEST).read_bytes())
    decisions = [{"itemId": item["itemId"], **decide(item)} for item in manifest["items"]]
    out.write_text(json.dumps({"packSha256": pack_sha, "reviewerName": reviewer, "decisions": decisions}), encoding="utf-8")
    return out


def freeze(pack_dir: Path, draft_path: Path, reviewer: str, out: Path, role: str = "fixture reviewer") -> list[str]:
    return ["freeze", "--pack", str(pack_dir), "--decisions", str(draft_path), "--reviewer-name", reviewer,
            "--reviewer-role", role, "--reviewed-on", "2026-10-03", "--out", str(out)]


def by_track(world: f.World, choices: dict[int, tuple[str, str | None]]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Decisions keyed by the fixture Track number: (label, unknownReason)."""
    numbers = {t.track_id: t.number for v in world.videos for t in v.tracks}

    def decide(item: dict[str, Any]) -> dict[str, Any]:
        label, reason = choices[numbers[item["trackId"]]]
        return {"label": label, **({"unknownReason": reason} if reason else {})}

    return decide


def measure(world: f.World, out: Path, *, samples: list[Path], labels: list[Path], overlap: list[Path], adjudications: list[Path],
            packs: list[Path], exports: list[Path] | None = None, requirements: Path | None = None) -> list[str]:
    return [*repeat("--sample", samples), *repeat("--labels", labels), *repeat("--overlap-labels", overlap),
            *repeat("--adjudication", adjudications), *repeat("--pack", packs),
            *repeat("--export", exports or world.exports()), "--pipeline-profile", str(world.profile_path),
            "--requirements", str(requirements or world.requirements), "--repository", str(world.repository),
            "--out", str(out)]


__all__ = ["build_labeling_pack", "freeze_labels", "run_subclass_measurement", "sample_tracks", "run", "sample", "pack",
           "draft", "freeze", "by_track", "measure"]


def batch(world: f.World, root: Path, *, target: int, seed: str, primary: dict[int, tuple[str, str | None]],
          overlap: dict[int, tuple[str, str | None]] | None = None, adjudicated: dict[int, tuple[str, str | None]] | None = None,
          design: str = "continuation", reason: str | None = None, exclude: list[Path] = (), overlap_fraction: str = "0.25"
          ) -> dict[str, Path]:
    """One complete batch: sample, both packs, frozen labels and the adjudication.

    ``overlap`` overrides the overlap reviewer's choices (default: agree with ``primary``);
    ``adjudicated`` gives the adjudicator's final choice for each disagreement."""
    root.mkdir(parents=True)
    sample_path = root / "sample.json"
    run(sample_tracks.main, sample(world, sample_path, target=target, seed=seed, design=design, reason=reason,
                                   exclude=list(exclude), overlap=overlap_fraction))
    primary_pack, overlap_pack = root / "pack-primary", root / "pack-overlap"
    run(build_labeling_pack.main, pack(world, sample_path, primary_pack, seed=f"{seed}-pack"))
    run(build_labeling_pack.main, pack(world, sample_path, overlap_pack, view="overlap", parent=primary_pack, seed=f"{seed}-pack"))
    second = {**primary, **(overlap or {})}
    primary_labels, overlap_labels = root / "labels-primary.json", root / "labels-overlap.json"
    run(freeze_labels.main, freeze(primary_pack, draft(primary_pack, by_track(world, primary), "Reviewer A", root / "d1.json"),
                                   "Reviewer A", primary_labels))
    run(freeze_labels.main, freeze(overlap_pack, draft(overlap_pack, by_track(world, second), "Reviewer B", root / "d2.json"),
                                   "Reviewer B", overlap_labels))
    numbers = {t.track_id: t.number for v in world.videos for t in v.tracks}
    labels = json.loads(primary_labels.read_text(encoding="utf-8"))
    overlap_tracks = {d["trackId"] for d in json.loads(overlap_labels.read_text(encoding="utf-8"))["decisions"]}
    decisions = []
    for d in labels["decisions"]:
        number = numbers[d["trackId"]]
        if d["trackId"] in overlap_tracks and primary[number] != second[number]:
            label, why = (adjudicated or {})[number]
            decisions.append({"itemId": d["itemId"], "adjudicatedLabel": label, **({"adjudicatedUnknownReason": why} if why else {})})
    primary_sha, overlap_sha = a.sha256_hex(primary_labels.read_bytes()), a.sha256_hex(overlap_labels.read_bytes())
    (root / "adjudication-decisions.json").write_text(json.dumps({
        "primaryLabelsSha256": primary_sha, "overlapLabelsSha256": overlap_sha,
        "sessionId": freeze_labels.session_id(primary_sha, overlap_sha), "decisions": decisions}), encoding="utf-8")
    adjudication = root / "adjudication.json"
    run(freeze_labels.main, ["adjudicate", "--primary", str(primary_labels), "--overlap", str(overlap_labels),
                             "--decisions", str(root / "adjudication-decisions.json"), "--adjudicator", "Adjudicator C",
                             "--adjudicated-on", "2026-10-04", "--out", str(adjudication)])
    return {"sample": sample_path, "primaryPack": primary_pack, "overlapPack": overlap_pack,
            "primaryLabels": primary_labels, "overlapLabels": overlap_labels, "adjudication": adjudication}


def overlap_numbers(world: f.World, sample_path: Path) -> list[int]:
    numbers = {t.track_id: t.number for v in world.videos for t in v.tracks}
    return sorted(numbers[i["trackId"]] for i in json.loads(sample_path.read_text(encoding="utf-8"))["overlapSelected"])
