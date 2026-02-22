"""
PassWall 2 Telegram Bot - UCI Interface (Hardened)
Wraps OpenWrt's `uci` command-line tool for reading/writing PassWall 2 configuration.
All interactions with the router's config are done through this module.

Security: All dynamic inputs are shell-escaped via shlex.quote().
Performance: uci_batch() groups multiple set commands into one process.
"""
import subprocess
import shlex
import json
import re
import time
import logging

logger = logging.getLogger("passwall2_bot")

APPNAME = "passwall2"
SERVER_APPNAME = "passwall2_server"

# Pre-compiled patterns for uci_foreach (avoid re-compiling per call)
_UCI_PATTERNS = {}  # cache: config_name -> compiled regex


def _run(cmd, timeout=10) -> str:
    """Run a shell command and return stdout, stripping trailing whitespace.
    cmd can be a string (shell=True) or a list (shell=False, preferred).
    """
    try:
        if isinstance(cmd, list):
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout
            )
        else:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=timeout
            )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        logger.warning("Command timed out after %ds: %s", timeout, cmd if isinstance(cmd, str) else " ".join(cmd))
        return ""
    except Exception as e:
        logger.error("Command failed: %s -> %s", cmd, e)
        return ""


def _safe(value):
    """Shell-escape a value for safe interpolation."""
    return shlex.quote(str(value))


def uci_get(config, section, option):
    """Get a single UCI value. Returns empty string if not found."""
    return _run(["uci", "-q", "get", f"{config}.{section}.{option}"])


def uci_get_type(config, section, option, default=""):
    """Get a UCI value with a default."""
    val = uci_get(config, section, option)
    return val if val else default


def uci_set(config, section, option, value):
    """Set a UCI value (shell-safe)."""
    _run(["uci", "set", f"{config}.{section}.{option}={value}"])


def uci_del(config, section, option=None):
    """Delete a UCI option or section."""
    if option:
        _run(["uci", "-q", "delete", f"{config}.{section}.{option}"])
    else:
        _run(["uci", "-q", "delete", f"{config}.{section}"])


def uci_commit(config):
    """Commit UCI changes."""
    _run(["uci", "commit", config])


def uci_show(config, section=None):
    """Show raw UCI output for a config/section."""
    cmd = ["uci", "-q", "show", config]
    if section:
        cmd[-1] = f"{config}.{section}"
    return _run(cmd)


def uci_get_all(config, section):
    """Get all options for a section as a dictionary."""
    raw = _run(["uci", "-q", "show", f"{config}.{section}"])
    result = {}
    for line in raw.splitlines():
        if "=" not in line:
            continue
        key_part, _, value = line.partition("=")
        parts = key_part.split(".")
        if len(parts) >= 3:
            opt = parts[2]
            value = value.strip("'\"")
            result[opt] = value
    return result


def uci_foreach(config, section_type):
    """
    Iterate over all sections of a given type.
    Returns a list of dicts with '.name' and '.type' plus all options.
    """
    raw = _run(["uci", "-q", "show", config])
    sections = {}
    # Use cached compiled pattern per config name
    if config not in _UCI_PATTERNS:
        _UCI_PATTERNS[config] = re.compile(
            r'^' + re.escape(config) + r'\.([a-zA-Z0-9_]+)(?:\.([a-zA-Z0-9_]+))?=(.+)$')
    pattern = _UCI_PATTERNS[config]
    for line in raw.splitlines():
        m = pattern.match(line)
        if not m:
            continue
        sec_name, opt, value = m.group(1), m.group(2), m.group(3)
        value = value.strip("'\"")
        if opt is None:
            # Section type declaration
            if value == section_type:
                if sec_name not in sections:
                    sections[sec_name] = {".name": sec_name, ".type": value}
        else:
            if sec_name in sections:
                sections[sec_name][opt] = value
    # For text fields that may be multi-line, fetch full value via uci get
    multiline_fields = {"domain_list", "ip_list"}
    for sec in sections.values():
        for field in multiline_fields:
            if field in sec:
                try:
                    full_val = _run(["uci", "-q", "get", f"{config}.{sec['.name']}.{field}"])
                    if full_val:
                        sec[field] = full_val.strip()
                except Exception:
                    pass
    return list(sections.values())


def uci_batch(operations):
    """
    Execute multiple UCI operations in a single process via 'uci batch'.
    operations: list of strings like ["set passwall2.@global[0].node=abc", "commit passwall2"]
    This avoids spawning N shell processes for N changes (Fork Bomb fix).
    """
    if not operations:
        return
    batch_input = "\n".join(operations) + "\n"
    try:
        subprocess.run(
            ["uci", "batch"],
            input=batch_input,
            capture_output=True, text=True, timeout=15
        )
    except Exception as e:
        logger.error("uci batch failed: %s", e)


# ─── PassWall 2 Specific Helpers ────────────────────────────────

def get_global_enabled():
    """Check if PassWall 2 is globally enabled."""
    return uci_get(APPNAME, "@global[0]", "enabled") == "1"


def set_global_enabled(enabled):
    """Enable or disable PassWall 2 globally."""
    uci_set(APPNAME, "@global[0]", "enabled", "1" if enabled else "0")
    uci_commit(APPNAME)


def get_current_node():
    """Get the currently active global node ID."""
    return uci_get(APPNAME, "@global[0]", "node")


def set_current_node(node_id):
    """Set the active global node."""
    uci_set(APPNAME, "@global[0]", "node", node_id)
    uci_commit(APPNAME)


# Simple node cache to avoid repeated subprocess calls
_nodes_cache = None
_nodes_cache_time = 0
_NODES_CACHE_TTL = 2  # seconds

def get_all_nodes(use_cache=True):
    """Get all configured nodes with ALL their UCI fields plus normalized keys used by the bot."""
    global _nodes_cache, _nodes_cache_time
    now = time.time()
    if use_cache and _nodes_cache is not None and (now - _nodes_cache_time) < _NODES_CACHE_TTL:
        return _nodes_cache

    all_nodes = uci_foreach(APPNAME, "nodes")
    for n in all_nodes:
        # Modify in-place instead of dict(n) copy
        n["id"] = n.get(".name", "")
        n["remark"] = n.get("remarks", n.get("address", n.get(".name", "?")))
        
        ntype = n.get("type", "")
        if ntype == "Xray":
            n.setdefault("address", n.get("xray_address", ""))
            n.setdefault("port", n.get("xray_port", ""))
            n.setdefault("protocol", n.get("xray_protocol", ""))
        elif ntype == "sing-box":
            n.setdefault("address", n.get("singbox_address", ""))
            n.setdefault("port", n.get("singbox_port", ""))
            n.setdefault("protocol", n.get("singbox_protocol", ""))
        elif ntype == "Hysteria2":
            n.setdefault("address", n.get("hysteria2_address", ""))
            n.setdefault("port", n.get("hysteria2_port", ""))
            n.setdefault("protocol", "hysteria2")
            
        for k in ["type", "protocol", "group", "address", "port"]:
            n.setdefault(k, "")

    _nodes_cache = all_nodes
    _nodes_cache_time = now
    return all_nodes


def get_socks_list():
    """Get all SOCKS proxy port configs."""
    return uci_foreach(APPNAME, "socks")


def get_acl_rules():
    """Get all ACL rules."""
    return uci_foreach(APPNAME, "acl_rule")


def get_shunt_rules():
    """Get all shunt routing rules."""
    return uci_foreach(APPNAME, "shunt_rules")


def get_haproxy_configs():
    """Get all HAProxy configurations."""
    return uci_foreach(APPNAME, "haproxy_config")


def get_subscribe_list():
    """Get all subscription URLs."""
    return uci_foreach(APPNAME, "subscribe_list")


def get_socks_list():
    """Get all SOCKS proxy entries."""
    return uci_foreach(APPNAME, "socks")


def get_haproxy_list():
    """Get all HAProxy load balancing entries."""
    return uci_foreach(APPNAME, "haproxy_config")


def set_acl_enabled(acl_name, enabled):
    """Enable/disable an ACL rule by name."""
    import re
    if not re.match(r'^[a-zA-Z0-9_]+$', str(acl_name)):
        return False
    uci_set(APPNAME, acl_name, "enabled", "1" if enabled else "0")
    uci_commit(APPNAME)
    return True


def add_node_from_url(share_url):
    """Add a node from a share URL (vless://, vmess://, ss://, trojan://, etc).
    Uses PassWall 2's built-in subscribe parser if available."""
    result = _run(["/usr/share/passwall2/subscribe.sh", "add", str(share_url)], timeout=10)
    return bool(result and "error" not in result.lower())


def add_socks_node(remark, address="127.0.0.1", port=7000, set_active=False):
    """Create or update a Socks5 node for DNS tunnel usage.
    Returns the node ID on success, empty string on failure."""
    # Check if a node with same remark already exists
    nodes = get_all_nodes()
    existing = None
    for n in nodes:
        if n.get("remark", "") == remark or n.get("remarks", "") == remark:
            existing = n.get("id", n.get(".name", ""))
            break

    if existing:
        # Update existing node
        uci_batch([
            f"set {APPNAME}.{existing}.type=Socks",
            f"set {APPNAME}.{existing}.protocol=socks",
            f"set {APPNAME}.{existing}.address={address}",
            f"set {APPNAME}.{existing}.port={port}",
            f"set {APPNAME}.{existing}.remark={remark}",
            f"commit {APPNAME}",
        ])
        node_id = existing
    else:
        # Create new node
        result = _run(["uci", "add", APPNAME, "nodes"])
        if not result:
            return ""
        node_id = result.strip()
        uci_batch([
            f"set {APPNAME}.{node_id}.type=Socks",
            f"set {APPNAME}.{node_id}.protocol=socks",
            f"set {APPNAME}.{node_id}.address={address}",
            f"set {APPNAME}.{node_id}.port={port}",
            f"set {APPNAME}.{node_id}.remark={remark}",
            f"commit {APPNAME}",
        ])

    if set_active and node_id:
        set_current_node(node_id)
        service_restart()

    return node_id


def edit_node(node_id, fields):
    """Edit multiple UCI fields for a node.
    fields: dict of {option: value} pairs.
    Returns True on success."""
    import re
    if not re.match(r'^[a-zA-Z0-9_]+$', str(node_id)):
        return False

    # Whitelist of editable node fields
    ALLOWED = {
        "remarks", "type", "protocol", "address", "port", "group",
        "uuid", "password", "security", "encryption", "flow",
        "transport", "tls", "tls_serverName", "tls_allowInsecure",
        "alpn", "fingerprint", "utls", "reality",
        "reality_publicKey", "reality_shortId", "reality_spiderX",
        "ws_host", "ws_path", "h2_host", "h2_path",
        "grpc_serviceName", "grpc_mode",
        "tcp_guise", "tcp_guise_http_host", "tcp_guise_http_path",
        "mkcp_guise", "mkcp_seed",
        "xhttp_host", "xhttp_path", "xhttp_mode",
        "httpupgrade_host", "httpupgrade_path",
        "method", "ss_method", "plugin", "plugin_opts",
        "obfs", "obfs_param", "protocol_param",
        "hysteria2_auth_password", "hysteria2_obfs_type", "hysteria2_obfs_password",
        "hysteria2_hop",
        "tuic_congestion_control", "tuic_udp_relay_mode", "tuic_alpn",
        "ech", "ech_config",
        # Sing-box prefixed fields
        "singbox_protocol", "singbox_address", "singbox_port",
        "singbox_uuid", "singbox_password", "singbox_transport",
        "singbox_tls", "singbox_tls_serverName",
        # Xray prefixed fields
        "xray_protocol", "xray_address", "xray_port",
        "xray_uuid", "xray_password", "xray_transport",
        "xray_tls", "xray_tls_serverName",
    }

    ops = []
    for key, value in fields.items():
        if key in ALLOWED:
            ops.append(f"set {APPNAME}.{node_id}.{key}={value}")
    if ops:
        ops.append(f"commit {APPNAME}")
        uci_batch(ops)
        return True
    return False


def get_server_users():
    """Get all server-side users (inbound nodes)."""
    return uci_foreach(SERVER_APPNAME, "user")


# ─── DNS Settings ───────────────────────────────────────────────

def get_dns_settings():
    """Get the current DNS configuration as a dict."""
    return {
        "direct_dns_query_strategy": uci_get_type(APPNAME, "@global[0]", "direct_dns_query_strategy", "UseIP"),
        "remote_dns_protocol": uci_get_type(APPNAME, "@global[0]", "remote_dns_protocol", "tcp"),
        "remote_dns": uci_get_type(APPNAME, "@global[0]", "remote_dns", "1.1.1.1"),
        "remote_dns_doh": uci_get_type(APPNAME, "@global[0]", "remote_dns_doh", "https://1.1.1.1/dns-query"),
        "remote_dns_client_ip": uci_get_type(APPNAME, "@global[0]", "remote_dns_client_ip", ""),
        "remote_dns_detour": uci_get_type(APPNAME, "@global[0]", "remote_dns_detour", "remote"),
        "remote_fakedns": uci_get_type(APPNAME, "@global[0]", "remote_fakedns", "0"),
        "remote_dns_query_strategy": uci_get_type(APPNAME, "@global[0]", "remote_dns_query_strategy", "UseIPv4"),
        "dns_hosts": uci_get_type(APPNAME, "@global[0]", "dns_hosts", ""),
        "dns_redirect": uci_get_type(APPNAME, "@global[0]", "dns_redirect", "1"),
    }


def set_dns_option(option, value):
    """Set a single DNS option."""
    uci_set(APPNAME, "@global[0]", option, value)
    uci_commit(APPNAME)


# ─── Service Control ────────────────────────────────────────────

def service_start():
    """Start PassWall 2 service."""
    set_global_enabled(True)
    return _run(["/etc/init.d/passwall2", "restart"], timeout=30)


def service_stop():
    """Stop PassWall 2 service."""
    set_global_enabled(False)
    return _run(["/etc/init.d/passwall2", "stop"], timeout=30)


def service_restart():
    """Restart PassWall 2 service."""
    return _run(["/etc/init.d/passwall2", "restart"], timeout=30)


def service_status():
    """Check if PassWall 2 processes are running."""
    result = _run("busybox top -bn1 | grep -v grep | grep '/tmp/etc/passwall2/bin/'")
    return len(result.strip()) > 0


def server_service_status():
    """Check if PassWall 2 Server processes are running."""
    result = _run("busybox top -bn1 | grep -v grep | grep '/tmp/etc/passwall2_server/bin/'")
    return len(result.strip()) > 0


# ─── Subscriptions ──────────────────────────────────────────────

def subscribe_update_all():
    """Trigger a manual subscription update for all subscriptions."""
    return _run(["lua", "/usr/share/passwall2/subscribe.lua", "start"], timeout=60)


# ─── Rules ──────────────────────────────────────────────────────

def update_rules(update_type="all"):
    """Trigger GeoIP/Geosite rule updates."""
    _run(f"lua /usr/share/passwall2/rule_update.lua log {_safe(update_type)} > /dev/null 2>&1 &")
    return True


# ─── Logs ───────────────────────────────────────────────────────

def get_log(lines=50):
    """Get the last N lines of the PassWall 2 log."""
    return _run(["tail", "-n", str(lines), "/tmp/log/passwall2.log"])


def get_server_log(lines=50):
    """Get the last N lines of the server log."""
    return _run(["tail", "-n", str(lines), "/tmp/log/passwall2_server.log"])


def clear_log():
    """Clear the PassWall 2 log."""
    try:
        with open("/tmp/log/passwall2.log", "w") as f:
            f.write("")
    except Exception:
        pass


# ─── Ping & Test ────────────────────────────────────────────────

def ping_node(address, port=None, ping_type="icmp"):
    """Ping a node address. Returns latency string or empty."""
    import re
    # Validate address to prevent shell injection (only allow alphanumeric, dots, colons, hyphens)
    if not re.match(r'^[a-zA-Z0-9.\-:]+$', str(address)):
        return ""
    if port and not re.match(r'^\d+$', str(port)):
        return ""

    if ping_type == "tcping" and port:
        result = _run(["tcping", "-q", "-c", "1", "-i", "1", "-t", "2", "-p", str(port), str(address)], timeout=5)
    else:
        result = _run(["ping", "-c", "1", "-W", "1", str(address)], timeout=5)

    # Extract latency from output
    match = re.search(r'time[=<](\d+(?:\.\d+)?)', result)
    return match.group(1) if match else ""


def urltest_node(node_id):
    """URL test a node. Returns latency string."""
    import re
    # Validate node_id format
    if not re.match(r'^[a-zA-Z0-9_]+$', str(node_id)):
        return ""
    return _run(["/usr/share/passwall2/test.sh", "url_test_node", str(node_id), "urltest_node"], timeout=15)


# ─── GeoView ────────────────────────────────────────────────────

def geo_lookup(value):
    """Lookup an IP/Domain in the GeoIP/Geosite databases."""
    import re
    # Validate input: allow alphanumeric, dots, colons, hyphens
    if not re.match(r'^[a-zA-Z0-9.\-:]+$', str(value)):
        return "Invalid input format."

    geo_dir = uci_get_type(APPNAME, "@global_rules[0]", "v2ray_location_asset", "/usr/share/v2ray/")
    geo_dir = geo_dir.rstrip("/")

    try:
        import ipaddress
        ipaddress.ip_address(value)
        geo_type = "geoip"
        file_path = f"{geo_dir}/geoip.dat"
    except ValueError:
        geo_type = "geosite"
        file_path = f"{geo_dir}/geosite.dat"

    result = _run([
        "geoview", "-type", geo_type, "-action", "lookup",
        "-input", file_path, "-value", value, "-lowmem=true"
    ], timeout=15)
    return result if result else "No matches found."


# ─── Backup / Restore ──────────────────────────────────────────

def create_backup():
    """Create a tar.gz backup and return the file path."""
    import time
    date_str = time.strftime("%y%m%d%H%M")
    tar_file = f"/tmp/passwall2-{date_str}-backup.tar.gz"
    files = [
        "/etc/config/passwall2",
        "/etc/config/passwall2_server",
        "/usr/share/passwall2/domains_excluded",
    ]
    _run(["tar", "-czf", tar_file] + files, timeout=15)
    return tar_file


def restore_backup(file_path):
    """Restore a backup from a tar.gz file."""
    import os
    import re
    # Validate file_path to prevent path traversal
    basename = os.path.basename(file_path)
    if not re.match(r'^passwall2-\d+-backup\.tar\.gz$', basename):
        logger.warning("Rejected suspicious backup filename: %s", basename)
        return False

    temp_dir = "/tmp/passwall2_bak"
    _run(["mkdir", "-p", temp_dir])
    _run(["tar", "-xzf", file_path, "-C", temp_dir], timeout=15)
    for backup_file in ["/etc/config/passwall2", "/etc/config/passwall2_server", "/usr/share/passwall2/domains_excluded"]:
        temp_file = f"{temp_dir}{backup_file}"
        _run(f"[ -f {_safe(temp_file)} ] && cp -f {_safe(temp_file)} {_safe(backup_file)}")
    _run(["rm", "-rf", temp_dir])
    _run(["rm", "-f", file_path])
    _run(["/etc/init.d/passwall2", "restart"], timeout=30)
    _run(["/etc/init.d/passwall2_server", "restart"], timeout=30)
    return True


# ─── Flush IPSET/NFTSET ────────────────────────────────────────

def flush_sets():
    """Flush IPSET/NFTSET caches (equivalent to 'Clear IPSET' in LuCI)."""
    use_nft = uci_get_type(APPNAME, "@global_forwarding[0]", "use_nft", "0")
    if use_nft == "1":
        _run(["nft", "flush", "set", "inet", "passwall2", "passwall2_vps"])
        _run(["nft", "flush", "set", "inet", "passwall2", "passwall2_vps6"])
    else:
        _run(["ipset", "flush", "passwall2_vps"])
        _run(["ipset", "flush", "passwall2_vps6"])
    service_restart()
    return True


# ─── Forwarding Settings ───────────────────────────────────────

def get_forwarding_settings():
    """Get all forwarding / firewall settings."""
    return {
        "tcp_no_redir_ports": uci_get_type(APPNAME, "@global_forwarding[0]", "tcp_no_redir_ports", ""),
        "udp_no_redir_ports": uci_get_type(APPNAME, "@global_forwarding[0]", "udp_no_redir_ports", ""),
        "tcp_redir_ports": uci_get_type(APPNAME, "@global_forwarding[0]", "tcp_redir_ports", "1:65535"),
        "udp_redir_ports": uci_get_type(APPNAME, "@global_forwarding[0]", "udp_redir_ports", "1:65535"),
        "use_nft": uci_get_type(APPNAME, "@global_forwarding[0]", "use_nft", "0"),
        "tcp_proxy_way": uci_get_type(APPNAME, "@global_forwarding[0]", "tcp_proxy_way", "redirect"),
        "ipv6_tproxy": uci_get_type(APPNAME, "@global_forwarding[0]", "ipv6_tproxy", "0"),
        "sniffing": uci_get_type(APPNAME, "@global_forwarding[0]", "sniffing", "1"),
        "route_only": uci_get_type(APPNAME, "@global_forwarding[0]", "route_only", "0"),
    }


def set_forwarding_option(option, value):
    """Set a single forwarding option."""
    uci_set(APPNAME, "@global_forwarding[0]", option, value)
    uci_commit(APPNAME)


# ─── Delay Settings ───────────────────────────────────────────

def get_delay_settings():
    """Get daemon / delay / automation settings."""
    return {
        "enabled": uci_get_type(APPNAME, "@global_delay[0]", "start_daemon", "0"),
        "start_delay": uci_get_type(APPNAME, "@global_delay[0]", "start_delay", "60"),
        "auto_stop": uci_get_type(APPNAME, "@global_delay[0]", "auto_stop", "0"),
        "auto_start": uci_get_type(APPNAME, "@global_delay[0]", "auto_start", "0"),
        "auto_restart": uci_get_type(APPNAME, "@global_delay[0]", "auto_restart", "0"),
    }


def set_delay_option(option, value):
    """Set a single delay/automation option."""
    uci_set(APPNAME, "@global_delay[0]", option, value)
    uci_commit(APPNAME)


# ─── Node Detail Management ───────────────────────────────────

def get_node_detail(node_id):
    """Get full configuration for a specific node."""
    import re
    if not re.match(r'^[a-zA-Z0-9_]+$', str(node_id)):
        return None
    return uci_get_all(APPNAME, node_id)


def delete_node(node_id):
    """Delete a node section from UCI."""
    import re
    if not re.match(r'^[a-zA-Z0-9_]+$', str(node_id)):
        return False
    uci_del(APPNAME, node_id)
    uci_commit(APPNAME)
    return True


def copy_node(node_id):
    """Duplicate a node: read all fields, create a new section with same data."""
    import re
    if not re.match(r'^[a-zA-Z0-9_]+$', str(node_id)):
        return None
    original = uci_get_all(APPNAME, node_id)
    if not original:
        return None
    # Add new section of type 'nodes'
    new_name = _run(["uci", "add", APPNAME, "nodes"]).strip()
    if not new_name:
        return None
    ops = []
    skip_keys = {".name", ".type", ".index", ".anonymous"}
    for key, val in original.items():
        if key in skip_keys:
            continue
        if key == "remarks":
            val = f"{val} (copy)"
        ops.append(f"set {APPNAME}.{new_name}.{key}={val}")
    ops.append(f"commit {APPNAME}")
    uci_batch(ops)
    return new_name


# ─── Socks Config ─────────────────────────────────────────────

def get_socks_config():
    """Get Socks main switch and all socks entries."""
    enabled = uci_get_type(APPNAME, "@global[0]", "socks_enabled", "0")
    entries = uci_foreach(APPNAME, "socks")
    result = []
    for s in entries:
        result.append({
            "id": s.get(".name", ""),
            "enabled": s.get("enabled", "0"),
            "node": s.get("node", ""),
            "port": s.get("port", ""),
            "http_port": s.get("http_port", "0"),
        })
    return {"socks_enabled": enabled, "entries": result}


def set_socks_enabled(enabled):
    """Enable or disable the global Socks switch."""
    uci_set(APPNAME, "@global[0]", "socks_enabled", "1" if enabled else "0")
    uci_commit(APPNAME)


# ─── Shunt Rule Detail ────────────────────────────────────────

def get_shunt_rule_detail(rule_name):
    """Get full details of a specific shunt rule (domain/IP lists, etc)."""
    import re
    if not re.match(r'^[a-zA-Z0-9_]+$', str(rule_name)):
        return None
    return uci_get_all(APPNAME, rule_name)


def set_shunt_rule_field(rule_name, field, value):
    """Update a field in a shunt rule (e.g. domain_list, ip_list)."""
    import re
    if not re.match(r'^[a-zA-Z0-9_]+$', str(rule_name)):
        return False
    uci_set(APPNAME, rule_name, field, value)
    uci_commit(APPNAME)
    return True


# ─── Global Advanced Options ──────────────────────────────────

def get_global_options():
    """Get advanced global options (localhost_proxy, client_proxy, etc)."""
    return {
        "localhost_proxy": uci_get_type(APPNAME, "@global[0]", "localhost_proxy", "1"),
        "client_proxy": uci_get_type(APPNAME, "@global[0]", "client_proxy", "1"),
        "node_socks_port": uci_get_type(APPNAME, "@global[0]", "node_socks_port", "1070"),
        "node_socks_bind_local": uci_get_type(APPNAME, "@global[0]", "node_socks_bind_local", "1"),
        "direct_dns_ipset": uci_get_type(APPNAME, "@global[0]", "write_ipset_direct", "1"),
    }


def set_global_option(option, value):
    """Set a single global option."""
    uci_set(APPNAME, "@global[0]", option, value)
    uci_commit(APPNAME)

