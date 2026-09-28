"""Corpus manifest v1: what was labelled, from which MAVI evidence, without any imagery.

The manifest mirrors MAVI's own evidence identity rather than inventing one:

* a **source** is one VideoAsset processed by one ProcessingRun (both MAVI UUIDs),
  with corpus-local pseudonymous ``siteId`` / ``cameraId`` (MAVI has no Site entity;
  the Corpus Custodian assigns site pseudonyms) and the recording *date* only;
* a **track** is a MAVI Track (UUID, object class) from that source;
* an **observation** is one accepted Evidence Set crop of the Track, identified by its
  MAVI Observation UUID, role (``representative`` / ``near-view`` / ``early-diverse`` /
  ``late-diverse``), evidence rank, byte size and SHA-256 — the same fields the S2b
  attribute lease carries (``LeaseObservation``).

The whole corpus carries one raw-evidence pin (vision pipeline profile SHA-256, Evidence
Set selector and scorer versions). Mixing crops produced under different pins is
refused: a selector or profile change re-derives the affected crops (S2c plan §10.2).
"""

from __future__ import annotations

from dataclasses import dataclass

from .canonical import (
    document_sha256,
    refuse_path_leaks,
    require,
    require_date,
    require_int,
    require_keys,
    require_pseudonym,
    require_sha256,
    require_token,
    require_uuid,
)

CORPUS_SCHEMA = "mavi-attribute-corpus-manifest-v1"
CORPUS_KINDS = ("operational", "synthetic-fixture")
ROLES = ("representative", "near-view", "early-diverse", "late-diverse")
LIGHTING = ("day", "night", "mixed", "unknown")
SETTING = ("indoor", "outdoor", "mixed", "unknown")
MAXIMUM_OBSERVATIONS = 4  # ADR-013 §4: at most four Evidence Set roles per Track


@dataclass(frozen=True, slots=True)
class Observation:
    observation_id: str
    track_id: str
    role: str
    evidence_rank: int
    sha256: str
    size_bytes: int
    width: int | None
    height: int | None


@dataclass(frozen=True, slots=True)
class Source:
    source_id: str
    site_id: str
    camera_id: str
    processing_run_id: str
    video_asset_id: str | None
    recording_date: str
    lighting: str
    setting: str
    frame_width: int | None
    frame_height: int | None
    source_class: str


@dataclass(frozen=True, slots=True)
class Track:
    track_id: str
    source_id: str
    object_class: str
    observations: tuple[Observation, ...]


@dataclass(frozen=True, slots=True)
class CorpusManifest:
    document: dict
    sha256: str
    corpus_id: str
    corpus_kind: str
    sources: dict[str, Source]
    tracks: dict[str, Track]

    @property
    def observations(self) -> dict[str, Observation]:
        return {o.observation_id: o for t in self.tracks.values() for o in t.observations}

    def source_of(self, track_id: str) -> Source:
        return self.sources[self.tracks[track_id].source_id]


def normalise_corpus(document: dict) -> dict:
    """Documented order: sources by sourceId, tracks by trackId, observations by evidenceRank."""
    normal = dict(document)
    normal["sources"] = sorted(document.get("sources", []), key=lambda s: s.get("sourceId", ""))
    tracks = []
    for track in sorted(document.get("tracks", []), key=lambda t: t.get("trackId", "")):
        track = dict(track)
        track["observations"] = sorted(track.get("observations", []), key=lambda o: o.get("evidenceRank", 0))
        tracks.append(track)
    normal["tracks"] = tracks
    return normal


def _optional_dimension(value: object, code: str) -> int | None:
    return None if value is None else require_int(value, code, 1, 100_000)


def parse_corpus(document: dict) -> CorpusManifest:
    code = "corpus_invalid"
    require_keys(document, code, ("schemaVersion", "corpusId", "revision", "supersedes", "corpusKind", "rawEvidencePin", "sources", "tracks"))
    require(document["schemaVersion"] == CORPUS_SCHEMA, f"{code}:schema")
    refuse_path_leaks(document, "corpus_path_leak")
    corpus_id = require_pseudonym(document["corpusId"], f"{code}:corpus_id")
    revision = require_int(document["revision"], f"{code}:revision", 1)
    require((revision == 1) == (document["supersedes"] is None), f"{code}:supersedes")
    if document["supersedes"] is not None:
        require_sha256(document["supersedes"], f"{code}:supersedes")
    require(document["corpusKind"] in CORPUS_KINDS, f"{code}:kind")
    pin = document["rawEvidencePin"]
    require(isinstance(pin, dict), f"{code}:pin")
    require_keys(pin, f"{code}:pin", ("visionPipelineProfileSha256", "evidenceSelectorVersion", "evidenceScorerVersion"))
    require_sha256(pin["visionPipelineProfileSha256"], f"{code}:pin")
    require_token(pin["evidenceSelectorVersion"], f"{code}:pin")
    require_token(pin["evidenceScorerVersion"], f"{code}:pin")

    sources: dict[str, Source] = {}
    require(isinstance(document["sources"], list) and document["sources"], f"{code}:sources")
    for entry in document["sources"]:
        scode = f"{code}:source"
        require(isinstance(entry, dict), scode)
        require_keys(entry, scode, ("sourceId", "siteId", "cameraId", "processingRunId", "videoAssetId", "recordingDate", "conditions"))
        source_id = require_pseudonym(entry["sourceId"], scode)
        require(source_id not in sources, f"corpus_duplicate_source:{source_id}")
        conditions = entry["conditions"]
        require(isinstance(conditions, dict), scode)
        require_keys(conditions, f"{scode}:conditions", ("lighting", "setting", "frameWidth", "frameHeight", "sourceClass"))
        require(conditions["lighting"] in LIGHTING and conditions["setting"] in SETTING, f"{scode}:conditions")
        require_token(conditions["sourceClass"], f"{scode}:conditions")
        require_date(entry["recordingDate"], f"{scode}:date")
        sources[source_id] = Source(
            source_id=source_id,
            site_id=require_pseudonym(entry["siteId"], f"{scode}:site"),
            camera_id=require_pseudonym(entry["cameraId"], f"{scode}:camera"),
            processing_run_id=require_uuid(entry["processingRunId"], f"{scode}:run"),
            video_asset_id=None if entry["videoAssetId"] is None else require_uuid(entry["videoAssetId"], f"{scode}:video"),
            recording_date=entry["recordingDate"],
            lighting=conditions["lighting"],
            setting=conditions["setting"],
            frame_width=_optional_dimension(conditions["frameWidth"], f"{scode}:frame"),
            frame_height=_optional_dimension(conditions["frameHeight"], f"{scode}:frame"),
            source_class=conditions["sourceClass"],
        )
    runs = [s.processing_run_id for s in sources.values()]
    require(len(runs) == len(set(runs)), "corpus_duplicate_processing_run")
    videos = [s.video_asset_id for s in sources.values() if s.video_asset_id is not None]
    # One VideoAsset processed twice would put the same footage in the corpus twice.
    require(len(videos) == len(set(videos)), "corpus_duplicate_video_asset")

    tracks: dict[str, Track] = {}
    observation_ids: set[str] = set()
    require(isinstance(document["tracks"], list) and document["tracks"], f"{code}:tracks")
    for entry in document["tracks"]:
        tcode = f"{code}:track"
        require(isinstance(entry, dict), tcode)
        require_keys(entry, tcode, ("trackId", "sourceId", "objectClass", "observations"))
        track_id = require_uuid(entry["trackId"], tcode)
        require(track_id not in tracks, f"corpus_duplicate_track:{track_id}")
        require(entry["sourceId"] in sources, f"corpus_track_source_unknown:{track_id}")
        require(entry["objectClass"] in ("person", "vehicle"), f"{tcode}:class")
        items = entry["observations"]
        require(isinstance(items, list) and 1 <= len(items) <= MAXIMUM_OBSERVATIONS, f"{tcode}:observations")
        observations = []
        for item in items:
            ocode = f"{code}:observation"
            require(isinstance(item, dict), ocode)
            require_keys(item, ocode, ("observationId", "role", "evidenceRank", "sha256", "sizeBytes", "width", "height"))
            observation_id = require_uuid(item["observationId"], ocode)
            require(observation_id not in observation_ids, f"corpus_duplicate_observation:{observation_id}")
            observation_ids.add(observation_id)
            require(item["role"] in ROLES, f"{ocode}:role")
            observations.append(
                Observation(
                    observation_id=observation_id,
                    track_id=track_id,
                    role=item["role"],
                    evidence_rank=require_int(item["evidenceRank"], f"{ocode}:rank", 0, MAXIMUM_OBSERVATIONS - 1),
                    sha256=require_sha256(item["sha256"], f"{ocode}:sha256"),
                    size_bytes=require_int(item["sizeBytes"], f"{ocode}:size", 1),
                    width=_optional_dimension(item["width"], f"{ocode}:width"),
                    height=_optional_dimension(item["height"], f"{ocode}:height"),
                )
            )
        roles = [o.role for o in observations]
        ranks = [o.evidence_rank for o in observations]
        require(len(set(roles)) == len(roles) and len(set(ranks)) == len(ranks), f"corpus_track_roles_not_unique:{track_id}")
        # S1 invariant: every accepted Track has its Representative (ADR-013 §4).
        require("representative" in roles, f"corpus_track_without_representative:{track_id}")
        tracks[track_id] = Track(track_id, entry["sourceId"], entry["objectClass"], tuple(sorted(observations, key=lambda o: o.evidence_rank)))

    normal = normalise_corpus(document)
    return CorpusManifest(
        document=normal,
        sha256=document_sha256(normal),
        corpus_id=corpus_id,
        corpus_kind=document["corpusKind"],
        sources=sources,
        tracks=tracks,
    )


def revise_corpus(previous: CorpusManifest, document: dict) -> CorpusManifest:
    """A revised manifest is a new identity: revision + 1 and ``supersedes`` = previous hash."""
    require(document.get("revision") == previous.document["revision"] + 1, "corpus_revision_not_incremented")
    require(document.get("supersedes") == previous.sha256, "corpus_revision_supersedes_mismatch")
    require(document.get("corpusId") == previous.corpus_id, "corpus_revision_id_changed")
    revised = parse_corpus(document)
    require(revised.sha256 != previous.sha256, "corpus_revision_identical")
    return revised
