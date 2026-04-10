from dataclasses import dataclass


def _pick_number(*values: object) -> float | None:
    for value in values:
        if value is None or value == "":
            continue
        if isinstance(value, (int, float)):
            return value
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


@dataclass
class UsdaImportFood:
    fdc_id: int | None
    description: str | None
    gtin_upc: str | None
    serving_size: float | None
    serving_size_unit: str | None
    energy_kcal: float | None
    protein_g: float | None
    carbs_g: float | None
    fat_g: float | None
    raw_payload: dict


def normalize_usda_food(food: dict) -> UsdaImportFood:
    nutrients = food.get("foodNutrients") or []
    energy_kcal = None
    protein_g = None
    carbs_g = None
    fat_g = None

    for nutrient in nutrients:
        name = nutrient.get("nutrientName")
        unit = nutrient.get("unitName")
        value = nutrient.get("value")
        if name == "Energy" and unit == "KCAL" and energy_kcal is None:
            energy_kcal = _pick_number(value)
        elif name == "Protein" and protein_g is None:
            protein_g = _pick_number(value)
        elif name in {"Carbohydrate, by difference", "Carbohydrate"} and carbs_g is None:
            carbs_g = _pick_number(value)
        elif name == "Total lipid (fat)" and fat_g is None:
            fat_g = _pick_number(value)

    return UsdaImportFood(
        fdc_id=food.get("fdcId"),
        description=food.get("description"),
        gtin_upc=food.get("gtinUpc"),
        serving_size=_pick_number(food.get("servingSize")),
        serving_size_unit=food.get("servingSizeUnit"),
        energy_kcal=energy_kcal,
        protein_g=protein_g,
        carbs_g=carbs_g,
        fat_g=fat_g,
        raw_payload=food,
    )
