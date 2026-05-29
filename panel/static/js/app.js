const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const DASHBOARD_NODE_LIMIT = 4;
let devicesTimer = null;
let dashboardTimer = null;
let trafficTimer = null;
let panelSettings = { theme: "dark", devices_refresh_sec: 15, dashboard_auto_refresh: false };

function resolveTheme(theme) {
  if (theme === "system") {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  return theme === "light" ? "light" : "dark";
}

function applyTheme(theme, persist = true) {
  const resolved = resolveTheme(theme);
  document.documentElement.setAttribute("data-theme", resolved);
  if (persist) localStorage.setItem("n1-theme", theme);
  $$(".theme-btn").forEach(b => b.classList.toggle("active", b.dataset.theme === theme));
}

function initThemeListener() {
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    const t = localStorage.getItem("n1-theme") || panelSettings.theme || "dark";
    if (t === "system") applyTheme("system", false);
  });
}

const MODE_HINTS = {
  rule: "规则：国内直连，其余走 AUTO",
  global: "全局：所有流量走 AUTO 代理",
  direct: "直连：所有流量不经过代理",
};

function toast(msg, isError = false) {
  const el = $("#toast");
  el.textContent = msg;
  el.style.borderColor = isError ? "var(--danger)" : "var(--border)";
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 2800);
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || data.message || res.statusText);
  return data;
}

function card(label, value, cls = "", extra = "", title = "") {
  const t = title ? ` title="${escapeHtml(title)}"` : "";
  return `<div class="card dash-card ${extra}"${t}><div class="label">${escapeHtml(label)}</div><div class="value ${cls}">${escapeHtml(value)}</div></div>`;
}

function nodeCard(name, delayMs, selected, alive) {
  const dc = delayClass(delayMs);
  const cls = [selected ? "selected" : "", alive === false ? "offline" : ""].filter(Boolean).join(" ");
  return `<button type="button" class="card dash-card node-chip ${cls}" data-node="${escapeHtml(name)}" title="${escapeHtml(name)}">
    <div class="label">${escapeHtml(name)}</div>
    <div class="value ${dc}">${escapeHtml(formatDelay(delayMs))}</div>
  </button>`;
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function delayClass(ms) {
  if (ms == null || ms <= 0) return "delay-muted";
  const v = Math.min(Math.round(ms), 999);
  if (v <= 120) return "delay-green";
  if (v <= 251) return "delay-yellow";
  if (v <= 460) return "delay-orange";
  return "delay-red";
}

function formatDelay(ms) {
  if (ms == null || ms <= 0) return "-";
  return `${Math.min(Math.round(ms), 999)} ms`;
}

function nodeStatusHtml(alive) {
  return alive
    ? '<span class="node-status on">在线</span>'
    : '<span class="node-status off">离线</span>';
}

function logLineClass(line) {
  const s = line.toLowerCase();
  if (/error|failed|fatal|invalid|denied/.test(s)) return "log-err";
  if (/warn|warning/.test(s)) return "log-warn";
  if (/info|level=info/.test(s)) return "log-info";
  return "";
}

function renderLogViewer(el, text, emptyMsg = "暂无内容") {
  if (!el) return 0;
  const raw = (text || "").trim();
  if (!raw) {
    el.innerHTML = `<div class="log-empty">${escapeHtml(emptyMsg)}</div>`;
    return 0;
  }
  const lines = raw.split("\n");
  el.innerHTML = lines.map(line => {
    const cls = logLineClass(line);
    return `<div class="log-line${cls ? " " + cls : ""}">${escapeHtml(line)}</div>`;
  }).join("");
  return lines.length;
}

function renderConnections(el, payload) {
  if (!el) return;
  const list = (payload?.connections || []).slice(0, 24);
  if (!list.length) {
    el.innerHTML = '<div class="log-empty">暂无活跃连接</div>';
    return;
  }
  el.innerHTML = `<ul class="conn-list">${list.map(c => {
    const meta = c.metadata || {};
    const host = meta.host || meta.destinationIP || meta.destination || "?";
    const src = meta.sourceIP || meta.sourceIp || "";
    const chain = (c.chains || []).join(" → ") || "-";
    const type = meta.type || c.rule || "";
    return `<li class="conn-item">
      <span class="conn-host">${escapeHtml(host)}</span>
      <span class="conn-meta">${src ? escapeHtml(src) + " · " : ""}${escapeHtml(type)}</span>
      <span class="conn-chain">${escapeHtml(chain)}</span>
    </li>`;
  }).join("")}</ul>`;
}

async function refreshConnections() {
  const conn = await api("/api/connections");
  renderConnections($("#connections-preview"), conn);
}

function formatVersion(v) {
  if (!v) return "-";
  if (typeof v === "string") return v;
  if (typeof v === "object" && v.version) return v.version;
  return "-";
}

function formatTraffic(info) {
  if (!info) return "-";
  const used = ((info.Upload || info.used || 0) + (info.Download || 0)) / (info.used ? 1 : 1024 ** 3);
  const usedGb = info.used_gb ?? (used / 1024 / 1024 / 1024);
  const totalGb = info.total_gb ?? (info.Total ? info.Total / 1024 / 1024 / 1024 : null);
  const expire = info.Expire ? new Date(info.Expire * 1000).toLocaleDateString() : "-";
  if (totalGb) return `${usedGb.toFixed(1)} / ${totalGb.toFixed(0)} GB · 到期 ${expire}`;
  return `${Number(usedGb).toFixed(1)} GB 已用 · 到期 ${expire === "-" ? "未知" : expire}`;
}

function setModeUI(mode) {
  $$(".mode-btn").forEach(b => b.classList.toggle("active", b.dataset.mode === mode));
  const hint = $("#mode-hint");
  if (hint) hint.textContent = MODE_HINTS[mode] || mode;
}

async function switchMode(mode) {
  await api("/api/mode", { method: "POST", body: JSON.stringify({ mode }) });
  setModeUI(mode);
  toast(`已切换为：${MODE_HINTS[mode] || mode}`);
}

const RING_COLORS = {
  green: "#22c55e",
  yellow: "#eab308",
  orange: "#f97316",
  red: "#ef4444",
};

function ringLevel(pct) {
  const p = Math.min(Math.max(pct || 0, 0), 100);
  if (p >= 90) return { color: RING_COLORS.red, cls: "level-red", label: "高" };
  if (p >= 75) return { color: RING_COLORS.orange, cls: "level-orange", label: "较高" };
  if (p >= 50) return { color: RING_COLORS.yellow, cls: "level-yellow", label: "中等" };
  return { color: RING_COLORS.green, cls: "level-green", label: "充足" };
}

function drawRing(canvas, pct, color) {
  const compact = canvas.closest(".overview-traffic");
  const size = compact ? 92 : 88;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = size * dpr;
  canvas.height = size * dpr;
  canvas.style.width = size + "px";
  canvas.style.height = size + "px";
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  const cx = size / 2, cy = size / 2, r = compact ? 33 : 32, lw = compact ? 11 : 12;
  const start = -Math.PI / 2;
  const end = start + (Math.min(pct, 100) / 100) * Math.PI * 2;
  ctx.clearRect(0, 0, size, size);
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, Math.PI * 2);
  const track = getComputedStyle(document.documentElement).getPropertyValue("--border").trim() || "#2d3a4f";
  ctx.strokeStyle = track;
  ctx.lineWidth = lw;
  ctx.stroke();
  if (pct > 0) {
    ctx.beginPath();
    ctx.arc(cx, cy, r, start, end);
    ctx.strokeStyle = color;
    ctx.lineWidth = lw;
    ctx.lineCap = "round";
    ctx.stroke();
  }
  ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--text").trim() || "#e7ecf3";
  ctx.font = compact ? "bold 15px sans-serif" : "bold 15px sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(Math.min(pct, 100).toFixed(0) + "%", cx, cy);
}

function renderTrafficRings(providers) {
  const el = $("#traffic-rings");
  if (!el) return;
  if (!providers?.length) {
    el.innerHTML = `<div class="ring-card ring-card-placeholder">
      <div class="ring-label">流量</div>
      <div class="ring-placeholder-core" aria-hidden="true"></div>
      <div class="ring-meta">暂无流量数据</div>
    </div>`;
    syncModeRingAlign();
    return;
  }
  el.innerHTML = providers.map((p, i) => {
    const pct = p.usage_percent ?? (p.total_gb ? (p.used_gb / p.total_gb * 100) : 0);
    const pctVal = Math.min(pct || 0, 100);
    const level = ringLevel(pctVal);
    const totalLabel = p.limit_gb ? `限额 ${p.limit_gb} GB` : (p.total_gb ? `套餐 ${p.total_gb} GB` : "未设限额");
    return `<div class="ring-card">
      <div class="ring-label">流量 · ${p.name}</div>
      <canvas id="ring-canvas-${i}"></canvas>
      <div class="ring-pct ${level.cls}">${pct ? pctVal.toFixed(1) + "%" : "—"}</div>
      <div class="ring-meta">${p.used_gb}G · ↑${p.upload_gb} ↓${p.download_gb}<br>${totalLabel}${p.alert ? " · ⚠" : ""}</div>
    </div>`;
  }).join("");
  providers.forEach((p, i) => {
    const pct = p.usage_percent ?? (p.total_gb ? (p.used_gb / p.total_gb * 100) : 0);
    const pctVal = Math.min(pct || 0, 100);
    const level = ringLevel(pctVal);
    const canvas = $(`#ring-canvas-${i}`);
    if (canvas) drawRing(canvas, pctVal, level.color);
  });
  syncModeRingAlign();
}

function syncModeRingAlign() {
  if (!$("#tab-dashboard")?.classList.contains("active")) return;
  const ring = document.querySelector(".overview-controls .ring-card");
  const modeSwitch = document.querySelector(".overview-controls .mode-switch");
  if (!ring || !modeSwitch) return;
  const ringH = Math.round(ring.getBoundingClientRect().height);
  if (ringH < 48) return;
  const h = `${ringH}px`;
  if (modeSwitch.style.height !== h) modeSwitch.style.height = h;
}

function scheduleModeRingAlign() {
  requestAnimationFrame(() => {
    requestAnimationFrame(syncModeRingAlign);
  });
}

window.addEventListener("resize", () => scheduleModeRingAlign());

let lastDashboardData = null;
let lastGoogleTest = null;

function googleCardValue(test) {
  if (!test) return { text: "点击测试", cls: "" };
  if (test.testing) return { text: "测试中…", cls: "" };
  return test.ok
    ? { text: test.ms != null ? `通过 ${test.ms}ms` : "通过", cls: "ok" }
    : { text: "失败", cls: "bad" };
}

async function runGoogleTest() {
  const el = $("#card-google");
  if (el) {
    el.classList.add("testing");
    el.querySelector(".value").textContent = "测试中…";
  }
  const t0 = performance.now();
  try {
    const r = await api("/api/proxy-test", { method: "POST" });
    const ms = Math.round(performance.now() - t0);
    lastGoogleTest = { ok: r.ok, ms, testing: false };
    toast(r.ok ? `Google 可达 · ${ms}ms` : "Google 失败", !r.ok);
  } catch (e) {
    lastGoogleTest = { ok: false, ms: null, testing: false };
    toast(e.message, true);
  }
  if (el) el.classList.remove("testing");
  updateGoogleCard();
}

function updateGoogleCard() {
  const el = $("#card-google");
  if (!el) return;
  const v = googleCardValue(lastGoogleTest);
  el.querySelector(".value").textContent = v.text;
  el.querySelector(".value").className = `value ${v.cls}`;
}

function displayNodes(autoNodes) {
  const list = autoNodes?.display_nodes;
  if (list?.length) return list;
  const all = autoNodes?.nodes || [];
  return pickNodesForDisplay(all, DASHBOARD_NODE_LIMIT);
}

function pickNodesForDisplay(nodes, limit) {
  if (nodes.length <= limit) return nodes;
  const sel = nodes.find(n => n.selected);
  const others = nodes.filter(n => !n.selected);
  const picked = [...(sel ? [sel] : []), ...others.slice(0, sel ? limit - 1 : limit)];
  return picked
    .sort((a, b) => {
      const da = a.delay > 0 ? a.delay : 99999;
      const db = b.delay > 0 ? b.delay : 99999;
      return da - db;
    })
    .slice(0, limit);
}

function renderNodeCards(autoNodes) {
  const el = $("#dashboard-nodes");
  if (!el) return;
  const nodes = displayNodes(autoNodes);
  if (!nodes.length) {
    if (el.querySelector(".node-chip:not(.node-skeleton)")) return;
    el.innerHTML = "<p class='hint overview-empty-hint'>暂无 AUTO 节点</p>";
    return;
  }
  el.innerHTML = nodes.map(n => nodeCard(n.name, n.delay, n.selected, n.alive)).join("");
  $$(".node-chip", el).forEach(btn => {
    btn.onclick = () => selectNode(btn.dataset.node);
  });
}

async function selectNode(name) {
  if (!name) return;
  try {
    const r = await api("/api/proxies/select", {
      method: "POST",
      body: JSON.stringify({ group: "AUTO", name }),
    });
    toast(`已切换：${r.now || name}`);
    await loadDashboard();
  } catch (e) {
    toast(e.message, true);
  }
}

function paintDashboard(data) {
  const m = data.mihomo || {};
  const cfg = m.configs || {};
  const mode = data.mode || cfg.mode || "rule";
  setModeUI(mode);

  renderTrafficRings(data.traffic?.providers);

  const tp = data.transparent_proxy || {};
  const tpLabel = tp.short || tp.label || "未配置";
  const tpOk = !!tp.active;
  const apPre = data.autopilot || {};
  const autoHint = apPre.switched ? "已触发" : "监控中";
  const cardsEl = $("#dashboard-cards");
  if (cardsEl) {
    cardsEl.innerHTML = [
      card("服务", data.service, data.service === "active" ? "ok" : "bad"),
      card("模式", mode, mode === "global" ? "ok" : ""),
      card("透明代理", tpLabel, tpOk ? "ok" : "", "", tp.label || tpLabel),
      card("连接数", String(m.connections_count ?? "-")),
      card("当前节点", data.auto_nodes?.now || "-", "ok"),
      card("自动切换", autoHint, apPre.switched ? "ok" : ""),
    ].join("");
  }

  renderNodeCards(data.auto_nodes);
  scheduleModeRingAlign();
  return data.autopilot || {};
}

async function loadDashboard() {
  const fusion = document.querySelector(".overview-fusion");
  fusion?.classList.add("is-refreshing");
  try {
    const data = await api("/api/dashboard");
    lastDashboardData = data;
    const ap = paintDashboard(data);
    if (ap.switched) {
      if (ap.reason === "traffic_failover") {
        toast(`已自动切换节点（机场流量阈值触发）: ${ap.to || ""}`);
      } else if (ap.reason === "not_in_top4") {
        toast(`已自动切换到低延迟节点: ${ap.to || ""}`);
      }
    }
    await refreshConnections();
  } catch (e) {
    if (lastDashboardData) paintDashboard(lastDashboardData);
    throw e;
  } finally {
    fusion?.classList.remove("is-refreshing");
  }
}

async function refreshTrafficOnly() {
  if (!$("#tab-dashboard")?.classList.contains("active")) return;
  const traffic = await api("/api/traffic");
  renderTrafficRings(traffic.providers || []);
}

async function refreshNodesWithDelay() {
  if (!confirm(`仅对概览上显示的 ${DASHBOARD_NODE_LIMIT} 个节点测速（每个约几 KB 流量）。继续？`)) return;
  toast(`正在测速 ${DASHBOARD_NODE_LIMIT} 个节点…`);
  try {
    const data = await api(`/api/proxies/auto?refresh=1&limit=${DASHBOARD_NODE_LIMIT}`);
    if (data.cooldown_left) {
      toast(`测速请求过于频繁，请 ${data.cooldown_left}s 后再试`);
    }
    renderNodeCards(data.auto_nodes);
    if (!data.cooldown_left) {
      toast(`测速完成（${data.delay_tested ?? DASHBOARD_NODE_LIMIT} 个，未测全部节点以省流量）`);
    }
  } catch (e) {
    toast(e.message, true);
  }
}

async function loadProxies() {
  const data = await api("/api/proxies");
  const auto = data.auto || {};
  $("#auto-info").innerHTML = `<p>当前：<strong>${auto.now || "-"}</strong> · 候选 ${auto.all?.length || 0} 个</p>`;
  $("#nodes-body").innerHTML = (data.nodes || []).map(n => {
    const delay = n.history?.[0]?.delay;
    const dc = delay != null && delay > 0 ? delayClass(delay) : "delay-muted";
    return `<tr>
      <td>${escapeHtml(n.name)}</td>
      <td>${escapeHtml(n.type || "-")}</td>
      <td>${nodeStatusHtml(n.alive)}</td>
      <td class="${dc}">${formatDelay(delay)}</td>
    </tr>`;
  }).join("");
}

async function fetchProviderUrl(name) {
  const r = await api(`/api/providers/${encodeURIComponent(name)}/url`);
  if (!r.url) throw new Error("无法获取订阅链接");
  return r.url;
}

async function copyProviderUrl(name) {
  try {
    const url = await fetchProviderUrl(name);
    await navigator.clipboard.writeText(url);
    toast("订阅链接已复制");
  } catch (e) {
    toast(e.message || "复制失败", true);
  }
}

function showProviderQr(name) {
  const dlg = $("#provider-qr-dialog");
  const img = $("#provider-qr-img");
  const title = $("#provider-qr-title");
  if (!dlg || !img) return;
  if (title) title.textContent = `订阅二维码 · ${name}`;
  img.src = `/api/providers/${encodeURIComponent(name)}/qr?_=${Date.now()}`;
  if (typeof dlg.showModal === "function") dlg.showModal();
  else dlg.classList.remove("hidden");
}

async function loadProviders() {
  const [data, traffic] = await Promise.all([api("/api/providers"), api("/api/traffic")]);
  const tmap = Object.fromEntries((traffic.providers || []).map(p => [p.name, p]));

  $("#providers-list").innerHTML = (data.providers || []).map(p => {
    const t = tmap[p.name] || {};
    return `
    <div class="card provider-card" data-name="${escapeHtml(p.name)}">
      <div class="value">${escapeHtml(p.name)}</div>
      <div class="meta">${escapeHtml(p.type_label || p.type)} · 间隔 ${p.interval || "-"}s · ${formatTraffic(t)}</div>
      <p class="hint provider-url-hint">${p.type === "http" ? "订阅链接已隐藏，请复制或扫码导入" : (p.path ? `路径 ${escapeHtml(p.path)}` : "内联/本地订阅")}</p>
      <div class="actions">
        ${p.type === "http" ? `<button class="btn sm" data-copy-url="${escapeHtml(p.name)}">复制链接</button>
        <button class="btn sm" data-qr-url="${escapeHtml(p.name)}">二维码</button>` : ""}
        <button class="btn sm" data-refresh="${escapeHtml(p.name)}">刷新订阅</button>
      </div>
      <div class="quota-form">
        <label>限额(GB)<input type="number" step="0.1" data-quota="${p.name}" value="${t.limit_gb || ""}" placeholder="-"></label>
        <label>告警%<input type="number" data-alert="${p.name}" value="${t.alert_percent || 80}" min="1" max="100"></label>
        <button class="btn sm danger" data-delete="${p.name}">删除</button>
        <button class="btn sm" data-save-quota="${p.name}">保存限额</button>
      </div>
    </div>`;
  }).join("") || "<p class='hint'>暂无机场，点击右上角添加</p>";

  $$("[data-copy-url]").forEach(btn => {
    btn.onclick = () => copyProviderUrl(btn.dataset.copyUrl).catch(e => toast(e.message, true));
  });
  $$("[data-qr-url]").forEach(btn => {
    btn.onclick = () => showProviderQr(btn.dataset.qrUrl);
  });
  $$("[data-save-quota]").forEach(btn => btn.onclick = async () => {
    const name = btn.dataset.saveQuota;
    const limit = $(`[data-quota="${name}"]`).value;
    const alert = $(`[data-alert="${name}"]`).value;
    await api("/api/traffic/quotas", { method: "PUT", body: JSON.stringify({ name, limit_gb: limit || null, alert_percent: alert }) });
    toast("限额已保存");
    loadDashboard();
  });
  $$("[data-refresh]").forEach(btn => btn.onclick = async () => {
    await api(`/api/providers/${btn.dataset.refresh}/refresh`, { method: "POST" });
    toast("订阅已刷新");
    loadProxies();
  });
  $$("[data-delete]").forEach(btn => btn.onclick = async () => {
    if (!confirm(`确定删除机场 ${btn.dataset.delete}？`)) return;
    await api(`/api/providers/${btn.dataset.delete}`, { method: "DELETE" });
    toast("已删除并应用");
    loadProviders();
    loadProxies();
  });
}

async function loadRules() {
  const [rules, modeData] = await Promise.all([api("/api/rules"), api("/api/mode")]);
  $("#rules-editor").value = (rules.rules || []).join("\n");
  setModeUI(modeData.runtime_mode || modeData.config_mode || "rule");
}

const POLICY_LABELS = { proxy: "允许", direct: "直连", block: "禁止" };

function formatDeviceSubline(d) {
  const parts = [];
  const host = (d.hostname || "").trim();
  if (host && host !== d.ip) parts.push(host);
  if (d.device_type) parts.push(d.device_type);
  return parts.join(" · ");
}

function deviceKey(d) {
  return (d.device_key || d.mac || "").trim() || "";
}

function renderDevicePolicyBtns(key, policy, { disabled = false } = {}) {
  if (!key) {
    return `<span class="hint device-no-mac">无 MAC，无法登记</span>`;
  }
  const dis = disabled ? " disabled" : "";
  return `<div class="seg-control device-policy-seg" data-policy-group="${escapeHtml(key)}" role="group">
    ${["proxy", "direct", "block"].map(p =>
      `<button type="button" class="seg-btn device-policy-btn${policy === p ? " active" : ""}${p === "block" ? " danger" : ""}"${dis}
        data-policy-pick="${escapeHtml(key)}" data-policy-value="${p}">${POLICY_LABELS[p]}</button>`
    ).join("")}
  </div>`;
}

function getSelectedDeviceKeys() {
  return $$("[data-device-select]:checked").map(cb => cb.dataset.deviceSelect).filter(Boolean);
}

async function saveDevicePolicy(deviceKey, policy, { silent = false } = {}) {
  try {
    await api(`/api/devices/${encodeURIComponent(deviceKey)}`, {
      method: "PUT",
      body: JSON.stringify({ policy }),
    });
    if (!silent) toast(`已登记：${POLICY_LABELS[policy] || policy}`);
    loadDevices(true);
  } catch (e) {
    toast(e.message, true);
    loadDevices(true);
  }
}

function bindDevicePolicyBtns(root) {
  $$(".device-policy-btn", root).forEach(btn => {
    btn.onclick = async () => {
      if (btn.classList.contains("active") || btn.disabled) return;
      const group = btn.closest(".device-policy-seg");
      const key = btn.dataset.policyPick;
      const policy = btn.dataset.policyValue;
      $$(".device-policy-btn", group).forEach(b => { b.disabled = true; });
      $$(".device-policy-btn", group).forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      await saveDevicePolicy(key, policy, { silent: true });
    };
  });
}

function updateDeviceBatchBar() {
  const n = getSelectedDeviceKeys().length;
  const bar = $("#device-batch-bar");
  if (bar) bar.hidden = n === 0;
  const count = $("#device-batch-count");
  if (count) count.textContent = n ? `已选 ${n} 台` : "";
  syncDevicesSelectAllState();
}

async function batchSetDevicePolicy(policy) {
  const macs = getSelectedDeviceKeys();
  if (!macs.length) {
    toast("请先勾选要批量设置的设备", true);
    return;
  }
  const label = POLICY_LABELS[policy] || policy;
  try {
    const r = await api("/api/devices/batch", {
      method: "POST",
      body: JSON.stringify({ macs, policy }),
    });
    const n = (r.updated || []).length;
    toast(`已批量设为「${label}」：${n} 台`);
    $$("[data-device-select]").forEach(cb => { cb.checked = false; });
    updateDeviceBatchBar();
    loadDevices(true);
  } catch (e) {
    toast(e.message, true);
  }
}

function setDeviceDefaultPolicyUI(policy) {
  const p = policy === "proxy" ? "proxy" : "direct";
  $("#btn-default-device-direct")?.classList.toggle("active", p === "direct");
  $("#btn-default-device-proxy")?.classList.toggle("active", p === "proxy");
}

async function saveDeviceDefaultPolicy(policy) {
  const p = policy === "proxy" ? "proxy" : "direct";
  try {
    const data = await api("/api/settings", {
      method: "PUT",
      body: JSON.stringify({ default_device_policy: p }),
    });
    panelSettings = { ...panelSettings, ...data };
    setDeviceDefaultPolicyUI(p);
    toast(p === "proxy" ? "新接入设备默认：允许" : "新接入设备默认：直连");
  } catch (e) {
    toast(e.message, true);
  }
}

async function loadDevices(silent = false) {
  const data = await api("/api/devices");
  const body = $("#devices-body");
  if (!body) return;
  const selectedBefore = new Set(getSelectedDeviceKeys());
  const onlineOnly = !!$("#devices-online-only")?.checked;
  setDeviceDefaultPolicyUI(data.default_device_policy || panelSettings.default_device_policy || "direct");
  const devices = (data.devices || []).filter(d => !onlineOnly || d.online);
  const groupWeight = { proxy: 0, direct: 1, block: 2 };
  devices.sort((a, b) => (groupWeight[a.policy] ?? 9) - (groupWeight[b.policy] ?? 9));
  let prevPolicy = "";
  body.innerHTML = devices.map(d => {
    const hosts = (d.hosts || []).slice(0, 2).join(", ");
    const policyLabel = POLICY_LABELS[d.policy] || d.policy;
    const key = deviceKey(d);
    const checked = key && selectedBefore.has(key) ? " checked" : "";
    const subline = formatDeviceSubline(d);
    const aliasVal = (d.alias || "").trim();
    const mac = (d.mac || "").trim();
    const canSelect = !!key;
    const header = d.policy !== prevPolicy
      ? `<tr class="policy-group-row"><td colspan="6">${escapeHtml(policyLabel)}</td></tr>`
      : "";
    prevPolicy = d.policy;
    return `${header}<tr data-device-key="${escapeHtml(key)}" data-ip="${escapeHtml(d.ip)}" data-policy="${escapeHtml(d.policy)}" class="${d.policy === "block" ? "device-row-block" : ""}${!canSelect ? " device-row-no-mac" : ""}">
      <td class="col-check"><input type="checkbox" data-device-select="${escapeHtml(key)}"${checked}${canSelect ? "" : " disabled"} aria-label="选择"></td>
      <td class="mono device-ip">${escapeHtml(d.ip || "—")}</td>
      <td class="device-name-cell">
        <input class="alias-input" data-device-key="${escapeHtml(key)}" data-original="${escapeHtml(aliasVal)}"
          value="${escapeHtml(aliasVal)}" placeholder="添加别名"${canSelect ? "" : " disabled"}>
        ${subline ? `<div class="device-meta hint" title="${escapeHtml(subline)}">${escapeHtml(subline)}</div>` : ""}
        ${hosts ? `<div class="device-meta device-hosts hint" title="${escapeHtml(hosts)}">${escapeHtml(hosts)}</div>` : ""}
      </td>
      <td class="mono device-mac-cell" title="${escapeHtml(mac)}">${mac ? escapeHtml(mac) : "<span class='hint'>—</span>"}</td>
      <td class="device-status-cell">
        <div class="device-status-line">
          <span class="status-dot ${d.online ? "on" : "off"}"></span>
          <span>${d.online ? "在线" : "离线"}</span>
        </div>
        ${(d.conn_count || 0) > 0 ? `<div class="device-conn-line hint">连接 ${d.conn_count}</div>` : ""}
      </td>
      <td class="device-policy-cell">${renderDevicePolicyBtns(key, d.policy)}</td>
    </tr>`;
  }).join("") || "<tr><td colspan='6' class='hint'>暂无设备，请确认终端网关/DNS 指向 N1</td></tr>";

  const sum = $("#devices-summary");
  if (sum) {
    sum.textContent = `共 ${data.total || 0} 台 · 在线 ${data.online || 0} 台 · 网段 ${data.lan_net || ""} · 策略按 MAC 登记（换 IP 仍生效）`;
  }

  bindDevicePolicyBtns(body);
  syncDevicesSelectAllState();

  $$("[data-device-select]", body).forEach(cb => {
    cb.onchange = updateDeviceBatchBar;
  });

  $$(".alias-input", body).forEach(inp => {
    inp.onblur = async () => {
      const key = inp.dataset.deviceKey;
      if (!key) return;
      const val = inp.value.trim();
      if (val === (inp.dataset.original || "")) return;
      const policy = inp.closest("tr")?.dataset.policy || "direct";
      try {
        await api(`/api/devices/${encodeURIComponent(key)}`, {
          method: "PUT",
          body: JSON.stringify({ alias: val, policy }),
        });
        inp.dataset.original = val;
        toast("别名已保存");
      } catch (e) { toast(e.message, true); }
    };
  });

  updateDeviceBatchBar();
  if (!silent) toast("设备列表已刷新");
}

function syncDevicesSelectAllState() {
  const all = $$("[data-device-select]");
  const sel = $("#devices-select-all");
  if (!sel || !all.length) {
    if (sel) sel.checked = false;
    return;
  }
  const checked = all.filter(cb => cb.checked).length;
  sel.checked = checked === all.length;
  sel.indeterminate = checked > 0 && checked < all.length;
}

function stopDevicesPolling() {
  if (devicesTimer) clearInterval(devicesTimer);
  devicesTimer = null;
}

function startDevicesPolling() {
  stopDevicesPolling();
  const sec = panelSettings.devices_refresh_sec || 15;
  devicesTimer = setInterval(() => loadDevices(true).catch(() => {}), sec * 1000);
}

async function loadSettings() {
  const data = await api("/api/settings");
  panelSettings = data;
  applyTheme(data.theme || localStorage.getItem("n1-theme") || "dark", true);
  const ar = $("#setting-auto-refresh");
  const ds = $("#setting-devices-sec");
  const as = $("#setting-auto-switch");
  const ass = $("#setting-auto-switch-sec");
  const tf = $("#setting-traffic-failover");
  const tt = $("#setting-traffic-threshold");
  const cd = $("#setting-node-cooldown");
  if (ar) ar.checked = !!data.dashboard_auto_refresh;
  if (ds) ds.value = data.devices_refresh_sec || 15;
  if (as) as.checked = !!data.auto_switch_enabled;
  if (ass) ass.value = data.auto_switch_interval_sec || 300;
  if (tf) tf.checked = !!data.traffic_failover_enabled;
  if (tt) tt.value = data.traffic_failover_threshold || 100;
  if (cd) cd.value = data.node_test_cooldown_sec || 600;
  setDeviceDefaultPolicyUI(data.default_device_policy || "direct");
  const about = $("#settings-about-port");
  if (about) about.textContent = `面板端口：${data.panel_port || 8088}`;
  const ver = $("#settings-about-version");
  if (ver) ver.textContent = `Mihomo 版本：${data.mihomo_version || "-"}`;
  const ip = $("#settings-about-ip");
  if (ip) ip.textContent = `本机 IP：${data.local_ip || "-"}`;
}

async function loadService() {
  const [dash, tun] = await Promise.all([api("/api/dashboard"), api("/api/tun")]);
  const cfg = dash.mihomo?.configs || {};
  $("#runtime-log").value = cfg["log-level"] || "info";
  $("#tun-enable").checked = !!tun.enable;
  $("#tun-status").textContent = JSON.stringify(tun, null, 2);
  $("#service-cards").innerHTML = [
    card("mihomo", dash.service, dash.service === "active" ? "ok" : "bad"),
    card("Mixed", "7890"),
    card("API", "127.0.0.1:9090"),
    card("面板", "8088"),
  ].join("");
  const logs = await api("/api/logs");
  const n = renderLogViewer($("#logs-box"), logs.logs, "暂无 mihomo 日志");
  const meta = $("#logs-meta");
  if (meta) meta.textContent = n ? `${n} 行` : "";
}

const SIDEBAR_COLLAPSED_KEY = "n1-sidebar-collapsed";

function initSidebarCollapse() {
  const layout = $(".layout");
  const btn = $("#btn-sidebar-toggle");
  if (!layout || !btn) return;

  const apply = (collapsed) => {
    layout.classList.toggle("sidebar-collapsed", collapsed);
    btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
    btn.textContent = collapsed ? "›" : "‹";
    btn.title = collapsed ? "展开侧栏" : "折叠侧栏";
  };

  apply(localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "1");
  btn.onclick = () => {
    const collapsed = !layout.classList.contains("sidebar-collapsed");
    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, collapsed ? "1" : "0");
    apply(collapsed);
  };
}

initSidebarCollapse();

$$(".nav").forEach(btn => btn.onclick = () => {
  stopDevicesPolling();
  if (trafficTimer) {
    clearInterval(trafficTimer);
    trafficTimer = null;
  }
  const tab = btn.dataset.tab;
  if (btn.classList.contains("active")) {
    const reload = { dashboard: loadDashboard, devices: () => loadDevices() };
    reload[tab]?.();
    return;
  }
  $$(".nav").forEach(n => n.classList.remove("active"));
  $$(".tab").forEach(t => t.classList.remove("active"));
  btn.classList.add("active");
  $(`#tab-${tab}`).classList.add("active");
  const loaders = {
    dashboard: loadDashboard,
    proxies: loadProxies,
    providers: loadProviders,
    rules: loadRules,
    devices: () => { loadDevices(true); startDevicesPolling(); },
    settings: loadSettings,
    service: loadService,
  };
  loaders[tab]?.();
  if (tab === "dashboard") {
    trafficTimer = setInterval(() => refreshTrafficOnly().catch(() => {}), 12000);
  }
});

$$(".mode-btn").forEach(btn => btn.onclick = () => switchMode(btn.dataset.mode).catch(e => toast(e.message, true)));

$("#btn-refresh-dashboard").onclick = () => loadDashboard().catch(e => toast(e.message, true));
$("#btn-refresh-connections").onclick = () => refreshConnections().then(() => toast("连接已刷新")).catch(e => toast(e.message, true));
$("#btn-nodes-delay").onclick = () => refreshNodesWithDelay().catch(e => toast(e.message, true));

$("#btn-delay-test").onclick = async () => {
  toast("测速中…");
  try {
    const r = await api("/api/proxies/delay", { method: "POST", body: JSON.stringify({}) });
    const sorted = Object.entries(r.delays || {}).sort((a, b) => (a[1] < 0 ? 99999 : a[1]) - (b[1] < 0 ? 99999 : b[1]));
    renderLogViewer($("#service-output"), sorted.slice(0, 20).map(([k, v]) => `${k}: ${v} ms`).join("\n"));
    toast("测速完成");
    loadProxies();
  } catch (e) { toast(e.message, true); }
};

let providerFormMeta = { types: [], presets: [] };

function syncProviderFormFields() {
  const t = $("#provider-type-select")?.value || "http";
  $$(".provider-field-url").forEach(el => el.classList.toggle("hidden", t !== "http"));
  $$(".provider-field-path").forEach(el => el.classList.toggle("hidden", t !== "file"));
  $$(".provider-field-payload").forEach(el => el.classList.toggle("hidden", t !== "inline"));
  $$(".provider-field-interval").forEach(el => el.classList.toggle("hidden", t !== "http"));
  $$(".provider-field-ua, .provider-field-headers").forEach(el => el.classList.toggle("hidden", t !== "http"));
  const urlInput = $("#form-add-provider")?.querySelector("[name=url]");
  if (urlInput) urlInput.required = t === "http";
}

function renderProviderPresets() {
  const box = $("#provider-presets");
  if (!box) return;
  box.innerHTML = (providerFormMeta.presets || []).map(p =>
    `<button type="button" class="btn sm provider-preset-btn" data-preset="${escapeHtml(p.id)}">${escapeHtml(p.label)}</button>`
  ).join("");
  $$(".provider-preset-btn", box).forEach(btn => {
    btn.onclick = () => {
      const preset = (providerFormMeta.presets || []).find(p => p.id === btn.dataset.preset);
      if (!preset) return;
      const sel = $("#provider-type-select");
      if (sel) sel.value = preset.provider_type || "http";
      syncProviderFormFields();
      const form = $("#form-add-provider");
      const hint = $("#provider-form-hint");
      if (hint && preset.hint) hint.textContent = preset.hint;
      if (!form) return;
      const url = form.querySelector("[name=url]");
      const path = form.querySelector("[name=path]");
      if (url && preset.url_placeholder) url.placeholder = preset.url_placeholder;
      if (path && preset.path_placeholder) path.placeholder = preset.path_placeholder;
      const hdr = form.querySelector("[name=headers]");
      if (hdr && preset.default_headers) {
        hdr.value = Object.entries(preset.default_headers).map(([k, v]) => `${k}: ${v}`).join("\n");
      }
    };
  });
}

async function loadProviderFormMeta() {
  try {
    providerFormMeta = await api("/api/providers/types");
    renderProviderPresets();
  } catch (_) {
    providerFormMeta = { types: [], presets: [] };
  }
}

$("#btn-show-add-provider").onclick = () => {
  $("#add-provider-form").classList.remove("hidden");
  loadProviderFormMeta();
  syncProviderFormFields();
};
$("#btn-cancel-add").onclick = () => $("#add-provider-form").classList.add("hidden");
$("#provider-type-select")?.addEventListener("change", syncProviderFormFields);

$("#form-add-provider").onsubmit = async e => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const provider_type = fd.get("provider_type") || "http";
  const payloadText = (fd.get("payload") || "").trim();
  try {
    await api("/api/providers", {
      method: "POST",
      body: JSON.stringify({
        name: fd.get("name"),
        provider_type,
        url: fd.get("url") || "",
        path: fd.get("path") || "",
        payload: provider_type === "inline" ? payloadText : null,
        interval: Number(fd.get("interval") || 3600),
        user_agent: fd.get("user_agent") || null,
        headers: (fd.get("headers") || "").trim() || null,
        limit_gb: fd.get("limit_gb") || null,
        filter: fd.get("filter") || null,
        exclude_filter: fd.get("exclude_filter") || null,
        add_to_auto: fd.get("add_to_auto") === "on",
      }),
    });
    toast("机场已添加");
    e.target.reset();
    $("#add-provider-form").classList.add("hidden");
    loadProviders();
    loadProxies();
  } catch (err) { toast(err.message, true); }
};

$("#btn-save-rules").onclick = async () => {
  const rules = $("#rules-editor").value.split("\n").map(s => s.trim()).filter(Boolean);
  try {
    const r = await api("/api/rules", { method: "PUT", body: JSON.stringify({ rules }) });
    renderLogViewer($("#service-output"), r.apply?.message || "已保存");
    toast(r.apply?.ok ? "规则已应用" : "应用失败", !r.apply?.ok);
  } catch (e) { toast(e.message, true); }
};

$$("[data-rule]").forEach(btn => btn.onclick = () => {
  const ta = $("#rules-editor");
  const line = btn.dataset.rule;
  if (!ta.value.includes(line)) ta.value = (ta.value.trim() ? ta.value.trim() + "\n" : "") + line;
});

$("#btn-runtime-save").onclick = async () => {
  try {
    await api("/api/runtime", { method: "PATCH", body: JSON.stringify({ "log-level": $("#runtime-log").value }) });
    toast("日志级别已更新");
  } catch (e) { toast(e.message, true); }
};

$("#btn-tun-save").onclick = async () => {
  const enable = $("#tun-enable").checked;
  if (enable && !confirm("启用 TUN 将修改路由并重启 mihomo，继续？")) return;
  try {
    const r = await api("/api/tun", { method: "POST", body: JSON.stringify({ enable }) });
    $("#tun-status").textContent = JSON.stringify(r.tun, null, 2) + "\n" + (r.apply?.message || "");
    toast(r.apply?.ok ? (enable ? "TUN 已启用" : "TUN 已关闭") : "应用失败", !r.apply?.ok);
    loadDashboard();
  } catch (e) { toast(e.message, true); }
};

$("#btn-validate").onclick = async () => {
  const r = await api("/api/config/validate", { method: "POST" });
  renderLogViewer($("#service-output"), r.message);
  toast(r.ok ? "配置有效" : "配置无效", !r.ok);
};

$("#btn-apply").onclick = async () => {
  const r = await api("/api/config/apply", { method: "POST" });
  renderLogViewer($("#service-output"), r.message || JSON.stringify(r));
  toast(r.ok ? "已应用" : "应用失败", !r.ok);
};

$("#btn-restart").onclick = async () => {
  const r = await api("/api/service/restart", { method: "POST" });
  renderLogViewer($("#service-output"), r.message);
  toast(r.ok ? "已重启" : "重启失败", !r.ok);
};

$("#btn-refresh-logs").onclick = () => loadService().catch(e => toast(e.message, true));

$("#btn-devices-refresh").onclick = () => loadDevices().catch(e => toast(e.message, true));
$("#devices-online-only").onchange = () => loadDevices(true).catch(e => toast(e.message, true));
$("#btn-default-device-direct")?.addEventListener("click", () => saveDeviceDefaultPolicy("direct"));
$("#btn-default-device-proxy")?.addEventListener("click", () => saveDeviceDefaultPolicy("proxy"));
$("#devices-select-all")?.addEventListener("change", e => {
  const on = e.target.checked;
  $$("[data-device-select]").forEach(cb => { cb.checked = on; });
  updateDeviceBatchBar();
});
$("#btn-batch-clear")?.addEventListener("click", () => {
  $$("[data-device-select]").forEach(cb => { cb.checked = false; });
  updateDeviceBatchBar();
});
$("#btn-batch-policy-proxy")?.addEventListener("click", () => batchSetDevicePolicy("proxy"));
$("#btn-batch-policy-direct")?.addEventListener("click", () => batchSetDevicePolicy("direct"));
$("#btn-batch-policy-block")?.addEventListener("click", () => batchSetDevicePolicy("block"));
$("#btn-devices-apply").onclick = async () => {
  try {
    const r = await api("/api/devices/apply", { method: "POST" });
    toast(r.ok ? "iptables 策略已应用" : (r.errors?.[0] || "应用完成"), !r.ok);
  } catch (e) { toast(e.message, true); }
};

$$(".theme-btn").forEach(btn => btn.onclick = async () => {
  applyTheme(btn.dataset.theme);
  try {
    await api("/api/settings", { method: "PUT", body: JSON.stringify({ theme: btn.dataset.theme }) });
    panelSettings.theme = btn.dataset.theme;
    toast("主题已保存");
  } catch (e) { toast(e.message, true); }
});

$("#form-settings").onsubmit = async e => {
  e.preventDefault();
  const fd = new FormData(e.target);
  try {
    const data = await api("/api/settings", {
      method: "PUT",
      body: JSON.stringify({
        dashboard_auto_refresh: fd.get("dashboard_auto_refresh") === "on",
        devices_refresh_sec: Number(fd.get("devices_refresh_sec") || 15),
        auto_switch_enabled: fd.get("auto_switch_enabled") === "on",
        auto_switch_interval_sec: Number(fd.get("auto_switch_interval_sec") || 300),
        traffic_failover_enabled: fd.get("traffic_failover_enabled") === "on",
        traffic_failover_threshold: Number(fd.get("traffic_failover_threshold") || 100),
        node_test_cooldown_sec: Number(fd.get("node_test_cooldown_sec") || 600),
      }),
    });
    panelSettings = data;
    toast("设置已保存");
    if ($("#tab-devices").classList.contains("active")) startDevicesPolling();
  } catch (err) { toast(err.message, true); }
};

$("#form-password").onsubmit = async e => {
  e.preventDefault();
  const fd = new FormData(e.target);
  if (!confirm("修改密码将重启面板并需重新登录，继续？")) return;
  try {
    const r = await api("/api/settings/password", {
      method: "POST",
      body: JSON.stringify({
        old_password: fd.get("old_password"),
        new_password: fd.get("new_password"),
        confirm_password: fd.get("confirm_password"),
      }),
    });
    toast(r.message || "密码已更新");
    setTimeout(() => { window.location.href = "/logout"; }, 1500);
  } catch (err) { toast(err.message, true); }
};

$("#btn-provider-qr-close")?.addEventListener("click", () => {
  const dlg = $("#provider-qr-dialog");
  if (dlg?.close) dlg.close();
  else dlg?.classList.add("hidden");
});

initThemeListener();
api("/api/settings").then(s => {
  panelSettings = s;
  applyTheme(s.theme || localStorage.getItem("n1-theme") || "dark", true);
  if (s.dashboard_auto_refresh) {
    dashboardTimer = setInterval(() => {
      if ($("#tab-dashboard")?.classList.contains("active")) loadDashboard().catch(() => {});
    }, 30000);
  }
}).catch(() => applyTheme(localStorage.getItem("n1-theme") || "dark"));

loadDashboard().catch(e => toast(e.message, true));
trafficTimer = setInterval(() => refreshTrafficOnly().catch(() => {}), 12000);
