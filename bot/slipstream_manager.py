"""
Slipstream DNS Tunnel Manager
Handles downloading, installing, configuring, and managing the
slipstream-client daemon on OpenWrt routers.
Supports multiple named config profiles with switching.
"""
import os
import json
import subprocess
import logging
import copy

logger = logging.getLogger(__name__)

SLIPSTREAM_BIN = "/usr/bin/slipstream-client"
SLIPSTREAM_CONF_DIR = "/etc/slipstream-rust"
SLIPSTREAM_CONF = os.path.join(SLIPSTREAM_CONF_DIR, "profiles.json")
SLIPSTREAM_CERT = os.path.join(SLIPSTREAM_CONF_DIR, "cert.pem")
SLIPSTREAM_INITD = "/etc/init.d/slipstream"
SLIPSTREAM_DEFAULT_PORT = 5201

GITHUB_RELEASE_URL = (
    "https://github.com/rooomer/passwall2-webapp/releases/download/"
    "slipstream-latest"
)

ARCH_MAP = {
    "x86_64": "slipstream-client-linux-amd64-musl",
    "aarch64": "slipstream-client-linux-arm64-musl",
    "armv7l": "slipstream-client-linux-armv7-musl",
}

DEFAULT_PROFILE = {
    "name": "Default",
    "domain": "",
    "resolver": "",
    "cert": "",
    "congestion": "dcubic",
    "keep_alive": 400,
    "gso": False,
}


def _run(cmd, timeout=30):
    """Run a shell command and return stdout."""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return r.stdout.strip()
    except Exception as e:
        logger.error("cmd failed: %s → %s", cmd, e)
        return ""


def detect_arch():
    """Detect router architecture."""
    arch = _run("uname -m")
    return arch or "unknown"


def get_download_url():
    """Get the download URL for the correct musl binary."""
    arch = detect_arch()
    filename = ARCH_MAP.get(arch)
    if not filename:
        return None, f"Unsupported architecture: {arch}"
    url = f"{GITHUB_RELEASE_URL}/{filename}"
    return url, None


def is_installed():
    """Check if slipstream-client binary exists."""
    return os.path.isfile(SLIPSTREAM_BIN)


# ── Profile Management ─────────────────────────────────────────

def _load_profiles():
    """Load all profiles from disk."""
    if os.path.isfile(SLIPSTREAM_CONF):
        try:
            with open(SLIPSTREAM_CONF) as f:
                data = json.load(f)
            if isinstance(data, dict) and "profiles" in data:
                return data
        except Exception:
            pass
    # Migrate old single-config if it exists
    old_conf = os.path.join(SLIPSTREAM_CONF_DIR, "config.json")
    if os.path.isfile(old_conf):
        try:
            with open(old_conf) as f:
                old = json.load(f)
            profile = {
                "name": "Default",
                "domain": old.get("domain", ""),
                "resolver": old.get("resolver", ""),
                "cert": old.get("cert", ""),
                "congestion": "dcubic",
                "keep_alive": 400,
                "gso": False,
            }
            return {"active": "Default", "profiles": [profile]}
        except Exception:
            pass
    return {"active": "", "profiles": []}


def _save_profiles(data):
    """Save profiles to disk."""
    os.makedirs(SLIPSTREAM_CONF_DIR, exist_ok=True)
    with open(SLIPSTREAM_CONF, "w") as f:
        json.dump(data, f, indent=2)


def get_profiles():
    """Get all profiles and which is active."""
    data = _load_profiles()
    return {
        "active": data.get("active", ""),
        "profiles": data.get("profiles", []),
    }


def add_profile(name, domain, resolver, cert="", congestion="dcubic", keep_alive=400, gso=False):
    """Add a new profile."""
    data = _load_profiles()
    profile = {
        "name": name,
        "domain": domain,
        "resolver": resolver,
        "cert": cert,
        "congestion": congestion,
        "keep_alive": keep_alive,
        "gso": gso,
    }
    data["profiles"].append(profile)
    if not data["active"]:
        data["active"] = name
    _save_profiles(data)
    return True, f"Profile '{name}' added"


def edit_profile(old_name, name, domain, resolver, cert="", congestion="dcubic", keep_alive=400, gso=False):
    """Edit an existing profile."""
    data = _load_profiles()
    for p in data["profiles"]:
        if p["name"] == old_name:
            p["name"] = name
            p["domain"] = domain
            p["resolver"] = resolver
            p["cert"] = cert
            p["congestion"] = congestion
            p["keep_alive"] = keep_alive
            p["gso"] = gso
            if data["active"] == old_name:
                data["active"] = name
            _save_profiles(data)
            return True, f"Profile '{name}' updated"
    return False, f"Profile '{old_name}' not found"


def delete_profile(name):
    """Delete a profile."""
    data = _load_profiles()
    data["profiles"] = [p for p in data["profiles"] if p["name"] != name]
    if data["active"] == name:
        data["active"] = data["profiles"][0]["name"] if data["profiles"] else ""
    _save_profiles(data)
    return True, f"Profile '{name}' deleted"


def switch_profile(name):
    """Switch active profile and restart service."""
    data = _load_profiles()
    found = None
    for p in data["profiles"]:
        if p["name"] == name:
            found = p
            break
    if not found:
        return False, f"Profile '{name}' not found"
    data["active"] = name
    _save_profiles(data)
    _write_init_script(
        found["domain"], found["resolver"],
        bool(found.get("cert", "").strip()),
        found.get("congestion", "dcubic"),
        found.get("keep_alive", 400),
        found.get("gso", False),
    )
    if found.get("cert", "").strip():
        with open(SLIPSTREAM_CERT, "w") as f:
            f.write(found["cert"])
    service_stop()
    ok, msg = service_start()
    return ok, f"Switched to '{name}': {msg}"


def get_active_profile():
    """Get the currently active profile dict."""
    data = _load_profiles()
    for p in data["profiles"]:
        if p["name"] == data.get("active", ""):
            return p
    return copy.deepcopy(DEFAULT_PROFILE)


# ── Installation ────────────────────────────────────────────────

def install_online():
    """Download and install the slipstream-client binary."""
    url, err = get_download_url()
    if err:
        return False, err
    logger.info("Downloading slipstream-client from %s", url)
    _run(f'wget -q -O "{SLIPSTREAM_BIN}" "{url}"', timeout=120)
    if not os.path.isfile(SLIPSTREAM_BIN) or os.path.getsize(SLIPSTREAM_BIN) < 1000:
        return False, "Download failed or file too small"
    _run(f'chmod +x "{SLIPSTREAM_BIN}"')
    return True, "Installed successfully"


def install_from_bytes(data_bytes: bytes):
    """Install slipstream-client from uploaded binary data."""
    os.makedirs(os.path.dirname(SLIPSTREAM_BIN), exist_ok=True)
    with open(SLIPSTREAM_BIN, "wb") as f:
        f.write(data_bytes)
    _run(f'chmod +x "{SLIPSTREAM_BIN}"')
    return True, f"Saved {len(data_bytes)} bytes to {SLIPSTREAM_BIN}"


# ── Service ─────────────────────────────────────────────────────

def _write_init_script(domain, resolver, use_cert=False, congestion="dcubic", keep_alive=400, gso=False):
    """Generate /etc/init.d/slipstream for OpenWrt procd."""
    cert_arg = f'--cert "{SLIPSTREAM_CERT}"' if use_cert else ""
    gso_arg = "--gso true" if gso else ""
    script = f"""#!/bin/sh /etc/rc.common
# Slipstream DNS Tunnel client
START=99
STOP=10
USE_PROCD=1

start_service() {{
    procd_open_instance
    procd_set_param command {SLIPSTREAM_BIN} \\
        --resolver "{resolver}" \\
        --domain "{domain}" \\
        --tcp-listen-port {SLIPSTREAM_DEFAULT_PORT} \\
        --congestion-control {congestion} \\
        --keep-alive-interval {keep_alive} \\
        {cert_arg} {gso_arg}
    procd_set_param respawn 3600 5 5
    procd_set_param stdout 1
    procd_set_param stderr 1
    procd_close_instance
}}
"""
    with open(SLIPSTREAM_INITD, "w") as f:
        f.write(script)
    _run(f'chmod +x "{SLIPSTREAM_INITD}"')


def save_and_start(domain, resolver, cert="", congestion="dcubic", keep_alive=400, gso=False):
    """Quick save single config and start (backward compat)."""
    data = _load_profiles()
    found = False
    for p in data["profiles"]:
        if p["name"] == "Default":
            p.update(domain=domain, resolver=resolver, cert=cert,
                     congestion=congestion, keep_alive=keep_alive, gso=gso)
            found = True
            break
    if not found:
        data["profiles"].append({
            "name": "Default", "domain": domain, "resolver": resolver,
            "cert": cert, "congestion": congestion, "keep_alive": keep_alive,
            "gso": gso,
        })
    data["active"] = "Default"
    _save_profiles(data)
    _write_init_script(domain, resolver, bool(cert.strip()), congestion, keep_alive, gso)
    if cert.strip():
        with open(SLIPSTREAM_CERT, "w") as f:
            f.write(cert)
    elif os.path.isfile(SLIPSTREAM_CERT):
        os.remove(SLIPSTREAM_CERT)
    if not is_installed():
        ok, msg = install_online()
        if not ok:
            return False, msg
    service_stop()
    ok, msg = service_start()
    service_enable()
    return ok, msg


def service_start():
    """Start slipstream service."""
    if not is_installed():
        return False, "Binary not installed"
    _run(f"{SLIPSTREAM_INITD} start")
    return True, "Started"


def service_stop():
    """Stop slipstream service."""
    _run(f"{SLIPSTREAM_INITD} stop")
    _run("killall slipstream-client 2>/dev/null")
    return True, "Stopped"


def service_enable():
    """Enable slipstream service on boot."""
    _run(f"{SLIPSTREAM_INITD} enable")


def service_disable():
    """Disable slipstream service on boot."""
    _run(f"{SLIPSTREAM_INITD} disable")


def get_status():
    """Get current status of slipstream."""
    installed = is_installed()
    running = bool(_run("pgrep -x slipstream-client"))
    port_open = bool(_run(f"netstat -tlnp 2>/dev/null | grep ':{SLIPSTREAM_DEFAULT_PORT} '"))
    active = get_active_profile()
    arch = detect_arch()
    return {
        "installed": installed,
        "running": running,
        "port_open": port_open,
        "port": SLIPSTREAM_DEFAULT_PORT,
        "arch": arch,
        "domain": active.get("domain", ""),
        "resolver": active.get("resolver", ""),
        "has_cert": bool(active.get("cert", "").strip()),
        "congestion": active.get("congestion", "dcubic"),
        "active_profile": active.get("name", ""),
    }
