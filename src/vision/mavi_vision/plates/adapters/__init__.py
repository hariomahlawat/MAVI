"""The closed, versioned registry of plate capability adapters (Stage 4 plan §2.4; ADR-013 item 8).

Only the Development fixture exists until a Model Selection Event selects real components (PR-6).
A Model Pack names its adapter through ``capabilitySpecific.<capabilityId>.adapterId``; an id outside
this registry is refused, never guessed.
"""

from __future__ import annotations

from mavi_vision.plates.adapters.fixture import FIXTURE_ADAPTER_ID, FixturePlateDetector, FixturePlateRecogniser
from mavi_vision.plates.inference import PlateDetector, PlateRecogniser


class AdapterUnavailable(ValueError):
    pass


def components_for(adapter_id: str, *, seed: str | None, development_only: bool, production_mode: bool) -> tuple[PlateDetector, PlateRecogniser]:
    """The detector and recogniser an adapter id names. The fixture is refused in Production."""
    if adapter_id == FIXTURE_ADAPTER_ID:
        if production_mode or not development_only:
            raise AdapterUnavailable("plate_fixture_forbidden_in_production")
        if not seed:
            raise AdapterUnavailable("plate_fixture_seed_required")
        return FixturePlateDetector(seed), FixturePlateRecogniser(seed)
    raise AdapterUnavailable("plate_adapter_unknown")


__all__ = ["AdapterUnavailable", "components_for"]
