"""Small, real Evidence Set values for tests that exercise staging and the wire."""

from __future__ import annotations

from io import BytesIO

from PIL import Image

from mavi_vision.common.analytical import NormalizedBoundingBox
from mavi_vision.evidence.encoder import EncodedImage
from mavi_vision.evidence.roles import ROLE_ORDER, EvidenceRole
from mavi_vision.evidence.selector import ResolvedEvidence, SelectedEvidence


def jpeg(width: int = 8, height: int = 8, value: int = 120) -> EncodedImage:
    buffer = BytesIO()
    Image.new("RGB", (width, height), (value, value, value)).save(buffer, format="JPEG", quality=85)
    return EncodedImage(buffer.getvalue(), width, height, 85, 0)


def resolved(
    *specs: tuple[EvidenceRole, int, int],
    confidence: float = 0.9,
    score: int = 800_000,
) -> tuple[ResolvedEvidence, ...]:
    """``specs`` are (role, source_frame_number, offset_ms) in role order."""
    items = []
    for rank, (role, frame, offset) in enumerate(specs):
        items.append(
            ResolvedEvidence(
                rank,
                SelectedEvidence(
                    role=role,
                    offset_ms=offset,
                    source_frame_number=frame,
                    confidence=confidence,
                    bounding_box=NormalizedBoundingBox(0.1, 0.1, 0.4, 0.5),
                    area=0.2,
                    quality_micro=score,
                    selection_micro=score,
                    qualified=True,
                    image=jpeg(value=40 + 50 * ROLE_ORDER.index(role)),
                ),
            )
        )
    return tuple(items)


def representative_only(frame: int = 0, offset: int = 0) -> tuple[ResolvedEvidence, ...]:
    return resolved((EvidenceRole.REPRESENTATIVE, frame, offset))


def observation(
    track_id: str,
    role: EvidenceRole = EvidenceRole.REPRESENTATIVE,
    rank: int = 0,
    *,
    frame: int = 1,
    offset: int = 0,
    confidence: float = 0.9,
    size: int = 10,
    prefix: str = "staging/job/attempt-0001",
):
    from mavi_vision.common.analytical import ArtifactDescriptor, ObservationDescriptor

    return ObservationDescriptor(
        role=role,
        rank=rank,
        offset_ms=offset,
        source_frame_number=frame,
        confidence=confidence,
        bounding_box=NormalizedBoundingBox(0.1, 0.1, 0.2, 0.4),
        quality_micro=800_000,
        selection_micro=800_000,
        crop=ArtifactDescriptor(
            storage_key=f"{prefix}/evidence/{track_id}-{role.value}.jpg",
            media_type="image/jpeg",
            size_bytes=size,
            sha256="a" * 64,
        ),
    )


def admitted_accounting(tracks):
    """Accounting for a result in which every candidate was admitted (tests only)."""
    from mavi_vision.common.analytical import EvidenceAccounting, RoleAccounting

    by_role = {}
    for role in ROLE_ORDER:
        sizes = [o.crop.size_bytes for t in tracks for o in t.observations if o.role is role]
        by_role[role] = RoleAccounting(len(sizes), len(sizes), 0, sum(sizes), sum(sizes))
    return EvidenceAccounting.of(by_role)
