#!/usr/bin/env python3
"""
PassWall 2 Bot — Diagnostic Script
===================================
Run on the router to debug all components:
  python3 /usr/share/passwall2_bot/debug_test.py

Tests:
  1. Python environment & imports
  2. UCI wrapper functions
  3. API server (starts on port 8099 to avoid conflict)
  4. Cloudflared binary availability
  5. CORS & HTTP method handling
  6. Full request/response cycle
"""

import sys
import os
import json
import time
import traceback

# Fix import path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

RESULTS = []

def test(name, fn):
    """Run a test and record result."""
    try:
        result = fn()
        RESULTS.append(("✅", name, str(result)))
        print(f"  ✅ {name}: {result}")
    except Exception as e:
        RESULTS.append(("❌", name, str(e)))
        print(f"  ❌ {name}: {e}")
        traceback.print_exc()

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

# ═══════════════════════════════════════════════════════════════
#  1. PYTHON ENVIRONMENT
# ═══════════════════════════════════════════════════════════════
section("1. Python Environment")
print(f"  Python: {sys.version}")
print(f"  Platform: {sys.platform}")
print(f"  CWD: {os.getcwd()}")
print(f"  Script: {os.path.abspath(__file__)}")

test("import json", lambda: "OK")
test("import threading", lambda: __import__("threading") and "OK")
test("import http.server", lambda: __import__("http.server") and "OK")
test("import secrets", lambda: __import__("secrets") and "OK")
test("import subprocess", lambda: __import__("subprocess") and "OK")
test("import urllib.parse", lambda: __import__("urllib.parse") and "OK")

# ═══════════════════════════════════════════════════════════════
#  2. BOT MODULE IMPORTS
# ═══════════════════════════════════════════════════════════════
section("2. Bot Module Imports")

test("import bot.config", lambda: __import__("bot.config") and "OK")
test("import bot.uci_wrapper", lambda: __import__("bot.uci_wrapper") and "OK")
test("import bot.telegram_api", lambda: __import__("bot.telegram_api") and "OK")
test("import bot.menus", lambda: __import__("bot.menus") and "OK")
test("import bot.api_server", lambda: __import__("bot.api_server") and "OK")
test("import bot.tunnel_manager", lambda: __import__("bot.tunnel_manager") and "OK")

# ═══════════════════════════════════════════════════════════════
#  3. UCI WRAPPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════
section("3. UCI Wrapper Functions")

try:
    from bot import uci_wrapper as uci

    test("uci.service_status()", lambda: uci.service_status())
    test("uci.get_current_node()", lambda: uci.get_current_node())
    test("uci.get_all_nodes()", lambda: f"{len(uci.get_all_nodes())} nodes found")
    test("uci.get_dns_settings()", lambda: json.dumps(uci.get_dns_settings(), indent=2)[:200])
    test("uci.get_acl_rules()", lambda: f"{len(uci.get_acl_rules())} ACL rules")
    test("uci.get_shunt_rules()", lambda: f"{len(uci.get_shunt_rules())} shunt rules")

    test("uci.get_socks_list()", lambda: f"{len(uci.get_socks_list())} socks entries")
    test("uci.get_haproxy_list()", lambda: f"{len(uci.get_haproxy_list())} haproxy entries")
    test("uci.get_subscribe_list()", lambda: f"{len(uci.get_subscribe_list())} subscriptions")

    test("uci.ping_node('8.8.8.8')", lambda: f"{uci.ping_node('8.8.8.8', ping_type='icmp')} ms")

    # Check which functions exist
    for fn_name in ['get_socks_list', 'get_haproxy_list', 'set_acl_enabled',
                    'add_node_from_url', 'get_log', 'get_server_log',
                    'set_forwarding_option', 'set_delay_option', 'set_global_option',
                    'set_shunt_rule_field', 'subscribe_update_all', 'update_rules',
                    'flush_sets', 'geo_lookup', 'uci_batch',
                    'delete_node', 'copy_node', 'set_current_node']:
        exists = hasattr(uci, fn_name)
        if exists:
            print(f"  ✅ uci.{fn_name} EXISTS")
        else:
            print(f"  ❌ uci.{fn_name} MISSING!")
            RESULTS.append(("❌", f"uci.{fn_name}", "MISSING"))

except Exception as e:
    print(f"  ❌ UCI import failed: {e}")
    traceback.print_exc()

# ═══════════════════════════════════════════════════════════════
#  4. API SERVER TEST
# ═══════════════════════════════════════════════════════════════
section("4. API Server (port 8099)")

try:
    from bot import api_server

    # Start on test port
    test_token = api_server.start_api_server(uci, token="DEBUG_TOKEN_123", host="127.0.0.1", port=8099)
    print(f"  Token: {test_token}")
    time.sleep(1)  # Give server time to start

    import urllib.request

    def api_test(method, path, body=None, expect_status=200):
        """Make a test HTTP request to the API server."""
        url = f"http://127.0.0.1:8099{path}"
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {test_token}")
        if body:
            req.add_header("Content-Type", "application/json")

        try:
            resp = urllib.request.urlopen(req, timeout=10)
            result = resp.read().decode()
            status = resp.getcode()
            return f"HTTP {status}, body={result[:200]}"
        except urllib.error.HTTPError as e:
            body_text = e.read().decode() if e.fp else ""
            return f"HTTP {e.code}: {e.reason} body={body_text[:200]}"
        except Exception as e:
            return f"ERROR: {e}"

    # Test OPTIONS (CORS preflight)
    def options_test():
        url = "http://127.0.0.1:8099/api/config"
        req = urllib.request.Request(url, method="OPTIONS")
        req.add_header("Origin", "https://rooomer.github.io")
        req.add_header("Access-Control-Request-Method", "GET")
        req.add_header("Access-Control-Request-Headers", "Authorization")
        try:
            resp = urllib.request.urlopen(req, timeout=5)
            headers = dict(resp.headers)
            cors_origin = headers.get("Access-Control-Allow-Origin", "MISSING")
            cors_methods = headers.get("Access-Control-Allow-Methods", "MISSING")
            cors_headers = headers.get("Access-Control-Allow-Headers", "MISSING")
            content_len = headers.get("Content-Length", "MISSING")
            return (f"HTTP {resp.getcode()}, "
                    f"CORS-Origin={cors_origin}, "
                    f"CORS-Methods={cors_methods}, "
                    f"CORS-Headers={cors_headers}, "
                    f"Content-Length={content_len}")
        except urllib.error.HTTPError as e:
            return f"HTTP {e.code}: {e.reason}"
        except Exception as e:
            return f"ERROR: {e}"

    test("OPTIONS /api/config (CORS preflight)", options_test)
    test("GET /api/config", lambda: api_test("GET", "/api/config"))
    test("GET /api/status", lambda: api_test("GET", "/api/status"))
    test("GET /api/ping (health)", lambda: api_test("GET", "/api/ping"))
    test("POST /api/action/ping", lambda: api_test("POST", "/api/action/ping", {"address": "8.8.8.8"}))
    test("POST /api/action/ping_all", lambda: api_test("POST", "/api/action/ping_all", {}))

    # Test without auth
    def no_auth_test():
        url = "http://127.0.0.1:8099/api/config"
        req = urllib.request.Request(url, method="GET")
        try:
            resp = urllib.request.urlopen(req, timeout=5)
            return f"HTTP {resp.getcode()} (SHOULD BE 401!)"
        except urllib.error.HTTPError as e:
            if e.code == 401:
                return "Correctly returned 401 Unauthorized"
            return f"HTTP {e.code}: {e.reason}"
        except Exception as e:
            return f"ERROR: {e}"

    test("GET /api/config (no auth)", no_auth_test)

    # Test bad method
    def bad_method_test():
        url = "http://127.0.0.1:8099/api/config"
        req = urllib.request.Request(url, method="PUT")
        req.add_header("Authorization", f"Bearer {test_token}")
        try:
            resp = urllib.request.urlopen(req, timeout=5)
            return f"HTTP {resp.getcode()}"
        except urllib.error.HTTPError as e:
            return f"HTTP {e.code}: {e.reason}"
        except Exception as e:
            return f"ERROR: {e}"

    test("PUT /api/config (bad method)", bad_method_test)

except Exception as e:
    print(f"  ❌ API Server failed: {e}")
    traceback.print_exc()

# ═══════════════════════════════════════════════════════════════
#  5. CLOUDFLARED CHECK
# ═══════════════════════════════════════════════════════════════
section("5. Cloudflared Binary")

import subprocess, platform

arch = platform.machine()
print(f"  Architecture: {arch}")

cf_path = "/usr/bin/cloudflared"
test("cloudflared exists", lambda: f"{'YES' if os.path.isfile(cf_path) else 'NO'} at {cf_path}")

if os.path.isfile(cf_path):
    test("cloudflared executable", lambda: f"{'YES' if os.access(cf_path, os.X_OK) else 'NO'}")
    test("cloudflared version", lambda: subprocess.run(
        [cf_path, "version"], capture_output=True, text=True, timeout=5
    ).stdout.strip() or subprocess.run(
        [cf_path, "version"], capture_output=True, text=True, timeout=5
    ).stderr.strip()[:100])
else:
    print(f"  ⚠️  cloudflared NOT found. It will be auto-downloaded on first bot start.")
    print(f"  Manual download for {arch}:")
    urls = {
        "aarch64": "cloudflared-linux-arm64",
        "armv7l": "cloudflared-linux-arm",
        "x86_64": "cloudflared-linux-amd64",
        "mips": "cloudflared-linux-mips",
    }
    binary = urls.get(arch, f"cloudflared-linux-{arch}")
    print(f"  wget -O /usr/bin/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/{binary}")
    print(f"  chmod +x /usr/bin/cloudflared")

# ═══════════════════════════════════════════════════════════════
#  6. PORT & PROCESS CHECK
# ═══════════════════════════════════════════════════════════════
section("6. Port & Process Check")

test("Port 8080 in use", lambda: subprocess.run(
    ["netstat", "-tlnp"], capture_output=True, text=True, timeout=5
).stdout if "8080" in subprocess.run(
    ["netstat", "-tlnp"], capture_output=True, text=True, timeout=5
).stdout else "Port 8080 is FREE")

test("Running python3 procs", lambda: subprocess.run(
    ["ps", "w"], capture_output=True, text=True, timeout=5
).stdout.count("python3"))

test("Running cloudflared procs", lambda: subprocess.run(
    ["ps", "w"], capture_output=True, text=True, timeout=5
).stdout.count("cloudflared"))

# ═══════════════════════════════════════════════════════════════
#  7. ENVIRONMENT VARIABLES
# ═══════════════════════════════════════════════════════════════
section("7. Environment Variables")
for var in ["PW_BOT_TOKEN", "PW_ADMIN_ID", "PW_WEBAPP_URL"]:
    val = os.environ.get(var, "")
    masked = val[:8] + "***" if val else "(not set)"
    print(f"  {var} = {masked}")

# ═══════════════════════════════════════════════════════════════
#  8. CONFIG FILE CHECK
# ═══════════════════════════════════════════════════════════════
section("8. Config Files")
for path in ["/etc/config/passwall2", "/etc/config/passwall2_server",
             "/etc/config/passwall2_bot", "/etc/init.d/passwall2_bot"]:
    exists = os.path.isfile(path)
    size = os.path.getsize(path) if exists else 0
    print(f"  {'✅' if exists else '❌'} {path} {'(' + str(size) + ' bytes)' if exists else '(MISSING)'}")

# ═══════════════════════════════════════════════════════════════
#  SUMMARY
# ═══════════════════════════════════════════════════════════════
section("SUMMARY")
failures = [r for r in RESULTS if r[0] == "❌"]
passes = [r for r in RESULTS if r[0] == "✅"]
print(f"  Total: {len(RESULTS)} tests")
print(f"  ✅ Passed: {len(passes)}")
print(f"  ❌ Failed: {len(failures)}")

if failures:
    print(f"\n  FAILURES:")
    for _, name, err in failures:
        print(f"    ❌ {name}: {err}")

print(f"\n{'='*60}")
print(f"  Copy ALL output above and send it back!")
print(f"{'='*60}")
