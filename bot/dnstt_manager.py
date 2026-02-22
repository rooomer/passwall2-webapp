"""
DNSTT DNS Tunnel Manager
Handles downloading, installing, configuring, and managing the
dnstt-client daemon on OpenWrt routers.
Supports multiple named config profiles with switching.
"""
import os
import json
import subprocess
import logging
import copy

logger = logging.getLogger(__name__)

DNSTT_BIN = "/usr/bin/dnstt-client"
DNSTT_CONF_DIR = "/etc/dnstt"
DNSTT_CONF = os.path.join(DNSTT_CONF_DIR, "profiles.json")
DNSTT_INITD = "/etc/init.d/dnstt"
DNSTT_DEFAULT_PORT = 7000

GITHUB_RELEASE_URL = (
    "https://github.com/rooomer/passwall2-webapp/releases/download/"
    "dnstt-latest"
)

ARCH_MAP = {
    "x86_64": "dnstt-client-linux-amd64",
    "aarch64": "dnstt-client-linux-arm64",
    "armv7l": "dnstt-client-linux-armv7",
}

DEFAULT_PROFILE = {
    "name": "Default",
    "domain": "",
    "pubkey": "",
    "resolver": "",
    "listen_port": DNSTT_DEFAULT_PORT,
    "transport": "udp",
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
    """Get the download URL for the correct binary."""
    arch = detect_arch()
    filename = ARCH_MAP.get(arch)
    if not filename:
        return None, f"Unsupported architecture: {arch}"
    url = f"{GITHUB_RELEASE_URL}/{filename}"
    return url, None


def is_installed():
    """Check if dnstt-client binary exists."""
    return os.path.isfile(DNSTT_BIN)


# ── Profile Management ─────────────────────────────────────────

def _load_profiles() -> dict:
    """Load all profiles from disk. Always returns {active: str, profiles: list}."""
    if os.path.isfile(DNSTT_CONF):
        try:
            with open(DNSTT_CONF) as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("profiles"), list):
                return {"active": str(data.get("active", "")), "profiles": data["profiles"]}
        except Exception:
            pass
    return {"active": "", "profiles": []}


def _save_profiles(data):
    """Save profiles to disk."""
    os.makedirs(DNSTT_CONF_DIR, exist_ok=True)
    with open(DNSTT_CONF, "w") as f:
        json.dump(data, f, indent=2)


def get_profiles():
    """Get all profiles and which is active."""
    data = _load_profiles()
    return {
        "active": data.get("active", ""),
        "profiles": data.get("profiles", []),
    }


def add_profile(name, domain, pubkey, resolver="", listen_port=DNSTT_DEFAULT_PORT, transport="udp"):
    """Add a new profile."""
    data = _load_profiles()
    profile = {
        "name": name,
        "domain": domain,
        "pubkey": pubkey,
        "resolver": resolver,
        "listen_port": listen_port,
        "transport": transport,
    }
    profiles_list: list = data["profiles"]
    profiles_list.append(profile)
    if not data["active"]:
        data["active"] = name
    _save_profiles(data)
    return True, f"Profile '{name}' added"


def edit_profile(old_name, name, domain, pubkey, resolver="", listen_port=DNSTT_DEFAULT_PORT, transport="udp"):
    """Edit an existing profile."""
    data = _load_profiles()
    profiles_list: list = data["profiles"]
    for p in profiles_list:
        if isinstance(p, dict) and p.get("name") == old_name:
            p["name"] = name
            p["domain"] = domain
            p["pubkey"] = pubkey
            p["resolver"] = resolver
            p["listen_port"] = listen_port
            p["transport"] = transport
            if data["active"] == old_name:
                data["active"] = name
            _save_profiles(data)
            return True, f"Profile '{name}' updated"
    return False, f"Profile '{old_name}' not found"


def delete_profile(name):
    """Delete a profile."""
    data = _load_profiles()
    profiles_list: list = data["profiles"]
    data["profiles"] = [p for p in profiles_list if isinstance(p, dict) and p.get("name") != name]
    if data["active"] == name:
        remaining = data["profiles"]
        data["active"] = remaining[0]["name"] if remaining else ""
    _save_profiles(data)
    return True, f"Profile '{name}' deleted"


def switch_profile(name):
    """Switch active profile and restart service."""
    data = _load_profiles()
    profiles_list: list = data["profiles"]
    found = any(isinstance(p, dict) and p.get("name") == name for p in profiles_list)
    if not found:
        return False, f"Profile '{name}' not found"
    data["active"] = name
    _save_profiles(data)
    # Apply the profile
    for p in data["profiles"]:
        if p["name"] == name:
            _write_init_script(
                p["domain"], p["pubkey"], p.get("resolver", ""),
                p.get("listen_port", DNSTT_DEFAULT_PORT), p.get("transport", "udp")
            )
            break
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
    """Download and install the dnstt-client binary."""
    url, err = get_download_url()
    if err:
        return False, err
    logger.info("Downloading dnstt-client from %s", url)
    _run(f'wget -q -O "{DNSTT_BIN}" "{url}"', timeout=120)
    if not os.path.isfile(DNSTT_BIN) or os.path.getsize(DNSTT_BIN) < 1000:
        return False, "Download failed or file too small"
    _run(f'chmod +x "{DNSTT_BIN}"')
    return True, "Installed successfully"


def install_from_bytes(data_bytes: bytes):
    """Install dnstt-client from uploaded binary data."""
    os.makedirs(os.path.dirname(DNSTT_BIN), exist_ok=True)
    with open(DNSTT_BIN, "wb") as f:
        f.write(data_bytes)
    _run(f'chmod +x "{DNSTT_BIN}"')
    return True, f"Saved {len(data_bytes)} bytes to {DNSTT_BIN}"


# ── Service ─────────────────────────────────────────────────────

def _write_init_script(domain, pubkey, resolver="", listen_port=DNSTT_DEFAULT_PORT, transport="udp"):
    """Generate /etc/init.d/dnstt for OpenWrt procd."""
    if transport == "doh" and resolver:
        resolver_arg = f'-doh "{resolver}"'
    elif transport == "dot" and resolver:
        resolver_arg = f'-dot "{resolver}:853"'
    elif resolver:
        resolver_arg = f'-udp "{resolver}:53"'
    else:
        resolver_arg = '-udp "8.8.8.8:53"'

    script = f"""#!/bin/sh /etc/rc.common
# DNSTT DNS Tunnel client
START=99
STOP=10
USE_PROCD=1

start_service() {{
    procd_open_instance
    procd_set_param command {DNSTT_BIN} \\
        {resolver_arg} \\
        -domain "{domain}" \\
        -pubkey-hex "{pubkey}" \\
        127.0.0.1:{listen_port}
    procd_set_param respawn 3600 5 5
    procd_set_param stdout 1
    procd_set_param stderr 1
    procd_close_instance
}}
"""
    with open(DNSTT_INITD, "w") as f:
        f.write(script)
    _run(f'chmod +x "{DNSTT_INITD}"')


def save_and_start(domain, pubkey, resolver="", listen_port=DNSTT_DEFAULT_PORT, transport="udp"):
    """Quick save single config and start (backward compat)."""
    data = _load_profiles()
    # Update or create "Default" profile
    found = False
    for p in data["profiles"]:
        if p["name"] == "Default":
            p.update(domain=domain, pubkey=pubkey, resolver=resolver,
                     listen_port=listen_port, transport=transport)
            found = True
            break
    if not found:
        data["profiles"].append({
            "name": "Default", "domain": domain, "pubkey": pubkey,
            "resolver": resolver, "listen_port": listen_port, "transport": transport,
        })
    data["active"] = "Default"
    _save_profiles(data)
    _write_init_script(domain, pubkey, resolver, listen_port, transport)
    if not is_installed():
        ok, msg = install_online()
        if not ok:
            return False, msg
    service_stop()
    ok, msg = service_start()
    service_enable()
    return ok, msg


def service_start():
    """Start dnstt service."""
    if not is_installed():
        return False, "Binary not installed"
    _run(f"{DNSTT_INITD} start")
    return True, "Started"


def service_stop():
    """Stop dnstt service."""
    _run(f"{DNSTT_INITD} stop")
    _run("killall dnstt-client 2>/dev/null")
    return True, "Stopped"


def service_enable():
    """Enable dnstt service on boot."""
    _run(f"{DNSTT_INITD} enable")


def service_disable():
    """Disable dnstt service on boot."""
    _run(f"{DNSTT_INITD} disable")


def get_status():
    """Get current status of dnstt."""
    installed = is_installed()
    running = bool(_run("pgrep -x dnstt-client"))
    active = get_active_profile()
    arch = detect_arch()
    return {
        "installed": installed,
        "running": running,
        "port": active.get("listen_port", DNSTT_DEFAULT_PORT),
        "arch": arch,
        "domain": active.get("domain", ""),
        "pubkey": active.get("pubkey", ""),
        "resolver": active.get("resolver", ""),
        "transport": active.get("transport", "udp"),
        "active_profile": active.get("name", ""),
    }
