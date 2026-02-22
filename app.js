/* ═══════════════════════════════════════════════════════════════
   PassWall 2 — Telegram Mini App (v3 - Real-Time API)
   Uses fetch() to talk to the OpenWrt router via Cloudflare Tunnel.
   The app NEVER closes — all results are shown live in the UI.
   ═══════════════════════════════════════════════════════════════ */

// ─── Global State ──────────────────────────────────────────────
const tg = window.Telegram?.WebApp;
let API_URL = '';
let SESSION_TOKEN = '';
let configData = {};
let pendingChanges = {};

// ─── Init ──────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    if (tg) {
        tg.ready();
        tg.expand();
        tg.MainButton.setText('Apply Changes');
        tg.MainButton.hide();
        tg.MainButton.onClick(applyChanges);
    }

    // Extract API URL and token from URL params
    const params = new URLSearchParams(window.location.search);
    API_URL = params.get('api') || '';
    SESSION_TOKEN = params.get('token') || '';

    if (API_URL) {
        loadConfig();
    } else {
        // Fallback: try old ?d= param for backward compatibility
        parseOldInitData(params);
    }
    renderDnsPresets();
});

// ═══════════════════════════════════════════════════════════════
//  API COMMUNICATION (Real-Time via fetch)
// ═══════════════════════════════════════════════════════════════

async function apiCall(endpoint, method = 'GET', body = null) {
    const opts = {
        method,
        headers: {
            'Authorization': `Bearer ${SESSION_TOKEN}`,
            'Content-Type': 'application/json',
        },
    };
    if (body) opts.body = JSON.stringify(body);

    try {
        const resp = await fetch(`${API_URL}${endpoint}`, opts);
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.error || `HTTP ${resp.status}`);
        }
        return await resp.json();
    } catch (e) {
        console.error(`API error (${endpoint}):`, e);
        showToast(`❌ ${e.message}`);
        throw e;
    }
}

// ─── Load Full Config from Router ──────────────────────────────
async function loadConfig() {
    showToast('Loading config...');
    try {
        configData = await apiCall('/api/config');
        populateUI(configData);
        showToast('✅ Config loaded!');
    } catch (e) {
        showToast('❌ Failed to load config');
    }
}

// ─── Backward Compatibility (old ?d= param) ───────────────────
function parseOldInitData(params) {
    try {
        const dataParam = params.get('d') || params.get('data');
        if (dataParam) {
            const raw = JSON.parse(dataParam);
            configData = {
                running: raw.s || false,
                active_node: raw.n || '',
                nodes: (raw.nl || []).map(n => ({
                    id: n.i || n.id,
                    remark: n.r || n.remark,
                    type: n.t || n.type || '',
                    protocol: n.p || n.protocol || '',
                    group: n.g || n.group || '',
                    address: n.a || n.address || '',
                    port: n.pt || n.port || '',
                })),
                dns: {
                    remote_dns_protocol: raw.dp || 'tcp',
                    remote_dns: raw.ds || '',
                    remote_dns_doh: raw.dd || '',
                    remote_fakedns: raw.df || '0',
                    dns_redirect: raw.dr || '1',
                    remote_dns_query_strategy: raw.dqs || 'UseIPv4',
                    direct_dns_query_strategy: raw.dqd || 'UseIP',
                    remote_dns_detour: raw.det || 'remote',
                },
                acl: raw.acl || [],
                shunt_rules: raw.shunt_rules || [],
                socks: raw.socks || [],
                haproxy: raw.haproxy || [],
            };
        }
    } catch (e) {
        console.error('parseOldInitData:', e);
    }
    populateUI(configData);
}

// ═══════════════════════════════════════════════════════════════
//  POPULATE UI
// ═══════════════════════════════════════════════════════════════

function populateUI(data) {
    // Status
    const running = data.running || false;
    const dot = document.getElementById('statusDot');
    const statusText = document.getElementById('statusText');
    if (running) { dot.classList.add('active'); statusText.textContent = 'Running'; }
    else { dot.classList.remove('active'); statusText.textContent = 'Stopped'; }
    document.getElementById('svcStatus').textContent = running ? '🟢 Running' : '🔴 Stopped';

    // Active node
    const activeId = data.active_node || '';
    const nodes = data.nodes || [];
    const activeNode = nodes.find(n => n.id === activeId);
    document.getElementById('activeNode').textContent = activeNode ? activeNode.remark : 'N/A';

    // DNS
    const dns = data.dns || {};
    document.getElementById('dnsProto').textContent = (dns.remote_dns_protocol || 'tcp').toUpperCase();
    document.getElementById('dnsServer').textContent =
        dns.remote_dns_protocol === 'doh' ? (dns.remote_dns_doh || '') : (dns.remote_dns || '');
    document.querySelectorAll('input[name="dns_proto"]').forEach(r => {
        r.checked = r.value === (dns.remote_dns_protocol || 'tcp');
    });
    document.getElementById('fakeDnsToggle').checked = dns.remote_fakedns === '1';
    document.getElementById('dnsRedirectToggle').checked = dns.dns_redirect === '1';
    document.getElementById('directStrategy').value = dns.direct_dns_query_strategy || 'UseIP';
    document.getElementById('remoteStrategy').value = dns.remote_dns_query_strategy || 'UseIPv4';
    document.getElementById('dnsDetour').value = dns.remote_dns_detour || 'remote';
    document.getElementById('ecsInput').value = dns.remote_dns_client_ip || '';
    document.getElementById('dnsHostsInput').value = dns.dns_hosts || '';

    // Nodes
    renderNodes(nodes, activeId);
    // ACL, Shunt, SOCKS, HAProxy, etc.
    renderACL(data.acl || []);
    renderShuntRules(data.shunt_rules || []);
    renderList('socksList', data.socks || [], s => ({
        name: `Port ${s.port || '?'}`, detail: `Node: ${s.node || 'N/A'}`, status: s.enabled === '1' ? '🟢' : '🔴'
    }));
    renderList('serverList', data.servers || [], s => ({
        name: s.remarks || s['.name'] || '?', detail: `${s.type || ''} :${s.port || '?'}`, status: s.enable === '1' ? '🟢' : '🔴'
    }));
    renderList('haproxyList', data.haproxy || [], c => ({
        name: `Node: ${c.lbss || '?'}`, detail: '', status: c.enabled === '1' ? '🟢' : '🔴'
    }));
    renderList('subList', data.subscriptions || [], s => ({
        name: s.remark || s['.name'] || '?', detail: s.url || '', status: '🔗'
    }));
    highlightDnsPreset();
}

// ═══════════════════════════════════════════════════════════════
//  NODE MANAGEMENT (Live API)
// ═══════════════════════════════════════════════════════════════

function renderNodes(nodes, activeId) {
    const container = document.getElementById('nodeList');
    if (!nodes.length) {
        container.innerHTML = '<div class="empty-state">No nodes available</div>';
        return;
    }
    container.innerHTML = '';
    nodes.forEach(n => {
        const isActive = (n.id === activeId);
        const el = document.createElement('div');
        el.className = `node-item ${isActive ? 'active' : ''}`;
        el.dataset.id = n.id;

        const dot = document.createElement('div');
        dot.className = 'node-dot';

        const info = document.createElement('div');
        info.className = 'node-info';
        info.onclick = () => selectNode(n.id);

        const name = document.createElement('div');
        name.className = 'node-name';
        name.textContent = n.remark || '?';

        const meta = document.createElement('div');
        meta.className = 'node-meta';
        meta.textContent = `${n.type || ''} ${n.protocol || ''} • ${n.group || ''}`;

        const latency = document.createElement('span');
        latency.className = 'node-latency';
        latency.id = `lat-${n.id}`;

        info.appendChild(name);
        info.appendChild(meta);
        el.appendChild(dot);
        el.appendChild(info);
        el.appendChild(latency);

        // Action buttons
        const actions = document.createElement('div');
        actions.className = 'node-actions';

        const pingBtn = makeBtn('📡', 'btn-info', 'Ping', () => pingNode(n));
        const tcpBtn = makeBtn('🔌', 'btn-warning', 'TCPing', () => tcpingNode(n));
        const useBtn = makeBtn('✅', 'btn-success', 'Use', () => selectNode(n.id));
        const detBtn = makeBtn('ℹ️', 'btn-secondary', 'Detail', () => openNodeModal(n));
        const delBtn = makeBtn('🗑️', 'btn-danger', 'Delete', () => deleteNode(n.id, n.remark));

        [pingBtn, tcpBtn, useBtn, detBtn, delBtn].forEach(b => actions.appendChild(b));
        el.appendChild(actions);
        container.appendChild(el);
    });
}

function makeBtn(icon, cls, title, onClick) {
    const b = document.createElement('button');
    b.className = `btn btn-xs ${cls}`;
    b.textContent = icon;
    b.title = title;
    b.onclick = (e) => { e.stopPropagation(); onClick(); };
    return b;
}

function filterNodes() {
    const q = document.getElementById('nodeSearch').value.toLowerCase();
    document.querySelectorAll('.node-item').forEach(el => {
        const name = el.querySelector('.node-name')?.textContent.toLowerCase() || '';
        const meta = el.querySelector('.node-meta')?.textContent.toLowerCase() || '';
        el.style.display = (name.includes(q) || meta.includes(q)) ? '' : 'none';
    });
}

async function selectNode(id) {
    if (!API_URL) {
        // Fallback to old sendData
        pendingChanges.node = id;
        pendingChanges.action = 'set_node';
        showMainButton();
        showToast('Node selected — tap Apply');
        return;
    }
    showToast('🔄 Switching node...');
    try {
        const r = await apiCall('/api/action/set_node', 'POST', { node: id });
        if (r.ok) {
            showToast('✅ Node switched & restarting!');
            document.querySelectorAll('.node-item').forEach(el => el.classList.toggle('active', el.dataset.id === id));
            const node = (configData.nodes || []).find(n => n.id === id);
            document.getElementById('activeNode').textContent = node ? node.remark : id;
        } else {
            showToast(`❌ ${r.error || 'Failed'}`);
        }
    } catch (e) { /* error already shown by apiCall */ }
}

async function deleteNode(id, name) {
    if (!confirm(`Delete node "${name || id}"?`)) return;
    try {
        const r = await apiCall('/api/action/delete_node', 'POST', { node: id });
        if (r.ok) {
            showToast('🗑️ Node deleted!');
            document.querySelector(`.node-item[data-id="${id}"]`)?.remove();
        } else { showToast(`❌ ${r.msg || 'Failed'}`); }
    } catch (e) { }
}

async function pingNode(node) {
    const latEl = document.getElementById(`lat-${node.id}`);
    if (latEl) { latEl.textContent = '...'; latEl.className = 'node-latency pinging'; }
    try {
        const r = await apiCall('/api/action/ping', 'POST', { address: node.address });
        if (latEl) {
            latEl.textContent = r.ok ? `${r.ms}ms` : '✕';
            latEl.className = `node-latency ${r.ok ? '' : 'timeout'}`;
        }
    } catch (e) {
        if (latEl) { latEl.textContent = '✕'; latEl.className = 'node-latency timeout'; }
    }
}

async function tcpingNode(node) {
    const latEl = document.getElementById(`lat-${node.id}`);
    if (latEl) { latEl.textContent = '...'; latEl.className = 'node-latency pinging'; }
    try {
        const r = await apiCall('/api/action/tcping', 'POST', { address: node.address, port: node.port || '443' });
        if (latEl) {
            latEl.textContent = r.ok ? `${r.ms}ms` : '✕';
            latEl.className = `node-latency ${r.ok ? '' : 'timeout'}`;
        }
    } catch (e) {
        if (latEl) { latEl.textContent = '✕'; latEl.className = 'node-latency timeout'; }
    }
}

async function pingAllNodes() {
    if (!API_URL) { showToast('API not connected'); return; }
    showToast('📡 Pinging all nodes...');
    // Set all to "..."
    (configData.nodes || []).forEach(n => {
        const el = document.getElementById(`lat-${n.id}`);
        if (el) { el.textContent = '...'; el.className = 'node-latency pinging'; }
    });
    try {
        const r = await apiCall('/api/action/ping_all', 'POST', {});
        (r.results || []).forEach(nr => {
            const el = document.getElementById(`lat-${nr.id}`);
            if (el) {
                el.textContent = nr.ok ? `${nr.ms}ms` : '✕';
                el.className = `node-latency ${nr.ok ? '' : 'timeout'}`;
            }
        });
        showToast('✅ Ping All complete!');
    } catch (e) { showToast('❌ Ping All failed'); }
}

function addNodeFromUrl() {
    const url = document.getElementById('shareUrlInput').value.trim();
    if (!url) return;
    // This uses old sendData since add_node_url is a one-shot
    if (API_URL) {
        apiCall('/api/action/add_node_url', 'POST', { url }).then(r => {
            showToast(r.ok ? '➕ Node added!' : '❌ Failed');
            document.getElementById('shareUrlInput').value = '';
            loadConfig(); // Reload to show new node
        }).catch(() => { });
    }
}

// ─── Node Detail Modal (with both ping types) ─────────────────
function openNodeModal(node) {
    const body = document.getElementById('nodeModalBody');
    document.getElementById('nodeModalTitle').textContent = `📋 ${escHtml(node.remark || '?')}`;
    body.innerHTML = '';

    const grid = document.createElement('div');
    grid.className = 'status-grid';
    [['Name', node.remark], ['Type', node.type], ['Protocol', node.protocol],
    ['Address', node.address], ['Port', node.port], ['Group', node.group], ['ID', node.id]
    ].forEach(([label, val]) => {
        const item = document.createElement('div');
        item.className = 'status-item';
        item.innerHTML = `<span class="status-label">${label}</span><span class="status-value">${escHtml(val || '—')}</span>`;
        grid.appendChild(item);
    });
    body.appendChild(grid);

    const pingRes = document.getElementById('nodePingResult');
    pingRes.style.display = 'none';

    document.getElementById('nodeUseBtn').onclick = () => { selectNode(node.id); closeNodeModal(); };
    document.getElementById('nodePingBtn').onclick = async () => {
        pingRes.style.display = 'block';
        pingRes.textContent = 'Testing...';
        try {
            const r = await apiCall('/api/action/ping_node', 'POST', {
                address: node.address, port: node.port, node_id: node.id
            });
            pingRes.textContent =
                `ICMP:    ${r.icmp_ms ? r.icmp_ms + ' ms' : '❌ timeout'}\n` +
                `TCPing:  ${r.tcp_ms ? r.tcp_ms + ' ms' : '❌ timeout'}`;
        } catch (e) { pingRes.textContent = '❌ Test failed'; }
    };
    document.getElementById('nodeCopyBtn').onclick = async () => {
        try {
            const r = await apiCall('/api/action/copy_node', 'POST', { node: node.id });
            showToast(r.ok ? '📋 Node copied!' : '❌ Failed');
            closeNodeModal();
            loadConfig();
        } catch (e) { }
    };
    document.getElementById('nodeDelBtn').onclick = async () => {
        if (confirm(`Delete "${node.remark}"?`)) {
            await deleteNode(node.id, node.remark);
            closeNodeModal();
        }
    };

    document.getElementById('nodeModal').style.display = 'flex';
}
function closeNodeModal() { document.getElementById('nodeModal').style.display = 'none'; }

// ═══════════════════════════════════════════════════════════════
//  ACL MANAGEMENT
// ═══════════════════════════════════════════════════════════════

function renderACL(rules) {
    const container = document.getElementById('aclList');
    if (!rules.length) { container.innerHTML = '<div class="empty-state">No ACL rules</div>'; return; }
    container.innerHTML = '';
    rules.forEach(r => {
        const el = document.createElement('div');
        el.className = 'list-item list-item-interactive';
        const infoDiv = document.createElement('div');
        infoDiv.innerHTML = `<div class="item-name">${escHtml(r.remarks || r['.name'] || '?')}</div><div class="item-detail">Source: ${escHtml(r.sources || 'all')}</div>`;

        const toggleLabel = document.createElement('label');
        toggleLabel.className = 'switch switch-sm';
        const input = document.createElement('input');
        input.type = 'checkbox';
        input.checked = r.enabled === '1';
        input.onchange = async () => {
            try {
                await apiCall('/api/action/set_acl', 'POST', { id: r['.name'], enabled: input.checked ? '1' : '0' });
                showToast(`ACL ${r.remarks || '?'}: ${input.checked ? 'enabled' : 'disabled'}`);
            } catch (e) { }
        };
        const slider = document.createElement('span');
        slider.className = 'slider';
        toggleLabel.appendChild(input);
        toggleLabel.appendChild(slider);
        el.appendChild(infoDiv);
        el.appendChild(toggleLabel);
        container.appendChild(el);
    });
}

// ═══════════════════════════════════════════════════════════════
//  SHUNT RULES
// ═══════════════════════════════════════════════════════════════

function renderShuntRules(rules) {
    const container = document.getElementById('shuntList');
    if (!rules.length) { container.innerHTML = '<div class="empty-state">No shunt rules</div>'; return; }
    container.innerHTML = '';
    rules.forEach(r => {
        const el = document.createElement('div');
        el.className = 'shunt-item';
        const domainCount = (r.domain_list || '').split('\n').filter(x => x.trim()).length;
        const ipCount = (r.ip_list || '').split('\n').filter(x => x.trim()).length;
        el.innerHTML = `<div class="shunt-header"><span class="shunt-name">${escHtml(r.remarks || r['.name'] || '?')}</span><button class="btn btn-xs btn-primary" onclick="openShuntModal(${JSON.stringify(r).replace(/"/g, '&quot;')})">✏️ Edit</button></div><div class="shunt-preview">📂 ${domainCount} domains, 🌐 ${ipCount} IPs</div>`;
        container.appendChild(el);
    });
}

let currentShuntRule = null;
function openShuntModal(rule) {
    currentShuntRule = typeof rule === 'string' ? JSON.parse(rule) : rule;
    document.getElementById('shuntModalTitle').textContent = `📝 ${escHtml(currentShuntRule.remarks || currentShuntRule['.name'] || 'Rule')}`;
    document.getElementById('shuntDomains').value = currentShuntRule.domain_list || '';
    document.getElementById('shuntIPs').value = currentShuntRule.ip_list || '';
    document.getElementById('shuntSaveBtn').onclick = async () => {
        try {
            await apiCall('/api/action/set_shunt', 'POST', {
                rule_name: currentShuntRule['.name'],
                domain_list: document.getElementById('shuntDomains').value,
                ip_list: document.getElementById('shuntIPs').value,
            });
            showToast('💾 Shunt rule saved!');
            closeShuntModal();
        } catch (e) { }
    };
    document.getElementById('shuntModal').style.display = 'flex';
}
function closeShuntModal() { document.getElementById('shuntModal').style.display = 'none'; }

// ═══════════════════════════════════════════════════════════════
//  GENERIC LIST RENDERER
// ═══════════════════════════════════════════════════════════════

function renderList(containerId, items, mapFn) {
    const container = document.getElementById(containerId);
    if (!items.length) { container.innerHTML = '<div class="empty-state">None configured</div>'; return; }
    container.innerHTML = '';
    items.forEach(item => {
        const { name, detail, status } = mapFn(item);
        const el = document.createElement('div');
        el.className = 'list-item';
        const infoDiv = document.createElement('div');
        infoDiv.innerHTML = `<div class="item-name">${escHtml(name)}</div>${detail ? `<div class="item-detail">${escHtml(detail)}</div>` : ''}`;
        const statusEl = document.createElement('span');
        statusEl.className = 'item-status';
        statusEl.textContent = status;
        el.appendChild(infoDiv);
        el.appendChild(statusEl);
        container.appendChild(el);
    });
}

// ═══════════════════════════════════════════════════════════════
//  DNS PRESETS
// ═══════════════════════════════════════════════════════════════

const DNS_TCP_PRESETS = [
    { addr: '1.1.1.1', label: 'Cloudflare' }, { addr: '1.1.1.2', label: 'CF-Security' },
    { addr: '8.8.8.8', label: 'Google' }, { addr: '8.8.4.4', label: 'Google 2' },
    { addr: '9.9.9.9', label: 'Quad9' }, { addr: '208.67.222.222', label: 'OpenDNS' },
];
const DNS_DOH_PRESETS = [
    { addr: 'https://1.1.1.1/dns-query', label: 'Cloudflare' },
    { addr: 'https://8.8.8.8/dns-query', label: 'Google' },
    { addr: 'https://9.9.9.9/dns-query', label: 'Quad9' },
    { addr: 'https://dns.adguard.com/dns-query,94.140.14.14', label: 'AdGuard' },
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
    if (proto === 'doh') pendingChanges.remote_dns_doh = addr;
    else pendingChanges.remote_dns = addr;
    pendingChanges.action = 'dns_change';
    document.querySelectorAll('.preset-chip').forEach(c => c.classList.toggle('active', c.dataset.addr === addr));
    document.getElementById('dnsServer').textContent = addr;
    showMainButton();
    showToast('DNS selected — tap Apply');
}

function setCustomDns() {
    const val = document.getElementById('customDns').value.trim();
    if (val) { selectDnsPreset(val); document.getElementById('customDns').value = ''; }
}

function setDnsProto(proto) {
    pendingChanges.remote_dns_protocol = proto;
    pendingChanges.action = 'dns_change';
    renderDnsPresets();
    showMainButton();
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
    pendingChanges.remote_dns_client_ip = document.getElementById('ecsInput').value.trim();
    pendingChanges.action = 'dns_change';
    showMainButton();
    showToast('ECS updated — tap Apply');
}

function setDnsHosts() {
    pendingChanges.dns_hosts = document.getElementById('dnsHostsInput').value.trim();
    pendingChanges.action = 'dns_change';
    showMainButton();
    showToast('Overrides updated — tap Apply');
}

// ═══════════════════════════════════════════════════════════════
//  SETTINGS (Instant via API)
// ═══════════════════════════════════════════════════════════════

async function setForwarding(key, value) {
    try {
        await apiCall('/api/action/set_forwarding', 'POST', { key, value });
        showToast(`✅ ${key} → ${value}`);
    } catch (e) { }
}

async function setDelay(key, value) {
    try {
        await apiCall('/api/action/set_delay', 'POST', { key, value });
        showToast(`✅ ${key} → ${value}`);
    } catch (e) { }
}

async function setGlobalOpt(key, value) {
    try {
        await apiCall('/api/action/set_global', 'POST', { key, value });
        showToast(`✅ ${key} → ${value}`);
    } catch (e) { }
}

// ═══════════════════════════════════════════════════════════════
//  ACTIONS
// ═══════════════════════════════════════════════════════════════

async function doAction(action) {
    showToast(`🔄 ${action}...`);
    try {
        const r = await apiCall(`/api/action/${action}`, 'POST', {});
        showToast(`✅ ${r.msg || action + ' done!'}`);
        // Refresh status after service actions
        if (['start', 'stop', 'restart'].includes(action)) {
            setTimeout(loadConfig, 2000);
        }
    } catch (e) { }
}

async function doGeoLookup() {
    const val = document.getElementById('geoInput').value.trim();
    if (!val) return;
    const resEl = document.getElementById('geoResult');
    resEl.textContent = 'Looking up...';
    try {
        const r = await apiCall('/api/action/geo_lookup', 'POST', { value: val });
        resEl.textContent = r.result || 'No result';
    } catch (e) { resEl.textContent = '❌ Lookup failed'; }
}

async function doPing() {
    const val = document.getElementById('pingInput').value.trim();
    if (!val) return;
    const resEl = document.getElementById('pingResult');
    resEl.textContent = 'Pinging...';
    try {
        const r = await apiCall('/api/action/ping', 'POST', { address: val });
        resEl.textContent = r.ok ? `${r.ms} ms` : '❌ Timeout';
    } catch (e) { resEl.textContent = '❌ Failed'; }
}

// ═══════════════════════════════════════════════════════════════
//  TABS
// ═══════════════════════════════════════════════════════════════

function switchTab(tabName) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(tc => tc.classList.remove('active'));
    document.querySelector(`.tab[data-tab="${tabName}"]`)?.classList.add('active');
    document.getElementById(`tab-${tabName}`)?.classList.add('active');
}

// ═══════════════════════════════════════════════════════════════
//  APPLY CHANGES (DNS batch — everything else is instant)
// ═══════════════════════════════════════════════════════════════

async function applyChanges() {
    if (Object.keys(pendingChanges).length === 0) { showToast('No changes'); return; }

    const action = pendingChanges.action || 'apply_config';
    const changes = { ...pendingChanges };
    delete changes.action;

    showToast('🔄 Applying...');
    try {
        if (action === 'set_node') {
            await apiCall('/api/action/set_node', 'POST', { node: changes.node });
        } else if (action === 'dns_change') {
            await apiCall('/api/action/dns_change', 'POST', { changes });
        } else {
            await apiCall('/api/config', 'POST', { changes });
        }
        showToast('✅ Changes applied!');
        pendingChanges = {};
        tg?.MainButton.hide();
        setTimeout(loadConfig, 1500);
    } catch (e) { showToast('❌ Apply failed'); }
}

function showMainButton() { if (tg) tg.MainButton.show(); }

// ═══════════════════════════════════════════════════════════════
//  UTILITY
// ═══════════════════════════════════════════════════════════════

function showToast(msg) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 2500);
}

function escHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
