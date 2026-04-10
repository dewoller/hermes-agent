from typing import Any

import httpx


class NutritionServiceClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8781",
        client: httpx.Client | None = None,
    ) -> None:
        self._client = client or httpx.Client(base_url=base_url)
        self._owns_client = client is None

    def analyze_meal(self, payload: dict[str, Any]) -> Any:
        response = self._client.post("/api/nutrition/v1/analyze", json=payload)
        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
