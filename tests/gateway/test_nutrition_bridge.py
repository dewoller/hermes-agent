"""Unit tests for NutritionBridge — all external calls mocked."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from gateway.nutrition_bridge import NutritionBridge, NUTRITION_SOUL


@pytest.fixture
def mock_client():
    c = MagicMock()
    c.analyze = AsyncMock()
    c.select = AsyncMock()
    c.correct = AsyncMock()
    c.get_pending = AsyncMock()
    return c


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
    r._run_agent = AsyncMock(
        return_value={"final_response": '[{"name": "apple", "confidence": 0.9}]'}
    )
    return r


def _event(chat_id="123", text="", media_urls=None):
    source = MagicMock()
    source.chat_id = chat_id
    e = MagicMock()
    e.text = text
    e.media_urls = media_urls or ["file:///photo.jpg"]
    e.source = source
    return e


# ── handle_photo_event ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_photo_passes_soul_to_run_agent(mock_client, mock_adapter, mock_runner):
    mock_client.analyze = AsyncMock(return_value={
        "candidate_set_id": "s1", "candidates": [{"id": "c1", "label": "Apple"}],
    })
    bridge = NutritionBridge(client=mock_client)
    await bridge.handle_photo_event(_event(), "sess", mock_runner, mock_adapter)

    args, kwargs = mock_runner._run_agent.call_args
    assert kwargs.get("context_prompt") == NUTRITION_SOUL


@pytest.mark.asyncio
async def test_photo_strips_markdown_fences(mock_client, mock_adapter, mock_runner):
    mock_runner._run_agent = AsyncMock(
        return_value={"final_response": '```json\n[{"name": "banana", "confidence": 0.8}]\n```'}
    )
    mock_client.analyze = AsyncMock(return_value={
        "candidate_set_id": "s1", "candidates": [{"id": "c1", "label": "Banana"}],
    })
    bridge = NutritionBridge(client=mock_client)
    await bridge.handle_photo_event(_event(), "sess", mock_runner, mock_adapter)

    obs = mock_client.analyze.call_args[0][1]
    assert obs[0]["name"] == "banana"


@pytest.mark.asyncio
async def test_photo_renders_inline_keyboard(mock_client, mock_adapter, mock_runner):
    mock_client.analyze = AsyncMock(return_value={
        "candidate_set_id": "setX",
        "candidates": [{"id": "c1", "label": "Apple"}, {"id": "c2", "label": "Pear"}],
    })
    bridge = NutritionBridge(client=mock_client)
    await bridge.handle_photo_event(_event(), "sess", mock_runner, mock_adapter)

    mock_adapter._bot.send_message.assert_called_once()
    markup = mock_adapter._bot.send_message.call_args[1]["reply_markup"]
    buttons = markup.inline_keyboard[0]
    assert buttons[0].callback_data == "nc:setX:c1"
    assert buttons[1].callback_data == "nc:setX:c2"


@pytest.mark.asyncio
async def test_photo_malformed_json_sends_error(mock_client, mock_adapter, mock_runner):
    mock_runner._run_agent = AsyncMock(return_value={"final_response": "not json"})
    bridge = NutritionBridge(client=mock_client)
    await bridge.handle_photo_event(_event(), "sess", mock_runner, mock_adapter)

    mock_adapter.send.assert_called_once()
    assert "try again" in mock_adapter.send.call_args[0][1].lower()
    mock_client.analyze.assert_not_called()


@pytest.mark.asyncio
async def test_photo_service_unavailable_sends_error(mock_client, mock_adapter, mock_runner):
    mock_client.analyze = AsyncMock(side_effect=Exception("refused"))
    bridge = NutritionBridge(client=mock_client)
    await bridge.handle_photo_event(_event(), "sess", mock_runner, mock_adapter)

    mock_adapter.send.assert_called_once()
    assert "unavailable" in mock_adapter.send.call_args[0][1].lower()


# ── handle_candidate_selection ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_selection_calls_select_correctly(mock_client, mock_adapter):
    mock_client.select = AsyncMock(return_value={"logged": True})
    bridge = NutritionBridge(client=mock_client)
    await bridge.handle_candidate_selection("nc:set1:cand1", "sess", mock_adapter, "123")

    mock_client.select.assert_called_once_with("sess", "set1", "cand1")
    mock_adapter.send.assert_called_once_with("123", "Logged!")


@pytest.mark.asyncio
async def test_selection_server_error_sends_unavailable(mock_client, mock_adapter):
    mock_client.select = AsyncMock(side_effect=Exception("500"))
    bridge = NutritionBridge(client=mock_client)
    await bridge.handle_candidate_selection("nc:set1:cand1", "sess", mock_adapter, "123")

    assert "unavailable" in mock_adapter.send.call_args[0][1].lower()


@pytest.mark.asyncio
async def test_selection_malformed_callback_no_reply(mock_client, mock_adapter):
    bridge = NutritionBridge(client=mock_client)
    await bridge.handle_candidate_selection("nc:only_two_parts", "sess", mock_adapter, "123")

    mock_client.select.assert_not_called()
    mock_adapter.send.assert_not_called()


# ── handle_correction ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_correction_with_pending_calls_correct(mock_client, mock_adapter):
    mock_client.get_pending = AsyncMock(
        return_value={"candidate_set_id": "set1", "candidates": []}
    )
    mock_client.correct = AsyncMock(return_value={"logged": True})
    bridge = NutritionBridge(client=mock_client)
    await bridge.handle_correction("grilled chicken", "sess", mock_adapter, "123")

    mock_client.correct.assert_called_once_with("sess", "set1", "grilled chicken")
    mock_adapter.send.assert_called_once_with("123", "Updated!")


@pytest.mark.asyncio
async def test_correction_no_pending_sends_prompt(mock_client, mock_adapter):
    mock_client.get_pending = AsyncMock(return_value=None)
    bridge = NutritionBridge(client=mock_client)
    await bridge.handle_correction("some text", "sess", mock_adapter, "123")

    mock_client.correct.assert_not_called()
    assert "photo" in mock_adapter.send.call_args[0][1].lower()


@pytest.mark.asyncio
async def test_correction_server_error_sends_unavailable(mock_client, mock_adapter):
    mock_client.get_pending = AsyncMock(
        return_value={"candidate_set_id": "set1", "candidates": []}
    )
    mock_client.correct = AsyncMock(side_effect=Exception("timeout"))
    bridge = NutritionBridge(client=mock_client)
    await bridge.handle_correction("text", "sess", mock_adapter, "123")

    assert "unavailable" in mock_adapter.send.call_args[0][1].lower()


@pytest.mark.asyncio
async def test_correction_get_pending_error_sends_unavailable(mock_client, mock_adapter):
    mock_client.get_pending = AsyncMock(side_effect=Exception("timeout"))
    bridge = NutritionBridge(client=mock_client)
    await bridge.handle_correction("some text", "sess", mock_adapter, "123")

    mock_client.correct.assert_not_called()
    assert "unavailable" in mock_adapter.send.call_args[0][1].lower()
