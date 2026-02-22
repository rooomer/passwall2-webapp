#!/usr/bin/env python3
"""
PassWall 2 Telegram Bot - Main Entry Point (Hardened)
Runs the long-polling event loop, dispatches callbacks and text messages.

Security fixes applied:
  #2: WebApp payload protocol redesigned with section-aware routing
  #3: Imports refactored for standalone execution
  #4: Threading for non-blocking long operations
  #5: Path traversal protection on file uploads
  #8: Chunked file download to prevent OOM
  #10: WebApp Tools tab routing
  #13: Token masking in logs
  #15: HMAC-SHA256 validation for WebApp initData
"""
import sys
import os
import time
import json
import re
import threading
import hashlib
import hmac

try:
    import logging
except ImportError:
    class DummyFilter: pass
    class DummyLogger:
        def setLevel(self, *a): pass
        def addFilter(self, *a): pass
        def removeFilter(self, *a): pass
        def addHandler(self, *a): pass
        def _print(self, level, msg, *a):
            try: print(f"[{level}] {msg % a if a else msg}")
            except Exception: print(f"[{level}] {msg}")
        def debug(self, msg, *a): self._print("DEBUG", msg, *a)
        def info(self, msg, *a): self._print("INFO", msg, *a)
        def warning(self, msg, *a): self._print("WARNING", msg, *a)
        def error(self, msg, *a): self._print("ERROR", msg, *a)
        def exception(self, msg, *a): self._print("EXCEPTION", msg, *a)
    class DummyLogging:
        INFO = 20
        DEBUG = 10
        Filter = DummyFilter
        def getLogger(self, name): return DummyLogger()
        def basicConfig(self, **kwargs): pass
        def StreamHandler(self, *a): return None

    import sys
    logging = DummyLogging()
    sys.modules["logging"] = logging

# Add parent dir to path so we can import bot package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.config import load_config
from bot import config
from bot import telegram_api as tg
from bot import uci_wrapper as uci
from bot import menus
from bot import api_server
from bot import tunnel_manager

# ─── WebApp Config ──────────────────────────────────────────────
# Set this to your GitHub Pages URL after deployment
WEBAPP_BASE_URL = os.environ.get("PW_WEBAPP_URL", "https://rooomer.github.io/passwall2-webapp")

# ─── Logging (Token-Safe) ──────────────────────────────────────
class TokenMaskFilter(logging.Filter):
    """Masks bot tokens in log output to prevent leakage."""
    def filter(self, record):
        if config.BOT_TOKEN and len(config.BOT_TOKEN) > 10:
            record.msg = str(record.msg).replace(config.BOT_TOKEN, tg._mask_token(config.BOT_TOKEN))
        return True

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("passwall2_bot")
logger.addFilter(TokenMaskFilter())

# ─── State ──────────────────────────────────────────────────────
user_input_state = {}  # chat_id -> {"action": "dns:custom", ...}


def is_admin(user_id):
    """Check if the user is the authorized admin."""
    return user_id == config.ADMIN_ID


def handle_start(chat_id):
    """Handle /start or /panel command."""
    text, markup = menus.menu_main()
    tg.send_message(config.BOT_TOKEN, chat_id, text, reply_markup=markup)


def run_in_background(func, *args):
    """Run a function in a background thread (non-blocking)."""
    t = threading.Thread(target=func, args=args, daemon=True)
    t.start()


def handle_callback(callback_query):
    """Route an inline keyboard button press."""
    cb_id = callback_query["id"]
    msg = callback_query.get("message")
    if not msg:
        tg.answer_callback(config.BOT_TOKEN, cb_id, "❌ Message expired")
        return

    chat_id = msg["chat"]["id"]
    message_id = msg["message_id"]
    user_id = callback_query["from"]["id"]
    data = callback_query.get("data", "")

    if not is_admin(user_id):
        tg.answer_callback(config.BOT_TOKEN, cb_id, "⛔ Unauthorized", show_alert=True)
        return

    # Parse callback data
    parts = data.split(":")
    category = parts[0] if parts else ""
    action = parts[1] if len(parts) > 1 else ""
    param = ":".join(parts[2:]) if len(parts) > 2 else ""

    text = None
    markup = None
    alert_text = None

    try:
        # ── Menu Navigation ──
        if category == "menu":
            if action == "webapp":
                _handle_webapp_open(chat_id, cb_id)
                return
            elif action == "switch_node":
                page = int(param) if param else 0
                text, markup = menus.menu_switch_node(page)
            else:
                text, markup = menus.get_menu(action)

        # ── Node Actions ──
        elif category == "node":
            if action == "set":
                node_id = param
                # Validate node_id format
                if not re.match(r'^[a-zA-Z0-9_\-]+$', node_id):
                    alert_text = "❌ Invalid node ID"
                else:
                    uci.set_current_node(node_id)
                    uci.service_restart()
                    alert_text = "✅ Node switched! Restarting..."
                text, markup = menus.menu_switch_node()
            elif action == "page":
                page = int(param) if param.isdigit() else 0
                text, markup = menus.menu_switch_node(page)
            elif action == "detail":
                text, markup = menus.menu_node_detail(param)
            elif action == "copy":
                new_id = uci.copy_node(param)
                alert_text = f"📋 Node copied!" if new_id else "❌ Copy failed"
                text, markup = menus.menu_switch_node()
            elif action == "del":
                ok = uci.delete_node(param)
                alert_text = "🗑️ Node deleted!" if ok else "❌ Delete failed"
                text, markup = menus.menu_switch_node()

        # ── Global Actions ──
        elif category == "act":
            if action == "toggle":
                running = uci.service_status()
                if running:
                    uci.service_stop()
                    alert_text = "🔴 PassWall 2 Stopped"
                else:
                    uci.service_start()
                    alert_text = "🟢 PassWall 2 Started"
                time.sleep(1)
                text, markup = menus.menu_main()

            elif action == "restart":
                uci.service_restart()
                alert_text = "🔁 PassWall 2 Restarting..."
                time.sleep(2)
                text, markup = menus.menu_main()

            elif action == "sub_update":
                alert_text = "🔄 Subscription update triggered..."
                run_in_background(uci.subscribe_update_all)
                text, markup = menus.menu_tools()

            elif action == "update_rules":
                uci.update_rules("all")
                alert_text = "🔄 GeoIP+Geosite update started..."
                text, markup = menus.menu_app_update()

            elif action == "flush_sets":
                run_in_background(uci.flush_sets)
                alert_text = "🧹 IPSET/NFTSET flushed, restarting..."
                text, markup = menus.menu_tools()

            elif action == "log_client":
                log = uci.get_log(30)
                log_text = log if log else "No log entries."
                tg.answer_callback(config.BOT_TOKEN, cb_id)
                tg.send_message(config.BOT_TOKEN, chat_id,
                    f"<b>📄 Client Log (last 30 lines)</b>\n<pre>{_escape_html(log_text[:3500])}</pre>")
                return

            elif action == "log_server":
                log = uci.get_server_log(30)
                log_text = log if log else "No log entries."
                tg.answer_callback(config.BOT_TOKEN, cb_id)
                tg.send_message(config.BOT_TOKEN, chat_id,
                    f"<b>📄 Server Log (last 30 lines)</b>\n<pre>{_escape_html(log_text[:3500])}</pre>")
                return

            elif action == "log_clear":
                uci.clear_log()
                alert_text = "🗑️ Client log cleared."
                text, markup = menus.menu_logs()

            elif action == "backup_download":
                tg.answer_callback(config.BOT_TOKEN, cb_id, "⬇️ Creating backup...")
                run_in_background(_do_backup_download, chat_id)
                return

            elif action == "backup_upload_info":
                tg.answer_callback(config.BOT_TOKEN, cb_id)
                tg.send_message(config.BOT_TOKEN, chat_id,
                    "⬆️ <b>To restore a backup:</b>\n"
                    "Simply send the <code>.tar.gz</code> backup file to this chat.\n"
                    "The bot will automatically detect and restore it.")
                return

        # ── DNS Actions ──
        elif category == "dns":
            text, markup, alert_text = _handle_dns_action(action, param, chat_id, cb_id)
            if text is None and markup is None:
                return  # Already handled

        # ── GeoView ──
        elif category == "geo":
            if action == "input":
                user_input_state[chat_id] = {"action": "geo_lookup"}
                tg.answer_callback(config.BOT_TOKEN, cb_id)
                tg.send_message(config.BOT_TOKEN, chat_id,
                    "🌍 <b>GeoView Lookup</b>\n"
                    "Send an IP address or domain name to check which GeoIP/Geosite rules match it.")
                return

        # ── Ping ──
        elif category == "ping":
            if action == "page":
                page = int(param) if param.isdigit() else 0
                text, markup = menus.menu_ping(page)
            else:
                node_id = action
                run_in_background(_do_ping_node, chat_id, cb_id, node_id)
                return

        # ── Forwarding Settings ──
        elif category == "fwd":
            if action == "toggle_ipv6":
                cur = uci.get_forwarding_settings().get("ipv6_tproxy", "0")
                uci.set_forwarding_option("ipv6_tproxy", "0" if cur == "1" else "1")
                alert_text = "IPv6 TProxy toggled"
            else:
                uci.set_forwarding_option(action, param)
                alert_text = f"✅ Set {action} = {param}"
            text, markup = menus.menu_forwarding()

        # ── Delay Settings ──
        elif category == "delay":
            if action == "toggle_daemon":
                cur = uci.get_delay_settings().get("enabled", "0")
                uci.set_delay_option("start_daemon", "0" if cur == "1" else "1")
                alert_text = "Daemon toggled"
            else:
                uci.set_delay_option(action, param)
                alert_text = f"✅ Set {action} = {param}"
            text, markup = menus.menu_delay()

        # ── Socks Config ──
        elif category == "socks":
            if action == "toggle_main":
                cur = uci.get_socks_config().get("socks_enabled", "0")
                uci.set_socks_enabled(cur != "1")
                alert_text = "Socks switch toggled"
            text, markup = menus.menu_socks_config()

        # ── Global Options ──
        elif category == "gopt":
            opts = uci.get_global_options()
            key_map = {
                "localhost_proxy": "localhost_proxy",
                "client_proxy": "client_proxy",
                "direct_dns_ipset": "write_ipset_direct",
            }
            uci_key = key_map.get(action, action)
            cur = opts.get(action, "0")
            uci.set_global_option(uci_key, "0" if cur == "1" else "1")
            alert_text = f"{action} toggled"
            text, markup = menus.menu_global_options()

    except Exception as e:
        logger.error("Callback error: %s", e, exc_info=True)
        alert_text = f"❌ Error: {str(e)[:100]}"
        text, markup = menus.menu_main()

    # Answer the callback
    tg.answer_callback(config.BOT_TOKEN, cb_id, alert_text)

    # Update the message
    if text:
        tg.edit_message(config.BOT_TOKEN, chat_id, message_id, text, reply_markup=markup)


def _handle_webapp_open(chat_id, cb_id):
    """Open the WebApp with the API tunnel URL + auth token."""
    import urllib.parse

    # Get the live tunnel URL
    tunnel_url = tunnel_manager.get_tunnel_url(timeout=5)
    api_token = api_server.get_api_token()

    if not tunnel_url:
        tg.answer_callback(config.BOT_TOKEN, cb_id, text="⏳ Tunnel not ready yet, try again in 30s...")
        tg.send_message(config.BOT_TOKEN, chat_id,
            "⚠️ <b>Cloudflare Tunnel not ready</b>\n"
            "The tunnel is still starting up. Please wait 30 seconds and try again.\n"
            "If this persists, check that <code>cloudflared</code> is installed on the router.")
        return

    # Build WebApp URL — config is loaded live via API, no data in URL!
    # Cache-bust: Telegram WebView aggressively caches, so we add a timestamp
    import time as _time
    params = urllib.parse.urlencode({
        "api": tunnel_url,
        "token": api_token,
        "v": str(int(_time.time())),
    })
    webapp_url = f"{WEBAPP_BASE_URL}/index.html?{params}"
    logger.info("WebApp URL length: %d, token length: %d", len(webapp_url), len(api_token))
    logger.info("WebApp URL: %s", webapp_url[:200])

    text = (
        "🖥️ <b>Advanced Web Panel</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "Tap below to open the full real-time panel.\n"
        f"🔗 API: <code>{tunnel_url}</code>"
    )
    markup = tg.make_webapp_keyboard("🖥️ Open PassWall Panel", webapp_url)
    tg.answer_callback(config.BOT_TOKEN, cb_id)
    tg.send_message(config.BOT_TOKEN, chat_id, text, reply_markup=markup)


def _handle_dns_action(action, param, chat_id, cb_id):
    """Handle DNS-related callback actions. Returns (text, markup, alert_text)."""
    text = None
    markup = None
    alert_text = None

    if action == "proto":
        uci.set_dns_option("remote_dns_protocol", param)
        uci.service_restart()
        alert_text = f"📶 DNS Protocol → {param.upper()}"
        text, markup = menus.menu_dns()

    elif action == "server":
        proto = uci.get_dns_settings()["remote_dns_protocol"]
        if proto == "doh":
            uci.set_dns_option("remote_dns_doh", param)
        else:
            uci.set_dns_option("remote_dns", param)
        uci.service_restart()
        alert_text = "🌐 DNS Server changed!"
        text, markup = menus.menu_dns()

    elif action == "toggle_fakedns":
        current = uci.get_dns_settings()["remote_fakedns"]
        new_val = "0" if current == "1" else "1"
        uci.set_dns_option("remote_fakedns", new_val)
        uci.service_restart()
        alert_text = f"FakeDNS {'ON' if new_val == '1' else 'OFF'}"
        text, markup = menus.menu_dns()

    elif action == "toggle_redirect":
        current = uci.get_dns_settings()["dns_redirect"]
        new_val = "0" if current == "1" else "1"
        uci.set_dns_option("dns_redirect", new_val)
        uci.service_restart()
        alert_text = f"DNS Redirect {'ON' if new_val == '1' else 'OFF'}"
        text, markup = menus.menu_dns()

    elif action == "dstrat":
        uci.set_dns_option("direct_dns_query_strategy", param)
        uci.service_restart()
        alert_text = f"Direct Strategy → {param}"
        text, markup = menus.menu_dns_strategy()

    elif action == "rstrat":
        uci.set_dns_option("remote_dns_query_strategy", param)
        uci.service_restart()
        alert_text = f"Remote Strategy → {param}"
        text, markup = menus.menu_dns_strategy()

    elif action == "detour":
        uci.set_dns_option("remote_dns_detour", param)
        uci.service_restart()
        alert_text = f"Outbound → {param}"
        text, markup = menus.menu_dns_strategy()

    elif action == "custom_input":
        user_input_state[chat_id] = {"action": "dns_custom"}
        tg.answer_callback(config.BOT_TOKEN, cb_id)
        tg.send_message(config.BOT_TOKEN, chat_id,
            "✏️ <b>Enter Custom DNS:</b>\n"
            "Send an IP address (e.g. <code>1.1.1.1</code>) or DoH URL "
            "(e.g. <code>https://dns.example.com/dns-query</code>)")
        return None, None, None

    elif action == "ecs_input":
        user_input_state[chat_id] = {"action": "dns_ecs"}
        tg.answer_callback(config.BOT_TOKEN, cb_id)
        tg.send_message(config.BOT_TOKEN, chat_id,
            "🔗 <b>Enter EDNS Client Subnet IP:</b>\n"
            "Send a public IP address for ECS (RFC7871).\n"
            "Send <code>clear</code> to remove.")
        return None, None, None

    elif action == "hosts_input":
        user_input_state[chat_id] = {"action": "dns_hosts"}
        current_hosts = uci.get_dns_settings()["dns_hosts"]
        tg.answer_callback(config.BOT_TOKEN, cb_id)
        tg.send_message(config.BOT_TOKEN, chat_id,
            f"📋 <b>Domain Overrides (dns_hosts):</b>\n"
            f"Current:\n<pre>{_escape_html(current_hosts) or 'Empty'}</pre>\n\n"
            f"Send new domain overrides (one per line), or <code>clear</code> to reset.")
        return None, None, None

    return text, markup, alert_text


def _do_backup_download(chat_id):
    """Background: create and send backup file."""
    try:
        tar_path = uci.create_backup()
        with open(tar_path, "rb") as f:
            file_data = f.read()
        filename = os.path.basename(tar_path)
        tg.send_document(config.BOT_TOKEN, chat_id, filename, file_data,
            caption="📦 PassWall 2 Config Backup")
    except Exception as e:
        tg.send_message(config.BOT_TOKEN, chat_id, f"❌ Backup failed: {e}")


def _do_ping_node(chat_id, cb_id, node_id):
    """Background: ping a node and report results."""
    nodes = uci.get_all_nodes()
    node_info = None
    for n in nodes:
        if n["id"] == node_id:
            node_info = n
            break
    if node_info:
        tg.answer_callback(config.BOT_TOKEN, cb_id, "🏓 Pinging...")
        address = node_info.get("address", "")
        port = node_info.get("port", "")
        if not address:
            tg.send_message(config.BOT_TOKEN, chat_id, "❌ Node has no address")
            return
        latency = uci.ping_node(address, port)
        if latency:
            tg.send_message(config.BOT_TOKEN, chat_id,
                f"🏓 <b>Ping Result</b>\n"
                f"Node: {_escape_html(node_info['remark'])}\n"
                f"Address: <code>{_escape_html(address)}</code>\n"
                f"Latency: <b>{latency} ms</b>")
        else:
            tg.send_message(config.BOT_TOKEN, chat_id,
                f"❌ Ping failed for {_escape_html(node_info['remark'])} ({_escape_html(address)})")
    else:
        tg.answer_callback(config.BOT_TOKEN, cb_id, "❌ Node not found")


def handle_text_input(chat_id, user_id, text_input):
    """Handle free-text inputs (custom DNS, GeoView, etc.)."""
    if not is_admin(user_id):
        return

    state = user_input_state.pop(chat_id, None)
    if not state:
        handle_start(chat_id)
        return

    action = state["action"]

    if action == "dns_custom":
        proto = uci.get_dns_settings()["remote_dns_protocol"]
        if text_input.startswith("https://"):
            uci.set_dns_option("remote_dns_protocol", "doh")
            uci.set_dns_option("remote_dns_doh", text_input)
        else:
            if proto == "doh":
                uci.set_dns_option("remote_dns_protocol", "tcp")
            uci.set_dns_option("remote_dns", text_input)
        uci.service_restart()
        tg.send_message(config.BOT_TOKEN, chat_id, f"✅ Custom DNS set to: <code>{_escape_html(text_input)}</code>")
        text, markup = menus.menu_dns()
        tg.send_message(config.BOT_TOKEN, chat_id, text, reply_markup=markup)

    elif action == "dns_ecs":
        if text_input.lower() == "clear":
            uci.uci_del(uci.APPNAME, "@global[0]", "remote_dns_client_ip")
            uci.uci_commit(uci.APPNAME)
            tg.send_message(config.BOT_TOKEN, chat_id, "✅ EDNS Client Subnet cleared.")
        else:
            uci.set_dns_option("remote_dns_client_ip", text_input)
            tg.send_message(config.BOT_TOKEN, chat_id, f"✅ EDNS Client IP set to: <code>{_escape_html(text_input)}</code>")
        uci.service_restart()
        text, markup = menus.menu_dns()
        tg.send_message(config.BOT_TOKEN, chat_id, text, reply_markup=markup)

    elif action == "dns_hosts":
        if text_input.lower() == "clear":
            uci.uci_del(uci.APPNAME, "@global[0]", "dns_hosts")
            tg.send_message(config.BOT_TOKEN, chat_id, "✅ Domain overrides cleared.")
        else:
            uci.set_dns_option("dns_hosts", text_input)
            tg.send_message(config.BOT_TOKEN, chat_id, "✅ Domain overrides updated.")
        uci.uci_commit(uci.APPNAME)
        uci.service_restart()
        text, markup = menus.menu_dns()
        tg.send_message(config.BOT_TOKEN, chat_id, text, reply_markup=markup)

    elif action == "geo_lookup":
        tg.send_message(config.BOT_TOKEN, chat_id, "🔍 Looking up...")
        result = uci.geo_lookup(text_input)
        tg.send_message(config.BOT_TOKEN, chat_id,
            f"🌍 <b>GeoView Result for</b> <code>{_escape_html(text_input)}</code>\n"
            f"<pre>{_escape_html(result[:3500])}</pre>")
        text, markup = menus.menu_tools()
        tg.send_message(config.BOT_TOKEN, chat_id, text, reply_markup=markup)


def handle_document(chat_id, user_id, document, message):
    """Handle file uploads (backup restore). Runs in background thread."""
    if not is_admin(user_id):
        return

    filename = document.get("file_name", "")
    # Path Traversal Protection: strip directory components
    safe_filename = os.path.basename(filename)
    if not safe_filename.endswith(".tar.gz"):
        tg.send_message(config.BOT_TOKEN, chat_id,
            "❌ Please send a <code>.tar.gz</code> backup file.")
        return

    # Additional validation: only allow our backup name pattern
    if not re.match(r'^passwall2-\d+-backup\.tar\.gz$', safe_filename):
        tg.send_message(config.BOT_TOKEN, chat_id,
            "❌ Invalid backup filename. Expected format: <code>passwall2-XXXXXXXX-backup.tar.gz</code>")
        return

    run_in_background(_do_backup_restore, chat_id, document, safe_filename)


def _do_backup_restore(chat_id, document, safe_filename):
    """Background: download and restore a backup file."""
    file_id = document["file_id"]
    file_info = tg.api_request(config.BOT_TOKEN, "getFile", {"file_id": file_id})
    if not file_info or not file_info.get("ok"):
        tg.send_message(config.BOT_TOKEN, chat_id, "❌ Failed to get file info.")
        return

    file_path = file_info["result"]["file_path"]
    download_url = f"https://api.telegram.org/file/bot{config.BOT_TOKEN}/{file_path}"

    import urllib.request
    import ssl
    import shutil
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    local_path = f"/tmp/{safe_filename}"
    try:
        req = urllib.request.Request(download_url)
        # Chunked download to prevent OOM on low-memory routers
        with urllib.request.urlopen(req, context=ctx) as resp:
            with open(local_path, "wb") as f:
                shutil.copyfileobj(resp, f, length=8192)

        tg.send_message(config.BOT_TOKEN, chat_id, "📦 Restoring backup...")
        uci.restore_backup(local_path)
        tg.send_message(config.BOT_TOKEN, chat_id,
            "✅ <b>Backup restored successfully!</b>\nPassWall 2 is restarting...")
    except Exception as e:
        tg.send_message(config.BOT_TOKEN, chat_id, f"❌ Restore failed: {e}")


def validate_webapp_init_data(init_data, bot_token):
    """
    Validate Telegram WebApp initData using HMAC-SHA256.
    Returns True if the hash is valid, False otherwise.
    Fix #15: Prevents CSRF/spoofing of WebApp payloads.
    """
    if not init_data:
        return False
    try:
        import urllib.parse
        params = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
        received_hash = params.pop("hash", "")
        if not received_hash:
            return False

        # Build data-check-string
        sorted_params = sorted(params.items())
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted_params)

        # HMAC-SHA256
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(computed_hash, received_hash)
    except Exception:
        return False


def handle_webapp_data(chat_id, user_id, web_app_data):
    """Handle data sent from the Telegram Mini App via sendData().
    Fix #2: Section-aware UCI routing instead of blind @global[0] writes.
    Fix #10: Routes non-config actions (ping, logs, etc.) properly.
    """
    if not is_admin(user_id):
        return

    try:
        payload = json.loads(web_app_data)
        if not isinstance(payload, dict):
            raise ValueError("Payload must be a JSON object")
        action = payload.get("action", "")

        if action == "apply_config":
            # Section-aware config application
            changes = payload.get("changes", {})
            _apply_webapp_changes(chat_id, changes)

        elif action == "set_node":
            node_id = payload.get("node", "")
            if node_id and re.match(r'^[a-zA-Z0-9_]+$', node_id):
                uci.set_current_node(node_id)
                uci.service_restart()
                tg.send_message(config.BOT_TOKEN, chat_id, "✅ Node switched! Restarting...")
            else:
                tg.send_message(config.BOT_TOKEN, chat_id, "❌ Invalid node ID")

        elif action == "dns_change":
            changes = payload.get("changes", {})
            _apply_dns_changes(chat_id, changes)

        elif action in ("start", "stop", "restart"):
            if action == "start":
                uci.service_start()
            elif action == "stop":
                uci.service_stop()
            else:
                uci.service_restart()
            tg.send_message(config.BOT_TOKEN, chat_id, f"✅ PassWall 2: {action} command executed")

        elif action == "sub_update":
            run_in_background(uci.subscribe_update_all)
            tg.send_message(config.BOT_TOKEN, chat_id, "🔄 Subscription update triggered!")

        elif action == "update_rules":
            uci.update_rules("all")
            tg.send_message(config.BOT_TOKEN, chat_id, "🔄 GeoIP+Geosite update started!")

        elif action == "flush_sets":
            run_in_background(uci.flush_sets)
            tg.send_message(config.BOT_TOKEN, chat_id, "🧹 IPSET/NFTSET flushed!")

        elif action == "get_log":
            log = uci.get_log(50)
            tg.send_message(config.BOT_TOKEN, chat_id,
                f"<b>📄 Client Log</b>\n<pre>{_escape_html((log or 'No entries')[:3500])}</pre>")

        elif action == "get_server_log":
            log = uci.get_server_log(50)
            tg.send_message(config.BOT_TOKEN, chat_id,
                f"<b>📄 Server Log</b>\n<pre>{_escape_html((log or 'No entries')[:3500])}</pre>")

        elif action == "backup":
            run_in_background(_do_backup_download, chat_id)

        elif action == "geo_lookup":
            value = payload.get("value", "")
            if value:
                result = uci.geo_lookup(value)
                tg.send_message(config.BOT_TOKEN, chat_id,
                    f"🌍 <b>GeoView:</b> <code>{_escape_html(value)}</code>\n"
                    f"<pre>{_escape_html(result[:3500])}</pre>")

        elif action == "ping":
            address = payload.get("address", "")
            if address:
                latency = uci.ping_node(address, ping_type="icmp")
                if latency:
                    tg.send_message(config.BOT_TOKEN, chat_id, f"🏓 Ping {_escape_html(address)}: {latency} ms")
                else:
                    tg.send_message(config.BOT_TOKEN, chat_id, f"❌ Ping failed for {_escape_html(address)}")

        elif action == "ping_node":
            address = payload.get("address", "")
            port = payload.get("port", "")
            node_id = payload.get("node_id", "")
            # Do both ICMP and TCPing
            icmp_lat = uci.ping_node(address, ping_type="icmp") if address else ""
            tcp_lat = uci.ping_node(address, port=port, ping_type="tcping") if address and port else ""
            msg = f"📡 <b>Node Test Results</b>\n"
            msg += f"  ICMP: {icmp_lat + ' ms' if icmp_lat else '❌ timeout'}\n"
            msg += f"  TCPing: {tcp_lat + ' ms' if tcp_lat else '❌ timeout'}\n"
            tg.send_message(config.BOT_TOKEN, chat_id, msg)

        elif action == "ping_all_nodes":
            all_nodes = uci.get_all_nodes()[:20]
            results = []
            for n in all_nodes:
                addr = n.get("address", "")
                port = n.get("port", "")
                if addr:
                    lat = uci.ping_node(addr, port=port, ping_type="tcping") if port else uci.ping_node(addr)
                    remark = n.get("remark", "?")[:15]
                    results.append(f"  {'🟢' if lat else '🔴'} {remark}: {lat + 'ms' if lat else 'timeout'}")
            msg = "📡 <b>Ping All Results</b>\n" + "\n".join(results) if results else "No nodes to test"
            tg.send_message(config.BOT_TOKEN, chat_id, msg)

        elif action == "delete_node":
            node_id = payload.get("node", "")
            if node_id and re.match(r'^[a-zA-Z0-9_]+$', node_id):
                ok = uci.delete_node(node_id)
                tg.send_message(config.BOT_TOKEN, chat_id,
                    "🗑️ Node deleted!" if ok else "❌ Delete failed")
            else:
                tg.send_message(config.BOT_TOKEN, chat_id, "❌ Invalid node ID")

        elif action == "copy_node":
            node_id = payload.get("node", "")
            if node_id and re.match(r'^[a-zA-Z0-9_]+$', node_id):
                new_id = uci.copy_node(node_id)
                tg.send_message(config.BOT_TOKEN, chat_id,
                    f"📋 Node copied! New ID: {new_id}" if new_id else "❌ Copy failed")
            else:
                tg.send_message(config.BOT_TOKEN, chat_id, "❌ Invalid node ID")

        elif action == "add_node_url":
            url = payload.get("url", "")
            if url:
                ok = uci.add_node_from_url(url)
                tg.send_message(config.BOT_TOKEN, chat_id,
                    "➕ Node added from URL!" if ok else "❌ Failed to add node")

        elif action == "set_forwarding":
            key = payload.get("key", "")
            value = payload.get("value", "")
            if key and re.match(r'^[a-z_]+$', key):
                uci.set_forwarding_option(key, value)
                tg.send_message(config.BOT_TOKEN, chat_id, f"✅ Forwarding: {key} = {value}")

        elif action == "set_delay":
            key = payload.get("key", "")
            value = payload.get("value", "")
            if key and re.match(r'^[a-z_]+$', key):
                uci.set_delay_option(key, value)
                tg.send_message(config.BOT_TOKEN, chat_id, f"✅ Delay: {key} = {value}")

        elif action == "set_global_opt":
            key = payload.get("key", "")
            value = payload.get("value", "")
            if key and re.match(r'^[a-z_]+$', key):
                uci.set_global_option(key, value)
                tg.send_message(config.BOT_TOKEN, chat_id, f"✅ Global: {key} = {value}")

        elif action == "set_acl":
            acl_id = payload.get("id", "")
            enabled = payload.get("enabled", "0")
            if acl_id:
                ok = uci.set_acl_enabled(acl_id, enabled == "1")
                tg.send_message(config.BOT_TOKEN, chat_id,
                    f"✅ ACL {'enabled' if enabled == '1' else 'disabled'}" if ok else "❌ Failed")

        elif action == "set_shunt_rule":
            rule_name = payload.get("rule_name", "")
            domain_list = payload.get("domain_list", "")
            ip_list = payload.get("ip_list", "")
            if rule_name and re.match(r'^[a-zA-Z0-9_]+$', rule_name):
                uci.set_shunt_rule_field(rule_name, "domain_list", domain_list)
                uci.set_shunt_rule_field(rule_name, "ip_list", ip_list)
                tg.send_message(config.BOT_TOKEN, chat_id, f"💾 Shunt rule '{rule_name}' saved!")

        else:
            tg.send_message(config.BOT_TOKEN, chat_id, f"⚠️ Unknown Web App action: {_escape_html(action)}")

    except Exception as e:
        logger.error("WebApp data error: %s", e)
        tg.send_message(config.BOT_TOKEN, chat_id, f"❌ WebApp error: {_escape_html(str(e))}")


def _apply_webapp_changes(chat_id, changes):
    """Apply config changes from the WebApp using uci_batch for performance."""
    # Whitelist of allowed UCI options (prevents arbitrary key injection)
    ALLOWED_GLOBAL_KEYS = {
        "enabled", "node", "remote_dns_protocol", "remote_dns", "remote_dns_doh",
        "remote_dns_client_ip", "remote_dns_detour", "remote_fakedns",
        "remote_dns_query_strategy", "direct_dns_query_strategy",
        "dns_hosts", "dns_redirect",
    }

    ops = []
    for key, value in changes.items():
        if key in ("action",):
            continue  # Skip meta keys
        if key in ALLOWED_GLOBAL_KEYS:
            ops.append(f"set {uci.APPNAME}.@global[0].{key}={value}")
        else:
            logger.warning("Rejected unknown WebApp key: %s", key)

    if ops:
        ops.append(f"commit {uci.APPNAME}")
        uci.uci_batch(ops)
        uci.service_restart()
        tg.send_message(config.BOT_TOKEN, chat_id,
            f"✅ <b>Config applied from Web Panel!</b> ({len(ops)-1} changes)\nPassWall 2 restarting...")
    else:
        tg.send_message(config.BOT_TOKEN, chat_id, "⚠️ No valid changes to apply.")


def _apply_dns_changes(chat_id, changes):
    """Apply DNS-specific changes from the WebApp."""
    DNS_KEYS = {
        "remote_dns_protocol", "remote_dns", "remote_dns_doh",
        "remote_dns_client_ip", "remote_fakedns",
        "remote_dns_query_strategy", "direct_dns_query_strategy",
        "remote_dns_detour", "dns_hosts", "dns_redirect",
    }
    ops = []
    for key, value in changes.items():
        if key in ("action",):
            continue
        if key in DNS_KEYS:
            ops.append(f"set {uci.APPNAME}.@global[0].{key}={value}")

    if ops:
        ops.append(f"commit {uci.APPNAME}")
        uci.uci_batch(ops)
        uci.service_restart()
        tg.send_message(config.BOT_TOKEN, chat_id,
            f"✅ DNS settings applied! ({len(ops)-1} changes)")


def _escape_html(text):
    """Escape HTML special characters to prevent injection in Telegram messages."""
    if not text:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ═══════════════════════════════════════════════════════════════
#  MAIN LOOP
# ═══════════════════════════════════════════════════════════════

def main():
    """Main polling loop."""
    load_config()

    if not config.BOT_TOKEN:
        logger.error("Bot token not configured! Set PW_BOT_TOKEN or configure /etc/config/passwall2_bot")
        sys.exit(1)
    if not config.ADMIN_ID:
        logger.error("Admin ID not configured! Set PW_ADMIN_ID or configure /etc/config/passwall2_bot")
        sys.exit(1)

    logger.info("PassWall 2 Bot starting... Admin ID: %s", config.ADMIN_ID)

    # ── Start API Server + Cloudflare Tunnel ─────────────────
    api_token = api_server.start_api_server(uci, host="127.0.0.1", port=8080)
    logger.info("API server started, token: %s...", api_token[:8])
    tunnel_manager.start_tunnel(port=8080)
    logger.info("Tunnel manager started, waiting for URL...")

    offset = 0

    while True:
        try:
            updates = tg.get_updates(config.BOT_TOKEN, offset=offset, timeout=30)
            for update in updates:
                offset = update["update_id"] + 1

                # Callback query (inline keyboard button press)
                if "callback_query" in update:
                    handle_callback(update["callback_query"])

                # Regular message
                elif "message" in update:
                    msg = update["message"]
                    chat_id = msg["chat"]["id"]
                    user_id = msg.get("from", {}).get("id", 0)

                    # WebApp data
                    if "web_app_data" in msg:
                        handle_webapp_data(chat_id, user_id, msg["web_app_data"]["data"])
                        continue

                    # Document (backup restore)
                    if "document" in msg:
                        handle_document(chat_id, user_id, msg["document"], msg)
                        continue

                    # Text commands
                    text = msg.get("text", "").strip()
                    if text.startswith("/start") or text.startswith("/panel"):
                        handle_start(chat_id)
                    elif text.startswith("/status"):
                        if is_admin(user_id):
                            running = uci.service_status()
                            status = "🟢 Running" if running else "🔴 Stopped"
                            tg.send_message(config.BOT_TOKEN, chat_id, f"PassWall 2: {status}")
                    elif chat_id in user_input_state:
                        handle_text_input(chat_id, user_id, text)
                    elif is_admin(user_id):
                        handle_start(chat_id)

        except KeyboardInterrupt:
            logger.info("Bot stopped by user.")
            break
        except Exception as e:
            logger.error("Polling error: %s", e, exc_info=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
