#!/usr/bin/env python3
"""
download_cidrs.py – Automate downloading popular Country/Datacenter CIDRs.
Run this script on the router to automatically populate your CIDR library
with IPs from countries that have many datacenters.
Uses raw sockets (no urllib) for OpenWrt compatibility.
"""

import sys
import os
import socket
import logging

try:
    import cidr_manager
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import cidr_manager
    except ImportError:
        print("Error: Could not import cidr_manager.py.")
        sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# ── Country-level CIDR lists from IPDeny ───────────────────────
# Countries with many VPS/datacenter providers:
COUNTRY_SOURCES = {
    # === Middle East ===
    "Iran": "ir",
    "Turkey": "tr",
    "UAE": "ae",
    # === Europe (DC-heavy) ===
    "Germany": "de",
    "Netherlands": "nl",
    "France": "fr",
    "United Kingdom": "gb",
    "Finland": "fi",
    "Sweden": "se",
    "Switzerland": "ch",
    "Poland": "pl",
    "Romania": "ro",
    "Bulgaria": "bg",
    "Lithuania": "lt",
    "Czech Republic": "cz",
    "Ukraine": "ua",
    "Russia": "ru",
    # === Americas ===
    "United States": "us",
    "Canada": "ca",
    "Brazil": "br",
    # === Asia-Pacific ===
    "Singapore": "sg",
    "Japan": "jp",
    "South Korea": "kr",
    "Hong Kong": "hk",
    "India": "in",
    "Australia": "au",
}

IPDENY_BASE = "http://www.ipdeny.com/ipblocks/data/countries/"


def http_get(host, path, timeout=15):
    """Fetch a URL via raw HTTP socket (no urllib needed)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect((host, 80))

    req = f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUser-Agent: Mozilla/5.0\r\nConnection: close\r\n\r\n"
    s.sendall(req.encode('ascii'))

    data = b""
    while True:
        chunk = s.recv(8192)
        if not chunk:
            break
        data += chunk
    s.close()

    text = data.decode('utf-8', errors='ignore')
    sep = text.find('\r\n\r\n')
    if sep == -1:
        return None, "Invalid HTTP response"

    status_line = text[:sep].splitlines()[0]
    body = text[sep + 4:].strip()

    if "200" not in status_line:
        return None, f"HTTP Error: {status_line}"

    return body, None


def main():
    print("=" * 50)
    print("  📡 CIDR Library Auto-Downloader")
    print("=" * 50)

    success = 0
    fail = 0

    # ── Download country lists ──
    print(f"\n🌍 Downloading {len(COUNTRY_SOURCES)} country CIDR lists...\n")

    for name, code in COUNTRY_SOURCES.items():
        url_path = f"/ipblocks/data/countries/{code}.zone"
        print(f"  [{code.upper()}] {name}...", end=" ", flush=True)
        try:
            body, err = http_get("www.ipdeny.com", url_path)
            if err:
                print(f"❌ {err}")
                fail += 1
                continue

            if not body:
                print("❌ Empty")
                fail += 1
                continue

            lines = [l for l in body.split('\n') if l.strip()]
            ok, msg = cidr_manager.add_or_update(f"🌍 {name} ({code.upper()})", body)
            if ok:
                print(f"✅ {len(lines)} ranges")
                success += 1
            else:
                print(f"❌ {msg}")
                fail += 1
        except Exception as e:
            print(f"❌ {e}")
            fail += 1

    # ── Summary ──
    print(f"\n{'=' * 50}")
    print(f"  ✅ Saved: {success}  |  ❌ Failed: {fail}")
    print(f"{'=' * 50}")
    print("Lists are now available in the WebApp / LuCI DNS Scanner.")


if __name__ == "__main__":
    main()
