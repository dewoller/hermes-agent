"""E2E contract tests for nutrition-service persisted correction flows."""

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from nutrition_service.api import create_app
from nutrition_service.db import create_schema
from nutrition_service.models import MealLog, SourceFoodUsda, SourceProductOff
from nutrition_service.service import NutritionService


def test_analyze_then_correct_logs_manual_meal_entry(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'nutrition.sqlite3'}"
    engine = create_engine(database_url)
    create_schema(engine)
    with Session(engine) as session:
        session.add(SourceFoodUsda(description="Chicken salad", energy_kcal=205.0, raw_payload={}))
        session.commit()
    client = TestClient(create_app(database_url=database_url))

    analyze = client.post(
        "/api/nutrition/v1/analyze",
        json={
            "session_id": "telegram:dm:1",
            "caption_text": "lunch",
            "image_paths": ["/tmp/lunch.jpg"],
        },
    )

    assert analyze.status_code == 200
    candidate_set_id = analyze.json()["candidate_set_id"]

    correct = client.post(
        "/api/nutrition/v1/correct",
        json={
            "session_id": "telegram:dm:1",
            "candidate_set_id": candidate_set_id,
            "correction_text": "two eggs and toast",
        },
    )

    assert correct.status_code == 200
    assert correct.json() == {"logged": True, "message": "Logged corrected meal."}

    with Session(engine) as session:
        meal_log = session.scalar(select(MealLog))
        assert meal_log is not None
        assert meal_log.title == "two eggs and toast"
        assert meal_log.calories is None


def test_label_observation_calories_override_seeded_packaged_food_profile(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'nutrition.sqlite3'}"
    engine = create_engine(database_url)
    create_schema(engine)
    with Session(engine) as session:
        session.add(
            SourceProductOff(
                barcode="930000000001",
                product_name="Protein Bar",
                brand_name="Test Brand",
                energy_kcal=210.0,
                raw_payload={},
            )
        )
        session.commit()

    async def analyze_image(_image_path: str) -> dict:
        return {
            "parsed_barcode": "930000000001",
            "parsed_product_name": "Protein Bar",
            "parsed_brand_name": "Test Brand",
            "parsed_nutrients_json": {"energy_kcal": 230.0},
            "confidence": 0.97,
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
            "caption_text": "snack",
            "image_paths": ["/tmp/wrapper.jpg"],
        },
    )

    assert analyze.status_code == 200
    payload = analyze.json()
    assert payload["candidates"][0]["calories"] == 230.0

    select_response = client.post(
        "/api/nutrition/v1/select",
        json={
            "session_id": "telegram:dm:1",
            "candidate_set_id": payload["candidate_set_id"],
            "candidate_id": payload["candidates"][0]["candidate_id"],
        },
    )

    assert select_response.status_code == 200

    with Session(engine) as session:
        meal_log = session.scalar(select(MealLog))
        assert meal_log is not None
        assert meal_log.title == "Test Brand Protein Bar"
        assert meal_log.calories == 230.0
