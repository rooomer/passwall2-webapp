"""
PassWall 2 — Lightweight REST API Server
=========================================
Pure Python HTTP server (no Flask/FastAPI dependencies) that runs on
the OpenWrt router alongside the Telegram bot.  It is fronted by a
Cloudflare Quick Tunnel so the Telegram Mini App (hosted on GitHub
Pages) can `fetch()` it over HTTPS.

Endpoints
─────────
GET  /api/config            → full UCI config JSON
POST /api/config            → batch UCI edits
POST /api/action/<name>     → service actions (ping, restart, …)

Security
────────
• Bound to 127.0.0.1 only (exposed solely via cloudflared).
• Every request must carry `Authorization: Bearer <TOKEN>`.
• Token is generated once per bot start and passed to the webapp URL.
"""

import json
import logging
import re
import secrets
import socketserver
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# ── Lazy imports (set by start_api_server) ──────────────────────
uci = None          # uci_wrapper module
_API_TOKEN = ""     # set at startup

logger = logging.getLogger("api_server")

# ═══════════════════════════════════════════════════════════════
#  CORS & AUTH HELPERS
# ═══════════════════════════════════════════════════════════════

def _cors_headers(origin=""):
    """Return CORS headers. Allow any origin since access is protected by Bearer token."""
    # The API is already secured by Bearer token auth, so we allow any origin.
    # This is necessary because Telegram WebView sends varying origins.
    return {
        "Access-Control-Allow-Origin": origin if origin else "*",
        "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization, Accept, Origin",
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Max-Age": "86400",
    }


def _check_auth(handler):
    """Return True if the Bearer token matches."""
    auth = handler.headers.get("Authorization", "").strip()
    expected = f"Bearer {_API_TOKEN}"
    if auth != expected:
        logger.warning("AUTH FAIL: got=%r  expect=%r", auth[:30], expected[:30])
    return auth == expected


# ═══════════════════════════════════════════════════════════════
#  REQUEST HANDLER
# ═══════════════════════════════════════════════════════════════

class APIHandler(BaseHTTPRequestHandler):
    """Minimal JSON REST API handler."""

    # Use HTTP/1.1 for persistent connections
    protocol_version = "HTTP/1.1"

    # Silence default stderr logging
    def log_message(self, format, *args):
        logger.debug(format, *args)

    # ── OPTIONS (CORS preflight) ────────────────────────────────
    def do_OPTIONS(self):
        """Handle CORS preflight requests - NO body, NO auth required."""
        origin = self.headers.get("Origin", "*")
        self.send_response(200)
        for k, v in _cors_headers(origin).items():
            self.send_header(k, v)
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ── GET ──────────────────────────────────────────────────────
    def do_GET(self):
        origin = self.headers.get("Origin", "*")
        path = urlparse(self.path).path.rstrip("/")

        # Health check — no auth required (used by tunnel probe)
        if path == "/api/ping":
            return self._send_json({"ok": True}, 200, origin)

        if not _check_auth(self):
            return self._send_json({"error": "unauthorized"}, 401, origin)

        if path == "/api/config":
            return self._handle_get_config(origin)
        elif path == "/api/status":
            return self._handle_get_status(origin)
        else:
            return self._send_json({"error": "not found"}, 404, origin)

    # ── POST ─────────────────────────────────────────────────────
    def do_POST(self):
        origin = self.headers.get("Origin", "*")
        if not _check_auth(self):
            return self._send_json({"error": "unauthorized"}, 401, origin)

        path = urlparse(self.path).path.rstrip("/")
        body = self._read_body()

        if path == "/api/config":
            return self._handle_post_config(body, origin)
        elif path.startswith("/api/action/"):
            action_name = path.split("/api/action/", 1)[1]
            return self._handle_action(action_name, body, origin)
        else:
            return self._send_json({"error": "not found"}, 404, origin)

    # ═══════════════════════════════════════════════════════════
    #  ROUTE HANDLERS
    # ═══════════════════════════════════════════════════════════

    def _handle_get_config(self, origin):
        """Return the full PassWall configuration."""
        try:
            dns = uci.get_dns_settings()
            all_nodes = uci.get_all_nodes()
            acl_rules = uci.get_acl_rules()
            shunt_rules = uci.get_shunt_rules()
            socks_list = uci.get_socks_list() if hasattr(uci, 'get_socks_list') else []
            haproxy_list = uci.get_haproxy_list() if hasattr(uci, 'get_haproxy_list') else []
            subscribe_list = uci.get_subscribe_list() if hasattr(uci, 'get_subscribe_list') else []
            server_list = uci.get_server_users() if hasattr(uci, 'get_server_users') else []

            # Build shunt node routing info: _shunt protocol nodes show which
            # rule maps to which destination node
            shunt_rule_names = [s.get(".name", "") for s in shunt_rules]
            shunt_nodes_info = []
            for n in all_nodes:
                if n.get("protocol") == "_shunt":
                    destinations = {}
                    for rname in shunt_rule_names:
                        if rname and rname in n:
                            dest = n[rname]
                            if isinstance(dest, list):
                                dest = dest[0] if dest else ""
                            dest = str(dest)
                            # Resolve dest node name
                            if dest.startswith("_"):
                                destinations[rname] = dest
                            else:
                                dn = next((nd for nd in all_nodes if nd.get("id") == dest), None)
                                destinations[rname] = dn.get("remark", dest) if dn else dest
                    # Also include default_node and other special fields
                    default_dest = str(n.get("default_node", ""))
                    if default_dest and not default_dest.startswith("_"):
                        dn = next((nd for nd in all_nodes if nd.get("id") == default_dest), None)
                        default_dest = dn.get("remark", default_dest) if dn else default_dest
                    shunt_nodes_info.append({
                        "id": n.get("id", ""),
                        "remarks": n.get("remark", ""),
                        "type": n.get("type", ""),
                        "default_node": default_dest,
                        "domainStrategy": n.get("domainStrategy", ""),
                        "destinations": destinations,
                    })

            config = {
                "running": uci.service_status(),
                "active_node": uci.get_current_node(),
                "nodes": all_nodes,
                "dns": dns,
                "acl": [{
                    ".name": a.get(".name", ""),
                    "remarks": a.get("remarks", a.get(".name", "?")),
                    "enabled": a.get("enabled", "0"),
                    "sources": a.get("sources", "all"),
                } for a in acl_rules],
                "shunt_rules": [dict(s) for s in shunt_rules],  # ALL fields
                "shunt_nodes": shunt_nodes_info,
                "socks": socks_list,
                "haproxy": haproxy_list,
                "subscriptions": subscribe_list,
                "servers": server_list,
            }
            self._send_json(config, 200, origin)
        except Exception as e:
            logger.error("get_config error: %s", e)
            self._send_json({"error": str(e)}, 500, origin)

    def _handle_get_status(self, origin):
        """Quick status check."""
        self._send_json({
            "running": uci.service_status(),
            "active_node": uci.get_current_node(),
        }, 200, origin)

    def _handle_post_config(self, body, origin):
        """Apply batch UCI changes."""
        try:
            changes = body.get("changes", {})
            if not isinstance(changes, dict):
                return self._send_json({"error": "changes must be dict"}, 400, origin)

            ALLOWED_KEYS = {
                "enabled", "node", "remote_dns_protocol", "remote_dns",
                "remote_dns_doh", "remote_dns_client_ip", "remote_dns_detour",
                "remote_fakedns", "remote_dns_query_strategy",
                "direct_dns_query_strategy", "dns_hosts", "dns_redirect",
            }
            ops = []
            for key, value in changes.items():
                if key in ALLOWED_KEYS and re.match(r'^[\w./:-]+$', str(value)):
                    ops.append(f"set passwall2.@global[0].{key}={value}")
            if ops:
                ops.append("commit passwall2")
                uci.uci_batch(ops)
            self._send_json({"ok": True, "applied": len(ops) - 1}, 200, origin)
        except Exception as e:
            logger.error("post_config error: %s", e)
            self._send_json({"error": str(e)}, 500, origin)

    def _handle_action(self, action, body, origin):
        """Route action requests."""
        try:
            result = _dispatch_action(action, body)
            self._send_json(result, 200, origin)
        except Exception as e:
            logger.error("action '%s' error: %s", action, e)
            self._send_json({"ok": False, "msg": str(e), "error": str(e)}, 500, origin)

    # ═══════════════════════════════════════════════════════════
    #  UTILITY
    # ═══════════════════════════════════════════════════════════

    def _read_body(self):
        """Read and parse JSON request body."""
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        # Safety: reject oversized requests (2MB max)
        if length > 2 * 1024 * 1024:
            self.rfile.read(min(length, 4096))  # drain a bit to keep connection clean
            return {}
        raw = self.rfile.read(length)
        try:
            result = json.loads(raw)
            del raw  # free raw bytes immediately
            return result
        except json.JSONDecodeError:
            return {}

    def _send_json(self, data, status=200, origin=""):
        """Send a JSON response with CORS headers and proper Content-Length."""
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        for k, v in _cors_headers(origin).items():
            self.send_header(k, v)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ═══════════════════════════════════════════════════════════════
#  ACTION DISPATCHER
# ═══════════════════════════════════════════════════════════════

def _get_dns_scanner():
    """Lazy import dns_scanner with helpful error if asyncio is missing."""
    try:
        from bot import dns_scanner as ds
        return ds
    except ImportError:
        pass
    try:
        import dns_scanner as ds
        return ds
    except ImportError as e:
        if "asyncio" in str(e):
            raise RuntimeError(
                "Missing python3-asyncio! Run: opkg update && opkg install python3-asyncio"
            )
        raise RuntimeError(f"Scanner module failed to load: {e}")


def _dispatch_action(action, body):
    """Execute a named action and return a dict result."""

    # ── Ping ────────────────────────────────────────────────────
    if action == "ping":
        address = body.get("address", "")
        if not address:
            return {"error": "address required"}
        lat = uci.ping_node(address, ping_type="icmp")
        return {"address": address, "type": "icmp", "ms": lat, "ok": bool(lat)}

    elif action == "tcping":
        address = body.get("address", "")
        port = body.get("port", "443")
        if not address:
            return {"error": "address required"}
        lat = uci.ping_node(address, port=str(port), ping_type="tcping")
        return {"address": address, "port": port, "type": "tcping", "ms": lat, "ok": bool(lat)}

    elif action == "ping_node":
        address = body.get("address", "")
        port = body.get("port", "")
        node_id = body.get("node_id", "")
        icmp_lat = uci.ping_node(address, ping_type="icmp") if address else ""
        tcp_lat = uci.ping_node(address, port=port, ping_type="tcping") if address and port else ""
        return {
            "node_id": node_id,
            "icmp_ms": icmp_lat,
            "tcp_ms": tcp_lat,
            "ok": bool(icmp_lat or tcp_lat),
        }

    elif action == "ping_all":
        nodes = uci.get_all_nodes()[:25]
        results = []
        for n in nodes:
            addr = n.get("address", "")
            port = n.get("port", "")
            lat = ""
            if addr and port:
                lat = uci.ping_node(addr, port=port, ping_type="tcping")
            elif addr:
                lat = uci.ping_node(addr, ping_type="icmp")
            results.append({
                "id": n.get("id", n.get(".name", "")),
                "remark": n.get("remark", n.get("remarks", "?"))[:20],
                "ms": lat,
                "ok": bool(lat),
            })
        return {"results": results}

    elif action == "check_services":
        import concurrent.futures
        SERVICES = [
            {"name": "Google", "host": "8.8.8.8", "icon": "🔍"},
            {"name": "Cloudflare", "host": "1.1.1.1", "icon": "☁️"},
            {"name": "GitHub", "host": "github.com", "port": "443", "icon": "🐙"},
            {"name": "Telegram", "host": "t.me", "port": "443", "icon": "📨"},
            {"name": "YouTube", "host": "youtube.com", "port": "443", "icon": "📺"},
            {"name": "X/Twitter", "host": "x.com", "port": "443", "icon": "🐦"},
            {"name": "Instagram", "host": "instagram.com", "port": "443", "icon": "📷"},
            {"name": "Arvan/IR", "host": "arvancloud.ir", "port": "443", "icon": "🌐"},
            {"name": "MCI/IR", "host": "mci.ir", "port": "443", "icon": "📱"},
            {"name": "Irancell/IR", "host": "mtn.ir", "port": "443", "icon": "📶"},
            # Gaming
            {"name": "Epic Games", "host": "epicgames.com", "port": "443", "icon": "🎮", "cat": "gaming"},
            {"name": "Steam", "host": "steam.com", "port": "443", "icon": "🎮", "cat": "gaming"},
            {"name": "Riot Games", "host": "riotgames.com", "port": "443", "icon": "🎮", "cat": "gaming"},
            {"name": "PlayStation", "host": "psn.com", "port": "443", "icon": "🎮", "cat": "gaming"},
            {"name": "Xbox Live", "host": "xbox.com", "port": "443", "icon": "🎮", "cat": "gaming"},
        ]
        def check_one(svc):
            host = svc["host"]
            port = svc.get("port", "")
            try:
                if port:
                    lat = uci.ping_node(host, port=port, ping_type="tcping")
                else:
                    lat = uci.ping_node(host, ping_type="icmp")
            except Exception:
                lat = ""
            return {
                "name": svc["name"],
                "host": host,
                "icon": svc.get("icon", ""),
                "cat": svc.get("cat", "general"),
                "ms": lat,
                "status": "READY" if lat else "DOWN",
            }
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(check_one, SERVICES))
        return {"services": results}

    # ── Slipstream DNS Tunnel ──────────────────────────────────
    elif action == "slipstream_status":
        from bot import slipstream_manager as sm
        return sm.get_status()

    elif action == "set_slipstream_config":
        from bot import slipstream_manager as sm
        domain = body.get("domain", "")
        resolver = body.get("resolver", "")
        cert = body.get("cert", "")
        congestion = body.get("congestion", "dcubic")
        keep_alive = body.get("keep_alive", 400)
        gso = body.get("gso", False)
        if not domain or not resolver:
            return {"ok": False, "msg": "domain and resolver are required"}
        ok, msg = sm.save_and_start(domain, resolver, cert, congestion, int(keep_alive), bool(gso))
        # Auto-create PassWall Socks node
        if ok:
            set_active = body.get("set_active", False)
            node_id = uci.add_socks_node("Slipstream Tunnel", "127.0.0.1", 5201, set_active=bool(set_active))
            msg += f" | PassWall node: {node_id}" if node_id else ""
        return {"ok": ok, "msg": msg}

    elif action == "slipstream_install":
        from bot import slipstream_manager as sm
        ok, msg = sm.install_online()
        return {"ok": ok, "msg": msg}

    elif action == "slipstream_stop":
        from bot import slipstream_manager as sm
        sm.service_stop()
        sm.service_disable()
        return {"ok": True, "msg": "Slipstream stopped"}

    elif action == "slipstream_profiles":
        from bot import slipstream_manager as sm
        return sm.get_profiles()

    elif action == "slipstream_add_profile":
        from bot import slipstream_manager as sm
        ok, msg = sm.add_profile(
            body.get("name", ""), body.get("domain", ""),
            body.get("resolver", ""), body.get("cert", ""),
            body.get("congestion", "dcubic"),
            body.get("keep_alive", 400), body.get("gso", False),
        )
        return {"ok": ok, "msg": msg}

    elif action == "slipstream_edit_profile":
        from bot import slipstream_manager as sm
        ok, msg = sm.edit_profile(
            body.get("old_name", ""), body.get("name", ""),
            body.get("domain", ""), body.get("resolver", ""),
            body.get("cert", ""), body.get("congestion", "dcubic"),
            body.get("keep_alive", 400), body.get("gso", False),
        )
        return {"ok": ok, "msg": msg}

    elif action == "slipstream_delete_profile":
        from bot import slipstream_manager as sm
        ok, msg = sm.delete_profile(body.get("name", ""))
        return {"ok": ok, "msg": msg}

    elif action == "slipstream_switch_profile":
        from bot import slipstream_manager as sm
        ok, msg = sm.switch_profile(body.get("name", ""))
        return {"ok": ok, "msg": msg}

    # ── DNSTT DNS Tunnel ──────────────────────────────────────
    elif action == "dnstt_status":
        from bot import dnstt_manager as dm
        return dm.get_status()

    elif action == "set_dnstt_config":
        from bot import dnstt_manager as dm
        domain = body.get("domain", "")
        pubkey = body.get("pubkey", "")
        resolver = body.get("resolver", "")
        listen_port = body.get("listen_port", 7000)
        transport = body.get("transport", "udp")
        if not domain or not pubkey:
            return {"ok": False, "msg": "domain and pubkey required"}
        ok, msg = dm.save_and_start(domain, pubkey, resolver, int(listen_port), transport)
        # Auto-create PassWall Socks node
        if ok:
            set_active = body.get("set_active", False)
            node_id = uci.add_socks_node("DNSTT Tunnel", "127.0.0.1", int(listen_port), set_active=bool(set_active))
            msg += f" | PassWall node: {node_id}" if node_id else ""
        return {"ok": ok, "msg": msg}

    elif action == "dnstt_install":
        from bot import dnstt_manager as dm
        ok, msg = dm.install_online()
        return {"ok": ok, "msg": msg}

    elif action == "dnstt_stop":
        from bot import dnstt_manager as dm
        dm.service_stop()
        dm.service_disable()
        return {"ok": True, "msg": "DNSTT stopped"}

    elif action == "dnstt_profiles":
        from bot import dnstt_manager as dm
        return dm.get_profiles()

    elif action == "dnstt_add_profile":
        from bot import dnstt_manager as dm
        ok, msg = dm.add_profile(
            body.get("name", ""), body.get("domain", ""),
            body.get("pubkey", ""), body.get("resolver", ""),
            body.get("listen_port", 7000), body.get("transport", "udp"),
        )
        return {"ok": ok, "msg": msg}

    elif action == "dnstt_edit_profile":
        from bot import dnstt_manager as dm
        ok, msg = dm.edit_profile(
            body.get("old_name", ""), body.get("name", ""),
            body.get("domain", ""), body.get("pubkey", ""),
            body.get("resolver", ""), body.get("listen_port", 7000),
            body.get("transport", "udp"),
        )
        return {"ok": ok, "msg": msg}

    elif action == "dnstt_delete_profile":
        from bot import dnstt_manager as dm
        ok, msg = dm.delete_profile(body.get("name", ""))
        return {"ok": ok, "msg": msg}

    elif action == "dnstt_switch_profile":
        from bot import dnstt_manager as dm
        ok, msg = dm.switch_profile(body.get("name", ""))
        return {"ok": ok, "msg": msg}

    # ── Service Control ─────────────────────────────────────────
    elif action == "start":
        uci.service_start()
        return {"ok": True, "msg": "PassWall started"}

    elif action == "stop":
        uci.service_stop()
        return {"ok": True, "msg": "PassWall stopped"}

    elif action == "restart":
        uci.service_restart()
        return {"ok": True, "msg": "PassWall restarted"}

    # ── Node Management ────────────────────────────────────────
    elif action == "set_node":
        node_id = body.get("node", "")
        if node_id and re.match(r'^[a-zA-Z0-9_]+$', node_id):
            uci.set_current_node(node_id)
            uci.service_restart()
            return {"ok": True, "msg": f"Switched to {node_id}"}
        return {"error": "invalid node_id"}

    elif action == "delete_node":
        node_id = body.get("node", "")
        if node_id and re.match(r'^[a-zA-Z0-9_]+$', node_id):
            ok = uci.delete_node(node_id)
            return {"ok": ok, "msg": "deleted" if ok else "failed"}
        return {"error": "invalid node_id"}

    elif action == "copy_node":
        node_id = body.get("node", "")
        if node_id and re.match(r'^[a-zA-Z0-9_]+$', node_id):
            new_id = uci.copy_node(node_id)
            return {"ok": bool(new_id), "new_id": new_id or ""}
        return {"error": "invalid node_id"}

    elif action == "add_node_url":
        url = body.get("url", "")
        if url:
            ok = uci.add_node_from_url(url)
            return {"ok": ok, "msg": "added" if ok else "failed"}
        return {"error": "url required"}

    elif action == "edit_node":
        node_id = body.get("node_id", "")
        fields = body.get("fields", {})
        if node_id and isinstance(fields, dict) and re.match(r'^[a-zA-Z0-9_]+$', node_id):
            ok = uci.edit_node(node_id, fields)
            return {"ok": ok, "msg": "saved" if ok else "no valid fields"}
        return {"error": "node_id and fields required"}

    # ── ACL ─────────────────────────────────────────────────────
    elif action == "set_acl":
        acl_id = body.get("id", "")
        enabled = body.get("enabled", "0")
        if acl_id:
            ok = uci.set_acl_enabled(acl_id, enabled == "1")
            return {"ok": ok}
        return {"error": "acl id required"}

    # ── Shunt Rules ─────────────────────────────────────────────
    elif action == "set_shunt":
        rule_name = body.get("rule_name", "")
        if not rule_name or not re.match(r'^[a-zA-Z0-9_]+$', rule_name):
            return {"error": "invalid rule_name"}
        # Save ALL provided shunt fields
        SHUNT_FIELDS = {
            "remarks", "protocol", "inbound", "network",
            "source", "sourcePort", "port",
            "domain_list", "ip_list",
        }
        for field in SHUNT_FIELDS:
            if field in body:
                uci.set_shunt_rule_field(rule_name, field, body[field])
        return {"ok": True, "msg": f"Shunt '{rule_name}' saved"}

    # ── DNS ──────────────────────────────────────────────────────
    elif action == "dns_change":
        changes = body.get("changes", {})
        if isinstance(changes, dict):
            DNS_KEYS = {
                "remote_dns_protocol", "remote_dns", "remote_dns_doh",
                "remote_dns_client_ip", "remote_dns_detour", "remote_fakedns",
                "remote_dns_query_strategy", "direct_dns_query_strategy",
                "dns_hosts", "dns_redirect",
            }
            for k, v in changes.items():
                if k in DNS_KEYS:
                    uci.set_dns_option(k, str(v))
            return {"ok": True}
        return {"error": "changes must be dict"}

    # ── Forwarding / Delay / Global ─────────────────────────────
    elif action == "set_forwarding":
        key = body.get("key", "")
        value = body.get("value", "")
        if key and re.match(r'^[a-z_]+$', key):
            uci.set_forwarding_option(key, value)
            return {"ok": True, "msg": f"{key}={value}"}
        return {"error": "invalid key"}

    elif action == "set_delay":
        key = body.get("key", "")
        value = body.get("value", "")
        if key and re.match(r'^[a-z_]+$', key):
            uci.set_delay_option(key, value)
            return {"ok": True, "msg": f"{key}={value}"}
        return {"error": "invalid key"}

    elif action == "set_global":
        key = body.get("key", "")
        value = body.get("value", "")
        if key and re.match(r'^[a-z_]+$', key):
            uci.set_global_option(key, value)
            return {"ok": True, "msg": f"{key}={value}"}
        return {"error": "invalid key"}

    # ── Logs ────────────────────────────────────────────────────
    elif action == "get_log":
        log = uci.get_log(80)
        return {"log": log or "No entries"}

    elif action == "get_server_log":
        log = uci.get_server_log(80)
        return {"log": log or "No entries"}

    # ── Subscriptions ──────────────────────────────────────────
    elif action == "sub_update":
        uci.subscribe_update_all()
        return {"ok": True, "msg": "Subscription update triggered"}

    elif action == "update_rules":
        uci.update_rules("all")
        return {"ok": True, "msg": "GeoIP/Geosite update started"}

    elif action == "flush_sets":
        uci.flush_sets()
        return {"ok": True, "msg": "IPSET/NFTSET flushed"}

    # ── GeoView ────────────────────────────────────────────────
    elif action == "geo_lookup":
        value = body.get("value", "")
        if value:
            result = uci.geo_lookup(value)
            return {"result": result}
        return {"error": "value required"}

    # ── DNS Tunnel Scanner v2 (FULL) ────────────────────────────────
    elif action == "dns_scanner_start":
        ds = _get_dns_scanner()
        domain = body.get("domain", "")
        cidr_text = body.get("cidr_text", "")
        concurrency = int(body.get("concurrency", 200))
        timeout = float(body.get("timeout", 2.5))
        dns_type = body.get("dns_type", "A")
        random_subdomain = body.get("random_subdomain", True)
        preset = body.get("preset", "normal")
        sample_size = int(body.get("sample_size", 0))
        blacklist_enabled = body.get("blacklist_enabled", False)
        auto_retry = body.get("auto_retry", False)
        check_ns = body.get("check_ns", False)
        domains = body.get("domains", "")
        source_port = int(body.get("source_port", 0))
        pre_scan_port = int(body.get("pre_scan_port", 0))
        pre_scan_rate = int(body.get("pre_scan_rate", 1000))
        if not domain or not cidr_text:
            return {"ok": False, "msg": "domain and cidr_text required"}
        ok, msg = ds.start_scan(domain, cidr_text, concurrency, timeout,
                                dns_type, random_subdomain, preset, sample_size,
                                blacklist_enabled, auto_retry, check_ns, domains,
                                source_port, pre_scan_port, pre_scan_rate)
        return {"ok": ok, "msg": msg}

    elif action == "dns_scanner_status":
        ds = _get_dns_scanner()
        return ds.get_status()

    elif action == "dns_scanner_stop":
        ds = _get_dns_scanner()
        ok, msg = ds.stop_scan()
        return {"ok": ok, "msg": msg}

    elif action == "dns_scanner_pause":
        ds = _get_dns_scanner()
        ok, msg = ds.pause_scan()
        return {"ok": ok, "msg": msg}

    elif action == "dns_scanner_resume":
        ds = _get_dns_scanner()
        ok, msg = ds.resume_scan()
        return {"ok": ok, "msg": msg}

    elif action == "dns_scanner_shuffle":
        ds = _get_dns_scanner()
        ok, msg = ds.shuffle_scan()
        return {"ok": ok, "msg": msg}

    elif action == "dns_scanner_export":
        ds = _get_dns_scanner()
        return ds.export_results()

    elif action == "dns_scanner_history":
        ds = _get_dns_scanner()
        return {"history": ds.get_scan_history()}

    elif action == "dns_scanner_save_project":
        ds = _get_dns_scanner()
        ok, msg = ds.save_project()
        return {"ok": ok, "msg": msg}

    elif action == "dns_scanner_load_project":
        ds = _get_dns_scanner()
        return ds.load_project()

    elif action == "dns_scanner_install_masscan":
        try:
            import platform
            arch = platform.machine()
            if "armv7" not in arch.lower():
                return {"ok": False, "msg": f"Auto-install currently only supports armv7. Your arch: {arch}"}
            
            import urllib.request
            import subprocess
            url = "https://github.com/rooomer/passwall2-webapp/releases/latest/download/masscan-armv7-openwrt.zip"
            zip_path = "/tmp/masscan-armv7-openwrt.zip"
            
            urllib.request.urlretrieve(url, zip_path)
            subprocess.run(["unzip", "-o", zip_path, "-d", "/tmp/"], check=True)
            subprocess.run(["mv", "/tmp/masscan", "/usr/bin/masscan"], check=True)
            subprocess.run(["chmod", "+x", "/usr/bin/masscan"], check=True)
            
            return {"ok": True, "msg": "Masscan installed successfully to /usr/bin/masscan"}
        except Exception as e:
            return {"ok": False, "msg": f"Install failed: {e}"}

    elif action == "dns_scanner_last_domain":
        ds = _get_dns_scanner()
        return {"domain": ds.load_last_domain()}

    elif action == "dns_scanner_get_blacklist":
        ds = _get_dns_scanner()
        return {"blacklist": ds.get_blacklist()}

    elif action == "dns_scanner_add_blacklist":
        ds = _get_dns_scanner()
        ip = body.get("ip", "")
        if not ip:
            return {"ok": False, "msg": "ip required"}
        ok, msg = ds.add_to_blacklist(ip)
        return {"ok": ok, "msg": msg}

    elif action == "dns_scanner_clear_blacklist":
        ds = _get_dns_scanner()
        ok, msg = ds.clear_blacklist()
        return {"ok": ok, "msg": msg}

    # ── CIDR List Manager ─────────────────────────────────────
    elif action == "get_cidr_lists":
        from bot import cidr_manager as cm
        return {"lists": cm.get_all()}

    elif action == "get_cidr_content":
        from bot import cidr_manager as cm
        name = body.get("name", "")
        return {"name": name, "content": cm.get_one(name)}

    elif action == "add_cidr_list":
        from bot import cidr_manager as cm
        name = body.get("name", "")
        content = body.get("content", "")
        ok, msg = cm.add_or_update(name, content)
        return {"ok": ok, "msg": msg}

    elif action == "delete_cidr_list":
        from bot import cidr_manager as cm
        name = body.get("name", "")
        ok, msg = cm.delete(name)
        return {"ok": ok, "msg": msg}

    else:
        return {"error": f"unknown action: {action}"}


# ═══════════════════════════════════════════════════════════════
#  SERVER STARTUP
# ═══════════════════════════════════════════════════════════════

def generate_token():
    """Generate a cryptographically secure session token."""
    return secrets.token_urlsafe(32)


def start_api_server(uci_module, token=None, host="127.0.0.1", port=8080):
    """Start the API server in a daemon thread.
    Returns the token used for authentication."""
    global uci, _API_TOKEN

    uci = uci_module
    _API_TOKEN = token or generate_token()

    # Write token to file for debugging/verification
    try:
        with open("/tmp/pw_api_token", "w") as f:
            f.write(_API_TOKEN)
    except Exception:
        pass

    # ThreadingHTTPServer: handle multiple requests concurrently
    # Without this, tunnel_manager probes block LuCI/webapp requests
    class ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
        daemon_threads = True
        allow_reuse_address = True  # prevent 'Address in use' on restart

    server = ThreadedHTTPServer((host, port), APIHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="api-server")
    thread.start()
    logger.info("API server started on %s:%d (threaded)", host, port)
    return _API_TOKEN


def get_api_token():
    """Return the current API token."""
    return _API_TOKEN
