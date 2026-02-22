import pytest
import json
import urllib.error
from unittest.mock import patch, MagicMock

from bot import telegram_api as tg

def test_mask_token():
    """Test token masking function to ensure no sensitive leaks."""
    assert tg._mask_token("123456789:ABCDEFGH") == "123456789:AB***"
    assert tg._mask_token("invalid_token") == "***"
    assert tg._mask_token(None) == "***"

@patch("urllib.request.urlopen")
def test_api_request_success(mock_urlopen):
    """Test a successful Telegram API request parsing."""
    mock_response = MagicMock()
    mock_response.read.return_value = b'{"ok": true, "result": {"message_id": 123}}'
    mock_response.__enter__.return_value = mock_response
    mock_urlopen.return_value = mock_response

    result = tg.api_request("123:TOKEN", "sendMessage", data={"chat_id": 1, "text": "Hi"})
    
    assert result is not None
    assert result["ok"] is True
    assert result["result"]["message_id"] == 123

@patch("time.sleep")
@patch("urllib.request.urlopen")
def test_api_request_rate_limit(mock_urlopen, mock_sleep):
    """Test handling of HTTP 429 Rate Limit responses (Fix #14)."""
    
    # First call throws HTTP 429
    error_mock = MagicMock()
    error_mock.read.return_value = b'{"ok": false, "error_code": 429, "parameters": {"retry_after": 2}}'
    http_error = urllib.error.HTTPError("url", 429, "Too Many Requests", {}, None)
    http_error.read = error_mock.read
    
    # Second call succeeds
    success_mock = MagicMock()
    success_mock.read.return_value = b'{"ok": true, "result": "sent!"}'
    success_mock.__enter__.return_value = success_mock

    mock_urlopen.side_effect = [http_error, success_mock]

    # Force rate_limit_until to 0 initially
    tg._rate_limit_until = 0

    result = tg.api_request("123:TOKEN", "sendMessage", {"text": "Retried"})

    # Should have slept for roughly 2 seconds
    mock_sleep.assert_called()
    assert abs(mock_sleep.call_args[0][0] - 2.0) < 0.1
    assert result["ok"] is True

def test_make_inline_keyboard():
    """Test inline keyboard JSON generator handles limits."""
    buttons = [
        [("Button 1", "cb:1")],
        [("Button 2", "cb:2"), ("Button 3", "cb:3")]
    ]
    kb_json = tg.make_inline_keyboard(buttons)
    kb = json.loads(kb_json)
    
    assert "inline_keyboard" in kb
    assert len(kb["inline_keyboard"]) == 2
    assert kb["inline_keyboard"][0][0]["text"] == "Button 1"
    assert kb["inline_keyboard"][1][1]["callback_data"] == "cb:3"

def test_make_inline_keyboard_truncation():
    """Ensure callback data longer than 64 bytes is truncated."""
    long_cb = "a" * 100
    buttons = [[("Long", long_cb)]]
    kb_json = tg.make_inline_keyboard(buttons)
    kb = json.loads(kb_json)
    
    # Should be exactly 64 bytes
    assert len(kb["inline_keyboard"][0][0]["callback_data"]) == 64
