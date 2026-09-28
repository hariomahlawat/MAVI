"""Synthetic S2c.1 corpus fixtures. They prove tooling; they are never corpus evidence."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

PIN = {
    "visionPipelineProfileSha256": "a" * 64,
    "evidenceSelectorVersion": "evidence-selector-v1-two-tier",
    "evidenceScorerVersion": "quality-v2",
}


def uid(*parts: object) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "mavi-s2c1-fixture/" + "/".join(map(str, parts))))


def sha(*parts: object) -> str:
    import hashlib

    return hashlib.sha256("/".join(map(str, parts)).encode()).hexdigest()


def build_corpus(
    sites: int = 3,
    cameras_per_site: int = 3,
    days: int = 12,
    tracks_per_source: int = 4,
    start: date = date(2026, 3, 2),
    kind: str = "synthetic-fixture",
) -> dict:
    """A corpus with one source per (site, camera, day); each Track has two crops."""
    sources, tracks = [], []
    for site in range(sites):
        for camera in range(cameras_per_site):
            for day in range(days):
                source_id = f"src-s{site}-c{camera}-d{day}"
                sources.append(
                    {
                        "sourceId": source_id,
                        "siteId": f"site-{site}",
                        "cameraId": f"cam-{site}-{camera}",
                        "processingRunId": uid("run", source_id),
                        "videoAssetId": uid("video", source_id),
                        "recordingDate": (start + timedelta(days=day)).isoformat(),
                        "conditions": {
                            "lighting": "night" if day % 3 == 0 else "day",
                            "setting": "outdoor",
                            "frameWidth": 1920,
                            "frameHeight": 1080,
                            "sourceClass": "h264-recorded",
                        },
                    }
                )
                for index in range(tracks_per_source):
                    track_id = uid("track", source_id, index)
                    object_class = "vehicle" if index % 4 == 3 else "person"
                    tracks.append(
                        {
                            "trackId": track_id,
                            "sourceId": source_id,
                            "objectClass": object_class,
                            "observations": [
                                {
                                    "observationId": uid("obs", track_id, 0),
                                    "role": "representative",
                                    "evidenceRank": 0,
                                    "sha256": sha("crop", track_id, 0),
                                    "sizeBytes": 20_000,
                                    "width": 96,
                                    "height": 64 + 40 * (index % 4),
                                },
                                {
                                    "observationId": uid("obs", track_id, 1),
                                    "role": "near-view",
                                    "evidenceRank": 1,
                                    "sha256": sha("crop", track_id, 1),
                                    "sizeBytes": 60_000,
                                    "width": 180,
                                    "height": 300,
                                },
                            ],
                        }
                    )
    return {
        "schemaVersion": "mavi-attribute-corpus-manifest-v1",
        "corpusId": "fixture-corpus",
        "revision": 1,
        "supersedes": None,
        "corpusKind": kind,
        "rawEvidencePin": dict(PIN),
        "sources": sources,
        "tracks": tracks,
    }


def policy(**overrides: object) -> dict:
    base = {
        "policyId": "s2c1-partition-policy",
        "version": "1",
        "seed": "fixture-seed",
        "dateBlockDays": 3,
        "heldOutSites": 1,
        "frozenLatestBlockFraction": 0.25,
        "targetFractions": {"training": 0.6, "tuning": 0.2, "selection": 0.2},
        "minimumCamerasPerPartition": 3,
        "requireUnseenFrozenCamera": True,
    }
    base.update(overrides)
    return base
