"""E2E contract tests for hermes-nutrition-bot.

Full path: run.py gate → bridge → real nutrition-service.
Agent loop is mocked (no Codex call). No real Telegram connection.

Run with: uv run pytest -m integration tests/e2e/ -n0 -v
"""
from __future__ import annotations

import os
import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock

from gateway.platforms.base import MessageEvent
from gateway.session import SessionSource
from gateway.config import Platform


def _service_url():
    return os.getenv("NUTRITION_SERVICE_BASE_URL", "http://172.17.0.1:8781")


@pytest.fixture(scope="session")
def _require_service():
    try:
        r = httpx.get(f"{_service_url()}/health", timeout=2.0)
        if r.status_code >= 500:
            pytest.skip("nutrition-service returned server error")
    except Exception:
        pytest.skip("nutrition-service unreachable")


@pytest.fixture
def runner_and_adapter():
    from gateway.run import GatewayRunner
    runner = object.__new__(GatewayRunner)
    runner.config = MagicMock()
    runner.config.group_sessions_per_user = True
    runner.config.thread_sessions_per_user = False
    runner._run_agent = AsyncMock(return_value={
        "final_response": '[{"name": "banana", "quantity_g": 120, "confidence": 0.85}]'
    })
    adapter = MagicMock()
    adapter.send = AsyncMock()
    adapter._bot = MagicMock()
    adapter._bot.send_message = AsyncMock()
    return runner, adapter


def _dm_event(chat_id, text="", media_urls=None, callback_data=None):
    source = SessionSource(
        platform=Platform.TELEGRAM, chat_id=chat_id, user_id=chat_id, chat_type="dm"
    )
    return MessageEvent(
        text=text, source=source,
        media_urls=media_urls or [],
        callback_data=callback_data,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_e2e_photo_flow_end_to_end(_require_service, runner_and_adapter):
    """Photo DM → gate → bridge → nutrition-service → inline keyboard sent."""
    runner, adapter = runner_and_adapter
    event = _dm_event("e2e_photo_user", media_urls=["file:///tmp/banana.jpg"])

    await runner._handle_nutrition_message(event, adapter)

    adapter._bot.send_message.assert_called_once()
    markup = adapter._bot.send_message.call_args[1]["reply_markup"]
    assert len(markup.inline_keyboard[0]) >= 1
    first_cb = markup.inline_keyboard[0][0].callback_data
    assert first_cb.startswith("nc:")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_e2e_callback_select_flow(_require_service, runner_and_adapter):
    """nc: callback → gate → bridge → nutrition-service /select → Logged!"""
    runner, adapter = runner_and_adapter
    from gateway.nutrition_client import NutritionClient
    from gateway.session import build_session_key
    client = NutritionClient()
    session_key = build_session_key(
        SessionSource(platform=Platform.TELEGRAM, chat_id="e2e_cb_user", user_id="e2e_cb_user", chat_type="dm"),
        group_sessions_per_user=True,
        thread_sessions_per_user=False,
    )
    data = await client.analyze(session_key, [{"name": "banana", "quantity_g": 120, "confidence": 0.9}])
    set_id = data["candidate_set_id"]
    cand_id = data["candidates"][0]["id"]

    event = _dm_event("e2e_cb_user", callback_data=f"nc:{set_id}:{cand_id}")
    await runner._handle_nutrition_message(event, adapter)

    adapter.send.assert_called_once()
    assert "Logged" in adapter.send.call_args[0][1]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_e2e_text_no_pending_prompts_photo(_require_service, runner_and_adapter):
    """Plain text + no pending → 'Send me a photo'."""
    runner, adapter = runner_and_adapter
    event = _dm_event("e2e_nopending_user", text="what did I eat?")

    await runner._handle_nutrition_message(event, adapter)

    adapter.send.assert_called_once()
    assert "photo" in adapter.send.call_args[0][1].lower()


@pytest.mark.asyncio
async def test_e2e_group_message_dropped(runner_and_adapter):
    """Non-DM message dropped silently (no service call needed)."""
    runner, adapter = runner_and_adapter
    source = SessionSource(
        platform=Platform.TELEGRAM, chat_id="grp1", user_id="u1", chat_type="group"
    )
    event = MessageEvent(text="hi group", source=source)

    result = await runner._handle_nutrition_message(event, adapter)

    assert result is False
    adapter.send.assert_not_called()
    adapter._bot.send_message.assert_not_called()
