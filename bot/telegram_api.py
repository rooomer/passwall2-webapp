"""
PassWall 2 Telegram Bot - Telegram API Layer (Hardened)
Uses only urllib (stdlib) to communicate with the Telegram Bot API.
Supports long polling, sending messages, inline keyboards, and sendData handling.

Fix #13: Token masking in logs.
Fix #14: Retry-After handling for HTTP 429 rate limits.
"""
import json
import time
import urllib.request
import urllib.error
import urllib.parse
import ssl
import logging
import codecs

try:
    codecs.lookup('idna')
except LookupError:
    # OpenWrt python3-light strips the idna codec, but telegram api doesn't use international domains
    codecs.register(lambda name: codecs.lookup('ascii') if name == 'idna' else None)

logger = logging.getLogger("passwall2_bot")

# Disable SSL verification for constrained OpenWrt environments
# (some builds lack full CA bundles)
_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE

# Rate limit state
_rate_limit_until = 0  # timestamp until which we should not send requests


def _mask_token(token):
    """Mask a bot token for safe logging: 12345:ABCDEF -> 12345:AB***"""
    if not token or ":" not in token:
        return "***"
    parts = token.split(":")
    return f"{parts[0]}:{parts[1][:2]}***"


def api_request(token, method, data=None, files=None, timeout=35):
    """Make a Telegram Bot API request. Returns parsed JSON or None.
    Handles HTTP 429 with automatic retry-after backoff.
    """
    global _rate_limit_until

    # Respect rate limit
    now = time.time()
    if now < _rate_limit_until:
        wait = _rate_limit_until - now
        logger.warning("Rate limited, sleeping %.1fs before API call", wait)
        time.sleep(wait)

    url = f"https://api.telegram.org/bot{token}/{method}"
    headers = {}

    if files:
        # Multipart form-data for file uploads
        boundary = "----PW2BotBoundary"
        body = b""
        for key, val in (data or {}).items():
            body += f"--{boundary}\r\n".encode()
            body += f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode()
            body += f"{val}\r\n".encode()
        for key, (filename, filedata, content_type) in files.items():
            body += f"--{boundary}\r\n".encode()
            body += f'Content-Disposition: form-data; name="{key}"; filename="{filename}"\r\n'.encode()
            body += f"Content-Type: {content_type}\r\n\r\n".encode()
            body += filedata + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif data:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    else:
        body = None

    req = urllib.request.Request(url, data=body, headers=headers, method="POST" if body else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ctx) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if not result.get("ok"):
                logger.error("API error [%s]: %s", method, result.get("description", "Unknown"))
            return result
    except urllib.error.HTTPError as e:
        if e.code == 429:
            # Rate limited - parse retry_after
            try:
                error_body = json.loads(e.read().decode())
                retry_after = error_body.get("parameters", {}).get("retry_after", 5)
            except Exception:
                retry_after = 5
            _rate_limit_until = time.time() + retry_after
            logger.warning("HTTP 429 FloodWait on %s, waiting %ds", method, retry_after)
            time.sleep(retry_after)
            # Retry once
            return api_request(token, method, data, files, timeout)
        else:
            try:
                err_text = e.read().decode()
            except Exception:
                err_text = str(e)
            logger.error("HTTP %s calling %s: %s", e.code, method, err_text[:200])
            return None
    except Exception as e:
        logger.error("Request error calling %s: %s", method, e)
        return None


def get_updates(token, offset=0, timeout=30):
    """Long-poll for new updates."""
    data = {"timeout": timeout}
    if offset:
        data["offset"] = offset
    result = api_request(token, "getUpdates", data, timeout=timeout + 5)
    if result and result.get("ok"):
        return result.get("result", [])
    return []


def send_message(token, chat_id, text, reply_markup=None, parse_mode="HTML"):
    """Send a text message with optional inline keyboard."""
    # Telegram message text limit is 4096 chars
    if len(text) > 4096:
        text = text[:4090] + "\n..."
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }
    if reply_markup:
        data["reply_markup"] = reply_markup
    return api_request(token, "sendMessage", data)


def edit_message(token, chat_id, message_id, text, reply_markup=None, parse_mode="HTML"):
    """Edit an existing message (for inline keyboard navigation)."""
    if len(text) > 4096:
        text = text[:4090] + "\n..."
    data = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": parse_mode,
    }
    if reply_markup:
        data["reply_markup"] = reply_markup
    return api_request(token, "editMessageText", data)


def answer_callback(token, callback_query_id, text=None, show_alert=False):
    """Answer a callback query (acknowledge button press)."""
    data = {"callback_query_id": callback_query_id}
    if text:
        data["text"] = text[:200]  # Telegram limit
        data["show_alert"] = show_alert
    return api_request(token, "answerCallbackQuery", data)


def send_document(token, chat_id, filename, filedata, caption=None):
    """Send a file (for config backup)."""
    data = {"chat_id": str(chat_id)}
    if caption:
        data["caption"] = caption
    files = {"document": (filename, filedata, "application/octet-stream")}
    return api_request(token, "sendDocument", data, files=files)


def make_inline_keyboard(buttons):
    """
    Build an InlineKeyboardMarkup JSON structure.
    buttons: list of rows, each row is a list of (text, callback_data) tuples.
    Telegram limit: callback_data must be <= 64 bytes.
    """
    keyboard = []
    for row in buttons:
        keyboard.append([
            {"text": text, "callback_data": cb_data[:64]}
            for text, cb_data in row
        ])
    return json.dumps({"inline_keyboard": keyboard})


def make_webapp_keyboard(text, url):
    """Build an InlineKeyboardMarkup with a single WebApp button."""
    return json.dumps({
        "inline_keyboard": [[
            {"text": text, "web_app": {"url": url}}
        ]]
    })
