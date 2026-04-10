import inspect
from typing import Any

from fastapi import FastAPI


def _resolve_analysis_not_configured(payload: dict[str, Any]) -> dict[str, Any]:
    raise RuntimeError("app.state.resolve_analysis must be configured before calling /analyze")


def create_app() -> FastAPI:
    app = FastAPI()
    app.state.resolve_analysis = _resolve_analysis_not_configured

    @app.get("/api/nutrition/v1/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/api/nutrition/v1/analyze")
    async def analyze(payload: dict[str, Any]) -> Any:
        result = app.state.resolve_analysis(payload)
        if inspect.isawaitable(result):
            result = await result
        return result

    @app.post("/api/nutrition/v1/select")
    def select(payload: dict[str, Any]) -> dict[str, bool]:
        return {"logged": True}

    @app.post("/api/nutrition/v1/correct")
    def correct(payload: dict[str, Any]) -> dict[str, bool]:
        return {"logged": True}

    return app
