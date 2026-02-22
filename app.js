/* ═══════════════════════════════════════════════════════════════
   PassWall 2 - Telegram Mini App JavaScript (v2 - Full Management)
   Communicates with the OpenWrt bot via Telegram.WebApp.sendData()
   ═══════════════════════════════════════════════════════════════ */

// ─── Telegram WebApp Instance ──────────────────────────────────
const tg = window.Telegram?.WebApp;
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
        parseInitData();
    }
    renderDnsPresets();
});

// ─── Parse Data from Bot ───────────────────────────────────────
function parseInitData() {
    try {
        const params = new URLSearchParams(window.location.search);
        const dataParam = params.get('d') || params.get('data');
        if (dataParam) {
            const raw = JSON.parse(dataParam);
            configData = {
                running: raw.s || raw.running || false,
                active_node: raw.n || raw.active_node || '',
                nodes: (raw.nl || raw.nodes || []).map(n => ({
                    id: n.i || n.id,
                    remark: n.r || n.remark,
                    type: n.t || n.type || '',
                    protocol: n.p || n.protocol || '',
                    group: n.g || n.group || 'default',
                    address: n.a || n.address || '',
                    port: n.pt || n.port || '',
                })),
                dns: {
                    remote_dns_protocol: raw.dp || (raw.dns && raw.dns.remote_dns_protocol) || 'tcp',
                    remote_dns: raw.ds || (raw.dns && raw.dns.remote_dns) || '',
                    remote_dns_doh: raw.dd || (raw.dns && raw.dns.remote_dns_doh) || '',
                    remote_fakedns: raw.df || (raw.dns && raw.dns.remote_fakedns) || '0',
                    dns_redirect: raw.dr || (raw.dns && raw.dns.dns_redirect) || '1',
                    remote_dns_query_strategy: raw.dqs || (raw.dns && raw.dns.remote_dns_query_strategy) || 'UseIPv4',
                    direct_dns_query_strategy: raw.dqd || (raw.dns && raw.dns.direct_dns_query_strategy) || 'UseIP',
                    remote_dns_detour: raw.det || (raw.dns && raw.dns.remote_dns_detour) || 'remote',
                    remote_dns_client_ip: (raw.dns && raw.dns.remote_dns_client_ip) || '',
                    dns_hosts: (raw.dns && raw.dns.dns_hosts) || '',
                },
                socks: raw.socks || [],
                servers: raw.servers || [],
                acl: raw.acl || [],
                shunt_rules: raw.shunt_rules || [],
                haproxy: raw.haproxy || [],
                subscriptions: raw.subscriptions || [],
            };
        }
    } catch (e) {
        console.error('Failed to parse init data:', e);
    }
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
    renderACL(data.acl || []);

    // Shunt Rules
    renderShuntRules(data.shunt_rules || []);

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

    highlightDnsPreset();
}

// ═══════════════════════════════════════════════════════════════
//  NODE MANAGEMENT
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
        latency.textContent = '';

        info.appendChild(name);
        info.appendChild(meta);
        el.appendChild(dot);
        el.appendChild(info);
        el.appendChild(latency);

        // Action buttons row
        const actions = document.createElement('div');
        actions.className = 'node-actions';

        const pingBtn = document.createElement('button');
        pingBtn.className = 'btn btn-xs btn-info';
        pingBtn.textContent = '📡';
        pingBtn.title = 'Ping';
        pingBtn.onclick = (e) => { e.stopPropagation(); pingNode(n); };

        const useBtn = document.createElement('button');
        useBtn.className = 'btn btn-xs btn-success';
        useBtn.textContent = '✅';
        useBtn.title = 'Use';
        useBtn.onclick = (e) => { e.stopPropagation(); selectNode(n.id); };

        const detailBtn = document.createElement('button');
        detailBtn.className = 'btn btn-xs btn-secondary';
        detailBtn.textContent = 'ℹ️';
        detailBtn.title = 'Detail';
        detailBtn.onclick = (e) => { e.stopPropagation(); openNodeModal(n); };

        const delBtn = document.createElement('button');
        delBtn.className = 'btn btn-xs btn-danger';
        delBtn.textContent = '🗑️';
        delBtn.title = 'Delete';
        delBtn.onclick = (e) => { e.stopPropagation(); deleteNode(n.id, n.remark); };

        actions.appendChild(pingBtn);
        actions.appendChild(useBtn);
        actions.appendChild(detailBtn);
        actions.appendChild(delBtn);
        el.appendChild(actions);

        container.appendChild(el);
    });
}

function filterNodes() {
    const q = document.getElementById('nodeSearch').value.toLowerCase();
    document.querySelectorAll('.node-item').forEach(el => {
        const name = el.querySelector('.node-name')?.textContent.toLowerCase() || '';
        const meta = el.querySelector('.node-meta')?.textContent.toLowerCase() || '';
        el.style.display = (name.includes(q) || meta.includes(q)) ? '' : 'none';
    });
}

function selectNode(id) {
    pendingChanges.node = id;
    pendingChanges.action = 'set_node';

    document.querySelectorAll('.node-item').forEach(el => {
        el.classList.toggle('active', el.dataset.id === id);
    });

    const node = (configData.nodes || []).find(n => n.id === id);
    document.getElementById('activeNode').textContent = node ? node.remark : id;

    showMainButton();
    showToast('Node selected — tap Apply');
}

function deleteNode(id, name) {
    if (confirm(`Delete node "${name || id}"?`)) {
        sendToBot({ action: 'delete_node', node: id });
        showToast('🗑️ Node deleted');
        // Remove from local list
        const el = document.querySelector(`.node-item[data-id="${id}"]`);
        if (el) el.remove();
    }
}

function pingNode(node) {
    const latEl = document.getElementById(`lat-${node.id}`);
    if (latEl) {
        latEl.textContent = '...';
        latEl.className = 'node-latency pinging';
    }
    sendToBot({ action: 'ping_node', address: node.address || '', port: node.port || '', node_id: node.id });
    showToast(`📡 Pinging ${node.remark || node.address}...`);
}

function pingAllNodes() {
    const nodes = configData.nodes || [];
    if (!nodes.length) { showToast('No nodes'); return; }
    nodes.forEach(n => {
        const latEl = document.getElementById(`lat-${n.id}`);
        if (latEl) { latEl.textContent = '...'; latEl.className = 'node-latency pinging'; }
    });
    sendToBot({ action: 'ping_all_nodes' });
    showToast(`📡 Pinging ${nodes.length} nodes...`);
}

function addNodeFromUrl() {
    const url = document.getElementById('shareUrlInput').value.trim();
    if (!url) return;
    sendToBot({ action: 'add_node_url', url: url });
    document.getElementById('shareUrlInput').value = '';
    showToast('➕ Adding node from URL...');
}

// ─── Node Detail Modal ────────────────────────────────────────
function openNodeModal(node) {
    const body = document.getElementById('nodeModalBody');
    document.getElementById('nodeModalTitle').textContent = `📋 ${escHtml(node.remark || '?')}`;

    body.innerHTML = '';
    const grid = document.createElement('div');
    grid.className = 'status-grid';

    const fields = [
        ['Name', node.remark],
        ['Type', node.type],
        ['Protocol', node.protocol],
        ['Address', node.address],
        ['Port', node.port],
        ['Group', node.group],
        ['ID', node.id],
    ];
    fields.forEach(([label, val]) => {
        const item = document.createElement('div');
        item.className = 'status-item';
        const lbl = document.createElement('span');
        lbl.className = 'status-label';
        lbl.textContent = label;
        const valEl = document.createElement('span');
        valEl.className = 'status-value';
        valEl.textContent = val || '—';
        if (label === 'ID') valEl.style.fontSize = '0.7rem';
        item.appendChild(lbl);
        item.appendChild(valEl);
        grid.appendChild(item);
    });
    body.appendChild(grid);

    // Reset ping result
    const pingRes = document.getElementById('nodePingResult');
    pingRes.style.display = 'none';
    pingRes.textContent = '';

    // Wire buttons
    document.getElementById('nodeUseBtn').onclick = () => {
        selectNode(node.id);
        closeNodeModal();
    };
    document.getElementById('nodePingBtn').onclick = () => {
        pingRes.style.display = 'block';
        pingRes.textContent = 'Pinging...';
        sendToBot({ action: 'ping_node', address: node.address, port: node.port, node_id: node.id });
    };
    document.getElementById('nodeCopyBtn').onclick = () => {
        sendToBot({ action: 'copy_node', node: node.id });
        showToast('📋 Node copied');
        closeNodeModal();
    };
    document.getElementById('nodeDelBtn').onclick = () => {
        if (confirm(`Delete "${node.remark}"?`)) {
            sendToBot({ action: 'delete_node', node: node.id });
            showToast('🗑️ Node deleted');
            closeNodeModal();
        }
    };

    document.getElementById('nodeModal').style.display = 'flex';
}

function closeNodeModal() {
    document.getElementById('nodeModal').style.display = 'none';
}

// ═══════════════════════════════════════════════════════════════
//  ACL MANAGEMENT
// ═══════════════════════════════════════════════════════════════

function renderACL(rules) {
    const container = document.getElementById('aclList');
    if (!rules.length) {
        container.innerHTML = '<div class="empty-state">No ACL rules</div>';
        return;
    }
    container.innerHTML = '';
    rules.forEach(r => {
        const el = document.createElement('div');
        el.className = 'list-item list-item-interactive';

        const infoDiv = document.createElement('div');
        const nameEl = document.createElement('div');
        nameEl.className = 'item-name';
        nameEl.textContent = r.remarks || r['.name'] || '?';
        infoDiv.appendChild(nameEl);

        const detailEl = document.createElement('div');
        detailEl.className = 'item-detail';
        detailEl.textContent = `Source: ${r.sources || 'all'}`;
        infoDiv.appendChild(detailEl);

        // Toggle switch
        const toggleLabel = document.createElement('label');
        toggleLabel.className = 'switch switch-sm';
        const toggleInput = document.createElement('input');
        toggleInput.type = 'checkbox';
        toggleInput.checked = r.enabled === '1';
        toggleInput.onchange = () => {
            sendToBot({ action: 'set_acl', id: r['.name'], enabled: toggleInput.checked ? '1' : '0' });
            showToast(`ACL ${r.remarks || '?'}: ${toggleInput.checked ? 'enabled' : 'disabled'}`);
        };
        const slider = document.createElement('span');
        slider.className = 'slider';
        toggleLabel.appendChild(toggleInput);
        toggleLabel.appendChild(slider);

        el.appendChild(infoDiv);
        el.appendChild(toggleLabel);
        container.appendChild(el);
    });
}

// ═══════════════════════════════════════════════════════════════
//  SHUNT RULES MANAGEMENT
// ═══════════════════════════════════════════════════════════════

function renderShuntRules(rules) {
    const container = document.getElementById('shuntList');
    if (!rules.length) {
        container.innerHTML = '<div class="empty-state">No shunt rules</div>';
        return;
    }
    container.innerHTML = '';
    rules.forEach(r => {
        const el = document.createElement('div');
        el.className = 'shunt-item';

        const header = document.createElement('div');
        header.className = 'shunt-header';

        const name = document.createElement('span');
        name.className = 'shunt-name';
        name.textContent = r.remarks || r['.name'] || '?';

        const editBtn = document.createElement('button');
        editBtn.className = 'btn btn-xs btn-primary';
        editBtn.textContent = '✏️ Edit';
        editBtn.onclick = () => openShuntModal(r);

        header.appendChild(name);
        header.appendChild(editBtn);

        const preview = document.createElement('div');
        preview.className = 'shunt-preview';
        const domainCount = (r.domain_list || '').split('\n').filter(x => x.trim()).length;
        const ipCount = (r.ip_list || '').split('\n').filter(x => x.trim()).length;
        preview.textContent = `📂 ${domainCount} domains, 🌐 ${ipCount} IPs`;

        el.appendChild(header);
        el.appendChild(preview);
        container.appendChild(el);
    });
}

let currentShuntRule = null;

function openShuntModal(rule) {
    currentShuntRule = rule;
    document.getElementById('shuntModalTitle').textContent = `📝 ${escHtml(rule.remarks || rule['.name'] || 'Rule')}`;
    document.getElementById('shuntDomains').value = rule.domain_list || '';
    document.getElementById('shuntIPs').value = rule.ip_list || '';

    document.getElementById('shuntSaveBtn').onclick = () => {
        const domains = document.getElementById('shuntDomains').value;
        const ips = document.getElementById('shuntIPs').value;
        sendToBot({
            action: 'set_shunt_rule',
            rule_name: rule['.name'] || '',
            domain_list: domains,
            ip_list: ips,
        });
        showToast('💾 Shunt rule saved');
        closeShuntModal();
    };

    document.getElementById('shuntModal').style.display = 'flex';
}

function closeShuntModal() {
    document.getElementById('shuntModal').style.display = 'none';
    currentShuntRule = null;
}

// ═══════════════════════════════════════════════════════════════
//  GENERIC LIST RENDERER (XSS-SAFE)
// ═══════════════════════════════════════════════════════════════

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

// ═══════════════════════════════════════════════════════════════
//  DNS PRESETS
// ═══════════════════════════════════════════════════════════════

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

// ═══════════════════════════════════════════════════════════════
//  SETTINGS MANAGEMENT
// ═══════════════════════════════════════════════════════════════

function setForwarding(key, value) {
    sendToBot({ action: 'set_forwarding', key: key, value: value });
    showToast(`✅ ${key} → ${value}`);
}

function setDelay(key, value) {
    sendToBot({ action: 'set_delay', key: key, value: value });
    showToast(`✅ ${key} → ${value}`);
}

function setGlobalOpt(key, value) {
    sendToBot({ action: 'set_global_opt', key: key, value: value });
    showToast(`✅ ${key} → ${value}`);
}

// ═══════════════════════════════════════════════════════════════
//  ACTIONS / COMMANDS
// ═══════════════════════════════════════════════════════════════

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

// ═══════════════════════════════════════════════════════════════
//  TAB SWITCHING
// ═══════════════════════════════════════════════════════════════

function switchTab(tabName) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(tc => tc.classList.remove('active'));
    document.querySelector(`.tab[data-tab="${tabName}"]`)?.classList.add('active');
    document.getElementById(`tab-${tabName}`)?.classList.add('active');
}

// ═══════════════════════════════════════════════════════════════
//  APPLY CHANGES
// ═══════════════════════════════════════════════════════════════

function applyChanges() {
    if (Object.keys(pendingChanges).length === 0) {
        showToast('No changes to apply');
        return;
    }

    const action = pendingChanges.action || 'apply_config';
    const changes = { ...pendingChanges };
    delete changes.action;

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
    const payload = typeof data === 'string' ? data : JSON.stringify(data);
    if (tg) {
        tg.sendData(payload);
    } else {
        console.log('sendData:', payload);
    }
}

function showMainButton() {
    if (tg) tg.MainButton.show();
}

// ═══════════════════════════════════════════════════════════════
//  UTILITY
// ═══════════════════════════════════════════════════════════════

function showToast(message) {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), 2500);
}

function escHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
