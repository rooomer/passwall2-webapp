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
