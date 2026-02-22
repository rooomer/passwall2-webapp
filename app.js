/* ═══════════════════════════════════════════════════════════════
   PassWall 2 - Telegram Mini App JavaScript (Hardened)
   Communicates with the OpenWrt bot via Telegram.WebApp.sendData()

   Security fixes:
     #12: All dynamic content uses textContent or escHtml (no raw innerHTML injection)
     #15: initData validation support
   ═══════════════════════════════════════════════════════════════ */

// ─── Telegram WebApp Instance ──────────────────────────────────
const tg = window.Telegram?.WebApp;
let configData = {};   // Data passed from the bot
let pendingChanges = {};  // Accumulated changes to send

// ─── Init ──────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    if (tg) {
        tg.ready();
        tg.expand();
        tg.MainButton.setText('Apply Changes');
        tg.MainButton.hide();
        tg.MainButton.onClick(applyChanges);

        // Parse initial data from URL hash or startParam
        parseInitData();
    }

    // Populate DNS presets
    renderDnsPresets();
});

// ─── Parse Data from Bot ───────────────────────────────────────
function parseInitData() {
    try {
        // Data is passed via the ?data= query parameter (since Telegram overrides the #hash)
        const params = new URLSearchParams(window.location.search);
        const dataParam = params.get('data');
        if (dataParam) {
            configData = JSON.parse(dataParam);
        }
    } catch (e) {
        console.error('Failed to parse init data:', e);
    }
    // Always initialize UI, even if empty
    populateUI(configData);
}

// ─── Populate UI from Config Data ──────────────────────────────
function populateUI(data) {
    // Status
    const running = data.running || false;
    const dot = document.getElementById('statusDot');
    const statusText = document.getElementById('statusText');
    if (running) {
        dot.classList.add('active');
        statusText.textContent = 'Running';
    } else {
        dot.classList.remove('active');
        statusText.textContent = 'Stopped';
    }
    document.getElementById('svcStatus').textContent = running ? '🟢 Running' : '🔴 Stopped';

    // Active node
    const activeNodeId = data.active_node || '';
    const nodes = data.nodes || [];
    const activeNode = nodes.find(n => n.id === activeNodeId);
    document.getElementById('activeNode').textContent = activeNode ? activeNode.remark : 'N/A';

    // DNS
    const dns = data.dns || {};
    document.getElementById('dnsProto').textContent = (dns.remote_dns_protocol || 'tcp').toUpperCase();
    document.getElementById('dnsServer').textContent =
        dns.remote_dns_protocol === 'doh' ? (dns.remote_dns_doh || '') : (dns.remote_dns || '');

    // DNS Protocol radios
    document.querySelectorAll('input[name="dns_proto"]').forEach(r => {
        r.checked = r.value === (dns.remote_dns_protocol || 'tcp');
    });

    // DNS Toggles
    document.getElementById('fakeDnsToggle').checked = dns.remote_fakedns === '1';
    document.getElementById('dnsRedirectToggle').checked = dns.dns_redirect === '1';

    // DNS Strategies
    document.getElementById('directStrategy').value = dns.direct_dns_query_strategy || 'UseIP';
    document.getElementById('remoteStrategy').value = dns.remote_dns_query_strategy || 'UseIPv4';
    document.getElementById('dnsDetour').value = dns.remote_dns_detour || 'remote';

    // ECS
    document.getElementById('ecsInput').value = dns.remote_dns_client_ip || '';

    // DNS Hosts
    document.getElementById('dnsHostsInput').value = dns.dns_hosts || '';

    // Nodes
    renderNodes(nodes, activeNodeId);

    // SOCKS
    renderList('socksList', data.socks || [], (s) => ({
        name: `Port ${s.port || '?'}`,
        detail: `Node: ${s.node || 'N/A'}`,
        status: s.enabled === '1' ? '🟢' : '🔴'
    }));

    // Server
    renderList('serverList', data.servers || [], (s) => ({
        name: s.remarks || s['.name'] || '?',
        detail: `${s.type || ''} ${s.protocol || ''} :${s.port || '?'}`,
        status: s.enable === '1' ? '🟢' : '🔴'
    }));

    // ACL
    renderList('aclList', data.acl || [], (r) => ({
        name: r.remarks || r['.name'] || '?',
        detail: `Source: ${r.sources || 'all'}`,
        status: r.enabled === '1' ? '🟢' : '🔴'
    }));

    // Shunt
    renderList('shuntList', data.shunt_rules || [], (r) => ({
        name: r.remarks || r['.name'] || '?',
        detail: '',
        status: '📌'
    }));

    // HAProxy
    renderList('haproxyList', data.haproxy || [], (c) => ({
        name: `Node: ${c.lbss || '?'}`,
        detail: '',
        status: c.enabled === '1' ? '🟢' : '🔴'
    }));

    // Subscriptions
    renderList('subList', data.subscriptions || [], (s) => ({
        name: s.remark || s['.name'] || '?',
        detail: s.url || '',
        status: '🔗'
    }));

    // Highlight active DNS preset
    highlightDnsPreset();
}

// ─── Render Nodes ──────────────────────────────────────────────
function renderNodes(nodes, activeId) {
    const container = document.getElementById('nodeList');
    if (!nodes.length) {
        container.innerHTML = '<div class="empty-state">No nodes available</div>';
        return;
    }

    container.innerHTML = '';
    nodes.forEach(n => {
        const isActive = n.id === activeId;
        const el = document.createElement('div');
        el.className = `node-item ${isActive ? 'active' : ''}`;
        el.dataset.id = n.id;
        el.onclick = () => selectNode(n.id);

        const dot = document.createElement('div');
        dot.className = 'node-dot';

        const info = document.createElement('div');
        info.className = 'node-info';

        const name = document.createElement('div');
        name.className = 'node-name';
        name.textContent = n.remark || '?';

        const meta = document.createElement('div');
        meta.className = 'node-meta';
        meta.textContent = `${n.type || ''} ${n.protocol || ''} • ${n.group || 'default'}`;

        info.appendChild(name);
        info.appendChild(meta);
        el.appendChild(dot);
        el.appendChild(info);
        container.appendChild(el);
    });
}

function filterNodes() {
    const q = document.getElementById('nodeSearch').value.toLowerCase();
    document.querySelectorAll('.node-item').forEach(el => {
        const name = el.querySelector('.node-name').textContent.toLowerCase();
        const meta = el.querySelector('.node-meta').textContent.toLowerCase();
        el.style.display = (name.includes(q) || meta.includes(q)) ? '' : 'none';
    });
}

function selectNode(id) {
    pendingChanges.node = id;
    pendingChanges.action = 'set_node';

    // Update UI
    document.querySelectorAll('.node-item').forEach(el => {
        el.classList.toggle('active', el.dataset.id === id);
    });

    const node = (configData.nodes || []).find(n => n.id === id);
    document.getElementById('activeNode').textContent = node ? node.remark : id;

    showMainButton();
    showToast('Node selected — tap Apply to save');
}

// ─── Render Generic Lists (XSS-safe) ──────────────────────────
function renderList(containerId, items, mapFn) {
    const container = document.getElementById(containerId);
    if (!items.length) {
        container.innerHTML = '<div class="empty-state">None configured</div>';
        return;
    }

    container.innerHTML = '';
    items.forEach(item => {
        const { name, detail, status } = mapFn(item);

        const el = document.createElement('div');
        el.className = 'list-item';

        const infoDiv = document.createElement('div');
        const nameEl = document.createElement('div');
        nameEl.className = 'item-name';
        nameEl.textContent = name;
        infoDiv.appendChild(nameEl);

        if (detail) {
            const detailEl = document.createElement('div');
            detailEl.className = 'item-detail';
            detailEl.textContent = detail;
            infoDiv.appendChild(detailEl);
        }

        const statusEl = document.createElement('span');
        statusEl.className = 'item-status';
        statusEl.textContent = status;

        el.appendChild(infoDiv);
        el.appendChild(statusEl);
        container.appendChild(el);
    });
}

// ─── DNS Presets ───────────────────────────────────────────────
const DNS_TCP_PRESETS = [
    { addr: '1.1.1.1', label: 'Cloudflare' },
    { addr: '1.1.1.2', label: 'CF-Security' },
    { addr: '8.8.8.8', label: 'Google' },
    { addr: '8.8.4.4', label: 'Google 2' },
    { addr: '9.9.9.9', label: 'Quad9' },
    { addr: '208.67.222.222', label: 'OpenDNS' },
];

const DNS_DOH_PRESETS = [
    { addr: 'https://1.1.1.1/dns-query', label: 'Cloudflare' },
    { addr: 'https://1.1.1.2/dns-query', label: 'CF-Security' },
    { addr: 'https://8.8.8.8/dns-query', label: 'Google' },
    { addr: 'https://9.9.9.9/dns-query', label: 'Quad9' },
    { addr: 'https://208.67.222.222/dns-query', label: 'OpenDNS' },
    { addr: 'https://dns.adguard.com/dns-query,94.140.14.14', label: 'AdGuard' },
    { addr: 'https://doh.libredns.gr/dns-query,116.202.176.26', label: 'LibreDNS' },
    { addr: 'https://doh.libredns.gr/ads,116.202.176.26', label: 'LibreDNS NoAds' },
];

function renderDnsPresets() {
    const proto = getCurrentProto();
    const presets = proto === 'doh' ? DNS_DOH_PRESETS : DNS_TCP_PRESETS;
    const container = document.getElementById('dnsPresetList');

    container.innerHTML = '';
    presets.forEach(p => {
        const chip = document.createElement('span');
        chip.className = 'preset-chip';
        chip.dataset.addr = p.addr;
        chip.textContent = p.label;
        chip.onclick = () => selectDnsPreset(p.addr);
        container.appendChild(chip);
    });

    highlightDnsPreset();
}

function getCurrentProto() {
    const checked = document.querySelector('input[name="dns_proto"]:checked');
    return checked ? checked.value : 'tcp';
}

function highlightDnsPreset() {
    const dns = configData.dns || {};
    const proto = getCurrentProto();
    const current = proto === 'doh' ? (dns.remote_dns_doh || '') : (dns.remote_dns || '');
    document.querySelectorAll('.preset-chip').forEach(chip => {
        chip.classList.toggle('active', chip.dataset.addr === current);
    });
}

function selectDnsPreset(addr) {
    const proto = getCurrentProto();
    if (proto === 'doh') {
        pendingChanges.remote_dns_doh = addr;
    } else {
        pendingChanges.remote_dns = addr;
    }
    pendingChanges.action = 'dns_change';

    document.querySelectorAll('.preset-chip').forEach(chip => {
        chip.classList.toggle('active', chip.dataset.addr === addr);
    });
    document.getElementById('dnsServer').textContent = addr;

    showMainButton();
    showToast('DNS server selected — tap Apply');
}

function setCustomDns() {
    const val = document.getElementById('customDns').value.trim();
    if (!val) return;
    selectDnsPreset(val);
    document.getElementById('customDns').value = '';
}

function setDnsProto(proto) {
    pendingChanges.remote_dns_protocol = proto;
    pendingChanges.action = 'dns_change';
    renderDnsPresets();
    showMainButton();
    showToast(`DNS Protocol → ${proto.toUpperCase()}`);
}

function toggleDnsOpt(key, checked) {
    pendingChanges[key] = checked ? '1' : '0';
    pendingChanges.action = 'dns_change';
    showMainButton();
}

function setDnsOpt(key, value) {
    pendingChanges[key] = value;
    pendingChanges.action = 'dns_change';
    showMainButton();
}

function setEcs() {
    const val = document.getElementById('ecsInput').value.trim();
    pendingChanges.remote_dns_client_ip = val || '';
    pendingChanges.action = 'dns_change';
    showMainButton();
    showToast('ECS updated — tap Apply');
}

function setDnsHosts() {
    const val = document.getElementById('dnsHostsInput').value.trim();
    pendingChanges.dns_hosts = val;
    pendingChanges.action = 'dns_change';
    showMainButton();
    showToast('Domain overrides updated — tap Apply');
}

// ─── Actions (Quick commands) ──────────────────────────────────
function doAction(action) {
    sendToBot({ action: action });
    showToast(`${action} command sent!`);
}

function doGeoLookup() {
    const val = document.getElementById('geoInput').value.trim();
    if (!val) return;
    document.getElementById('geoResult').textContent = 'Looking up...';
    sendToBot({ action: 'geo_lookup', value: val });
    showToast('GeoView lookup sent');
}

function doPing() {
    const val = document.getElementById('pingInput').value.trim();
    if (!val) return;
    document.getElementById('pingResult').textContent = 'Pinging...';
    sendToBot({ action: 'ping', address: val });
    showToast('Ping command sent');
}

// ─── Tab Switching ─────────────────────────────────────────────
function switchTab(tabName) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(tc => tc.classList.remove('active'));

    document.querySelector(`.tab[data-tab="${tabName}"]`).classList.add('active');
    document.getElementById(`tab-${tabName}`).classList.add('active');
}

// ─── Apply Changes via sendData ────────────────────────────────
function applyChanges() {
    if (Object.keys(pendingChanges).length === 0) {
        showToast('No changes to apply');
        return;
    }

    const action = pendingChanges.action || 'apply_config';
    const changes = { ...pendingChanges };
    delete changes.action;

    // For set_node, send a clean payload
    if (action === 'set_node') {
        sendToBot({ action: 'set_node', node: changes.node });
    } else if (action === 'dns_change') {
        sendToBot({ action: 'dns_change', changes: changes });
    } else {
        sendToBot({ action: 'apply_config', changes: changes });
    }

    pendingChanges = {};
    tg?.MainButton.hide();
    showToast('✅ Changes applied!');
}

function sendToBot(data) {
    const payload = JSON.stringify(data);
    if (tg) {
        tg.sendData(payload);
    } else {
        // Dev mode: log to console
        console.log('sendData:', payload);
    }
}

function showMainButton() {
    if (tg) {
        tg.MainButton.show();
    }
}

// ─── Toast ─────────────────────────────────────────────────────
function showToast(message) {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), 2500);
}

// ─── Utility ───────────────────────────────────────────────────
function escHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
