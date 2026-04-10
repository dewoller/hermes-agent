from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from nutrition_service.models import Base


def create_engine_from_url(database_url: str):
    return create_engine(database_url, future=True)


def create_session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def create_schema(engine) -> None:
    Base.metadata.create_all(engine)
