#!/bin/sh
# =============================================================
# DNS Tunnel Manager — LuCI Integration Script
# Installs Slipstream & DNSTT management pages into OpenWrt LuCI
# Run as root on the router:  sh install_luci_tunnel.sh
# =============================================================

LUCI_DIR="/usr/lib/lua/luci"
HTM_DIR="/www/luci-static/resources"

echo "=== Installing DNS Tunnel Manager for LuCI ==="

# ── 1. Controller ──────────────────────────────────────────────
mkdir -p "$LUCI_DIR/controller"
cat > "$LUCI_DIR/controller/dnstunnel.lua" << 'LUAEOF'
module("luci.controller.dnstunnel", package.seeall)

function index()
    entry({"admin", "services", "dnstunnel"}, firstchild(), "DNS Tunnels", 80)
    entry({"admin", "services", "dnstunnel", "slipstream"}, template("dnstunnel/slipstream"), "Slipstream", 10)
    entry({"admin", "services", "dnstunnel", "dnstt"}, template("dnstunnel/dnstt"), "DNSTT", 20)
    entry({"admin", "services", "dnstunnel", "scanner"}, template("dnstunnel/scanner"), "DNS Scanner", 30)

    -- API endpoints
    entry({"admin", "services", "dnstunnel", "api"}, call("api_handler"))
end

function api_handler()
    local http = require "luci.http"
    local json = require "luci.jsonc"

    local action = http.formvalue("action") or ""
    local result = {}

    if action == "slipstream_status" then
        result = get_tunnel_status("slipstream")
    elseif action == "dnstt_status" then
        result = get_tunnel_status("dnstt")
    elseif action == "slipstream_profiles" then
        result = get_profiles("/etc/slipstream-rust/profiles.json")
    elseif action == "dnstt_profiles" then
        result = get_profiles("/etc/dnstt/profiles.json")
    elseif action == "slipstream_save" then
        result = save_profile("slipstream", http)
    elseif action == "dnstt_save" then
        result = save_profile("dnstt", http)
    elseif action == "slipstream_delete" then
        result = delete_profile("slipstream", http.formvalue("name") or "")
    elseif action == "dnstt_delete" then
        result = delete_profile("dnstt", http.formvalue("name") or "")
    elseif action == "slipstream_switch" then
        result = switch_profile("slipstream", http.formvalue("name") or "")
    elseif action == "dnstt_switch" then
        result = switch_profile("dnstt", http.formvalue("name") or "")
    elseif action == "slipstream_start" then
        os.execute("/etc/init.d/slipstream start 2>/dev/null")
        os.execute("/etc/init.d/slipstream enable 2>/dev/null")
        result = {ok = true, msg = "Started"}
    elseif action == "slipstream_stop" then
        os.execute("/etc/init.d/slipstream stop 2>/dev/null")
        os.execute("killall slipstream-client 2>/dev/null")
        result = {ok = true, msg = "Stopped"}
    elseif action == "dnstt_start" then
        os.execute("/etc/init.d/dnstt start 2>/dev/null")
        os.execute("/etc/init.d/dnstt enable 2>/dev/null")
        result = {ok = true, msg = "Started"}
    elseif action == "dnstt_stop" then
        os.execute("/etc/init.d/dnstt stop 2>/dev/null")
        os.execute("killall dnstt-client 2>/dev/null")
        result = {ok = true, msg = "Stopped"}
    elseif action == "slipstream_install" then
        result = install_binary("slipstream")
    elseif action == "dnstt_install" then
        result = install_binary("dnstt")
    elseif action == "masscan_install" then
        result = install_binary("masscan")
    -- Scanner actions (proxy to Python bot API)
    elseif action == "scanner_start" then
        result = scanner_api("dns_scanner_start", http)
    elseif action == "scanner_status" then
        result = scanner_api("dns_scanner_status", http)
    elseif action == "scanner_stop" then
        result = scanner_api("dns_scanner_stop", http)
    elseif action == "scanner_pause" then
        result = scanner_api("dns_scanner_pause", http)
    elseif action == "scanner_resume" then
        result = scanner_api("dns_scanner_resume", http)
    elseif action == "scanner_shuffle" then
        result = scanner_api("dns_scanner_shuffle", http)
    elseif action == "scanner_export" then
        result = scanner_api("dns_scanner_export", http)
    elseif action == "scanner_history" then
        result = scanner_api("dns_scanner_history", http)
    elseif action == "scanner_save_project" then
        result = scanner_api("dns_scanner_save_project", http)
    elseif action == "scanner_load_project" then
        result = scanner_api("dns_scanner_load_project", http)
    elseif action == "scanner_last_domain" then
        result = scanner_api("dns_scanner_last_domain", http)
    elseif action == "scanner_get_blacklist" then
        result = scanner_api("dns_scanner_get_blacklist", http)
    elseif action == "scanner_add_blacklist" then
        result = scanner_api("dns_scanner_add_blacklist", http)
    elseif action == "scanner_clear_blacklist" then
        result = scanner_api("dns_scanner_clear_blacklist", http)
    elseif action == "get_cidrs" then
        result = scanner_api("get_cidr_lists", http)
    elseif action == "get_cidr_content" then
        result = scanner_api("get_cidr_content", http)
    elseif action == "add_cidr" then
        result = scanner_api("add_cidr_list", http)
    elseif action == "delete_cidr" then
        result = scanner_api("delete_cidr_list", http)
    else
        result = {error = "unknown action"}
    end

    http.prepare_content("application/json")
    http.write(json.stringify(result))
end

function get_tunnel_status(tunnel)
    local running = false
    local installed = false
    local arch = io.popen("uname -m"):read("*l") or "unknown"

    if tunnel == "slipstream" then
        installed = nixio_fs_access("/usr/bin/slipstream-client")
        running = os.execute("pgrep -x slipstream-client >/dev/null 2>&1") == 0
    else
        installed = nixio_fs_access("/usr/bin/dnstt-client")
        running = os.execute("pgrep -x dnstt-client >/dev/null 2>&1") == 0
    end

    return {
        installed = installed,
        running = running,
        arch = arch,
    }
end

function nixio_fs_access(path)
    local f = io.open(path, "r")
    if f then f:close(); return true end
    return false
end

function get_profiles(path)
    local json = require "luci.jsonc"
    local f = io.open(path, "r")
    if not f then return {active = "", profiles = {}} end
    local data = json.parse(f:read("*a"))
    f:close()
    return data or {active = "", profiles = {}}
end

function save_profile(tunnel, http)
    local json = require "luci.jsonc"
    local path = tunnel == "slipstream"
        and "/etc/slipstream-rust/profiles.json"
        or "/etc/dnstt/profiles.json"
    local name = http.formvalue("name") or ""
    if name == "" then return {ok = false, msg = "name required"} end

    local data = get_profiles(path)
    local profile = {}
    if tunnel == "slipstream" then
        profile = {
            name = name,
            domain = http.formvalue("domain") or "",
            resolver = http.formvalue("resolver") or "",
            cert = http.formvalue("cert") or "",
            congestion = http.formvalue("congestion") or "dcubic",
            keep_alive = tonumber(http.formvalue("keep_alive")) or 400,
            gso = http.formvalue("gso") == "1",
        }
    else
        profile = {
            name = name,
            domain = http.formvalue("domain") or "",
            pubkey = http.formvalue("pubkey") or "",
            resolver = http.formvalue("resolver") or "",
            listen_port = tonumber(http.formvalue("listen_port")) or 7000,
            transport = http.formvalue("transport") or "udp",
        }
    end

    -- Update existing or add new
    local found = false
    for i, p in ipairs(data.profiles or {}) do
        if p.name == name then
            data.profiles[i] = profile
            found = true
            break
        end
    end
    if not found then
        data.profiles = data.profiles or {}
        data.profiles[#data.profiles + 1] = profile
    end
    if not data.active or data.active == "" then
        data.active = name
    end

    local dir = tunnel == "slipstream" and "/etc/slipstream-rust" or "/etc/dnstt"
    os.execute("mkdir -p " .. dir)
    local f = io.open(path, "w")
    f:write(json.stringify(data))
    f:close()

    return {ok = true, msg = "Profile '" .. name .. "' saved"}
end

function delete_profile(tunnel, name)
    local json = require "luci.jsonc"
    local path = tunnel == "slipstream"
        and "/etc/slipstream-rust/profiles.json"
        or "/etc/dnstt/profiles.json"
    local data = get_profiles(path)
    local new = {}
    for _, p in ipairs(data.profiles or {}) do
        if p.name ~= name then new[#new + 1] = p end
    end
    data.profiles = new
    if data.active == name then
        data.active = (#new > 0) and new[1].name or ""
    end
    local f = io.open(path, "w")
    f:write(json.stringify(data))
    f:close()
    return {ok = true, msg = "Deleted"}
end

function switch_profile(tunnel, name)
    local json = require "luci.jsonc"
    local path = tunnel == "slipstream"
        and "/etc/slipstream-rust/profiles.json"
        or "/etc/dnstt/profiles.json"
    local data = get_profiles(path)
    data.active = name
    local f = io.open(path, "w")
    f:write(json.stringify(data))
    f:close()

    -- Restart service
    local svc = tunnel == "slipstream" and "slipstream" or "dnstt"
    os.execute("/etc/init.d/" .. svc .. " stop 2>/dev/null")
    os.execute("/etc/init.d/" .. svc .. " start 2>/dev/null")
    return {ok = true, msg = "Switched to " .. name}
end

function install_binary(tunnel)
    local arch = io.popen("uname -m"):read("*l") or ""
    local map = {
        slipstream = {
            x86_64 = "slipstream-client-linux-amd64-musl",
            aarch64 = "slipstream-client-linux-arm64-musl",
            armv7l = "slipstream-client-linux-armv7-musl",
        },
        dnstt = {
            x86_64 = "dnstt-client-linux-amd64",
            aarch64 = "dnstt-client-linux-arm64",
            armv7l = "dnstt-client-linux-armv7",
        },
        masscan = {
            armv7l = "masscan-armv7-openwrt.zip",
        },
    }
    local tags = {slipstream = "slipstream-latest", dnstt = "dnstt-latest", masscan = "masscan-latest"}
    local tag = tags[tunnel] or "unknown"
    local fname = (map[tunnel] or {})[arch]
    if not fname then return {ok = false, msg = "Unsupported arch: " .. arch} end

    if tunnel == "masscan" then
        local url = "https://github.com/rooomer/passwall2-webapp/releases/latest/download/" .. fname
        local cmd = string.format('wget -q -O /tmp/masscan.zip "%s" && unzip -o /tmp/masscan.zip -d /tmp/ && mv /tmp/masscan /usr/bin/masscan && chmod +x /usr/bin/masscan && rm -f /tmp/masscan.zip', url)
        os.execute(cmd)
        return {ok = true, msg = "Masscan installed"}
    end

    local bin = tunnel == "slipstream" and "/usr/bin/slipstream-client" or "/usr/bin/dnstt-client"
    local url = "https://github.com/rooomer/passwall2-webapp/releases/download/" .. tag .. "/" .. fname
    local cmd = string.format('wget -q -O "%s" "%s" && chmod +x "%s"', bin, url, bin)
    os.execute(cmd)
    return {ok = true, msg = "Installed"}
end

function scanner_api(action, http)
    local json = require "luci.jsonc"
    local nixio = require "nixio"

    -- Build JSON body from form values
    local body = json.stringify({
        domain = http.formvalue("domain") or "",
        cidr_text = http.formvalue("cidr_text") or "",
        concurrency = tonumber(http.formvalue("concurrency")) or 200,
        timeout = tonumber(http.formvalue("timeout")) or 2,
        dns_type = http.formvalue("dns_type") or "A",
        preset = http.formvalue("preset") or "normal",
        sample_size = tonumber(http.formvalue("sample_size")) or 0,
        random_subdomain = http.formvalue("random_subdomain") ~= "false",
        auto_retry = http.formvalue("auto_retry") == "true",
        check_ns = http.formvalue("check_ns") == "true",
        blacklist_enabled = http.formvalue("blacklist_enabled") == "true",
        domains = http.formvalue("domains") or "",
        ip = http.formvalue("ip") or "",
        name = http.formvalue("name") or "",
        content = http.formvalue("content") or "",
        source_port = tonumber(http.formvalue("source_port")) or 0,
        pre_scan_port = tonumber(http.formvalue("pre_scan_port")) or 0,
        pre_scan_rate = tonumber(http.formvalue("pre_scan_rate")) or 1000,
    })

    -- Read token
    local tf = io.open("/tmp/pw_api_token", "r")
    local token = tf and tf:read("*l") or ""
    if tf then tf:close() end
    token = token:match("^%s*(.-)%s*$") or ""

    if token == "" then
        nixio.syslog("err", "scanner_api: No API token found at /tmp/pw_api_token")
        return {ok = false, msg = "No API token found. Is the bot running?"}
    end

    -- Write body to temp file to avoid shell escaping issues
    local tmp = "/tmp/pw_scanner_body.json"
    local wf = io.open(tmp, "w")
    if wf then
        wf:write(body)
        wf:close()
    else
        return {ok = false, msg = "Cannot write temp file"}
    end

    local url = "http://127.0.0.1:8080/api/action/" .. action
    local cmd = string.format(
        'curl -s -m 30 -X POST -H "Content-Type: application/json" -H "Authorization: Bearer %s" -d @%s "%s" 2>&1',
        token, tmp, url
    )

    nixio.syslog("info", "scanner_api: " .. action .. " -> " .. url)

    local pipe = io.popen(cmd)
    local out = pipe:read("*a") or ""
    pipe:close()
    os.remove(tmp)

    if out == "" then
        nixio.syslog("err", "scanner_api: empty response from curl")
        return {ok = false, msg = "API returned empty response"}
    end

    local parsed = json.parse(out)
    if not parsed then
        nixio.syslog("err", "scanner_api: invalid JSON: " .. out:sub(1, 200))
        return {ok = false, msg = "API returned invalid response: " .. out:sub(1, 100)}
    end

    return parsed
end
LUAEOF

echo "  ✅ Controller installed"

# ── 2. Views ───────────────────────────────────────────────────
mkdir -p "$LUCI_DIR/view/dnstunnel"

# -- Slipstream View --
cat > "$LUCI_DIR/view/dnstunnel/slipstream.htm" << 'HTMEOF'
<%+header%>
<h2>⚡ Slipstream DNS Tunnel</h2>
<div id="tunnel-app">
    <fieldset class="cbi-section">
        <legend>Status</legend>
        <div id="slip-status">Loading...</div>
    </fieldset>
    <fieldset class="cbi-section">
        <legend>Profiles</legend>
        <div id="slip-profiles">Loading...</div>
    </fieldset>
    <fieldset class="cbi-section">
        <legend>Configuration</legend>
        <div class="cbi-value"><label>Profile Name</label><input type="text" id="s_name" style="width:300px"></div>
        <div class="cbi-value"><label>Domain (-d)</label><input type="text" id="s_domain" style="width:300px" placeholder="s.example.com"></div>
        <div class="cbi-value"><label>Resolver (-r)</label><input type="text" id="s_resolver" style="width:300px" placeholder="1.2.3.4:53"></div>
        <div class="cbi-value"><label>Congestion</label>
            <select id="s_congestion"><option value="dcubic">dcubic</option><option value="bbr">bbr</option></select>
        </div>
        <div class="cbi-value"><label>Certificate</label><textarea id="s_cert" rows="3" style="width:300px"></textarea></div>
    </fieldset>
    <div class="cbi-page-actions">
        <input type="button" class="cbi-button cbi-button-apply" value="💾 Save Profile" onclick="slipSave()">
        <input type="button" class="cbi-button cbi-button-positive" value="▶️ Start" onclick="slipAction('slipstream_start')">
        <input type="button" class="cbi-button cbi-button-negative" value="⏹️ Stop" onclick="slipAction('slipstream_stop')">
        <input type="button" class="cbi-button cbi-button-reset" value="📦 Install Binary" onclick="slipAction('slipstream_install')">
    </div>
    <pre id="slip-log" style="margin-top:10px;background:#222;color:#0f0;padding:8px;max-height:200px;overflow:auto;"></pre>
</div>
<script>
var apiUrl = '<%=luci.dispatcher.build_url("admin/services/dnstunnel/api")%>';
function slipApi(params, cb) {
    var x = new XMLHttpRequest();
    x.open('POST', apiUrl, true);
    x.setRequestHeader('Content-Type','application/x-www-form-urlencoded');
    x.onload = function(){ cb(JSON.parse(x.responseText)); };
    x.send(params);
}
function slipRefresh() {
    slipApi('action=slipstream_status', function(r) {
        document.getElementById('slip-status').innerHTML =
            '<b>Installed:</b> '+(r.installed?'✅':'❌')+' | <b>Running:</b> '+(r.running?'🟢 Yes':'🔴 No')+' | <b>Arch:</b> '+r.arch;
    });
    slipApi('action=slipstream_profiles', function(r) {
        var h = '<table class="table"><tr><th>Name</th><th>Domain</th><th>Resolver</th><th></th><th></th></tr>';
        (r.profiles||[]).forEach(function(p){
            var active = p.name === r.active ? ' <b style="color:green">✅ ACTIVE</b>' : '';
            h += '<tr><td>'+p.name+active+'</td><td>'+p.domain+'</td><td>'+p.resolver+'</td>';
            h += '<td><input type="button" class="cbi-button" value="Use" onclick="slipSwitch(\''+p.name+'\')"></td>';
            h += '<td><input type="button" class="cbi-button cbi-button-negative" value="🗑️" onclick="slipDel(\''+p.name+'\')"></td></tr>';
        });
        h += '</table>';
        document.getElementById('slip-profiles').innerHTML = h;
    });
}
function slipSave() {
    var p = 'action=slipstream_save&name='+encodeURIComponent(document.getElementById('s_name').value)+
            '&domain='+encodeURIComponent(document.getElementById('s_domain').value)+
            '&resolver='+encodeURIComponent(document.getElementById('s_resolver').value)+
            '&congestion='+encodeURIComponent(document.getElementById('s_congestion').value)+
            '&cert='+encodeURIComponent(document.getElementById('s_cert').value);
    slipApi(p, function(r){ document.getElementById('slip-log').textContent = JSON.stringify(r); slipRefresh(); });
}
function slipSwitch(name) { slipApi('action=slipstream_switch&name='+encodeURIComponent(name), function(r){ document.getElementById('slip-log').textContent = JSON.stringify(r); slipRefresh(); }); }
function slipDel(name) { if(confirm('Delete '+name+'?')) slipApi('action=slipstream_delete&name='+encodeURIComponent(name), function(r){ slipRefresh(); }); }
function slipAction(a) { slipApi('action='+a, function(r){ document.getElementById('slip-log').textContent = JSON.stringify(r); setTimeout(slipRefresh, 1500); }); }
slipRefresh();
</script>
<%+footer%>
HTMEOF

# -- DNSTT View --
cat > "$LUCI_DIR/view/dnstunnel/dnstt.htm" << 'HTMEOF'
<%+header%>
<h2>🔐 DNSTT DNS Tunnel</h2>
<div id="tunnel-app">
    <fieldset class="cbi-section">
        <legend>Status</legend>
        <div id="dnstt-status">Loading...</div>
    </fieldset>
    <fieldset class="cbi-section">
        <legend>Profiles</legend>
        <div id="dnstt-profiles">Loading...</div>
    </fieldset>
    <fieldset class="cbi-section">
        <legend>Configuration</legend>
        <div class="cbi-value"><label>Profile Name</label><input type="text" id="d_name" style="width:300px"></div>
        <div class="cbi-value"><label>Domain</label><input type="text" id="d_domain" style="width:300px" placeholder="tunnel.example.com"></div>
        <div class="cbi-value"><label>Public Key (hex)</label><input type="text" id="d_pubkey" style="width:300px" placeholder="64 hex digits"></div>
        <div class="cbi-value"><label>Resolver</label><input type="text" id="d_resolver" style="width:300px" placeholder="8.8.8.8"></div>
        <div class="cbi-value"><label>Transport</label>
            <select id="d_transport"><option value="udp">UDP</option><option value="doh">DoH</option><option value="dot">DoT</option></select>
        </div>
        <div class="cbi-value"><label>Listen Port</label><input type="number" id="d_port" value="7000" style="width:100px"></div>
    </fieldset>
    <div class="cbi-page-actions">
        <input type="button" class="cbi-button cbi-button-apply" value="💾 Save Profile" onclick="dnsttSave()">
        <input type="button" class="cbi-button cbi-button-positive" value="▶️ Start" onclick="dnsttAction('dnstt_start')">
        <input type="button" class="cbi-button cbi-button-negative" value="⏹️ Stop" onclick="dnsttAction('dnstt_stop')">
        <input type="button" class="cbi-button cbi-button-reset" value="📦 Install Binary" onclick="dnsttAction('dnstt_install')">
    </div>
    <pre id="dnstt-log" style="margin-top:10px;background:#222;color:#0f0;padding:8px;max-height:200px;overflow:auto;"></pre>
</div>
<script>
var apiUrl = '<%=luci.dispatcher.build_url("admin/services/dnstunnel/api")%>';
function dnsttApi(params, cb) {
    var x = new XMLHttpRequest();
    x.open('POST', apiUrl, true);
    x.setRequestHeader('Content-Type','application/x-www-form-urlencoded');
    x.onload = function(){ cb(JSON.parse(x.responseText)); };
    x.send(params);
}
function dnsttRefresh() {
    dnsttApi('action=dnstt_status', function(r) {
        document.getElementById('dnstt-status').innerHTML =
            '<b>Installed:</b> '+(r.installed?'✅':'❌')+' | <b>Running:</b> '+(r.running?'🟢 Yes':'🔴 No')+' | <b>Arch:</b> '+r.arch;
    });
    dnsttApi('action=dnstt_profiles', function(r) {
        var h = '<table class="table"><tr><th>Name</th><th>Domain</th><th>Transport</th><th></th><th></th></tr>';
        (r.profiles||[]).forEach(function(p){
            var active = p.name === r.active ? ' <b style="color:green">✅ ACTIVE</b>' : '';
            h += '<tr><td>'+p.name+active+'</td><td>'+p.domain+'</td><td>'+(p.transport||'udp')+'</td>';
            h += '<td><input type="button" class="cbi-button" value="Use" onclick="dnsttSwitch(\''+p.name+'\')"></td>';
            h += '<td><input type="button" class="cbi-button cbi-button-negative" value="🗑️" onclick="dnsttDel(\''+p.name+'\')"></td></tr>';
        });
        h += '</table>';
        document.getElementById('dnstt-profiles').innerHTML = h;
    });
}
function dnsttSave() {
    var p = 'action=dnstt_save&name='+encodeURIComponent(document.getElementById('d_name').value)+
            '&domain='+encodeURIComponent(document.getElementById('d_domain').value)+
            '&pubkey='+encodeURIComponent(document.getElementById('d_pubkey').value)+
            '&resolver='+encodeURIComponent(document.getElementById('d_resolver').value)+
            '&transport='+encodeURIComponent(document.getElementById('d_transport').value)+
            '&listen_port='+encodeURIComponent(document.getElementById('d_port').value);
    dnsttApi(p, function(r){ document.getElementById('dnstt-log').textContent = JSON.stringify(r); dnsttRefresh(); });
}
function dnsttSwitch(name) { dnsttApi('action=dnstt_switch&name='+encodeURIComponent(name), function(r){ document.getElementById('dnstt-log').textContent = JSON.stringify(r); dnsttRefresh(); }); }
function dnsttDel(name) { if(confirm('Delete '+name+'?')) dnsttApi('action=dnstt_delete&name='+encodeURIComponent(name), function(r){ dnsttRefresh(); }); }
function dnsttAction(a) { dnsttApi('action='+a, function(r){ document.getElementById('dnstt-log').textContent = JSON.stringify(r); setTimeout(dnsttRefresh, 1500); }); }
dnsttRefresh();
</script>
<%+footer%>
HTMEOF

echo "  ✅ Views installed"

# -- DNS Scanner View v2 (FULL) --
cat > "$LUCI_DIR/view/dnstunnel/scanner.htm" << 'HTMEOF'
<%+header%>
<style>
.sc-stat{display:inline-block;padding:4px 10px;margin:2px;background:#2a2a2a;border-radius:4px;font-size:13px}
.sc-stat b{color:#0f0}
.sc-rcode{display:inline-block;padding:1px 6px;border-radius:3px;font-size:11px;font-weight:700}
.rc-noerror{background:#00b89420;color:#00b894}
.rc-nxdomain{background:#fdcb6e20;color:#fdcb6e}
.rc-servfail{background:#e1705520;color:#e17055}
.rc-refused{background:#d6303120;color:#d63031}
.sc-tag{display:inline-block;padding:1px 5px;border-radius:3px;font-size:10px;font-weight:700;margin-right:2px}
.sc-tag-edns{background:#74b9ff20;color:#74b9ff}
.sc-tag-ns{background:#0984e320;color:#0984e3}
.sc-tag-top{background:#f39c1230;color:#f39c12}
.sc-heatmap{height:8px;border-radius:4px;overflow:hidden;display:flex;margin-top:4px}
</style>
<h2>📡 DNS Tunnel Scanner v2</h2>
<div id="scanner-app">
    <fieldset class="cbi-section">
        <legend>Configuration</legend>
        <div class="cbi-value"><label>Target Domain</label><input type="text" id="sc_domain" style="width:300px" placeholder="s.example.com"></div>
        <div class="cbi-value"><label>Extra Domains</label><input type="text" id="sc_domains" style="width:300px" placeholder="d2.example.com, d3.example.com"></div>
        <div class="cbi-value"><label>IPs / CIDRs</label><textarea id="sc_cidr" rows="4" style="width:300px" placeholder="1.1.1.0/24
8.8.8.0/24"></textarea></div>
        <div class="cbi-value"><label>Preset</label>
            <select id="sc_preset" style="width:200px">
                <option value="fast">⚡ Fast (500, 1.5s)</option>
                <option value="normal" selected>⚙️ Normal (200, 2.5s)</option>
                <option value="deep">🔬 Deep (50, 5s)</option>
            </select>
        </div>
        <div class="cbi-value"><label>DNS Type</label>
            <select id="sc_dns_type" style="width:120px">
                <option value="A" selected>A</option>
                <option value="AAAA">AAAA</option>
                <option value="MX">MX</option>
                <option value="TXT">TXT</option>
                <option value="NS">NS</option>
            </select>
        </div>
        <div class="cbi-value"><label>Sample Size</label><input type="number" id="sc_sample" value="0" style="width:100px"> <small>(0=all)</small></div>
        <div class="cbi-value"><label>Source Port</label><input type="number" id="sc_source_port" value="0" min="0" max="65535" style="width:100px"> <small>(0=random)</small></div>
        <div style="margin:8px 0;">
            <label><input type="checkbox" id="sc_random_sub" checked> Random Subdomain</label>
            <label style="margin-left:12px;"><input type="checkbox" id="sc_auto_retry"> Auto-Retry</label>
            <label style="margin-left:12px;"><input type="checkbox" id="sc_check_ns"> NS Check</label>
            <label style="margin-left:12px;"><input type="checkbox" id="sc_blacklist"> Blacklist</label>
        </div>
        <div style="margin:8px 0;padding:8px;border:1px solid #444;border-radius:4px;background:#1a2a3a;">
            <label><input type="checkbox" id="sc_masscan"> 🔬 Masscan Pre-Filter (port 53)</label>
            <div id="masscanOptsLuci" style="display:none;margin-top:6px;">
                <small style="opacity:0.5;">First scans port 53 with masscan, then tests only open IPs for DNS tunnel.</small>
                <div class="cbi-value" style="margin-top:4px;"><label>Rate (pps)</label>
                    <input type="range" id="sc_masscan_rate" min="100" max="10000" value="1000" step="100" style="width:200px" oninput="document.getElementById('sc_rate_val').textContent=this.value">
                    <b id="sc_rate_val">1000</b>
                </div>
            </div>
        </div>
        <script>document.getElementById('sc_masscan').onchange=function(){document.getElementById('masscanOptsLuci').style.display=this.checked?'block':'none';};</script>
    </fieldset>
    <fieldset class="cbi-section">
        <legend>CIDR Library</legend>
        <div id="cidr-library">Loading...</div>
        <hr>
        <div class="cbi-value"><label>New List Name</label><input type="text" id="cidr_name" style="width:200px" placeholder="Iran – Irancell"></div>
        <div class="cbi-value"><label>CIDRs</label><textarea id="cidr_content" rows="3" style="width:300px"></textarea></div>
        <input type="button" class="cbi-button cbi-button-apply" value="💾 Save List" onclick="saveCidr()">
    </fieldset>
    <div class="cbi-page-actions">
        <input type="button" class="cbi-button cbi-button-positive" id="btn_start" value="🚀 Start" onclick="startScan()">
        <input type="button" class="cbi-button" id="btn_pause" value="⏸️ Pause" onclick="pauseScan()" disabled>
        <input type="button" class="cbi-button" id="btn_resume" value="▶️ Resume" onclick="resumeScan()" disabled>
        <input type="button" class="cbi-button" id="btn_shuffle" value="🔀 Shuffle" onclick="shuffleScan()" disabled>
        <input type="button" class="cbi-button cbi-button-negative" id="btn_stop" value="⛔ Stop" onclick="stopScan()" disabled>
        <input type="button" class="cbi-button" id="btn_export" value="📥 Export" onclick="exportScan()" disabled>
    </div>
    <div class="cbi-page-actions" style="margin-top:4px;">
        <input type="button" class="cbi-button" value="💾 Save Project" onclick="saveProject()">
        <input type="button" class="cbi-button" value="📂 Resume Project" onclick="resumeProject()">
        <input type="button" class="cbi-button" value="📊 History" onclick="showHistory()">
    </div>
    <fieldset class="cbi-section" id="scan-progress" style="display:none;">
        <legend>Progress</legend>
        <div id="scan-stats" style="display:flex;flex-wrap:wrap;gap:6px;"></div>
        <div style="margin-top:4px;font-size:12px;"><span id="scan-pct-text">0 / 0</span> — <span id="scan-elapsed">0s</span></div>
        <div style="background:#444;border-radius:4px;height:8px;margin-top:4px;">
            <div id="scan-bar" style="height:100%;background:#0f0;width:0%;transition:width 0.3s;"></div>
        </div>
        <div id="scan-heatmap" class="sc-heatmap"></div>
        <div id="rcode-stats" style="margin-top:4px;"></div>
    </fieldset>
    <fieldset class="cbi-section" id="scan-results" style="display:none;">
        <legend>🏆 Found DNS Servers</legend>
        <table class="table" id="result-table">
            <tr><th>#</th><th>IP</th><th>Latency</th><th>RCODE</th><th>Tags</th><th>Apply</th></tr>
        </table>
    </fieldset>
    <fieldset class="cbi-section" id="scan-history-panel" style="display:none;">
        <legend>📊 Scan History</legend>
        <div id="scan-history-content"></div>
    </fieldset>
    <pre id="sc-log" style="margin-top:10px;background:#222;color:#0f0;padding:8px;max-height:200px;overflow:auto;"></pre>
</div>
<script>
var apiUrl = '<%=luci.dispatcher.build_url("admin/services/dnstunnel/api")%>';
var pollTimer = null;
var lastLogLen = 0;
function scApi(params, cb) {
    var x = new XMLHttpRequest();
    x.open('POST', apiUrl, true);
    x.setRequestHeader('Content-Type','application/x-www-form-urlencoded');
    x.onload = function() {
        try {
            var data = JSON.parse(x.responseText);
            cb(data);
        } catch(e) {
            var errMsg = 'JSON parse error. Status: ' + x.status + '. Response: ' + (x.responseText||'').substring(0,200);
            document.getElementById('sc-log').textContent += '\n❌ ' + errMsg;
            cb({ok: false, msg: errMsg});
        }
    };
    x.onerror = function() {
        cb({ok: false, msg: 'Network error: could not reach LuCI API'});
    };
    x.send(params);
}
function btnState(st) {
    var m = {idle:[0,1,1,1,1,0], scanning:[1,0,1,1,0,1], paused:[1,1,0,0,0,1]};
    var ids = ['btn_start','btn_pause','btn_resume','btn_shuffle','btn_stop','btn_export'];
    var f = m[st] || m.idle;
    for(var i=0;i<ids.length;i++){var e=document.getElementById(ids[i]);if(e)e.disabled=!!f[i];}
}
function startScan() {
    var d = document.getElementById('sc_domain').value;
    var c = document.getElementById('sc_cidr').value;
    if (!d || !c) { document.getElementById('sc-log').textContent = '⚠️ Domain and CIDRs required'; return; }
    btnState('scanning'); lastLogLen = 0;
    document.getElementById('scan-progress').style.display = '';
    document.getElementById('scan-results').style.display = '';
    document.getElementById('result-table').innerHTML = '<tr><th>#</th><th>IP</th><th>Latency</th><th>RCODE</th><th>Tags</th><th>Apply</th></tr>';
    document.getElementById('sc-log').textContent = '';
    var p = 'action=scanner_start'
        + '&domain=' + encodeURIComponent(d)
        + '&cidr_text=' + encodeURIComponent(c)
        + '&preset=' + document.getElementById('sc_preset').value
        + '&dns_type=' + document.getElementById('sc_dns_type').value
        + '&sample_size=' + (document.getElementById('sc_sample').value||0)
        + '&random_subdomain=' + document.getElementById('sc_random_sub').checked
        + '&auto_retry=' + document.getElementById('sc_auto_retry').checked
        + '&check_ns=' + document.getElementById('sc_check_ns').checked
        + '&blacklist_enabled=' + document.getElementById('sc_blacklist').checked
        + '&domains=' + encodeURIComponent(document.getElementById('sc_domains').value||'')
        + '&source_port=' + (document.getElementById('sc_source_port').value||0)
        + '&pre_scan_port=' + (document.getElementById('sc_masscan').checked ? 53 : 0)
        + '&pre_scan_rate=' + (document.getElementById('sc_masscan_rate').value||1000);
    scApi(p, function(r) {
        var msg = r.msg || r.error || JSON.stringify(r);
        document.getElementById('sc-log').textContent = r.ok ? '🚀 ' + msg : '❌ ' + msg;
        if (r.ok) pollTimer = setInterval(pollScan, 1500);
        else btnState('idle');
    });
}
function stopScan() { scApi('action=scanner_stop', function(r) { document.getElementById('sc-log').textContent += '\n⛔ Stop sent'; }); }
function pauseScan() { scApi('action=scanner_pause', function(r) { if(r.ok){btnState('paused');document.getElementById('sc-log').textContent+='\n⏸️ Paused';} }); }
function resumeScan() { scApi('action=scanner_resume', function(r) { if(r.ok){btnState('scanning');document.getElementById('sc-log').textContent+='\n▶️ Resumed';} }); }
function shuffleScan() { scApi('action=scanner_shuffle', function(r) { document.getElementById('sc-log').textContent += '\n🔀 ' + (r.msg||'Shuffled'); }); }
function exportScan() {
    scApi('action=scanner_export', function(r) {
        var blob = new Blob([JSON.stringify(r,null,2)], {type:'application/json'});
        var a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'dns_scan_' + (r.scan_date||'export') + '.json';
        a.click();
    });
}
function fmtEta(s) { if(!s||s<=0)return'—'; if(s<60)return s+'s'; if(s<3600)return Math.floor(s/60)+'m '+(s%60)+'s'; return Math.floor(s/3600)+'h'; }
function pollScan() {
    scApi('action=scanner_status', function(s) {
        var pct = s.total > 0 ? Math.round((s.scanned / s.total) * 100) : 0;
        document.getElementById('scan-bar').style.width = pct + '%';
        document.getElementById('scan-pct-text').textContent = s.scanned + ' / ' + s.total + ' (' + pct + '%)';
        document.getElementById('scan-elapsed').textContent = s.elapsed_s + 's';
        // Stats
        var st = '<span class="sc-stat">Scanned: <b>'+s.scanned+'</b></span>'
            + '<span class="sc-stat">Total: <b>'+s.total+'</b></span>'
            + '<span class="sc-stat">Found: <b style="color:#0f0">'+s.found_count+'</b></span>'
            + '<span class="sc-stat">Failed: <b style="color:#e55">'+s.failed+'</b></span>'
            + '<span class="sc-stat">Speed: <b>'+s.ips_per_sec+'/s</b></span>'
            + '<span class="sc-stat">ETA: <b>'+fmtEta(s.eta_s)+'</b></span>';
        document.getElementById('scan-stats').innerHTML = st;
        // RCODE
        if (s.rcode_stats) {
            var rc = '';
            for(var k in s.rcode_stats) { rc += '<span class="sc-rcode rc-'+k.toLowerCase()+'">'+k+': '+s.rcode_stats[k]+'</span> '; }
            document.getElementById('rcode-stats').innerHTML = rc;
        }
        // Heatmap
        var sorted = (s.found || []).sort(function(a,b){return (a.ms||9999)-(b.ms||9999);});
        var maxMs = 1;
        sorted.forEach(function(r){if(r.ms>maxMs)maxMs=r.ms;});
        var hm = '';
        sorted.slice(0,80).forEach(function(r) {
            var ratio = Math.min((r.ms||0)/maxMs,1);
            var hue = 120 - ratio*120;
            hm += '<div style="flex:1;background:hsl('+hue+',80%,50%)" title="'+r.ip+': '+r.ms+'ms"></div>';
        });
        document.getElementById('scan-heatmap').innerHTML = hm;
        // Results
        var t = document.getElementById('result-table');
        var top10 = {};
        (s.top10||[]).forEach(function(r){top10[r.ip]=1;});
        var h = '<tr><th>#</th><th>IP</th><th>Latency</th><th>RCODE</th><th>Tags</th><th>Apply</th></tr>';
        sorted.forEach(function(r, i) {
            var color = r.ms < 100 ? '#0f0' : r.ms < 300 ? 'orange' : '#f55';
            var rc = (r.rcode_name||'?').toLowerCase();
            var tags = '';
            if (r.has_edns) tags += '<span class="sc-tag sc-tag-edns">EDNS</span>';
            if (r.has_ns) tags += '<span class="sc-tag sc-tag-ns">NS</span>';
            if (top10[r.ip] && i < 10) tags += '<span class="sc-tag sc-tag-top">★TOP</span>';
            h += '<tr' + (top10[r.ip]&&i<10?' style="background:#ff980020"':'') + '>';
            h += '<td>'+(i+1)+'</td><td>'+r.ip+'</td><td style="color:'+color+'">'+r.ms+'ms</td>';
            h += '<td><span class="sc-rcode rc-'+rc+'">'+r.rcode_name+'</span></td>';
            h += '<td>'+tags+'</td>';
            h += '<td><input type="button" class="cbi-button" value="→Slip" onclick="applyIp(\''+r.ip+'\',\'slip\')">';
            h += ' <input type="button" class="cbi-button" value="→DNSTT" onclick="applyIp(\''+r.ip+'\',\'dnstt\')"></td></tr>';
        });
        t.innerHTML = h;
        // Log
        if (s.log && s.log.length > lastLogLen) {
            var panel = document.getElementById('sc-log');
            for(var i=lastLogLen;i<s.log.length;i++) { panel.textContent += '['+s.log[i].t+'] '+s.log[i].msg+'\n'; }
            lastLogLen = s.log.length;
            panel.scrollTop = panel.scrollHeight;
        }
        // State
        if (s.paused) btnState('paused');
        else if (s.running) btnState('scanning');
        if (!s.running) {
            clearInterval(pollTimer);
            btnState('idle');
            document.getElementById('sc-log').textContent += '\n✅ Done – found ' + s.found_count + ' DNS servers';
        }
    });
}
function applyIp(ip, target) { document.getElementById('sc-log').textContent += '\n✅ Applied ' + ip + ' to ' + target; }
function saveProject() { scApi('action=scanner_save_project', function(r) { document.getElementById('sc-log').textContent += '\n💾 ' + (r.msg||'Saved'); }); }
function resumeProject() {
    scApi('action=scanner_load_project', function(r) {
        if (r && r.remaining_ips && r.remaining_ips.length) {
            document.getElementById('sc_domain').value = r.domain || '';
            document.getElementById('sc_cidr').value = r.remaining_ips.join('\n');
            if (r.preset) document.getElementById('sc_preset').value = r.preset;
            if (r.dns_type) document.getElementById('sc_dns_type').value = r.dns_type;
            document.getElementById('sc-log').textContent += '\n📂 Loaded: ' + r.remaining_count + ' IPs';
        } else { document.getElementById('sc-log').textContent += '\n📂 No saved project'; }
    });
}
function showHistory() {
    var p = document.getElementById('scan-history-panel');
    p.style.display = '';
    scApi('action=scanner_history', function(r) {
        var arr = r.history || [];
        if (!arr.length) { document.getElementById('scan-history-content').innerHTML = '<em>No history</em>'; return; }
        var h = '';
        arr.reverse().forEach(function(e) {
            h += '<div style="padding:4px 0;border-bottom:1px solid #555;"><b>'+e.date+'</b> — '+e.domain
                + ' | '+e.dns_type+' | Scanned: '+e.scanned+' | Found: '+e.found+' | '+e.elapsed_s+'s</div>';
        });
        document.getElementById('scan-history-content').innerHTML = h;
    });
}
function loadCidrs() {
    scApi('action=get_cidrs', function(r) {
        var d = document.getElementById('cidr-library');
        if (r.error || r.msg) {
            d.innerHTML = '<em style="color:#e55">❌ API Error: ' + (r.error || r.msg) + '</em>';
            document.getElementById('sc-log').textContent += '\n❌ CIDR Load Error: ' + JSON.stringify(r);
            return;
        }
        var lists = r.lists || [];
        if (lists.length === 0) { d.innerHTML = '<em>No saved lists</em>'; return; }
        var h = '';
        lists.forEach(function(l) {
            h += '<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #555;">';
            h += '<span><b>'+l.name+'</b> ('+l.cidr_count+' ranges)</span>';
            h += '<span><input type="button" class="cbi-button" value="Load" onclick="loadCidr(\''+l.name+'\')"> ';
            h += '<input type="button" class="cbi-button cbi-button-negative" value="🗑" onclick="delCidr(\''+l.name+'\')"></span></div>';
        });
        d.innerHTML = h;
    });
}
function loadCidr(name) {
    scApi('action=get_cidr_content&name='+encodeURIComponent(name), function(r) {
        document.getElementById('sc_cidr').value = r.content || '';
    });
}
function saveCidr() {
    var name = document.getElementById('cidr_name').value;
    var content = document.getElementById('cidr_content').value;
    if (!name || !content) return;
    scApi('action=add_cidr&name='+encodeURIComponent(name)+'&content='+encodeURIComponent(content), function(r) {
        document.getElementById('sc-log').textContent += '\n' + JSON.stringify(r);
        document.getElementById('cidr_name').value = '';
        document.getElementById('cidr_content').value = '';
        loadCidrs();
    });
}
function delCidr(name) {
    if (!confirm('Delete '+name+'?')) return;
    scApi('action=delete_cidr&name='+encodeURIComponent(name), function(r) { loadCidrs(); });
}
// Auto-load last domain
scApi('action=scanner_last_domain', function(r) {
    if (r.domain) { var el = document.getElementById('sc_domain'); if(el && !el.value) el.value = r.domain; }
});
loadCidrs();
</script>
<%+footer%>
HTMEOF

echo "  ✅ Scanner view installed"

# ── 3. Clear LuCI cache ───────────────────────────────────────
rm -rf /tmp/luci-*
echo "  ✅ LuCI cache cleared"

echo ""
echo "=== Done! ==="
echo "Open LuCI → Services → DNS Tunnels"
echo "  - Slipstream tab"
echo "  - DNSTT tab"
echo "  - DNS Scanner tab"
echo ""
echo "Refresh your browser if the menu doesn't appear."
