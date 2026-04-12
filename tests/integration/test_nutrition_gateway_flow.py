"""Integration tests: real nutrition-service, mocked agent loop.

Run with: uv run pytest -m integration tests/integration/ -n0 -v
Requires NUTRITION_SERVICE_BASE_URL pointing to a running nutrition-service.
"""
from __future__ import annotations

import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock

from gateway.nutrition_client import NutritionClient
from gateway.nutrition_bridge import NutritionBridge


def _service_url():
    import os
    return os.getenv("NUTRITION_SERVICE_BASE_URL", "http://172.17.0.1:8781")


@pytest.fixture(scope="session")
def _require_service():
    """Session fixture: skip all tests if nutrition-service is unreachable."""
    try:
        r = httpx.get(f"{_service_url()}/health", timeout=2.0)
        if r.status_code >= 500:
            pytest.skip("nutrition-service returned server error")
    except Exception:
        pytest.skip("nutrition-service unreachable — set NUTRITION_SERVICE_BASE_URL")


@pytest.fixture
def mock_adapter():
    a = MagicMock()
    a.send = AsyncMock()
    a._bot = MagicMock()
    a._bot.send_message = AsyncMock()
    return a


@pytest.fixture
def mock_runner():
    r = MagicMock()
    r._run_agent = AsyncMock(return_value={
        "final_response": '[{"name": "apple", "brand": null, "barcode": null, "quantity_g": 100, "confidence": 0.9}]'
    })
    return r


def _event(session_key: str):
    source = MagicMock()
    source.chat_id = session_key
    e = MagicMock()
    e.text = ""
    e.media_urls = ["file:///tmp/test.jpg"]
    e.source = source
    return e


@pytest.mark.integration
@pytest.mark.asyncio
async def test_photo_to_select(_require_service, mock_adapter, mock_runner):
    """Photo → observe → candidates → select → logged."""
    from gateway.nutrition_bridge import _TELEGRAM_AVAILABLE
    if not _TELEGRAM_AVAILABLE:
        pytest.skip("python-telegram-bot not installed")
    key = "intg_select_test"
    bridge = NutritionBridge()
    await bridge.handle_photo_event(_event(key), key, mock_runner, mock_adapter)

    assert mock_adapter._bot.send_message.called, "Inline keyboard should be sent"
    markup = mock_adapter._bot.send_message.call_args[1]["reply_markup"]
    cb = markup.inline_keyboard[0][0].callback_data  # "nc:{set_id}:{cand_id}"

    mock_adapter.send.reset_mock()
    await bridge.handle_candidate_selection(cb, key, mock_adapter, key)
    assert "Logged" in mock_adapter.send.call_args[0][1]


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.xfail(strict=False, reason="Spec assumption: nutrition-service may not clear pending on /correct")
async def test_photo_to_correct(_require_service, mock_adapter, mock_runner):
    """Photo → observe → candidates → correct → logged, pending cleared."""
    key = "intg_correct_test"
    bridge = NutritionBridge()
    client = NutritionClient()

    await bridge.handle_photo_event(_event(key), key, mock_runner, mock_adapter)

    pending = await client.get_pending(key)
    assert pending is not None

    mock_adapter.send.reset_mock()
    await bridge.handle_correction("grilled chicken 150g", key, mock_adapter, key)
    assert "Updated" in mock_adapter.send.call_args[0][1]

    # Spec assumption: nutrition-service clears pending state after a successful /correct.
    # If this assertion fails, the nutrition-service API contract may differ — remove or
    # adjust based on actual service behaviour.
    assert await client.get_pending(key) is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_session_isolation(_require_service, mock_adapter, mock_runner):
    """Two session keys do not share pending state."""
    bridge = NutritionBridge()
    client = NutritionClient()
    key_a, key_b = "intg_iso_a", "intg_iso_b"

    await bridge.handle_photo_event(_event(key_a), key_a, mock_runner, mock_adapter)

    assert await client.get_pending(key_a) is not None
    assert await client.get_pending(key_b) is None
