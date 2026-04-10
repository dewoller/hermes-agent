from sqlalchemy import create_engine, inspect

from nutrition_service.db import create_schema


def test_create_schema_creates_core_tables():
    engine = create_engine("sqlite+pysqlite:///:memory:")

    create_schema(engine)

    tables = set(inspect(engine).get_table_names())
    assert "source_product_off" in tables
    assert "food_item" in tables
    assert "nutrient_profile" in tables
    assert "image_asset" in tables
    assert "label_observation" in tables
    assert "analysis_request" in tables
    assert "meal_candidate" in tables
    assert "meal_log" in tables
