from __future__ import annotations

import inspect
import json
from typing import Any
import re

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from nutrition_service.contracts import CandidateModel
from nutrition_service.resolution import build_source_candidates
from nutrition_service.models import (
    AnalysisRequest,
    ImageAsset,
    LabelObservation,
    MealCandidate,
    MealLog,
    SourceFoodFsanz,
    SourceFoodUsda,
    SourceProductOff,
)
from tools.vision_tools import vision_analyze_tool

_LABEL_OBSERVATION_PROMPT = """
Inspect this food image for packaged-food label evidence.
Return JSON only with these keys:
- parsed_barcode: string or null
- parsed_product_name: string or null
- parsed_brand_name: string or null
- parsed_nutrients_json: object with any of energy_kcal, protein_g, carbs_g, fat_g when visible
- confidence: number from 0 to 1

If this is not a readable packaged-food label or wrapper, return {}.
Do not include markdown fences or explanatory text.
""".strip()

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


class NutritionService:
    def __init__(self, session_factory: sessionmaker[Session] | Any, image_analyzer: Any | None = None) -> None:
        self._session_factory = session_factory
        self._image_analyzer = image_analyzer or self._analyze_image

    async def analyze(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = str(payload.get("session_id") or "").strip()
        caption_text = str(payload.get("caption_text") or "").strip()
        image_paths = [str(path).strip() for path in list(payload.get("image_paths") or []) if str(path).strip()]
        image_observations = [
            await self._call_image_analyzer(image_path)
            for image_path in image_paths
        ]
        best_label_observation = self._best_label_observation(image_observations)

        with self._session_factory() as session:
            analysis_request = AnalysisRequest(
                session_id=session_id,
                caption_text=caption_text or None,
                status="completed",
            )
            session.add(analysis_request)
            session.flush()

            for image_path, observation in zip(image_paths, image_observations):
                image_asset = ImageAsset(
                    analysis_request_id=analysis_request.id,
                    storage_path=image_path,
                )
                session.add(image_asset)
                session.flush()
                if observation:
                    session.add(
                        LabelObservation(
                            image_asset_id=image_asset.id,
                            parsed_product_name=self._clean_text(observation.get("parsed_product_name")),
                            parsed_brand_name=self._clean_text(observation.get("parsed_brand_name")),
                            parsed_barcode=self._clean_text(observation.get("parsed_barcode")),
                            parsed_nutrients_json=self._clean_mapping(observation.get("parsed_nutrients_json")),
                            confidence=self._coerce_confidence(observation.get("confidence")),
                            status="pending",
                        )
                    )
            candidates = build_source_candidates(
                caption_text=caption_text,
                label_observation=best_label_observation,
                off_rows=self._source_rows(
                    session,
                    select(
                        SourceProductOff.id,
                        SourceProductOff.barcode,
                        SourceProductOff.product_name,
                        SourceProductOff.brand_name,
                        SourceProductOff.energy_kcal,
                        SourceProductOff.protein_g,
                        SourceProductOff.carbs_g,
                        SourceProductOff.fat_g,
                    ),
                ),
                fsanz_rows=self._source_rows(
                    session,
                    select(
                        SourceFoodFsanz.id,
                        SourceFoodFsanz.food_name,
                        SourceFoodFsanz.energy_kcal,
                        SourceFoodFsanz.protein_g,
                        SourceFoodFsanz.carbs_g,
                        SourceFoodFsanz.fat_g,
                    ),
                ),
                usda_rows=self._source_rows(
                    session,
                    select(
                        SourceFoodUsda.id,
                        SourceFoodUsda.gtin_upc,
                        SourceFoodUsda.description,
                        SourceFoodUsda.energy_kcal,
                        SourceFoodUsda.protein_g,
                        SourceFoodUsda.carbs_g,
                        SourceFoodUsda.fat_g,
                    ),
                ),
            )

            validated_candidates = [CandidateModel(**candidate).model_dump() for candidate in candidates]

            for candidate in validated_candidates:
                session.add(
                    MealCandidate(
                        analysis_request_id=analysis_request.id,
                        candidate_id=candidate["candidate_id"],
                        candidate_title=candidate["title"],
                        reason_text=candidate["reason_text"],
                        confidence=candidate["confidence"],
                        calories=candidate.get("calories"),
                        protein_g=candidate.get("protein_g"),
                        carbs_g=candidate.get("carbs_g"),
                        fat_g=candidate.get("fat_g"),
                    )
                )

            session.commit()

            return {
                "candidate_set_id": str(analysis_request.id),
                "candidates": validated_candidates,
            }

    def select_candidate(self, payload: dict[str, Any]) -> dict[str, Any]:
        candidate_set_id = self._parse_analysis_request_id(payload.get("candidate_set_id"))
        candidate_id = str(payload.get("candidate_id") or "").strip()

        with self._session_factory() as session:
            analysis_request = session.get(AnalysisRequest, candidate_set_id)
            candidate = session.scalar(
                select(MealCandidate).where(
                    MealCandidate.analysis_request_id == candidate_set_id,
                    MealCandidate.candidate_id == candidate_id,
                )
            )
            if analysis_request is None or candidate is None:
                return {"logged": False, "message": "Nutrition candidate not found."}

            analysis_request.status = "selected"
            session.add(
                MealLog(
                    analysis_request_id=analysis_request.id,
                    title=candidate.candidate_title,
                    calories=candidate.calories,
                )
            )
            session.commit()
            return {"logged": True, "message": f"Logged {candidate.candidate_title}."}

    def correct_candidate(self, payload: dict[str, Any]) -> dict[str, Any]:
        candidate_set_id = self._parse_analysis_request_id(payload.get("candidate_set_id"))
        correction_text = str(payload.get("correction_text") or "").strip()

        with self._session_factory() as session:
            analysis_request = session.get(AnalysisRequest, candidate_set_id)
            if analysis_request is None:
                return {"logged": False, "message": "Nutrition candidate not found."}

            analysis_request.status = "corrected"
            session.add(
                MealLog(
                    analysis_request_id=analysis_request.id,
                    title=correction_text,
                    calories=None,
                )
            )
            session.commit()
            return {"logged": True, "message": "Logged corrected meal."}

    @staticmethod
    def _source_rows(session: Session, statement) -> list[dict[str, Any]]:
        return [dict(row._mapping) for row in session.execute(statement).all()]

    @staticmethod
    async def _analyze_image(image_path: str) -> dict[str, Any] | None:
        result_json = await vision_analyze_tool(image_path, _LABEL_OBSERVATION_PROMPT)
        try:
            result = json.loads(result_json)
        except json.JSONDecodeError:
            return None
        if not isinstance(result, dict) or result.get("success") is not True:
            return None
        analysis = str(result.get("analysis") or "").strip()
        if not analysis:
            return None
        return NutritionService._parse_label_observation_response(analysis)

    async def _call_image_analyzer(self, image_path: str) -> dict[str, Any] | None:
        try:
            result = self._image_analyzer(image_path)
            if inspect.isawaitable(result):
                result = await result
        except Exception:
            return None
        if not isinstance(result, dict):
            return None
        return result

    @staticmethod
    def _best_label_observation(observations: list[dict[str, Any] | None]) -> dict[str, Any] | None:
        valid = [observation for observation in observations if isinstance(observation, dict)]
        if not valid:
            return None
        return max(valid, key=lambda observation: NutritionService._coerce_confidence(observation.get("confidence")))

    @staticmethod
    def _parse_label_observation_response(analysis: str) -> dict[str, Any] | None:
        payload = analysis.strip()
        if payload.startswith("```"):
            payload = re.sub(r"^```(?:json)?\s*", "", payload)
            payload = re.sub(r"\s*```$", "", payload)
        if not payload.startswith("{"):
            match = _JSON_OBJECT_RE.search(payload)
            if match:
                payload = match.group(0)
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict):
            return None
        return parsed

    @staticmethod
    def _clean_text(value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None

    @staticmethod
    def _clean_mapping(value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        return value

    @staticmethod
    def _coerce_confidence(value: Any) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return 0.0
        if confidence < 0:
            return 0.0
        if confidence > 1:
            return 1.0
        return confidence

    @staticmethod
    def _parse_analysis_request_id(raw_value: Any) -> int | None:
        try:
            return int(str(raw_value).strip())
        except (TypeError, ValueError):
            return None
