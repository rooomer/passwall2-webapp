"""
PassWall 2 Telegram Bot - Menu Handlers
Implements the full Inline Keyboard navigation tree and callback routing.
Every menu is a function that returns (text, reply_markup).
"""
import json
import logging
from . import uci_wrapper as uci
from . import telegram_api as tg

logger = logging.getLogger("passwall2_bot")

# ─── Emoji Constants ────────────────────────────────────────────
E_ON = "🟢"
E_OFF = "🔴"
E_NODE = "🛡️"
E_RULES = "🌐"
E_TOOLS = "🔧"
E_DNS = "📡"
E_ACL = "🚦"
E_SHUNT = "📝"
E_SOCKS = "🧦"
E_SERVER = "📥"
E_SUB = "🔄"
E_HAP = "⚖️"
E_LOG = "📄"
E_BACKUP = "📦"
E_PING = "🚀"
E_GEO = "🌍"
E_UPDATE = "✨"
E_BACK = "◀️"
E_HOME = "🏠"


# ═══════════════════════════════════════════════════════════════
#  MAIN DASHBOARD
# ═══════════════════════════════════════════════════════════════

def menu_main():
    """Main Dashboard showing global status."""
    running = uci.service_status()
    enabled = uci.get_global_enabled()
    node_id = uci.get_current_node()
    node_name = "N/A"
    if node_id:
        nodes = uci.get_all_nodes()
        for n in nodes:
            if n["id"] == node_id:
                node_name = n["remark"]
                break

    status_icon = E_ON if running else E_OFF
    status_text = "Running" if running else "Stopped"
    enabled_text = "Enabled" if enabled else "Disabled"

    text = (
        f"<b>{E_HOME} PassWall 2 Control Panel</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Status: {status_icon} <b>{status_text}</b>\n"
        f"Config: <b>{enabled_text}</b>\n"
        f"Active Node: <code>{node_name}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )

    toggle_text = f"{E_OFF} Stop" if running else f"{E_ON} Start"
    buttons = [
        [(toggle_text, "act:toggle"), ("🔁 Restart", "act:restart")],
        [(f"{E_NODE} Nodes", "menu:nodes"), (f"{E_RULES} Rules", "menu:rules")],
        [(f"{E_TOOLS} Tools", "menu:tools"), (f"🖥️ Web Panel", "menu:webapp")],
        [("⚙️ Global Options", "menu:global_options")],
    ]
    return text, tg.make_inline_keyboard(buttons)


# ═══════════════════════════════════════════════════════════════
#  NODES MENU
# ═══════════════════════════════════════════════════════════════

def menu_nodes():
    """Nodes sub-menu: TCP/UDP switching, SOCKS, Server-side."""
    text = (
        f"<b>{E_NODE} Node Management</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Select a category:"
    )
    buttons = [
        [("🔀 Switch Main Node", "menu:switch_node")],
        [(f"{E_SOCKS} SOCKS Servers", "menu:socks"), ("🧦 Socks Config", "menu:socks_config")],
        [(f"{E_SERVER} Server-Side (Inbound)", "menu:server")],
        [(f"{E_BACK} Back", "menu:main")],
    ]
    return text, tg.make_inline_keyboard(buttons)


def menu_switch_node(page=0):
    """List all nodes for switching the active global node."""
    nodes: list = uci.get_all_nodes()
    current = uci.get_current_node()
    PAGE_SIZE = 8

    total_pages = max(1, (len(nodes) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, len(nodes))

    text = (
        f"<b>🔀 Select Active Node</b> (Page {page+1}/{total_pages})\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Current: <code>{current}</code>\n"
        f"Tap a node to activate it:"
    )

    buttons = []
    for n in nodes[start:end]:
        marker = "✅ " if n["id"] == current else ""
        label = f"{marker}{n['remark']} [{n['type']}]"
        if len(label) > 40:
            label = label[:37] + "..."
        buttons.append([(label, f"node:set:{n['id']}")])

    # Pagination
    nav_row = []
    if page > 0:
        nav_row.append(("⬅️ Prev", f"node:page:{page-1}"))
    if page < total_pages - 1:
        nav_row.append(("Next ➡️", f"node:page:{page+1}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append([(f"{E_BACK} Back", "menu:nodes")])
    return text, tg.make_inline_keyboard(buttons)


def menu_socks():
    """List SOCKS proxy ports."""
    socks_list = uci.get_socks_list()
    text = (
        f"<b>{E_SOCKS} SOCKS Server Ports</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
    )
    if not socks_list:
        text += "No SOCKS ports configured."
    else:
        for i, s in enumerate(socks_list):
            enabled = s.get("enabled", "0") == "1"
            port = s.get("port", "?")
            node = s.get("node", "N/A")
            icon = E_ON if enabled else E_OFF
            text += f"{icon} Port {port} → Node: <code>{node}</code>\n"

    buttons = [[(f"{E_BACK} Back", "menu:nodes")]]
    return text, tg.make_inline_keyboard(buttons)


def menu_server():
    """Server-side (inbound) nodes."""
    users = uci.get_server_users()
    server_enabled = uci.uci_get(uci.SERVER_APPNAME, "global", "enable") == "1"
    status_icon = E_ON if server_enabled else E_OFF

    text = (
        f"<b>{E_SERVER} Server-Side (Inbound Nodes)</b>\n"
        f"Server Status: {status_icon}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
    )
    if not users:
        text += "No server users configured."
    else:
        for u in users:
            enabled = u.get("enable", "0") == "1"
            remarks = u.get("remarks", u[".name"])
            utype = u.get("type", "?")
            protocol = u.get("protocol", "")
            port = u.get("port", "?")
            icon = E_ON if enabled else E_OFF
            text += f"{icon} {remarks} ({utype} {protocol}) :{port}\n"

    buttons = [[(f"{E_BACK} Back", "menu:nodes")]]
    return text, tg.make_inline_keyboard(buttons)


# ═══════════════════════════════════════════════════════════════
#  RULES MENU (ACL, Shunt, DNS)
# ═══════════════════════════════════════════════════════════════

def menu_rules():
    """Rules sub-menu: ACL, Shunt, DNS."""
    text = (
        f"<b>{E_RULES} Rules & Routing</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Manage access control, routing rules, and DNS:"
    )
    buttons = [
        [(f"{E_ACL} ACL Manager", "menu:acl")],
        [(f"{E_SHUNT} Shunt / Routing", "menu:shunt")],
        [(f"{E_DNS} DNS Settings", "menu:dns")],
        [(f"{E_BACK} Back", "menu:main")],
    ]
    return text, tg.make_inline_keyboard(buttons)


def menu_acl():
    """ACL rules list."""
    rules = uci.get_acl_rules()
    text = (
        f"<b>{E_ACL} Access Control List</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
    )
    if not rules:
        text += "No ACL rules configured."
    else:
        for r in rules:
            enabled = r.get("enabled", "1") == "1"
            remarks = r.get("remarks", r[".name"])
            sources = r.get("sources", "all")
            node = r.get("node", "global")
            icon = E_ON if enabled else E_OFF
            text += f"{icon} <b>{remarks}</b>\n   Source: {sources} → Node: <code>{node}</code>\n"

    buttons = [[(f"{E_BACK} Back", "menu:rules")]]
    return text, tg.make_inline_keyboard(buttons)


def menu_shunt():
    """Shunt routing rules list."""
    rules = uci.get_shunt_rules()
    text = (
        f"<b>{E_SHUNT} Shunt / Routing Rules</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
    )
    if not rules:
        text += "No shunt rules configured."
    else:
        for r in rules:
            remarks = r.get("remarks", r[".name"])
            text += f"📌 <b>{remarks}</b>\n"

    buttons = [[(f"{E_BACK} Back", "menu:rules")]]
    return text, tg.make_inline_keyboard(buttons)


# ═══════════════════════════════════════════════════════════════
#  DNS MENU (Deep)
# ═══════════════════════════════════════════════════════════════

DNS_PRESETS_TCP = [
    ("1.1.1.1", "CloudFlare"),
    ("1.1.1.2", "CloudFlare-Security"),
    ("8.8.4.4", "Google"),
    ("8.8.8.8", "Google"),
    ("9.9.9.9", "Quad9"),
    ("149.112.112.112", "Quad9"),
    ("208.67.220.220", "OpenDNS"),
    ("208.67.222.222", "OpenDNS"),
]

DNS_PRESETS_DOH = [
    ("https://1.1.1.1/dns-query", "CloudFlare"),
    ("https://1.1.1.2/dns-query", "CloudFlare-Security"),
    ("https://8.8.4.4/dns-query", "Google 8844"),
    ("https://8.8.8.8/dns-query", "Google 8888"),
    ("https://9.9.9.9/dns-query", "Quad9"),
    ("https://208.67.222.222/dns-query", "OpenDNS"),
    ("https://dns.adguard.com/dns-query,94.140.14.14", "AdGuard"),
    ("https://doh.libredns.gr/dns-query,116.202.176.26", "LibreDNS"),
    ("https://doh.libredns.gr/ads,116.202.176.26", "LibreDNS NoAds"),
]


def menu_dns():
    """Main DNS settings menu."""
    dns = uci.get_dns_settings()
    proto = dns.get("remote_dns_protocol", "tcp")
    proto_label = {"tcp": "TCP", "udp": "UDP", "doh": "DoH"}.get(proto) or str(proto)

    if proto == "doh":
        active_dns = dns["remote_dns_doh"]
    else:
        active_dns = dns["remote_dns"]

    fakedns = dns["remote_fakedns"] == "1"
    redirect = dns["dns_redirect"] == "1"
    direct_strat = dns["direct_dns_query_strategy"]
    remote_strat = dns["remote_dns_query_strategy"]
    ecs = dns["remote_dns_client_ip"] or "Not set"
    detour = dns["remote_dns_detour"]

    text = (
        f"<b>{E_DNS} DNS Configuration</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Protocol: <b>{proto_label}</b>\n"
        f"Server: <code>{active_dns}</code>\n"
        f"FakeDNS: {E_ON if fakedns else E_OFF}\n"
        f"DNS Redirect: {E_ON if redirect else E_OFF}\n"
        f"Direct Strategy: <b>{direct_strat}</b>\n"
        f"Remote Strategy: <b>{remote_strat}</b>\n"
        f"EDNS Client IP: <code>{ecs}</code>\n"
        f"Outbound: <b>{detour}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )

    fakedns_label = f"{E_ON} FakeDNS ON" if fakedns else f"{E_OFF} FakeDNS OFF"
    redirect_label = f"{E_ON} Redirect ON" if redirect else f"{E_OFF} Redirect OFF"

    buttons = [
        [("📶 Protocol: " + proto_label, "menu:dns_proto")],
        [("🌐 Change DNS Server", "menu:dns_server")],
        [("✏️ Custom DNS", "dns:custom_input")],
        [(fakedns_label, "dns:toggle_fakedns")],
        [(redirect_label, "dns:toggle_redirect")],
        [("📊 Query Strategies", "menu:dns_strategy")],
        [("🔗 EDNS Client IP", "dns:ecs_input")],
        [("📋 Domain Overrides", "dns:hosts_input")],
        [(f"{E_BACK} Back", "menu:rules")],
    ]
    return text, tg.make_inline_keyboard(buttons)


def menu_dns_proto():
    """Select DNS protocol."""
    current = uci.get_dns_settings()["remote_dns_protocol"]
    text = (
        f"<b>📶 Select Remote DNS Protocol</b>\n"
        f"Current: <b>{current.upper()}</b>"
    )
    buttons = [
        [("TCP" + (" ✅" if current == "tcp" else ""), "dns:proto:tcp")],
        [("UDP" + (" ✅" if current == "udp" else ""), "dns:proto:udp")],
        [("DoH (DNS over HTTPS)" + (" ✅" if current == "doh" else ""), "dns:proto:doh")],
        [(f"{E_BACK} Back", "menu:dns")],
    ]
    return text, tg.make_inline_keyboard(buttons)


def menu_dns_server():
    """Select from preset DNS servers, depending on current protocol."""
    proto = uci.get_dns_settings()["remote_dns_protocol"]
    if proto == "doh":
        presets = DNS_PRESETS_DOH
        current = uci.get_dns_settings()["remote_dns_doh"]
    else:
        presets = DNS_PRESETS_TCP
        current = uci.get_dns_settings()["remote_dns"]

    text = (
        f"<b>🌐 Select DNS Server ({proto.upper()})</b>\n"
        f"Current: <code>{current}</code>"
    )
    buttons = []
    for addr, label in presets:
        marker = " ✅" if addr == current else ""
        buttons.append([(f"{label}{marker}", f"dns:server:{addr}")])
    buttons.append([("✏️ Custom DNS", "dns:custom_input")])
    buttons.append([(f"{E_BACK} Back", "menu:dns")])
    return text, tg.make_inline_keyboard(buttons)


def menu_dns_strategy():
    """Query strategy settings for Direct and Remote."""
    dns = uci.get_dns_settings()
    direct = dns["direct_dns_query_strategy"]
    remote = dns["remote_dns_query_strategy"]
    detour = dns["remote_dns_detour"]

    text = (
        f"<b>📊 Query Strategies</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Direct: <b>{direct}</b>\n"
        f"Remote: <b>{remote}</b>\n"
        f"Outbound: <b>{detour}</b>"
    )
    buttons = [
        [("Direct: UseIP", "dns:dstrat:UseIP"), ("UseIPv4", "dns:dstrat:UseIPv4"), ("UseIPv6", "dns:dstrat:UseIPv6")],
        [("Remote: UseIP", "dns:rstrat:UseIP"), ("UseIPv4", "dns:rstrat:UseIPv4"), ("UseIPv6", "dns:rstrat:UseIPv6")],
        [("Outbound: Remote", "dns:detour:remote"), ("Direct", "dns:detour:direct")],
        [(f"{E_BACK} Back", "menu:dns")],
    ]
    return text, tg.make_inline_keyboard(buttons)


# ═══════════════════════════════════════════════════════════════
#  TOOLS MENU
# ═══════════════════════════════════════════════════════════════

def menu_tools():
    """Tools sub-menu."""
    text = (
        f"<b>{E_TOOLS} System Tools</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Select a tool:"
    )
    buttons = [
        [(f"{E_SUB} Update Subscriptions", "act:sub_update")],
        [(f"{E_UPDATE} App/Core Updates", "menu:app_update")],
        [(f"{E_HAP} HAProxy Status", "menu:haproxy")],
        [(f"{E_PING} Ping / URL Test", "menu:ping")],
        [(f"{E_GEO} GeoView Lookup", "geo:input")],
        [(f"{E_LOG} View Logs", "menu:logs")],
        [(f"{E_BACKUP} Backup / Restore", "menu:backup")],
        [("🔀 Forwarding", "menu:forwarding"), ("⏱️ Delay", "menu:delay")],
        [("🧹 Clear IPSET/NFT", "act:flush_sets")],
        [(f"{E_BACK} Back", "menu:main")],
    ]
    return text, tg.make_inline_keyboard(buttons)


def menu_haproxy():
    """HAProxy load balancer status."""
    configs = uci.get_haproxy_configs()
    hap_running = uci._run("busybox top -bn1 | grep -v grep | grep haproxy") != ""

    text = (
        f"<b>{E_HAP} HAProxy Load Balancing</b>\n"
        f"Status: {E_ON if hap_running else E_OFF}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
    )
    if not configs:
        text += "No HAProxy nodes configured."
    else:
        for c in configs:
            lbss = c.get("lbss", "?")
            enabled = c.get("enabled", "1") == "1"
            icon = E_ON if enabled else E_OFF
            text += f"{icon} Node: <code>{lbss}</code>\n"

    buttons = [[(f"{E_BACK} Back", "menu:tools")]]
    return text, tg.make_inline_keyboard(buttons)


def menu_logs():
    """View logs."""
    text = (
        f"<b>{E_LOG} PassWall 2 Logs</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )
    buttons = [
        [("📄 Client Log (last 30)", "act:log_client")],
        [("📄 Server Log (last 30)", "act:log_server")],
        [("🗑️ Clear Client Log", "act:log_clear")],
        [(f"{E_BACK} Back", "menu:tools")],
    ]
    return text, tg.make_inline_keyboard(buttons)


def menu_backup():
    """Backup / Restore controls."""
    text = (
        f"<b>{E_BACKUP} Backup & Restore</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Download your config or upload to restore."
    )
    buttons = [
        [("⬇️ Download Backup", "act:backup_download")],
        [("⬆️ Upload Restore (send file)", "act:backup_upload_info")],
        [(f"{E_BACK} Back", "menu:tools")],
    ]
    return text, tg.make_inline_keyboard(buttons)


def menu_ping(page=0):
    """Ping/URL test menu - show nodes to test (paginated)."""
    nodes: list = uci.get_all_nodes()
    PAGE_SIZE = 8

    total_pages = max(1, (len(nodes) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, len(nodes))

    text = (
        f"<b>{E_PING} Ping / URL Test</b> (Page {page+1}/{total_pages})\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Select a node to test:"
    )
    buttons = []
    for n in nodes[start:end]:
        label = f"{n['remark']}"
        if len(label) > 40:
            label = label[:37] + "..."
        buttons.append([(label, f"ping:{n['id']}")])

    # Pagination
    nav_row = []
    if page > 0:
        nav_row.append(("⬅️ Prev", f"ping:page:{page-1}"))
    if page < total_pages - 1:
        nav_row.append(("Next ➡️", f"ping:page:{page+1}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append([(f"{E_BACK} Back", "menu:tools")])
    return text, tg.make_inline_keyboard(buttons)


def menu_app_update():
    """App/Core update info."""
    text = (
        f"<b>{E_UPDATE} App & Core Updates</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Trigger rule updates or check for component updates."
    )
    buttons = [
        [("🔄 Update GeoIP+Geosite", "act:update_rules")],
        [(f"{E_BACK} Back", "menu:tools")],
    ]
    return text, tg.make_inline_keyboard(buttons)


# ═══════════════════════════════════════════════════════════════
#  FORWARDING SETTINGS
# ═══════════════════════════════════════════════════════════════

def menu_forwarding():
    """Forwarding / firewall settings."""
    fwd = uci.get_forwarding_settings()
    tcp_way = fwd.get("tcp_proxy_way", "redirect").upper()
    nft = "NFTables" if fwd.get("use_nft") == "1" else "IPTables"
    ipv6 = "✅" if fwd.get("ipv6_tproxy") == "1" else "⬜"

    text = (
        f"<b>🔀 Forwarding Settings</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"TCP Proxy Way: <b>{tcp_way}</b>\n"
        f"Firewall Tool: <b>{nft}</b>\n"
        f"TCP Redir Ports: <code>{fwd.get('tcp_redir_ports', 'All')}</code>\n"
        f"UDP Redir Ports: <code>{fwd.get('udp_redir_ports', 'All')}</code>\n"
        f"IPv6 TProxy: {ipv6}\n"
    )
    buttons = [
        [("REDIRECT", "fwd:tcp_proxy_way:redirect"), ("TPROXY", "fwd:tcp_proxy_way:tproxy")],
        [("NFTables", "fwd:use_nft:1"), ("IPTables", "fwd:use_nft:0")],
        [("Toggle IPv6 TProxy", "fwd:toggle_ipv6")],
        [(f"{E_BACK} Back", "menu:tools")],
    ]
    return text, tg.make_inline_keyboard(buttons)


# ═══════════════════════════════════════════════════════════════
#  DELAY SETTINGS
# ═══════════════════════════════════════════════════════════════

def menu_delay():
    """Delay / daemon automation settings."""
    d = uci.get_delay_settings()
    daemon = "✅" if d.get("enabled") == "1" else "⬜"

    text = (
        f"<b>⏱️ Delay Settings</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Daemon: {daemon}\n"
        f"Delay Start: <b>{d.get('start_delay', '60')}s</b>\n"
        f"Auto Stop: <b>{d.get('auto_stop', 'Disable')}</b>\n"
        f"Auto Start: <b>{d.get('auto_start', 'Disable')}</b>\n"
        f"Auto Restart: <b>{d.get('auto_restart', 'Disable')}</b>\n"
    )
    buttons = [
        [("Toggle Daemon", "delay:toggle_daemon")],
        [("Set Delay 30s", "delay:start_delay:30"), ("Set Delay 60s", "delay:start_delay:60")],
        [("Set Delay 120s", "delay:start_delay:120")],
        [(f"{E_BACK} Back", "menu:tools")],
    ]
    return text, tg.make_inline_keyboard(buttons)


# ═══════════════════════════════════════════════════════════════
#  SOCKS CONFIG
# ═══════════════════════════════════════════════════════════════

def menu_socks_config():
    """Socks Main Switch + table of SOCKS listeners."""
    cfg = uci.get_socks_config()
    enabled = "✅ ON" if cfg.get("socks_enabled") == "1" else "⬜ OFF"
    entries = cfg.get("entries", [])

    lines = [
        f"<b>{E_SOCKS} SOCKS Configuration</b>",
        f"━━━━━━━━━━━━━━━━━━━━━",
        f"Main Switch: <b>{enabled}</b>",
        f"━━━━━━━━━━━━━━━━━━━━━",
    ]
    if entries:
        for i, s in enumerate(entries):
            st = "✅" if s.get("enabled") == "1" else "⬜"
            lines.append(
                f"{i+1}. {st} Port:<code>{s.get('port', '?')}</code> "
                f"HTTP:<code>{s.get('http_port', '0')}</code>"
            )
    else:
        lines.append("<i>No SOCKS entries configured.</i>")

    text = "\n".join(lines)
    toggle_cb = "socks:toggle_main"
    buttons = [
        [("Toggle Main Switch", toggle_cb)],
        [(f"{E_BACK} Back", "menu:nodes")],
    ]
    return text, tg.make_inline_keyboard(buttons)


# ═══════════════════════════════════════════════════════════════
#  NODE DETAIL
# ═══════════════════════════════════════════════════════════════

def menu_node_detail(node_id=""):
    """Show full details of a single node with action buttons."""
    if not node_id:
        return menu_switch_node()
    detail = uci.get_node_detail(node_id)
    if not detail:
        return menu_switch_node()

    remark = detail.get("remarks", node_id)
    node_type = detail.get("type", "?")
    protocol = detail.get("protocol", "?")
    address = detail.get("address", "?")
    port = detail.get("port", "?")
    transport = detail.get("transport", "RAW")
    tls_val = "✅" if detail.get("tls") == "1" else "⬜"

    text = (
        f"<b>📋 Node Detail</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Name: <b>{remark}</b>\n"
        f"Type: <code>{node_type}</code>\n"
        f"Protocol: <code>{protocol}</code>\n"
        f"Address: <code>{address}</code>\n"
        f"Port: <code>{port}</code>\n"
        f"Transport: <code>{transport}</code>\n"
        f"TLS: {tls_val}\n"
    )
    buttons = [
        [("✅ Use This Node", f"node:set:{node_id}")],
        [("📋 Copy Node", f"node:copy:{node_id}"), ("🗑️ Delete", f"node:del:{node_id}")],
        [(f"{E_BACK} Back", "menu:switch_node")],
    ]
    return text, tg.make_inline_keyboard(buttons)


# ═══════════════════════════════════════════════════════════════
#  GLOBAL OPTIONS (Localhost/Client Proxy, etc.)
# ═══════════════════════════════════════════════════════════════

def menu_global_options():
    """Advanced global toggles (localhost proxy, client proxy, etc)."""
    opts = uci.get_global_options()
    lp = "✅" if opts.get("localhost_proxy") == "1" else "⬜"
    cp = "✅" if opts.get("client_proxy") == "1" else "⬜"
    ipset = "✅" if opts.get("direct_dns_ipset") == "1" else "⬜"

    text = (
        f"<b>⚙️ Global Options</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Localhost Proxy: {lp}\n"
        f"Client Proxy: {cp}\n"
        f"Socks Port: <code>{opts.get('node_socks_port', '1070')}</code>\n"
        f"Direct DNS → IPSet: {ipset}\n"
    )
    buttons = [
        [("Toggle Localhost Proxy", "gopt:localhost_proxy")],
        [("Toggle Client Proxy", "gopt:client_proxy")],
        [("Toggle DNS IPSet", "gopt:direct_dns_ipset")],
        [(f"{E_BACK} Back", "menu:main")],
    ]
    return text, tg.make_inline_keyboard(buttons)


# ═══════════════════════════════════════════════════════════════
#  MENU DISPATCHER
# ═══════════════════════════════════════════════════════════════

MENU_MAP = {
    "main": menu_main,
    "nodes": menu_nodes,
    "switch_node": menu_switch_node,
    "socks": menu_socks,
    "socks_config": menu_socks_config,
    "server": menu_server,
    "rules": menu_rules,
    "acl": menu_acl,
    "shunt": menu_shunt,
    "dns": menu_dns,
    "dns_proto": menu_dns_proto,
    "dns_server": menu_dns_server,
    "dns_strategy": menu_dns_strategy,
    "tools": menu_tools,
    "haproxy": menu_haproxy,
    "logs": menu_logs,
    "backup": menu_backup,
    "ping": menu_ping,
    "app_update": menu_app_update,
    "forwarding": menu_forwarding,
    "delay": menu_delay,
    "global_options": menu_global_options,
}


def get_menu(name, **kwargs):
    """Dispatch to a menu handler by name."""
    handler = MENU_MAP.get(name)
    if handler:
        return handler(**kwargs)
    return menu_main()

