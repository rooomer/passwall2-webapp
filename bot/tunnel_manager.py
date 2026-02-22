"""
PassWall 2 — Cloudflare Quick Tunnel Manager
=============================================
Downloads the `cloudflared` binary for the router's architecture,
starts a quick tunnel pointing at the local API server, and extracts
the random `*.trycloudflare.com` URL for the Telegram Bot to pass
to the Mini App.

Usage:
    from tunnel_manager import start_tunnel, get_tunnel_url
    start_tunnel(port=8080)
    url = get_tunnel_url()  # blocks until URL is available or timeout
"""

import logging
import os
import platform
import re
import subprocess
import threading
import time
import stat

logger = logging.getLogger("tunnel_manager")

# ── State ───────────────────────────────────────────────────────
_tunnel_url = ""
_tunnel_lock = threading.Lock()
_tunnel_ready = threading.Event()
_tunnel_proc = None

# ── Architecture → Download URL mapping ─────────────────────────
# Cloudflare publishes static binaries for many platforms.
# OpenWrt routers are typically: arm, aarch64, mips, mipsel, x86_64
CLOUDFLARED_URLS = {
    "aarch64":  "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64",
    "armv7l":   "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm",
    "armv6l":   "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm",
    "mips":     "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-mips",
    "mipsel":   "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-mipsle",
    "x86_64":   "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
    "i686":     "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-386",
}

CLOUDFLARED_PATH = "/usr/bin/cloudflared"
CLOUDFLARED_DIR = "/tmp/cloudflared_workdir"


def _detect_arch():
    """Detect CPU architecture for binary download."""
    machine = platform.machine().lower()
    # OpenWrt uname may report differently
    if "aarch64" in machine or "arm64" in machine:
        return "aarch64"
    elif "armv7" in machine or "armv8" in machine:
        return "armv7l"
    elif "armv6" in machine:
        return "armv6l"
    elif "mips" in machine and "el" in machine:
        return "mipsel"
    elif "mips" in machine:
        return "mips"
    elif "x86_64" in machine or "amd64" in machine:
        return "x86_64"
    elif "i686" in machine or "i386" in machine:
        return "i686"
    return machine


def _download_cloudflared():
    """Download the cloudflared binary if not present."""
    if os.path.isfile(CLOUDFLARED_PATH):
        logger.info("cloudflared already exists at %s", CLOUDFLARED_PATH)
        return True

    arch = _detect_arch()
    url = CLOUDFLARED_URLS.get(arch)
    if not url:
        logger.error("No cloudflared binary available for arch: %s", arch)
        return False

    logger.info("Downloading cloudflared for %s from %s", arch, url)
    try:
        # Use wget (available on all OpenWrt) or curl
        ret = subprocess.run(
            ["wget", "-q", "-O", CLOUDFLARED_PATH, url],
            timeout=120,
            capture_output=True,
        )
        if ret.returncode != 0:
            # Fallback to curl
            ret = subprocess.run(
                ["curl", "-sL", "-o", CLOUDFLARED_PATH, url],
                timeout=120,
                capture_output=True,
            )
        if ret.returncode != 0:
            logger.error("Failed to download cloudflared: %s", ret.stderr.decode(errors="replace"))
            return False

        # Make executable
        os.chmod(CLOUDFLARED_PATH, os.stat(CLOUDFLARED_PATH).st_mode | stat.S_IEXEC)
        logger.info("cloudflared downloaded successfully to %s", CLOUDFLARED_PATH)
        return True
    except Exception as e:
        logger.error("Download error: %s", e)
        return False


def _run_tunnel(port):
    """Run cloudflared quick tunnel and parse the URL from its output."""
    global _tunnel_url, _tunnel_proc

    # Ensure work directory exists
    os.makedirs(CLOUDFLARED_DIR, exist_ok=True)

    cmd = [
        CLOUDFLARED_PATH,
        "tunnel",
        "--url", f"http://127.0.0.1:{port}",
        "--no-autoupdate",
    ]

    logger.info("Starting cloudflared: %s", " ".join(cmd))

    try:
        _tunnel_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # cloudflared logs to stderr
            text=True,
            bufsize=1,
            env={**os.environ, "HOME": CLOUDFLARED_DIR},
        )

        # Read output lines looking for the tunnel URL
        # RFC 952: hostname must start with a letter or digit, not a hyphen
        url_pattern = re.compile(r'https://([a-zA-Z0-9][a-zA-Z0-9\-]*)\.trycloudflare\.com')
        for line in iter(_tunnel_proc.stdout.readline, ""):
            line = line.strip()
            if line:
                logger.debug("cloudflared: %s", line)
            match = url_pattern.search(line)
            if match:
                candidate_url = match.group(0)
                hostname = match.group(1)
                # Extra safety: reject hostnames that end with a hyphen too
                if hostname.startswith("-") or hostname.endswith("-"):
                    logger.warning("⚠️ Skipping invalid tunnel hostname: %s (starts/ends with hyphen)", candidate_url)
                    continue
                logger.info("🔗 Tunnel URL found: %s — verifying...", candidate_url)

                # Quick local sanity check: can we reach our own API?
                local_ok = False
                try:
                    local_ret = subprocess.run(
                        ["wget", "-q", "-O", "/dev/null", "--timeout=2",
                         f"http://127.0.0.1:{port}/api/ping"],
                        timeout=4, capture_output=True, text=True,
                    )
                    local_ok = (local_ret.returncode == 0)
                    if local_ok:
                        logger.info("✅ Local API is reachable at 127.0.0.1:%d", port)
                    else:
                        logger.warning("⚠️ Local API probe failed (rc=%d): %s",
                                      local_ret.returncode, local_ret.stderr.strip())
                except Exception as e:
                    logger.warning("⚠️ Local API probe error: %s", e)

                # Set tunnel URL immediately if local API works
                # (external probe through PassWall routing is unreliable)
                with _tunnel_lock:
                    _tunnel_url = candidate_url
                if local_ok:
                    logger.info("🚀 Tunnel ready (local API verified): %s", _tunnel_url)
                else:
                    logger.warning("⚠️ Tunnel URL set but local API unreachable: %s", _tunnel_url)
                _tunnel_ready.set()

        # Process ended
        _tunnel_proc.wait()
        logger.warning("cloudflared process exited with code %s", _tunnel_proc.returncode)

    except Exception as e:
        logger.error("Tunnel error: %s", e)
    finally:
        with _tunnel_lock:
            _tunnel_url = ""
        _tunnel_ready.clear()


def _tunnel_loop(port):
    """Keep the tunnel running, restarting on failure."""
    while True:
        logger.info("Starting tunnel loop (port %d)...", port)
        _download_cloudflared()
        if os.path.isfile(CLOUDFLARED_PATH):
            _run_tunnel(port)
        else:
            logger.error("cloudflared binary not available, retrying in 30s...")
        # Wait before retry
        time.sleep(30)


# ═══════════════════════════════════════════════════════════════
#  PUBLIC API
# ═══════════════════════════════════════════════════════════════

def start_tunnel(port=8080):
    """Start the cloudflare tunnel in a background daemon thread."""
    thread = threading.Thread(
        target=_tunnel_loop,
        args=(port,),
        daemon=True,
        name="cf-tunnel",
    )
    thread.start()
    logger.info("Tunnel manager started (waiting for URL...)")


def get_tunnel_url(timeout=60):
    """Get the current tunnel URL. Blocks until available or timeout."""
    if _tunnel_ready.wait(timeout=timeout):
        with _tunnel_lock:
            return _tunnel_url
    return ""


def stop_tunnel():
    """Stop the tunnel process."""
    global _tunnel_proc
    if _tunnel_proc:
        try:
            _tunnel_proc.terminate()
            _tunnel_proc.wait(timeout=5)
        except Exception:
            _tunnel_proc.kill()
        _tunnel_proc = None
        logger.info("Tunnel stopped")
