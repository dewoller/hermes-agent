from urllib.parse import urljoin
from typing import Any

import httpx

_DEFAULT_BASE_URL = "http://127.0.0.1:8781"
_UNSET = object()


class NutritionServiceClient:
    def __init__(
        self,
        base_url: str | object = _UNSET,
        client: httpx.Client | None = None,
    ) -> None:
        explicit_base_url = base_url is not _UNSET
        resolved_base_url = str(base_url) if explicit_base_url else _DEFAULT_BASE_URL

        if client is None:
            self._client = httpx.Client(base_url=resolved_base_url)
            self._owns_client = True
            effective_base_url = resolved_base_url
        else:
            self._client = client
            self._owns_client = False
            effective_base_url = resolved_base_url if explicit_base_url else str(client.base_url)

        self._analyze_url = urljoin(effective_base_url.rstrip("/") + "/", "api/nutrition/v1/analyze")

    def analyze_meal(self, payload: dict[str, Any]) -> Any:
        response = self._client.post(self._analyze_url, json=payload)
        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
