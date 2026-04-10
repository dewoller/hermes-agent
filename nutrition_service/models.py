from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SourceProductOff(Base):
    __tablename__ = "source_product_off"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    barcode: Mapped[str | None] = mapped_column(String(64), index=True)
    product_name: Mapped[str | None] = mapped_column(Text)
    brand_name: Mapped[str | None] = mapped_column(Text)
    nutriments_raw: Mapped[dict | None] = mapped_column(JSON)
    raw_payload: Mapped[dict] = mapped_column(JSON)


class FoodItem(Base):
    __tablename__ = "food_item"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(Text)
    brand_name: Mapped[str | None] = mapped_column(Text)
    canonical_barcode: Mapped[str | None] = mapped_column(String(64), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class NutrientProfile(Base):
    __tablename__ = "nutrient_profile"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    food_item_id: Mapped[int] = mapped_column(ForeignKey("food_item.id"))
    profile_kind: Mapped[str] = mapped_column(String(32), index=True)
    serving_basis_type: Mapped[str] = mapped_column(String(32))
    energy_kcal: Mapped[float | None] = mapped_column(Float)
    protein_g: Mapped[float | None] = mapped_column(Float)
    carbs_g: Mapped[float | None] = mapped_column(Float)
    fat_g: Mapped[float | None] = mapped_column(Float)
    provenance_json: Mapped[dict | None] = mapped_column(JSON)


class ImageAsset(Base):
    __tablename__ = "image_asset"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_file_id: Mapped[str | None] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(Text)


class LabelObservation(Base):
    __tablename__ = "label_observation"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    image_asset_id: Mapped[int] = mapped_column(ForeignKey("image_asset.id"))
    parsed_barcode: Mapped[str | None] = mapped_column(String(64), index=True)
    parsed_nutrients_json: Mapped[dict | None] = mapped_column(JSON)
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), index=True)


class AnalysisRequest(Base):
    __tablename__ = "analysis_request"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(255), index=True)
    caption_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), index=True)


class MealCandidate(Base):
    __tablename__ = "meal_candidate"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_title: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    calories: Mapped[float | None] = mapped_column(Float)


class MealLog(Base):
    __tablename__ = "meal_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    calories: Mapped[float | None] = mapped_column(Float)
