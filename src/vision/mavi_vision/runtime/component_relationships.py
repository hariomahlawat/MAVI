"""Cross-artefact variant rules of the one variant model (ADR-014 §4a; P-17).

These pure checks relate a component binding, a runtime profile's variant
classes and a qualification record. They are the single implementation used by
the v1->v2 migration generator (S2a.1) and, from S2a.3, by the resolver and
``verify_repo``.
"""

from __future__ import annotations

from typing import Mapping

from mavi_vision.runtime.binding import RuntimePackVariantV2
from mavi_vision.runtime.manifest import ReleaseMetadataError
from mavi_vision.runtime.qualification_v2 import QualificationRecordV2
from mavi_vision.runtime.variants import VariantClass


def check_binding_variants(
    *,
    binding_variants: Mapping[str, RuntimePackVariantV2],
    variant_classes: Mapping[str, VariantClass],
) -> None:
    """The binding declares exactly the family's deployable (class B) variants."""
    for variant in sorted(variant_classes):
        variant_class = variant_classes[variant]
        declared = variant in binding_variants
        if variant_class is VariantClass.DEPLOYABLE and not declared:
            raise ReleaseMetadataError(f"binding_variant_missing:{variant}")
        if variant_class is VariantClass.KNOWN_NOT_RELEASABLE and declared:
            raise ReleaseMetadataError(f"binding_variant_not_releasable:{variant}")
    for variant in sorted(set(binding_variants) - set(variant_classes)):
        raise ReleaseMetadataError(f"binding_variant_unknown:{variant}")


def check_record_variants(
    *,
    record: QualificationRecordV2,
    binding_variants: Mapping[str, RuntimePackVariantV2],
    variant_classes: Mapping[str, VariantClass],
) -> None:
    """Class B carries the bound Runtime Pack id; class A carries none (P-17)."""
    for variant in sorted(record.variants):
        record_variant = record.variants[variant]
        variant_class = variant_classes.get(variant)
        if variant_class is VariantClass.DEPLOYABLE:
            if record_variant.runtime_pack_id is None:
                raise ReleaseMetadataError(f"qualification_runtime_pack_required:{variant}")
            bound = binding_variants.get(variant)
            if bound is None:
                raise ReleaseMetadataError(f"binding_variant_missing:{variant}")
            if record_variant.runtime_pack_id != bound.runtime_pack_id:
                raise ReleaseMetadataError(f"qualification_runtime_pack_mismatch:{variant}")
        elif variant_class is VariantClass.KNOWN_NOT_RELEASABLE:
            if record_variant.runtime_pack_id is not None:
                raise ReleaseMetadataError(f"qualification_runtime_pack_forbidden:{variant}")
        else:
            raise ReleaseMetadataError(f"qualification_variant_unknown:{variant}")


__all__ = ["check_binding_variants", "check_record_variants"]
