"""Integration tests for persisted nutrition-service meal flows."""

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from nutrition_service.api import create_app
from nutrition_service.db import create_schema
from nutrition_service.models import AnalysisRequest, ImageAsset, LabelObservation, MealCandidate, MealLog, SourceFoodFsanz, SourceFoodUsda, SourceProductOff
from nutrition_service.service import NutritionService


def test_analyze_then_select_persists_request_candidates_and_meal_log(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'nutrition.sqlite3'}"
    engine = create_engine(database_url)
    create_schema(engine)
    with Session(engine) as session:
        session.add_all(
            [
                SourceProductOff(product_name="Protein Bar", brand_name="Test Brand", energy_kcal=210.0, raw_payload={}),
                SourceFoodFsanz(food_name="Boiled egg", energy_kcal=155.0, raw_payload={}),
                SourceFoodUsda(description="Chicken salad", energy_kcal=205.0, raw_payload={}),
            ]
        )
        session.commit()
    client = TestClient(create_app(database_url=database_url))

    analyze = client.post(
        "/api/nutrition/v1/analyze",
        json={
            "session_id": "telegram:dm:1",
            "caption_text": "chicken salad lunch",
            "image_paths": ["/tmp/lunch.jpg"],
        },
    )

    assert analyze.status_code == 200
    payload = analyze.json()
    assert payload["candidate_set_id"]
    assert [candidate["title"] for candidate in payload["candidates"]] == [
        "Chicken salad",
        "Test Brand Protein Bar",
        "Boiled egg",
    ]

    with Session(engine) as session:
        analysis_request = session.scalar(select(AnalysisRequest))
        image_asset = session.scalar(select(ImageAsset))
        meal_candidates = session.scalars(select(MealCandidate).order_by(MealCandidate.id)).all()

        assert analysis_request is not None
        assert analysis_request.session_id == "telegram:dm:1"
        assert analysis_request.caption_text == "chicken salad lunch"
        assert image_asset is not None
        assert image_asset.storage_path == "/tmp/lunch.jpg"
        assert [candidate.candidate_title for candidate in meal_candidates] == [
            "Chicken salad",
            "Test Brand Protein Bar",
            "Boiled egg",
        ]

    select_response = client.post(
        "/api/nutrition/v1/select",
        json={
            "session_id": "telegram:dm:1",
            "candidate_set_id": payload["candidate_set_id"],
            "candidate_id": payload["candidates"][0]["candidate_id"],
        },
    )

    assert select_response.status_code == 200
    assert select_response.json() == {"logged": True, "message": "Logged Chicken salad."}

    with Session(engine) as session:
        meal_log = session.scalar(select(MealLog))
        assert meal_log is not None
        assert meal_log.title == "Chicken salad"
        assert meal_log.calories == 205.0


def test_analyze_persists_label_observation_and_prefers_packaged_match(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'nutrition.sqlite3'}"
    engine = create_engine(database_url)
    create_schema(engine)
    with Session(engine) as session:
        session.add_all(
            [
                SourceProductOff(
                    barcode="930000000001",
                    product_name="Protein Bar",
                    brand_name="Test Brand",
                    energy_kcal=210.0,
                    raw_payload={},
                ),
                SourceFoodFsanz(food_name="Boiled egg", energy_kcal=155.0, raw_payload={}),
            ]
        )
        session.commit()

    async def analyze_image(_image_path: str) -> dict:
        return {
            "parsed_barcode": "930000000001",
            "parsed_product_name": "Protein Bar",
            "parsed_brand_name": "Test Brand",
            "parsed_nutrients_json": {"energy_kcal": 230.0},
            "confidence": 0.94,
        }

    service = NutritionService(
        session_factory=lambda: Session(engine),
        image_analyzer=analyze_image,
    )
    client = TestClient(create_app(service=service))

    analyze = client.post(
        "/api/nutrition/v1/analyze",
        json={
            "session_id": "telegram:dm:1",
            "caption_text": "lunch",
            "image_paths": ["/tmp/wrapper.jpg"],
        },
    )

    assert analyze.status_code == 200
    payload = analyze.json()
    assert payload["candidates"][0]["title"] == "Test Brand Protein Bar"
    assert payload["candidates"][0]["calories"] == 230.0

    with Session(engine) as session:
        observation = session.scalar(select(LabelObservation))
        assert observation is not None
        assert observation.parsed_barcode == "930000000001"
        assert observation.parsed_nutrients_json == {"energy_kcal": 230.0}
        assert observation.status == "pending"


def test_analyze_falls_back_to_caption_ranking_when_image_analyzer_fails(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'nutrition.sqlite3'}"
    engine = create_engine(database_url)
    create_schema(engine)
    with Session(engine) as session:
        session.add(SourceFoodUsda(description="Chicken salad", energy_kcal=205.0, raw_payload={}))
        session.commit()

    async def analyze_image(_image_path: str) -> dict:
        raise RuntimeError("vision backend exploded")

    service = NutritionService(
        session_factory=lambda: Session(engine),
        image_analyzer=analyze_image,
    )
    client = TestClient(create_app(service=service))

    analyze = client.post(
        "/api/nutrition/v1/analyze",
        json={
            "session_id": "telegram:dm:1",
            "caption_text": "chicken salad lunch",
            "image_paths": ["/tmp/wrapper.jpg"],
        },
    )

    assert analyze.status_code == 200
    payload = analyze.json()
    assert payload["candidates"][0]["title"] == "Chicken salad"

    with Session(engine) as session:
        assert session.scalar(select(LabelObservation)) is None
