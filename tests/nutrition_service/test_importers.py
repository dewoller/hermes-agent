from click.testing import CliRunner

from nutrition_service.cli import cli
from nutrition_service.importers.fsanz import normalize_fsanz_row
from nutrition_service.importers.off import normalize_off_record
from nutrition_service.importers.usda import normalize_usda_food


def test_normalize_off_record_extracts_core_nutrients():
    row = {
        "code": "930000000001",
        "product_name": "Test Bar",
        "brands": "Test Brand",
        "serving_size": "50 g",
        "nutriments": {
            "energy-kcal_serving": 210,
            "proteins_serving": 20,
            "carbohydrates_serving": 15,
            "fat_serving": 7,
        },
    }

    normalized = normalize_off_record(row)

    assert normalized.barcode == "930000000001"
    assert normalized.product_name == "Test Bar"
    assert normalized.energy_kcal == 210
    assert normalized.protein_g == 20


def test_normalize_fsanz_row_extracts_generic_food_fields():
    row = {"Food ID": "A001", "Food Name": "Boiled egg", "Energy, kcal": "155", "Protein, g": "12.6"}

    normalized = normalize_fsanz_row(row)

    assert normalized.food_name == "Boiled egg"
    assert normalized.energy_kcal == 155
    assert normalized.protein_g == 12.6


def test_normalize_usda_food_extracts_serving_and_gtin():
    food = {
        "fdcId": 123,
        "description": "Protein Bar",
        "gtinUpc": "008181234567",
        "servingSize": 50,
        "servingSizeUnit": "g",
        "foodNutrients": [{"nutrientName": "Energy", "unitName": "KCAL", "value": 205}],
    }

    normalized = normalize_usda_food(food)

    assert normalized.fdc_id == 123
    assert normalized.gtin_upc == "008181234567"
    assert normalized.serving_size == 50
    assert normalized.energy_kcal == 205


def test_normalize_usda_food_preserves_first_valid_duplicate_nutrient_value():
    food = {
        "fdcId": 321,
        "description": "Duplicate Nutrient Bar",
        "gtinUpc": "000000000321",
        "servingSize": 60,
        "servingSizeUnit": "g",
        "foodNutrients": [
            {"nutrientName": "Energy", "unitName": "KCAL", "value": 205},
            {"nutrientName": "Energy", "unitName": "KCAL", "value": ""},
            {"nutrientName": "Protein", "unitName": "G", "value": 18.5},
            {"nutrientName": "Protein", "unitName": "G", "value": None},
            {"nutrientName": "Carbohydrate, by difference", "unitName": "G", "value": 23},
            {"nutrientName": "Carbohydrate, by difference", "unitName": "G", "value": "nope"},
            {"nutrientName": "Total lipid (fat)", "unitName": "G", "value": 9},
            {"nutrientName": "Total lipid (fat)", "unitName": "G", "value": "bad"},
        ],
    }

    normalized = normalize_usda_food(food)

    assert normalized.energy_kcal == 205
    assert normalized.protein_g == 18.5
    assert normalized.carbs_g == 23
    assert normalized.fat_g == 9


def test_import_commands_accept_existing_files_and_reject_missing_files(tmp_path):
    runner = CliRunner()
    existing_paths = {
        "import-off": tmp_path / "off.json",
        "import-fsanz": tmp_path / "fsanz.csv",
        "import-usda": tmp_path / "usda.json",
    }

    for path in existing_paths.values():
        path.write_text("[]", encoding="utf-8")

    for command, path in existing_paths.items():
        result = runner.invoke(cli, [command, str(path)])

        assert result.exit_code == 0
        assert f"{command} {path}" in result.output

    missing_path = tmp_path / "missing.json"

    for command in existing_paths:
        result = runner.invoke(cli, [command, str(missing_path)])

        assert result.exit_code != 0
        assert "does not exist" in result.output
