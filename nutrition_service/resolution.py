from collections.abc import Mapping, Sequence
import math
from typing import Any


def _normalized_words(text: str) -> set[str]:
    return {
        word
        for word in str(text or "").lower().replace("/", " ").replace("-", " ").split()
        if word
    }


def _score_title_match(*, caption_text: str, title: str, source_name: str) -> tuple[float, str]:
    caption = str(caption_text or "").strip().lower()
    title_text = str(title or "").strip()
    title_lower = title_text.lower()
    overlap = len(_normalized_words(caption) & _normalized_words(title_text))
    phrase_match = bool(caption and title_lower and title_lower in caption)
    base_scores = {
        "off": 0.45,
        "usda": 0.40,
        "fsanz": 0.35,
    }
    confidence = base_scores.get(source_name, 0.30)
    if overlap:
        confidence += min(0.30, overlap * 0.15)
    if phrase_match:
        confidence += 0.20
    confidence = min(confidence, 0.99)
    if overlap or phrase_match:
        return confidence, f"matched caption text against {source_name.upper()} source data"
    return confidence, f"fallback {source_name.upper()} source candidate"


def _normalized_barcode(value: Any) -> str:
    return "".join(ch for ch in str(value or "").strip() if ch.isdigit())


def _normalized_phrase(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _matched_label_reason(
    *,
    source_name: str,
    title: str,
    barcode: Any,
    label_observation: Mapping[str, Any] | None,
) -> tuple[float, str, bool]:
    if not label_observation:
        return 0.0, "", False

    observed_barcode = _normalized_barcode(label_observation.get("parsed_barcode"))
    candidate_barcode = _normalized_barcode(barcode)
    if observed_barcode and candidate_barcode and observed_barcode == candidate_barcode:
        return 0.99, f"matched label observation barcode against {source_name.upper()} source data", True

    observed_product = _normalized_phrase(label_observation.get("parsed_product_name"))
    observed_brand = _normalized_phrase(label_observation.get("parsed_brand_name"))
    title_text = _normalized_phrase(title)
    if observed_brand and observed_brand not in title_text:
        return 0.0, "", False
    if observed_product and observed_product in title_text:
        if observed_brand and observed_brand in title_text:
            return 0.97, f"matched label observation text against {source_name.upper()} source data", True
        return 0.95, f"matched label observation text against {source_name.upper()} source data", True
    return 0.0, "", False


def _apply_label_nutrients(
    candidate: dict[str, Any],
    label_observation: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not label_observation:
        return candidate
    parsed_nutrients = label_observation.get("parsed_nutrients_json")
    if not isinstance(parsed_nutrients, Mapping):
        return candidate
    for candidate_key in ("calories", "protein_g", "carbs_g", "fat_g"):
        source_key = "energy_kcal" if candidate_key == "calories" else candidate_key
        if parsed_nutrients.get(source_key) is not None:
            candidate[candidate_key] = parsed_nutrients.get(source_key)
    return candidate


def build_source_candidates(
    *,
    caption_text: str,
    label_observation: Mapping[str, Any] | None = None,
    off_rows: Sequence[Mapping[str, Any]],
    fsanz_rows: Sequence[Mapping[str, Any]],
    usda_rows: Sequence[Mapping[str, Any]],
    limit: int = 3,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    for row in off_rows:
        title = " ".join(
            part.strip()
            for part in (str(row.get("brand_name") or ""), str(row.get("product_name") or ""))
            if part and part.strip()
        )
        if not title:
            continue
        matched_confidence, matched_reason, matched = _matched_label_reason(
            source_name="off",
            title=title,
            barcode=row.get("barcode"),
            label_observation=label_observation,
        )
        if matched:
            candidate = {
                "candidate_id": f"off:{row.get('id')}",
                "title": title,
                "calories": row.get("energy_kcal"),
                "protein_g": row.get("protein_g"),
                "carbs_g": row.get("carbs_g"),
                "fat_g": row.get("fat_g"),
                "confidence": matched_confidence,
                "reason_text": matched_reason,
            }
            candidates.append(_apply_label_nutrients(candidate, label_observation))
            continue

        confidence, reason_text = _score_title_match(caption_text=caption_text, title=title, source_name="off")
        candidates.append(
            {
                "candidate_id": f"off:{row.get('id')}",
                "title": title,
                "calories": row.get("energy_kcal"),
                "protein_g": row.get("protein_g"),
                "carbs_g": row.get("carbs_g"),
                "fat_g": row.get("fat_g"),
                "confidence": confidence,
                "reason_text": reason_text,
            }
        )

    for row in fsanz_rows:
        title = str(row.get("food_name") or "").strip()
        if not title:
            continue
        confidence, reason_text = _score_title_match(
            caption_text=caption_text,
            title=title,
            source_name="fsanz",
        )
        candidates.append(
            {
                "candidate_id": f"fsanz:{row.get('id')}",
                "title": title,
                "calories": row.get("energy_kcal"),
                "protein_g": row.get("protein_g"),
                "carbs_g": row.get("carbs_g"),
                "fat_g": row.get("fat_g"),
                "confidence": confidence,
                "reason_text": reason_text,
            }
        )

    for row in usda_rows:
        title = str(row.get("description") or "").strip()
        if not title:
            continue
        matched_confidence, matched_reason, matched = _matched_label_reason(
            source_name="usda",
            title=title,
            barcode=row.get("gtin_upc"),
            label_observation=label_observation,
        )
        if matched:
            candidate = {
                "candidate_id": f"usda:{row.get('id')}",
                "title": title,
                "calories": row.get("energy_kcal"),
                "protein_g": row.get("protein_g"),
                "carbs_g": row.get("carbs_g"),
                "fat_g": row.get("fat_g"),
                "confidence": matched_confidence,
                "reason_text": matched_reason,
            }
            candidates.append(_apply_label_nutrients(candidate, label_observation))
            continue

        confidence, reason_text = _score_title_match(caption_text=caption_text, title=title, source_name="usda")
        candidates.append(
            {
                "candidate_id": f"usda:{row.get('id')}",
                "title": title,
                "calories": row.get("energy_kcal"),
                "protein_g": row.get("protein_g"),
                "carbs_g": row.get("carbs_g"),
                "fat_g": row.get("fat_g"),
                "confidence": confidence,
                "reason_text": reason_text,
            }
        )

    return rank_candidates(candidates)[:limit]


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
