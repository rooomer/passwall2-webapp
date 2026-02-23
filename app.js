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
    const headers = {
        'Authorization': `Bearer ${SESSION_TOKEN}`,
        'Accept': 'application/json',
    };
    // Only set Content-Type for requests with a body
    if (body) headers['Content-Type'] = 'application/json';

    const opts = { method, headers, mode: 'cors' };
    if (body) opts.body = JSON.stringify(body);

    try {
        const resp = await fetch(`${API_URL}${endpoint}`, opts);
        if (!resp.ok) {
            let errMsg = `HTTP ${resp.status}`;
            try { const err = await resp.json(); errMsg = err.error || errMsg; } catch (e) { }
            throw new Error(errMsg);
        }
        return await resp.json();
    } catch (e) {
        const msg = e.message || 'Network error';
        console.error(`API error (${endpoint}):`, e);
        // Show user-friendly error for common issues
        if (msg.includes('Failed to fetch') || msg.includes('NetworkError')) {
            showToast('❌ Cannot reach router API. Tunnel may be down.');
        } else {
            showToast(`❌ ${msg}`);
        }
        throw e;
    }
}

// ─── Load Full Config from Router ──────────────────────────────
async function loadConfig(retries = 30, delay = 5000) {
    showToast('⏳ Connecting to router...');
    for (let attempt = 1; attempt <= retries; attempt++) {
        try {
            configData = await apiCall('/api/config');
            populateUI(configData);
            showToast('✅ Config loaded!');
            return; // success!
        } catch (e) {
            if (attempt < retries) {
                const mins = Math.floor((attempt * delay / 1000) / 60);
                const secs = Math.floor((attempt * delay / 1000) % 60);
                showToast(`⏳ Tunnel warming up... ${mins}:${String(secs).padStart(2, '0')} (retry ${attempt}/${retries})`);
                await new Promise(r => setTimeout(r, delay));
                // Keep delay at 10s after first few tries
                if (delay < 10000) delay = Math.min(delay * 1.3, 10000);
            } else {
                showToast('❌ Failed to connect — try refreshing the page');
            }
        }
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
    renderShuntNodes(data.shunt_nodes || []);
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
        info.onclick = () => openNodeModal(n);

        const name = document.createElement('div');
        name.className = 'node-name';
        name.textContent = n.remark || '?';

        const meta = document.createElement('div');
        meta.className = 'node-meta';
        const addr = n.address || '';
        const port = n.port || '';
        const addrStr = addr ? `${addr}${port ? ':' + port : ''}` : '';
        meta.textContent = `${n.type || ''} ${n.protocol || ''} ${addrStr ? '• ' + addrStr : ''}`;

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
        const editBtn = makeBtn('✏️', 'btn-primary', 'Edit', () => openNodeEditModal(n));
        const delBtn = makeBtn('🗑️', 'btn-danger', 'Delete', () => deleteNode(n.id, n.remark));

        [pingBtn, tcpBtn, useBtn, editBtn, delBtn].forEach(b => actions.appendChild(b));
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

function latencyClass(ms) {
    const n = parseFloat(ms);
    if (!n || n <= 0) return 'latency-bad';
    if (n < 100) return 'latency-good';
    if (n < 200) return 'latency-ok';
    return 'latency-slow';
}

function pingNode(node) {
    const el = document.getElementById(`lat-${node.id}`);
    if (el) { el.textContent = '⏳'; el.className = 'node-latency'; }
    apiCall('/api/action/ping', 'POST', { address: node.address }).then(r => {
        if (el) {
            if (r.ok) {
                el.textContent = `${r.ms}ms`;
                el.className = `node-latency ${latencyClass(r.ms)}`;
            } else {
                el.textContent = '❌';
                el.className = 'node-latency latency-bad';
            }
        }
    }).catch(() => { if (el) { el.textContent = '❌'; el.className = 'node-latency latency-bad'; } });
}

async function tcpingNode(node) {
    const el = document.getElementById(`lat-${node.id}`);
    if (el) { el.textContent = '⏳'; el.className = 'node-latency'; }
    apiCall('/api/action/tcping', 'POST', { address: node.address, port: node.port || '443' }).then(r => {
        if (el) {
            if (r.ok) {
                el.textContent = `${r.ms}ms`;
                el.className = `node-latency ${latencyClass(r.ms)}`;
            } else {
                el.textContent = '❌';
                el.className = 'node-latency latency-bad';
            }
        }
    }).catch(() => { if (el) { el.textContent = '❌'; el.className = 'node-latency latency-bad'; } });
}

function pingAllNodes() {
    showToast('📡 Pinging all nodes...');
    // Set all to loading
    document.querySelectorAll('.node-latency').forEach(el => {
        el.textContent = '⏳'; el.className = 'node-latency';
    });
    apiCall('/api/action/ping_all', 'POST', {}).then(r => {
        if (r.results) {
            r.results.forEach(res => {
                const el = document.getElementById(`lat-${res.id}`);
                if (el) {
                    if (res.ok) {
                        el.textContent = `${res.ms}ms`;
                        el.className = `node-latency ${latencyClass(res.ms)}`;
                    } else {
                        el.textContent = '❌';
                        el.className = 'node-latency latency-bad';
                    }
                }
            });
            showToast(`✅ Pinged ${r.results.length} nodes`);
        }
    }).catch(() => showToast('❌ Ping all failed'));
}

async function addNodeFromUrl() {
    const raw = document.getElementById('shareUrlInput').value.trim();
    if (!raw) return;
    // Support multi-line paste — one URL per line
    const urls = raw.split('\n').map(s => s.trim()).filter(s => s && s.includes('://'));
    if (!urls.length) { showToast('❌ No valid URLs'); return; }
    if (!API_URL) return;
    let added = 0, failed = 0;
    showToast(`➕ Adding ${urls.length} node(s)...`);
    for (const url of urls) {
        try {
            const r = await apiCall('/api/action/add_node_url', 'POST', { url });
            if (r.ok) added++; else failed++;
        } catch { failed++; }
    }
    document.getElementById('shareUrlInput').value = '';
    showToast(`✅ ${added} added${failed ? `, ❌ ${failed} failed` : ''}`);
    loadConfig();
}

// ─── Node Detail Modal (with both ping types) ─────────────────
function openNodeModal(node) {
    const body = document.getElementById('nodeModalBody');
    document.getElementById('nodeModalTitle').textContent = `📋 ${escHtml(node.remark || '?')}`;
    body.innerHTML = '';

    // Show ALL fields from the node (full UCI data)
    const grid = document.createElement('div');
    grid.className = 'status-grid';
    // Priority fields first, then all others
    const priorityKeys = ['remark', 'type', 'protocol', 'address', 'port', 'group',
        'uuid', 'password', 'transport', 'tls', 'tls_serverName', 'security',
        'encryption', 'flow', 'reality', 'reality_publicKey'];
    const skipKeys = new Set(['.name', '.type', 'id', 'remarks']);
    const shown = new Set();

    const addField = (label, val) => {
        if (!val && val !== '0') return;
        const item = document.createElement('div');
        item.className = 'status-item';
        item.innerHTML = `<span class="status-label">${escHtml(label)}</span><span class="status-value" style="word-break:break-all">${escHtml(String(val))}</span>`;
        grid.appendChild(item);
    };

    // Show priority fields first
    priorityKeys.forEach(key => {
        if (node[key]) { addField(key, node[key]); shown.add(key); }
    });
    addField('ID', node.id); shown.add('id');

    // Show remaining fields
    Object.keys(node).forEach(key => {
        if (!shown.has(key) && !skipKeys.has(key)) {
            addField(key, node[key]);
        }
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
            const icmpCls = r.icmp_ms ? latencyClass(r.icmp_ms) : '';
            const tcpCls = r.tcp_ms ? latencyClass(r.tcp_ms) : '';
            pingRes.innerHTML =
                `ICMP:   <span class="${icmpCls}">${r.icmp_ms ? r.icmp_ms + ' ms' : '❌ timeout'}</span>\n` +
                `TCPing: <span class="${tcpCls}">${r.tcp_ms ? r.tcp_ms + ' ms' : '❌ timeout'}</span>`;
        } catch (e) { pingRes.textContent = '❌ Test failed'; }
    };
    document.getElementById('nodeEditBtn').onclick = () => { closeNodeModal(); openNodeEditModal(node); };
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

// ─── Node Edit Modal ───────────────────────────────────────────
let currentEditNode = null;
const NODE_EDIT_FIELDS = [
    { key: 'remarks', label: 'Remarks', type: 'text' },
    { key: 'type', label: 'Type', type: 'select', options: ['Xray', 'sing-box', 'Hysteria2', 'SS', 'SSR', 'Brook'] },
    { key: 'protocol', label: 'Protocol', type: 'select', options: ['vless', 'vmess', 'trojan', 'shadowsocks', 'socks', 'http', 'wireguard', 'hysteria2', 'tuic'] },
    { key: 'address', label: 'Address', type: 'text' },
    { key: 'port', label: 'Port', type: 'text' },
    { key: 'uuid', label: 'UUID / User ID', type: 'text' },
    { key: 'password', label: 'Password', type: 'text' },
    { key: 'security', label: 'Security', type: 'text' },
    { key: 'encryption', label: 'Encryption', type: 'text' },
    { key: 'flow', label: 'Flow Control', type: 'select', options: ['', 'xtls-rprx-vision', 'xtls-rprx-vision-udp443'] },
    { key: 'transport', label: 'Transport', type: 'select', options: ['', 'raw', 'ws', 'grpc', 'h2', 'httpupgrade', 'xhttp', 'mkcp', 'quic'] },
    { key: 'tls', label: 'TLS', type: 'select', options: ['0', '1'] },
    { key: 'tls_serverName', label: 'TLS Server Name (SNI)', type: 'text' },
    { key: 'tls_allowInsecure', label: 'Allow Insecure', type: 'select', options: ['0', '1'] },
    { key: 'fingerprint', label: 'uTLS Fingerprint', type: 'select', options: ['', 'chrome', 'firefox', 'safari', 'edge', 'ios', 'android', 'random', 'randomized'] },
    { key: 'alpn', label: 'ALPN', type: 'text' },
    { key: 'reality', label: 'Reality', type: 'select', options: ['0', '1'] },
    { key: 'reality_publicKey', label: 'Reality Public Key', type: 'text' },
    { key: 'reality_shortId', label: 'Reality Short ID', type: 'text' },
    { key: 'reality_spiderX', label: 'Reality SpiderX', type: 'text' },
    { key: 'ws_host', label: 'WS Host', type: 'text' },
    { key: 'ws_path', label: 'WS Path', type: 'text' },
    { key: 'h2_host', label: 'H2 Host', type: 'text' },
    { key: 'h2_path', label: 'H2 Path', type: 'text' },
    { key: 'grpc_serviceName', label: 'gRPC Service Name', type: 'text' },
    { key: 'httpupgrade_host', label: 'HTTPUpgrade Host', type: 'text' },
    { key: 'httpupgrade_path', label: 'HTTPUpgrade Path', type: 'text' },
    { key: 'group', label: 'Group', type: 'text' },
];

function openNodeEditModal(node) {
    currentEditNode = node;
    document.getElementById('nodeEditTitle').textContent = `✏️ ${escHtml(node.remark || node.id)}`;
    const body = document.getElementById('nodeEditBody');
    body.innerHTML = '';

    NODE_EDIT_FIELDS.forEach(f => {
        const group = document.createElement('div');
        group.className = 'custom-input-group';
        const label = document.createElement('label');
        label.textContent = f.label;
        group.appendChild(label);

        if (f.type === 'select') {
            const sel = document.createElement('select');
            sel.id = `ne-${f.key}`;
            (f.options || []).forEach(opt => {
                const o = document.createElement('option');
                o.value = opt; o.textContent = opt || '(none)';
                if (String(node[f.key] || '') === opt) o.selected = true;
                sel.appendChild(o);
            });
            // If current value not in options, add it
            const curVal = String(node[f.key] || '');
            if (curVal && !f.options.includes(curVal)) {
                const o = document.createElement('option');
                o.value = curVal; o.textContent = curVal; o.selected = true;
                sel.insertBefore(o, sel.firstChild);
            }
            group.appendChild(sel);
        } else {
            const inp = document.createElement('input');
            inp.type = 'text'; inp.id = `ne-${f.key}`;
            inp.value = node[f.key] || '';
            group.appendChild(inp);
        }
        body.appendChild(group);
    });

    document.getElementById('nodeEditSaveBtn').onclick = saveNodeEdit;
    document.getElementById('nodeEditModal').style.display = 'flex';
}

async function saveNodeEdit() {
    if (!currentEditNode) return;
    const fields = {};
    NODE_EDIT_FIELDS.forEach(f => {
        const el = document.getElementById(`ne-${f.key}`);
        if (el) {
            const newVal = el.value;
            const oldVal = String(currentEditNode[f.key] || '');
            if (newVal !== oldVal) fields[f.key] = newVal;
        }
    });
    if (Object.keys(fields).length === 0) { showToast('No changes'); return; }
    try {
        const r = await apiCall('/api/action/edit_node', 'POST', {
            node_id: currentEditNode.id, fields
        });
        showToast(r.ok ? '💾 Node saved!' : `❌ ${r.msg || 'Failed'}`);
        closeNodeEditModal();
        loadConfig();
    } catch (e) { showToast('❌ Save failed'); }
}

function closeNodeEditModal() { document.getElementById('nodeEditModal').style.display = 'none'; }

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
        // Show all key info in preview
        const infoParts = [];
        if (r.protocol) infoParts.push(`Proto: ${r.protocol}`);
        if (r.network && r.network !== 'tcp,udp') infoParts.push(`Net: ${r.network}`);
        if (r.inbound) infoParts.push(`In: ${r.inbound}`);
        if (r.source) infoParts.push(`Src: ${r.source}`);
        if (r.port) infoParts.push(`Port: ${r.port}`);
        const infoStr = infoParts.length ? `<div class="shunt-meta">${escHtml(infoParts.join(' | '))}</div>` : '';

        el.innerHTML = `<div class="shunt-header"><span class="shunt-name">${escHtml(r.remarks || r['.name'] || '?')}</span><button class="btn btn-xs btn-primary" onclick='openShuntModal(${JSON.stringify(JSON.stringify(r))})'>✏️ Edit</button></div>${infoStr}<div class="shunt-preview">📂 ${domainCount} domains, 🌐 ${ipCount} IPs</div>`;
        container.appendChild(el);
    });
}

function renderShuntNodes(shuntNodes) {
    let container = document.getElementById('shuntNodesList');
    if (!container) {
        // Create container dynamically after shuntList
        const shuntList = document.getElementById('shuntList');
        if (shuntList && shuntList.parentNode) {
            container = document.createElement('div');
            container.id = 'shuntNodesList';
            container.style.marginTop = '12px';
            shuntList.parentNode.insertBefore(container, shuntList.nextSibling);
        } else { return; }
    }
    if (!shuntNodes || !shuntNodes.length) { container.innerHTML = ''; return; }
    container.innerHTML = '<div style="font-weight:600;font-size:0.95rem;margin-bottom:8px;">🔀 Shunt Routing Nodes</div>';
    shuntNodes.forEach(sn => {
        const el = document.createElement('div');
        el.className = 'shunt-item';
        const dests = sn.destinations || {};
        const destEntries = Object.entries(dests);
        let destHtml = destEntries.map(([rule, dest]) => {
            const destLabel = dest === '_direct' ? '🟢 Direct' : dest === '_blackhole' ? '⛔ Block' : dest === '_default' ? '🔵 Default' : escHtml(dest);
            return `<div style="display:flex;justify-content:space-between;padding:2px 0;font-size:0.8rem;"><span style="color:rgba(255,255,255,0.7);">${escHtml(rule)}</span><span style="font-weight:600;">${destLabel}</span></div>`;
        }).join('');
        if (sn.default_node) {
            const defLabel = sn.default_node === '_direct' ? '🟢 Direct' : sn.default_node === '_blackhole' ? '⛔ Block' : escHtml(sn.default_node);
            destHtml += `<div style="display:flex;justify-content:space-between;padding:2px 0;font-size:0.8rem;border-top:1px solid rgba(255,255,255,0.1);margin-top:4px;padding-top:4px;"><span style="color:rgba(255,255,255,0.5);">Default</span><span style="font-weight:600;">${defLabel}</span></div>`;
        }
        el.innerHTML = `<div class="shunt-header"><span class="shunt-name">${escHtml(sn.remarks || sn.id)}</span><span class="shunt-meta">${escHtml(sn.type)} | ${escHtml(sn.domainStrategy || 'auto')}</span></div><div style="margin-top:6px;">${destHtml || '<div class="empty-state">No routes</div>'}</div>`;
        container.appendChild(el);
    });
}

let currentShuntRule = null;
function openShuntModal(rule) {
    currentShuntRule = typeof rule === 'string' ? JSON.parse(rule) : rule;
    document.getElementById('shuntModalTitle').textContent = `📝 ${escHtml(currentShuntRule.remarks || currentShuntRule['.name'] || 'Rule')}`;
    // Populate ALL fields
    document.getElementById('shuntRemarks').value = currentShuntRule.remarks || '';
    document.getElementById('shuntProtocol').value = currentShuntRule.protocol || '';
    document.getElementById('shuntInbound').value = currentShuntRule.inbound || '';
    document.getElementById('shuntNetwork').value = currentShuntRule.network || 'tcp,udp';
    document.getElementById('shuntSource').value = currentShuntRule.source || '';
    document.getElementById('shuntSourcePort').value = currentShuntRule.sourcePort || '';
    document.getElementById('shuntPort').value = currentShuntRule.port || '';
    document.getElementById('shuntDomains').value = currentShuntRule.domain_list || '';
    document.getElementById('shuntIPs').value = currentShuntRule.ip_list || '';
    document.getElementById('shuntSaveBtn').onclick = async () => {
        try {
            await apiCall('/api/action/set_shunt', 'POST', {
                rule_name: currentShuntRule['.name'],
                remarks: document.getElementById('shuntRemarks').value,
                protocol: document.getElementById('shuntProtocol').value,
                inbound: document.getElementById('shuntInbound').value,
                network: document.getElementById('shuntNetwork').value,
                source: document.getElementById('shuntSource').value,
                sourcePort: document.getElementById('shuntSourcePort').value,
                port: document.getElementById('shuntPort').value,
                domain_list: document.getElementById('shuntDomains').value,
                ip_list: document.getElementById('shuntIPs').value,
            });
            showToast('💾 Shunt rule saved!');
            closeShuntModal();
            loadConfig();
        } catch (e) { showToast('❌ Save failed'); }
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

async function checkServices() {
    const grid = document.getElementById('svcMonitorGrid');
    grid.innerHTML = '<div class="empty-state">⏳ Checking services...</div>';
    try {
        const r = await apiCall('/api/action/check_services', 'POST', {});
        const services = r.services || [];
        const general = services.filter(s => s.cat !== 'gaming');
        const gaming = services.filter(s => s.cat === 'gaming');
        let html = '';
        if (general.length) {
            html += '<div class="svc-section-title">🌐 General Services</div><div class="svc-grid">';
            general.forEach(s => { html += buildSvcCard(s); });
            html += '</div>';
        }
        if (gaming.length) {
            html += '<div class="svc-section-title" style="margin-top:12px;">🎮 Gaming Services</div><div class="svc-grid">';
            gaming.forEach(s => { html += buildSvcCard(s); });
            html += '</div>';
        }
        grid.innerHTML = html || '<div class="empty-state">No services</div>';
    } catch (e) { grid.innerHTML = '<div class="empty-state">❌ Check failed</div>'; }
}
function buildSvcCard(s) {
    const isUp = s.status === 'READY';
    const badge = isUp ? '<span class="svc-badge svc-up">READY</span>' : '<span class="svc-badge svc-down">DOWN</span>';
    const latency = s.ms ? `<span class="svc-latency">${s.ms}ms</span>` : '';
    return `<div class="svc-card ${isUp ? '' : 'svc-card-down'}"><div class="svc-card-top"><span class="svc-icon">${escHtml(s.icon)}</span><div><div class="svc-name">${escHtml(s.name)}</div><div class="svc-host">${escHtml(s.host)}</div></div></div><div class="svc-card-bottom">${badge}${latency}</div></div>`;
}

// ═══════════════════════════════════════════════════════════════
//  SLIPSTREAM DNS TUNNEL (with profiles)
// ═══════════════════════════════════════════════════════════════

async function refreshSlipstream() {
    const log = document.getElementById('slipLog');
    log.textContent = 'Checking status...';
    try {
        const r = await apiCall('/api/action/slipstream_status', 'POST', {});
        const badge = document.getElementById('slipStatus');
        if (r.running) { badge.textContent = 'RUNNING'; badge.className = 'svc-badge svc-up'; }
        else { badge.textContent = 'STOPPED'; badge.className = 'svc-badge svc-down'; }
        document.getElementById('slipArch').textContent = 'Arch: ' + (r.arch || '—');
        document.getElementById('slipInstalled').textContent = 'Binary: ' + (r.installed ? '✅' : '❌');
        document.getElementById('slipPort').textContent = 'Port: ' + (r.port || '—');
        if (r.domain) document.getElementById('slipDomain').value = r.domain;
        if (r.resolver) document.getElementById('slipResolver').value = r.resolver;
        if (r.active_profile) document.getElementById('slipActiveProfile').textContent = '📌 ' + r.active_profile;
        log.textContent = JSON.stringify(r, null, 2);
        loadSlipProfiles();
    } catch (e) { log.textContent = '❌ Failed to get status'; }
}

async function loadSlipProfiles() {
    try {
        const r = await apiCall('/api/action/slipstream_profiles', 'POST', {});
        const list = document.getElementById('slipProfileList');
        if (!list) return;
        if (!r.profiles || r.profiles.length === 0) {
            list.innerHTML = '<div class="empty-state">No profiles yet</div>';
            return;
        }
        list.innerHTML = r.profiles.map(p => `
            <div class="profile-item ${p.name === r.active ? 'profile-active' : ''}" onclick="switchSlipProfile('${p.name}')">
                <div class="profile-info">
                    <strong>${p.name === r.active ? '✅ ' : ''}${p.name}</strong>
                    <small>${p.domain || '—'} → ${p.resolver || '—'}</small>
                </div>
                <div class="profile-actions">
                    <button class="btn btn-danger btn-xs" onclick="event.stopPropagation();deleteSlipProfile('${p.name}')">🗑️</button>
                </div>
            </div>
        `).join('');
    } catch (e) { /* silent */ }
}

async function switchSlipProfile(name) {
    const log = document.getElementById('slipLog');
    log.textContent = '🔄 Switching to ' + name + '...';
    try {
        const r = await apiCall('/api/action/slipstream_switch_profile', 'POST', { name });
        log.textContent = r.ok ? '✅ ' + r.msg : '❌ ' + r.msg;
        setTimeout(refreshSlipstream, 1500);
    } catch (e) { log.textContent = '❌ Switch failed'; }
}

async function deleteSlipProfile(name) {
    if (!confirm('Delete profile "' + name + '"?')) return;
    try {
        await apiCall('/api/action/slipstream_delete_profile', 'POST', { name });
        loadSlipProfiles();
    } catch (e) { /* silent */ }
}

async function slipstreamConnect() {
    const domain = document.getElementById('slipDomain').value.trim();
    const resolver = document.getElementById('slipResolver').value.trim();
    const cert = document.getElementById('slipCert').value.trim();
    const congestion = document.getElementById('slipCongestion')?.value || 'dcubic';
    const log = document.getElementById('slipLog');
    if (!domain || !resolver) { log.textContent = '⚠️ Domain and Resolver are required'; return; }
    log.textContent = '🚀 Saving config and connecting...';
    try {
        const set_active = document.getElementById('slipSetActive')?.checked || false;
        const r = await apiCall('/api/action/set_slipstream_config', 'POST', { domain, resolver, cert, congestion, set_active });
        log.textContent = r.ok ? '✅ ' + r.msg : '❌ ' + r.msg;
        setTimeout(refreshSlipstream, 2000);
    } catch (e) { log.textContent = '❌ Connection failed'; }
}

async function slipstreamSaveProfile() {
    const name = prompt('Profile name:');
    if (!name) return;
    const domain = document.getElementById('slipDomain').value.trim();
    const resolver = document.getElementById('slipResolver').value.trim();
    const cert = document.getElementById('slipCert').value.trim();
    const congestion = document.getElementById('slipCongestion')?.value || 'dcubic';
    const log = document.getElementById('slipLog');
    try {
        const r = await apiCall('/api/action/slipstream_add_profile', 'POST', { name, domain, resolver, cert, congestion });
        log.textContent = r.ok ? '✅ ' + r.msg : '❌ ' + r.msg;
        loadSlipProfiles();
    } catch (e) { log.textContent = '❌ Failed to save profile'; }
}

async function slipstreamDisconnect() {
    const log = document.getElementById('slipLog');
    log.textContent = '⛔ Disconnecting...';
    try {
        const r = await apiCall('/api/action/slipstream_stop', 'POST', {});
        log.textContent = '✅ ' + r.msg;
        setTimeout(refreshSlipstream, 1000);
    } catch (e) { log.textContent = '❌ Failed'; }
}

async function slipstreamInstall() {
    const log = document.getElementById('slipLog');
    log.textContent = '📦 Downloading binary for your architecture...';
    try {
        const r = await apiCall('/api/action/slipstream_install', 'POST', {});
        log.textContent = r.ok ? '✅ ' + r.msg : '❌ ' + r.msg;
        setTimeout(refreshSlipstream, 1000);
    } catch (e) { log.textContent = '❌ Install failed'; }
}

// ═══════════════════════════════════════════════════════════════
//  DNSTT DNS TUNNEL (with profiles)
// ═══════════════════════════════════════════════════════════════

async function refreshDnstt() {
    const log = document.getElementById('dnsttLog');
    log.textContent = 'Checking status...';
    try {
        const r = await apiCall('/api/action/dnstt_status', 'POST', {});
        const badge = document.getElementById('dnsttStatus');
        if (r.running) { badge.textContent = 'RUNNING'; badge.className = 'svc-badge svc-up'; }
        else { badge.textContent = 'STOPPED'; badge.className = 'svc-badge svc-down'; }
        document.getElementById('dnsttArch').textContent = 'Arch: ' + (r.arch || '—');
        document.getElementById('dnsttInstalled').textContent = 'Binary: ' + (r.installed ? '✅' : '❌');
        document.getElementById('dnsttPort').textContent = 'Port: ' + (r.port || '—');
        if (r.domain) document.getElementById('dnsttDomain').value = r.domain;
        if (r.pubkey) document.getElementById('dnsttPubkey').value = r.pubkey;
        if (r.resolver) document.getElementById('dnsttResolver').value = r.resolver;
        if (r.port) document.getElementById('dnsttListenPort').value = r.port;
        if (r.transport) document.getElementById('dnsttTransport').value = r.transport;
        if (r.active_profile) document.getElementById('dnsttActiveProfile').textContent = '📌 ' + r.active_profile;
        log.textContent = JSON.stringify(r, null, 2);
        loadDnsttProfiles();
    } catch (e) { log.textContent = '❌ Failed to get status'; }
}

async function loadDnsttProfiles() {
    try {
        const r = await apiCall('/api/action/dnstt_profiles', 'POST', {});
        const list = document.getElementById('dnsttProfileList');
        if (!list) return;
        if (!r.profiles || r.profiles.length === 0) {
            list.innerHTML = '<div class="empty-state">No profiles yet</div>';
            return;
        }
        list.innerHTML = r.profiles.map(p => `
            <div class="profile-item ${p.name === r.active ? 'profile-active' : ''}" onclick="switchDnsttProfile('${p.name}')">
                <div class="profile-info">
                    <strong>${p.name === r.active ? '✅ ' : ''}${p.name}</strong>
                    <small>${p.domain || '—'} (${p.transport || 'udp'})</small>
                </div>
                <div class="profile-actions">
                    <button class="btn btn-danger btn-xs" onclick="event.stopPropagation();deleteDnsttProfile('${p.name}')">🗑️</button>
                </div>
            </div>
        `).join('');
    } catch (e) { /* silent */ }
}

async function switchDnsttProfile(name) {
    const log = document.getElementById('dnsttLog');
    log.textContent = '🔄 Switching to ' + name + '...';
    try {
        const r = await apiCall('/api/action/dnstt_switch_profile', 'POST', { name });
        log.textContent = r.ok ? '✅ ' + r.msg : '❌ ' + r.msg;
        setTimeout(refreshDnstt, 1500);
    } catch (e) { log.textContent = '❌ Switch failed'; }
}

async function deleteDnsttProfile(name) {
    if (!confirm('Delete profile "' + name + '"?')) return;
    try {
        await apiCall('/api/action/dnstt_delete_profile', 'POST', { name });
        loadDnsttProfiles();
    } catch (e) { /* silent */ }
}

async function dnsttConnect() {
    const domain = document.getElementById('dnsttDomain').value.trim();
    const pubkey = document.getElementById('dnsttPubkey').value.trim();
    const resolver = document.getElementById('dnsttResolver').value.trim();
    const listen_port = parseInt(document.getElementById('dnsttListenPort').value) || 7000;
    const transport = document.getElementById('dnsttTransport')?.value || 'udp';
    const log = document.getElementById('dnsttLog');
    if (!domain || !pubkey) { log.textContent = '⚠️ Domain and Public Key are required'; return; }
    log.textContent = '🚀 Saving config and connecting...';
    try {
        const set_active = document.getElementById('dnsttSetActive')?.checked || false;
        const r = await apiCall('/api/action/set_dnstt_config', 'POST', { domain, pubkey, resolver, listen_port, transport, set_active });
        log.textContent = r.ok ? '✅ ' + r.msg : '❌ ' + r.msg;
        setTimeout(refreshDnstt, 2000);
    } catch (e) { log.textContent = '❌ Connection failed'; }
}

async function dnsttSaveProfile() {
    const name = prompt('Profile name:');
    if (!name) return;
    const domain = document.getElementById('dnsttDomain').value.trim();
    const pubkey = document.getElementById('dnsttPubkey').value.trim();
    const resolver = document.getElementById('dnsttResolver').value.trim();
    const listen_port = parseInt(document.getElementById('dnsttListenPort').value) || 7000;
    const transport = document.getElementById('dnsttTransport')?.value || 'udp';
    const log = document.getElementById('dnsttLog');
    try {
        const r = await apiCall('/api/action/dnstt_add_profile', 'POST', { name, domain, pubkey, resolver, listen_port, transport });
        log.textContent = r.ok ? '✅ ' + r.msg : '❌ ' + r.msg;
        loadDnsttProfiles();
    } catch (e) { log.textContent = '❌ Failed to save profile'; }
}

async function dnsttDisconnect() {
    const log = document.getElementById('dnsttLog');
    log.textContent = '⛔ Disconnecting...';
    try {
        const r = await apiCall('/api/action/dnstt_stop', 'POST', {});
        log.textContent = '✅ ' + r.msg;
        setTimeout(refreshDnstt, 1000);
    } catch (e) { log.textContent = '❌ Failed'; }
}

async function dnsttInstall() {
    const log = document.getElementById('dnsttLog');
    log.textContent = '📦 Downloading binary for your architecture...';
    try {
        const r = await apiCall('/api/action/dnstt_install', 'POST', {});
        log.textContent = r.ok ? '✅ ' + r.msg : '❌ ' + r.msg;
        setTimeout(refreshDnstt, 1000);
    } catch (e) { log.textContent = '❌ Install failed'; }
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

// ═══════════════════════════════════════════════════════════════
//  DNS TUNNEL SCANNER v2 (FULL – all 48 features)
// ═══════════════════════════════════════════════════════════════
let _scanPollTimer = null;
let _lastLogLen = 0;
let _scanNotifyCtx = null; // AudioContext for sound

function _scanBtnState(state) {
    const ids = ['btnStartScan', 'btnStopScan', 'btnPauseScan', 'btnResumeScan', 'btnShuffleScan', 'btnExportScan'];
    const map = {
        idle: [false, true, true, true, true, false],
        scanning: [true, false, false, true, true, true],
        paused: [true, false, true, false, false, true],
    };
    const flags = map[state] || map.idle;
    ids.forEach((id, i) => { const el = document.getElementById(id); if (el) el.disabled = flags[i]; });
}

function toggleMasscanOpts() {
    const on = document.getElementById('scanMasscanEnabled').checked;
    document.getElementById('masscanOpts').style.display = on ? 'block' : 'none';
}

async function startDnsScan() {
    const domain = document.getElementById('scanDomain').value.trim();
    const cidr_text = document.getElementById('scanCidrText').value.trim();
    const preset = document.getElementById('scanPreset').value;
    const dns_type = document.getElementById('scanDnsType').value;
    const sample_size = parseInt(document.getElementById('scanSampleSize').value) || 0;
    const random_subdomain = document.getElementById('scanRandomSub').checked;
    const auto_retry = document.getElementById('scanAutoRetry').checked;
    const check_ns = document.getElementById('scanCheckNs').checked;
    const blacklist_enabled = document.getElementById('scanBlacklistEnabled').checked;
    const domains = (document.getElementById('scanExtraDomains').value || '').trim();
    const source_port = parseInt(document.getElementById('scanSourcePort').value) || 0;
    const pre_scan_port = document.getElementById('scanMasscanEnabled').checked ? 53 : 0;
    const pre_scan_rate = parseInt(document.getElementById('scanMasscanRate').value) || 1000;

    if (!domain) { showToast('⚠️ Target Domain is required'); return; }
    if (!cidr_text) { showToast('⚠️ Enter IPs/CIDRs or select a CIDR list'); return; }

    _scanBtnState('scanning');
    _lastLogLen = 0;
    document.getElementById('scanStatsBar').style.display = 'block';
    document.getElementById('scanResultsWrap').style.display = 'block';
    document.getElementById('scanLogWrap').style.display = 'block';
    document.getElementById('scanResultsBody').innerHTML = '';
    document.getElementById('scanLogPanel').textContent = '';
    document.getElementById('scannerStatus').textContent = pre_scan_port ? 'masscan phase…' : 'starting…';

    try {
        const r = await apiCall('/api/action/dns_scanner_start', 'POST', {
            domain, cidr_text, preset, dns_type, sample_size, random_subdomain,
            auto_retry, check_ns, blacklist_enabled, domains, source_port,
            pre_scan_port, pre_scan_rate
        });
        showToast(r.ok ? '🚀 ' + r.msg : '❌ ' + r.msg);
        if (r.ok) {
            _scanPollTimer = setInterval(pollScanStatus, 1200);
        } else {
            _scanBtnState('idle');
        }
    } catch (e) { showToast('❌ Failed to start scan'); _scanBtnState('idle'); }
}

async function stopDnsScan() {
    try {
        await apiCall('/api/action/dns_scanner_stop', 'POST', {});
        showToast('⛔ Stop signal sent');
    } catch (e) { /* ignore */ }
}

async function pauseDnsScan() {
    try {
        const r = await apiCall('/api/action/dns_scanner_pause', 'POST', {});
        if (r.ok) { _scanBtnState('paused'); showToast('⏸️ Scan paused'); }
    } catch (e) { /* ignore */ }
}

async function resumeDnsScan() {
    try {
        const r = await apiCall('/api/action/dns_scanner_resume', 'POST', {});
        if (r.ok) { _scanBtnState('scanning'); showToast('▶️ Scan resumed'); }
    } catch (e) { /* ignore */ }
}

async function shuffleDnsScan() {
    try {
        const r = await apiCall('/api/action/dns_scanner_shuffle', 'POST', {});
        showToast(r.ok ? '🔀 ' + r.msg : '❌ ' + (r.msg || 'Shuffle failed'));
    } catch (e) { /* ignore */ }
}

async function exportDnsScan() {
    try {
        const r = await apiCall('/api/action/dns_scanner_export', 'POST', {});
        const blob = new Blob([JSON.stringify(r, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a'); a.href = url;
        a.download = `dns_scan_${r.scan_date || 'results'}.json`.replace(/[: ]/g, '_');
        a.click(); URL.revokeObjectURL(url);
        showToast('📥 Results exported');
    } catch (e) { showToast('❌ Export failed'); }
}

function clearScanLog() {
    document.getElementById('scanLogPanel').textContent = '';
    _lastLogLen = 0;
}

function _fmtEta(secs) {
    if (!secs || secs <= 0) return '—';
    if (secs < 60) return secs + 's';
    if (secs < 3600) return Math.floor(secs / 60) + 'm ' + (secs % 60) + 's';
    return Math.floor(secs / 3600) + 'h ' + Math.floor((secs % 3600) / 60) + 'm';
}

// ── Notification Sound ─────────────────────────────────────────
let _prevFoundCount = 0;
function _playNotifySound() {
    try {
        if (!_scanNotifyCtx) _scanNotifyCtx = new (window.AudioContext || window.webkitAudioContext)();
        const osc = _scanNotifyCtx.createOscillator();
        const gain = _scanNotifyCtx.createGain();
        osc.connect(gain); gain.connect(_scanNotifyCtx.destination);
        osc.frequency.value = 880; gain.gain.value = 0.15;
        osc.start(); osc.stop(_scanNotifyCtx.currentTime + 0.15);
    } catch (e) { }
}

// ── Latency Heatmap ────────────────────────────────────────────
function _renderHeatmap(found) {
    const el = document.getElementById('latencyHeatmap');
    if (!el || !found || !found.length) return;
    const maxMs = Math.max(...found.map(r => r.ms || 0), 1);
    el.innerHTML = found.slice(0, 100).map(r => {
        const ratio = Math.min((r.ms || 0) / maxMs, 1);
        const hue = 120 - (ratio * 120); // green → red
        return `<div style="flex:1;background:hsl(${hue},80%,50%)" title="${r.ip}: ${r.ms}ms"></div>`;
    }).join('');
}

// ── Install Masscan ────────────────────────────────────────────
async function installMasscan() {
    try {
        const btn = event.currentTarget;
        const origHtml = btn.innerHTML;
        btn.innerHTML = '<span class="spinner" style="width:12px;height:12px;"></span> Installing...';
        btn.disabled = true;

        const res = await apiCall('/api/action/dns_scanner_install_masscan', 'POST', {});
        if (res.ok) {
            showToast('✅ Masscan Installed!');
            btn.innerHTML = '<span class="material-icons" style="font-size:0.9rem;">check</span> Installed';
            setTimeout(() => { btn.innerHTML = origHtml; btn.disabled = false; }, 3000);
        } else {
            alert('Install Failed: ' + (res.msg || 'Unknown error'));
            btn.innerHTML = origHtml;
            btn.disabled = false;
        }
    } catch (e) {
        alert('Install Error: ' + e);
        event.currentTarget.disabled = false;
        event.currentTarget.innerHTML = '<span class="material-icons" style="font-size:0.9rem;">download</span> Install';
    }
}

// ── Poll Status ────────────────────────────────────────────────
async function pollScanStatus() {
    try {
        const s = await apiCall('/api/action/dns_scanner_status', 'POST', {});
        const pct = s.total > 0 ? ((s.scanned / s.total) * 100).toFixed(1) : 0;

        // Stats
        document.getElementById('statScanned').textContent = s.scanned.toLocaleString();
        document.getElementById('statTotal').textContent = s.total.toLocaleString();
        document.getElementById('statFound').textContent = s.found_count;
        document.getElementById('statFailed').textContent = s.failed.toLocaleString();
        document.getElementById('statSpeed').textContent = s.ips_per_sec + ' /s';
        document.getElementById('statEta').textContent = _fmtEta(s.eta_s);

        // Progress
        document.getElementById('scanProgressBar').style.width = pct + '%';
        document.getElementById('scanProgressText').textContent =
            `${s.scanned.toLocaleString()} / ${s.total.toLocaleString()} (${pct}%)`;
        document.getElementById('scanElapsed').textContent = s.elapsed_s + 's';

        // Status badge
        const badge = document.getElementById('scannerStatus');
        if (s.paused) { badge.textContent = '⏸️ paused'; }
        else if (s.running && s.phase === 'masscan') {
            badge.textContent = '🔍 masscan: ' + (s.masscan_progress || 'starting...');
        }
        else if (s.running) { badge.textContent = '🟢 scanning'; }
        else { badge.textContent = 'idle'; }

        // RCODE stats
        const rcDiv = document.getElementById('rcodeStats');
        if (s.rcode_stats) {
            rcDiv.innerHTML = Object.entries(s.rcode_stats).map(([k, v]) =>
                `<span class="rcode-badge ${k.toLowerCase()}">${k}: ${v}</span>`
            ).join(' ');
        }

        // Notification sound
        if (document.getElementById('scanNotifySound').checked && s.found_count > _prevFoundCount) {
            _playNotifySound();
        }
        _prevFoundCount = s.found_count;

        // Results count
        document.getElementById('scanResultCount').textContent = `${s.found_count} found`;

        // Render results table (sorted by latency)
        const tbody = document.getElementById('scanResultsBody');
        const sorted = (s.found || []).sort((a, b) => (a.ms || 9999) - (b.ms || 9999));
        const top10ips = new Set((s.top10 || []).map(r => r.ip));

        tbody.innerHTML = sorted.map((r, i) => {
            const cls = r.ms < 100 ? 'lat-fast' : r.ms < 300 ? 'lat-mid' : 'lat-slow';
            const isTop = top10ips.has(r.ip);
            const rowCls = isTop && i < 10 ? 'scan-result-top' : '';
            const rcodeCls = (r.rcode_name || '').toLowerCase();
            let tags = '';
            if (r.has_edns) tags += '<span class="tag-badge edns">EDNS</span>';
            if (r.has_ns) tags += '<span class="tag-badge ns-ok">NS-OK</span>';
            if (isTop && i < 10) tags += '<span class="tag-badge top10">★ TOP</span>';

            return `<tr class="${rowCls}">
                <td><input type="checkbox" class="scan-select-cb" data-ip="${r.ip}"></td>
                <td>${i + 1}</td>
                <td>${escHtml(r.ip)}</td>
                <td class="${cls}">${r.ms}ms</td>
                <td><span class="rcode-badge ${rcodeCls}">${r.rcode_name || '?'}</span></td>
                <td>${tags}</td>
                <td>
                    <button class="copy-ip-btn" onclick="navigator.clipboard.writeText('${r.ip}');showToast('📋 Copied')">📋</button>
                    <button class="btn btn-xs btn-success" onclick="applyScanIp('${r.ip}','slip')">→Slip</button>
                    <button class="btn btn-xs btn-primary" onclick="applyScanIp('${r.ip}','dnstt')">→DNSTT</button>
                    <button class="btn btn-xs btn-danger" onclick="blacklistIp('${r.ip}')">🚫</button>
                </td>
            </tr>`;
        }).join('');

        // Latency heatmap
        _renderHeatmap(sorted);

        // Log panel (append new entries only)
        if (s.log && s.log.length > _lastLogLen) {
            const panel = document.getElementById('scanLogPanel');
            const newEntries = s.log.slice(_lastLogLen);
            newEntries.forEach(e => {
                panel.textContent += `[${e.t}] ${e.msg}\n`;
            });
            _lastLogLen = s.log.length;
            panel.scrollTop = panel.scrollHeight;
        }

        // State transitions
        if (s.paused) { _scanBtnState('paused'); }
        else if (s.running) { _scanBtnState('scanning'); }

        if (!s.running) {
            clearInterval(_scanPollTimer);
            _scanPollTimer = null;
            _scanBtnState('idle');
            showToast('✅ Scan finished – found ' + s.found_count + ' DNS servers');
            if (document.getElementById('scanNotifySound').checked) _playNotifySound();
        }
    } catch (e) { /* keep polling */ }
}

function applyScanIp(ip, target) {
    if (target === 'slip') {
        const el = document.getElementById('slipResolver');
        if (el) { el.value = ip + ':53'; }
        showToast('✅ Applied ' + ip + ' to Slipstream resolver');
    } else {
        const el = document.getElementById('dnsttResolver');
        if (el) { el.value = ip + ':53'; }
        showToast('✅ Applied ' + ip + ' to DNSTT resolver');
    }
}

// ── Toggle Select All ─────────────────────────────────────────
function toggleSelectAll(master) {
    document.querySelectorAll('.scan-select-cb').forEach(cb => cb.checked = master.checked);
}

// ── Batch Apply ─────────────────────────────────────────────
function batchApplyAll() {
    const selected = [...document.querySelectorAll('.scan-select-cb:checked')].map(cb => cb.dataset.ip);
    if (!selected.length) { showToast('⚠️ Select IPs first using the checkboxes'); return; }
    const joined = selected.join(', ');
    navigator.clipboard.writeText(joined);
    showToast(`📦 Copied ${selected.length} IPs: ${joined.slice(0, 60)}…`);
}

// ── Save / Resume Project ─────────────────────────────────────
async function saveProject() {
    try {
        const r = await apiCall('/api/action/dns_scanner_save_project', 'POST', {});
        showToast(r.ok ? '💾 ' + r.msg : '❌ ' + (r.msg || 'Nothing to save'));
    } catch (e) { showToast('❌ Save failed'); }
}

async function resumeProject() {
    try {
        const proj = await apiCall('/api/action/dns_scanner_load_project', 'POST', {});
        if (proj && proj.remaining_ips && proj.remaining_ips.length) {
            document.getElementById('scanDomain').value = proj.domain || '';
            document.getElementById('scanCidrText').value = proj.remaining_ips.join('\n');
            if (proj.preset) document.getElementById('scanPreset').value = proj.preset;
            if (proj.dns_type) document.getElementById('scanDnsType').value = proj.dns_type;
            showToast(`📂 Loaded project: ${proj.remaining_count} IPs, domain=${proj.domain}`);
        } else {
            showToast('📂 No saved project found');
        }
    } catch (e) { showToast('❌ Load failed'); }
}

// ── Scan History ──────────────────────────────────────────────
async function viewScanHistory() {
    const panel = document.getElementById('scanHistoryPanel');
    panel.style.display = 'block';
    try {
        const r = await apiCall('/api/action/dns_scanner_history', 'POST', {});
        const arr = r.history || [];
        if (!arr.length) {
            document.getElementById('scanHistoryContent').innerHTML = '<em>No scan history yet</em>';
            return;
        }
        document.getElementById('scanHistoryContent').innerHTML = arr.reverse().map(h =>
            `<div style="padding:6px 0;border-bottom:1px solid var(--glass-border);">
                <strong>${h.date}</strong> — ${h.domain}<br>
                <span style="opacity:0.7;">
                    ${h.dns_type} | ${h.preset} | Scanned: ${h.scanned} | Found: ${h.found} |
                    Time: ${h.elapsed_s}s | Top: ${(h.top3 || []).join(', ')}
                </span>
            </div>`
        ).join('');
    } catch (e) { document.getElementById('scanHistoryContent').innerHTML = '<em>Error loading history</em>'; }
}

// ── Blacklist ─────────────────────────────────────────────────
function openBlacklistModal() {
    document.getElementById('blacklistModal').style.display = 'flex';
    loadBlacklist();
}

function closeBlacklistModal() {
    document.getElementById('blacklistModal').style.display = 'none';
}

async function loadBlacklist() {
    try {
        const r = await apiCall('/api/action/dns_scanner_get_blacklist', 'POST', {});
        const list = r.blacklist || [];
        document.getElementById('blacklistList').innerHTML = list.length
            ? list.map(ip => `<div style="padding:3px 0;">${escHtml(ip)}</div>`).join('')
            : '<em>Blacklist is empty</em>';
    } catch (e) { /* ignore */ }
}

async function addToBlacklist() {
    const ip = document.getElementById('blacklistInput').value.trim();
    if (!ip) return;
    try {
        const r = await apiCall('/api/action/dns_scanner_add_blacklist', 'POST', { ip });
        showToast(r.ok ? '🚫 ' + r.msg : '❌ ' + r.msg);
        document.getElementById('blacklistInput').value = '';
        loadBlacklist();
    } catch (e) { showToast('❌ Failed'); }
}

async function blacklistIp(ip) {
    try {
        const r = await apiCall('/api/action/dns_scanner_add_blacklist', 'POST', { ip });
        showToast(r.ok ? '🚫 Blacklisted ' + ip : '❌ ' + r.msg);
    } catch (e) { showToast('❌ Failed'); }
}

async function clearBlacklist() {
    try {
        const r = await apiCall('/api/action/dns_scanner_clear_blacklist', 'POST', {});
        showToast(r.ok ? '🗑 ' + r.msg : '❌ ' + r.msg);
        loadBlacklist();
    } catch (e) { showToast('❌ Failed'); }
}

// ── Domain Caching (auto-load last domain) ────────────────────
async function _loadLastDomain() {
    try {
        const r = await apiCall('/api/action/dns_scanner_last_domain', 'POST', {});
        if (r.domain) {
            const el = document.getElementById('scanDomain');
            if (el && !el.value) el.value = r.domain;
        }
    } catch (e) { /* ignore */ }
}

// ── Keyboard Shortcuts ────────────────────────────────────────
document.addEventListener('keydown', function (e) {
    // Ignore if user is typing in an input/textarea/select
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) return;
    switch (e.key.toLowerCase()) {
        case 's': startDnsScan(); break;
        case 'p': pauseDnsScan(); break;
        case 'r': resumeDnsScan(); break;
        case 'e': exportDnsScan(); break;
        case 'x': stopDnsScan(); break;
    }
});

// Auto-load last domain on page ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _loadLastDomain);
} else {
    _loadLastDomain();
}

// ═══════════════════════════════════════════════════════════════
//  CIDR LIST MANAGER
// ═══════════════════════════════════════════════════════════════
let _cidrCache = [];

async function loadCidrLists() {
    try {
        const r = await apiCall('/api/action/get_cidr_lists', 'POST', {});
        _cidrCache = r.lists || [];
        populateCidrDropdown();
    } catch (e) { /* ignore */ }
}

function populateCidrDropdown() {
    const sel = document.getElementById('scanCidrSelect');
    // keep the first "Custom" option
    while (sel.options.length > 1) sel.remove(1);
    _cidrCache.forEach(c => {
        const opt = document.createElement('option');
        opt.value = c.name;
        opt.textContent = `📋 ${c.name} (${c.cidr_count} ranges)`;
        sel.appendChild(opt);
    });
}

async function onCidrSourceChange() {
    const sel = document.getElementById('scanCidrSelect');
    const ta = document.getElementById('scanCidrText');
    if (sel.value === '__custom__') {
        ta.value = '';
        ta.disabled = false;
        return;
    }
    try {
        const r = await apiCall('/api/action/get_cidr_content', 'POST', { name: sel.value });
        ta.value = r.content || '';
        ta.disabled = true;
    } catch (e) { toast('❌ Failed to load list'); }
}

function openCidrModal() {
    document.getElementById('cidrModal').style.display = 'flex';
    renderCidrModal();
}
function closeCidrModal() {
    document.getElementById('cidrModal').style.display = 'none';
}

async function renderCidrModal() {
    await loadCidrLists();
    const c = document.getElementById('cidrListContainer');
    if (_cidrCache.length === 0) {
        c.innerHTML = '<div style="opacity:.6;text-align:center;padding:12px;">No saved CIDR lists</div>';
        return;
    }
    c.innerHTML = _cidrCache.map(l => `
        <div class="cidr-item">
            <span class="cidr-item-name" onclick="selectCidrFromModal('${escHtml(l.name)}')"><strong>${escHtml(l.name)}</strong> — ${l.cidr_count} ranges</span>
            <button class="btn btn-xs btn-danger" onclick="event.stopPropagation(); deleteCidrList('${escHtml(l.name)}')">🗑</button>
        </div>
    `).join('');
}

async function saveCidrList() {
    const name = document.getElementById('cidrNewName').value.trim();
    const content = document.getElementById('cidrNewContent').value.trim();
    if (!name || !content) { toast('⚠️ Name and content required'); return; }
    try {
        const r = await apiCall('/api/action/add_cidr_list', 'POST', { name, content });
        toast(r.ok ? '✅ ' + r.msg : '❌ ' + r.msg);
        document.getElementById('cidrNewName').value = '';
        document.getElementById('cidrNewContent').value = '';
        await renderCidrModal();
    } catch (e) { toast('❌ Save failed'); }
}

async function deleteCidrList(name) {
    if (!confirm(`Delete "${name}"?`)) return;
    try {
        const r = await apiCall('/api/action/delete_cidr_list', 'POST', { name });
        toast(r.ok ? '✅ ' + r.msg : '❌ ' + r.msg);
        await renderCidrModal();
    } catch (e) { toast('❌ Delete failed'); }
}

async function selectCidrFromModal(name) {
    try {
        const r = await apiCall('/api/action/get_cidr_content', 'POST', { name });
        const ta = document.getElementById('scanCidrText');
        ta.value = r.content || '';
        ta.disabled = true;
        // Also set the dropdown to match
        const sel = document.getElementById('scanCidrSelect');
        sel.value = name;
        closeCidrModal();
        showToast('✅ Loaded: ' + name);
    } catch (e) { showToast('❌ Failed to load list'); }
}

// Load CIDR lists on page load
document.addEventListener('DOMContentLoaded', () => { loadCidrLists(); });
