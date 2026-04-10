from collections.abc import Mapping, Sequence
import math
from typing import Any


def choose_packaged_profile(label_profile, user_profile, off_profile, usda_profile):
    for profile in (label_profile, user_profile, off_profile, usda_profile):
        if profile is not None:
            return profile
    return None


def _candidate_value(candidate: Any, field_name: str, default: Any = None) -> Any:
    if isinstance(candidate, Mapping):
        return candidate.get(field_name, default)
    return getattr(candidate, field_name, default)


def _candidate_confidence(candidate: Any) -> float:
    raw_confidence = _candidate_value(candidate, "confidence", 0.0)
    if isinstance(raw_confidence, bool) or isinstance(raw_confidence, str):
        return 0.0
    try:
        confidence = float(raw_confidence)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(confidence):
        return 0.0
    return confidence


def rank_candidates(candidates: Sequence[Any]) -> list[Any]:
    return sorted(
        candidates,
        key=lambda candidate: (-_candidate_confidence(candidate), -len(str(_candidate_value(candidate, "reason_text", "") or "").strip())),
    )
