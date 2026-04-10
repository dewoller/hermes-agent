from sqlalchemy import create_engine, inspect

from nutrition_service.db import create_engine_from_url, create_schema, create_session_factory


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


def test_schema_layer_exposes_engine_and_session_behavior():
    engine = create_engine_from_url("sqlite+pysqlite:///:memory:")

    assert engine.url.drivername == "sqlite+pysqlite"
    assert engine.url.database == ":memory:"

    session_factory = create_session_factory(engine)
    assert session_factory.kw["bind"] is engine
    assert session_factory.kw["autoflush"] is False
    assert "autocommit" not in session_factory.kw
    assert "future" not in session_factory.kw

    session = session_factory()
    try:
        assert session.bind is engine
        assert session.autoflush is False
    finally:
        session.close()


def test_nutrient_profile_has_food_item_foreign_key():
    engine = create_engine("sqlite+pysqlite:///:memory:")

    create_schema(engine)

    columns = {column["name"]: column for column in inspect(engine).get_columns("nutrient_profile")}
    assert columns["food_item_id"]["nullable"] is False

    foreign_keys = inspect(engine).get_foreign_keys("nutrient_profile")
    assert foreign_keys == [
        {
            "name": None,
            "constrained_columns": ["food_item_id"],
            "referred_schema": None,
            "referred_table": "food_item",
            "referred_columns": ["id"],
            "options": {},
        }
    ]
