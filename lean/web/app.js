/* DataClaw Lean · 工作台（无框架，原生 JS + SSE） */
const $ = (s, r = document) => r.querySelector(s);
const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const S = { data: null, emp: null, session: null, streaming: false, cur: null };

async function api(path, body) {
  const r = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (r.status === 401) { location.href = "/login"; throw new Error("未登录"); }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error?.message || "请求失败");
  return j;
}
function toast(msg, bad) {
  const t = $("#toast"); t.textContent = msg; t.hidden = false;
  t.style.background = bad ? "#be123c" : "#171a23";
  clearTimeout(t._t); t._t = setTimeout(() => (t.hidden = true), 2600);
}

/* ---------------- 启动 ---------------- */
(async function boot() {
  try { S.data = await api("/api/bootstrap"); } catch (e) { return; }
  const u = S.data.user;
  $("#me-name").textContent = u.name; $("#me-role").textContent = u.dept;
  $("#me-avatar").textContent = u.name.slice(-2);
  if (S.data.isAdmin) $("#nav-admin").hidden = false;
  S.emp = S.data.employees[0] || null;
  renderNav(); renderEmpPick(); renderEmployees(); renderSkills(); renderChatHead(); loadSessions();
  $("#logout").onclick = async () => { await api("/api/logout", {}); location.href = "/login"; };
  document.querySelectorAll(".nav[data-view]").forEach(a => a.onclick = () => { renderNav(a.dataset.view); });
  $("#new-session").onclick = () => newSession();
  $("#send").onclick = send;
  $("#input").onkeydown = e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } };
  $("#new-emp").onclick = openEmpModal;
  $("#emp-tpl").onchange = () => {
    const t = S.data.templates.find(x => x.id === $("#emp-tpl").value);
    if (t) { $("#emp-soul").value = t.soul; $("#emp-name").value = t.name + "（我的）"; }
  };
  $("#emp-save").onclick = createEmp;
  document.querySelectorAll("[data-close]").forEach(b => b.onclick = closeAll);
  $("#ap-yes").onclick = () => decide(true);
  $("#ap-no").onclick = () => decide(false);
  if (location.hash === "#employees") renderNav("employees");
  if (location.hash === "#skills") renderNav("skills");
})();

function renderNav(view = "chat") {
  document.querySelectorAll(".nav[data-view]").forEach(a => a.classList.toggle("on", a.dataset.view === view));
  document.querySelectorAll(".view").forEach(v => v.classList.toggle("on", v.id === "view-" + view));
  history.replaceState(null, "", "#" + view);
}

/* ---------------- 员工/会话 ---------------- */
function renderEmpPick() {
  const box = $("#emp-pick"); box.innerHTML = "";
  S.data.employees.forEach(e => {
    const d = el("div", "emp-item" + (S.emp?.id === e.id ? " on" : ""));
    d.innerHTML = `<span class="avatar">${esc(e.avatar || e.name.slice(0, 2))}</span><span>${esc(e.name)}<small class="muted"> · ${e.skills.length} 技能</small></span>`;
    d.onclick = () => { S.emp = e; S.session = null; $("#msgs").innerHTML = ""; renderEmpPick(); renderChatHead(); loadSessions(); };
    box.appendChild(d);
  });
}
function renderChatHead() {
  const h = $("#chat-head");
  if (!S.emp) { h.innerHTML = `<span class="muted">还没有员工，先去「员工」页创建</span>`; return; }
  h.innerHTML = `<span class="avatar">${esc(S.emp.avatar || S.emp.name.slice(0, 2))}</span>
    <div><b>${esc(S.emp.name)}</b><br><small>${esc(S.emp.role)} · 已装 ${S.emp.skills.length} 个技能 ${S.emp.agentId ? "· 来自公共员工" : ""}</small></div>`;
}
async function loadSessions() {
  if (!S.emp) return;
  const r = await api(`/api/sessions?emp=${S.emp.id}${S.session ? "&sid=" + S.session.id : ""}`);
  const items = r.items || [];
  if (!items.length) { $("#sessions").innerHTML = `<div class="empty">还没有会话<br>直接在右侧提问即可</div>`; return; }
  renderSessions(items, r.activeId || items[0].id);
  if (!S.session) S.session = items[0];
  if (r.messages && r.messages.length) paintMessages(r.messages);
}
function renderSessions(items, activeId) {
  const box = $("#sessions"); box.innerHTML = "";
  items.forEach(s => {
    const d = el("div", "sess" + (s.id === activeId ? " on" : ""));
    d.innerHTML = `<b>${esc(s.title)}</b><small>${s.count} 条 · ${new Date(s.updated).toLocaleString("zh-CN", { hour12: false }).slice(5, 16)}</small>`;
    d.onclick = () => openSession(s.id);
    box.appendChild(d);
  });
}
async function openSession(id) {
  const r = await api(`/api/sessions?emp=${S.emp.id}&sid=${id}`);
  S.session = (r.items || []).find(x => x.id === id) || S.session;
  renderSessions((r.items || []), id);
  paintMessages(r.messages || []);
}
function newSession() { S.session = null; $("#msgs").innerHTML = ""; document.querySelectorAll(".sess").forEach(x => x.classList.remove("on")); }

/* ---------------- 消息渲染 ---------------- */
function paintMessages(list) {
  $("#msgs").innerHTML = "";
  list.forEach(m => {
    const node = el("div", "msg " + m.role);
    if (m.role === "user") node.innerHTML = `<div class="bubble">${esc(m.content)}</div>`;
    else {
      node.appendChild(stepsNode(m.steps || []));
      node.appendChild(el("div", "text", esc(m.content)));
      (m.artifacts || []).forEach(a => node.appendChild(artifactNode(a)));
    }
    $("#msgs").appendChild(node);
  });
  scrollBottom();
}
function stepsNode(steps) {
  const wrap = el("div", "steps");
  steps.forEach(s => {
    const d = el("div", "step " + s.status);
    d.innerHTML = `<span class="dot"></span><div><b>${esc(s.title)}</b> <small>${s.status === "done" ? (s.ms || 0) + "ms" : s.status}</small>
      <div class="out">${esc(JSON.stringify(s.output ?? {}, null, 1))}</div></div>`;
    d.onclick = () => d.classList.toggle("open");
    wrap.appendChild(d);
  });
  return wrap;
}

function artifactNode(a) {
  const p = a.payload || {};
  const wrap = el("div", "art");
  const head = el("div", "head");
  head.innerHTML = `<div><b>${esc(a.title)}</b><br><small>${a.kind === "dashboard" ? "可视化大屏" : a.kind === "report" ? "Markdown 报告" : a.kind === "html" ? "网页产物" : "Word 文档"}</small></div>`;
  if (a.kind === "docx") head.innerHTML += `<a class="btn sm" href="/api/artifact/${a.id}/download">下载修订版</a>`;
  wrap.appendChild(head);
  const body = el("div", "body");

  if (a.kind === "dashboard") {
    body.innerHTML = `<div class="kpis">${(p.kpis || []).map(k => `<div class="kpi"><small>${esc(k.label)}</small><b>${esc(k.value)}</b>${k.delta ? `<small style="color:${String(k.delta).startsWith("-") ? "#be123c" : "#047857"}">${esc(k.delta)}</small>` : ""}</div>`).join("")}</div>
      <div class="charts">${(p.charts || []).map((c, i) => `<div class="chart"><b>${esc(c.title || "")}</b><div id="chart-${a.id}-${i}" style="height:${c.height || 260}px"></div></div>`).join("")}</div>
      <ul class="insights">${(p.insights || []).map(i => `<li class="${i.level}">${esc(i.text)}</li>`).join("")}</ul>
      <p class="tiny muted">数据来源：${esc(p.source?.datasource || "demo.db")} · ${p.source?.rows || 0} 行 · 已脱敏：${(p.source?.masked || []).join(", ") || "无"}</p>`;
    wrap.appendChild(body);
    setTimeout(() => (p.charts || []).forEach((c, i) => {
      const dom = document.getElementById(`chart-${a.id}-${i}`);
      if (dom && window.echarts) echarts.init(dom).setOption(c.option);
    }), 30);
  } else if (a.kind === "report") {
    body.innerHTML = `<div class="report">${p.html || ""}</div>`;
    wrap.appendChild(body);
  } else if (a.kind === "html") {
    const f = el("iframe", "guide"); f.setAttribute("sandbox", "allow-same-origin"); f.srcdoc = p.html || "";
    wrap.appendChild(f);
  } else if (a.kind === "docx") {
    const st = p.stats || {};
    body.innerHTML = `<div style="display:flex;gap:8px;margin-bottom:10px">
        <span class="badge">风险 ${st.risks || 0}</span><span class="badge high">高 ${st.high || 0}</span>
        <span class="badge medium">中 ${st.medium || 0}</span><span class="badge low">低 ${st.low || 0}</span></div>
      <table class="redlines"><thead><tr><th>条款</th><th>风险</th><th>问题</th><th>修订建议</th></tr></thead><tbody>
      ${(p.redlines || []).map(r => `<tr><td>${esc(r.clause)}<br><small class="muted">${esc(r.title)}</small></td>
        <td><span class="badge ${r.level}">${r.level === "high" ? "高" : r.level === "medium" ? "中" : "低"}</span></td>
        <td>${esc(r.issue)}</td><td>${esc(r.suggestion)}</td></tr>`).join("")}</tbody></table>`;
    wrap.appendChild(body);
  }
  return wrap;
}

function scrollBottom() { const m = $("#msgs"); m.scrollTop = m.scrollHeight; }

/* ---------------- 发送 / SSE ---------------- */
async function send() {
  if (S.streaming) return;
  const ta = $("#input"); const text = ta.value.trim(); if (!text) return;
  if (!S.emp) { toast("请先创建数字员工", true); return; }
  ta.value = "";
  S.streaming = true; $("#send").disabled = true; $("#send").textContent = "执行中…";

  const userNode = el("div", "msg user", `<div class="bubble">${esc(text)}</div>`);
  $("#msgs").appendChild(userNode);
  const node = el("div", "msg assistant");
  const steps = el("div", "steps"); const textEl = el("div", "text cursor");
  node.append(steps, textEl); $("#msgs").appendChild(node);
  scrollBottom();

  S.cur = { content: "", steps: [], artifacts: [], stepNodes: {} };
  try {
    await stream("/api/chat", { sessionId: S.session?.id || "", empId: S.emp.id, content: text }, (ev, d) => {
      if (ev === "start") { if (!S.session) S.session = { id: d.sessionId, title: d.title }; }
      else if (ev === "step") renderStep(steps, d);
      else if (ev === "delta") { S.cur.content += d.text; textEl.textContent = S.cur.content; scrollBottom(); }
      else if (ev === "artifact") { node.appendChild(artifactNode(d)); scrollBottom(); }
      else if (ev === "approval") showApproval(d);
      else if (ev === "done") { S.streaming = false; }
    });
  } catch (e) { toast(e.message, true); }
  textEl.classList.remove("cursor");
  $("#send").disabled = false; $("#send").textContent = "发送";
  S.streaming = false;
  loadSessions();
}

function renderStep(box, s) {
  if (s.status === "running") {
    const d = el("div", "step");
    d.innerHTML = `<span class="dot"></span><div><b>${esc(s.title)}</b> <small>执行中…</small></div>`;
    box.appendChild(d); S.cur.stepNodes[s.tool] = d; scrollBottom(); return;
  }
  const d = S.cur?.stepNodes?.[s.tool];
  if (d) {
    d.className = "step " + s.status;
    d.innerHTML = `<span class="dot"></span><div><b>${esc(s.title)}</b> <small>${s.ms || 0}ms</small>
      <div class="out">${esc(JSON.stringify(s.output ?? {}, null, 1))}</div></div>`;
    d.onclick = () => d.classList.toggle("open");
  }
}

async function stream(path, body, onEvent) {
  const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) { const j = await res.json().catch(() => ({})); throw new Error(j.error?.message || "请求失败"); }
  const reader = res.body.getReader(); const dec = new TextDecoder(); let buf = "";
  for (;;) {
    const { done, value } = await reader.read(); if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const raw = buf.slice(0, i); buf = buf.slice(i + 2);
      const ev = /^event:\s*(.+)$/m.exec(raw)?.[1] || "message";
      const data = /^data:\s*([\s\S]*)$/m.exec(raw)?.[1] || "{}";
      try { onEvent(ev, JSON.parse(data)); } catch (_) {}
    }
  }
}

/* ---------------- HITL 审批 ---------------- */
function showApproval(d) {
  $("#ap-action").textContent = d.action;
  $("#ap-reason").textContent = d.reason;
  $("#modal-approve").hidden = false;
  $("#modal-approve").dataset.id = d.id;
}
async function decide(ok) {
  const id = $("#modal-approve").dataset.id;
  $("#modal-approve").hidden = true;
  await api("/api/chat/approve", { id, decision: ok ? "approved" : "rejected" }).catch(e => toast(e.message, true));
}

/* ---------------- 员工页 ---------------- */
function renderEmployees() {
  const box = $("#emp-cards"); box.innerHTML = "";
  if (!S.data.employees.length) { box.innerHTML = `<div class="empty">还没有数字员工，点右上角「新建员工」</div>`; return; }
  S.data.employees.forEach(e => {
    const c = el("div", "ecard");
    const skills = e.skills.map(id => S.data.skills.find(s => s.id === id)?.name).filter(Boolean).join("、") || "未装载技能";
    c.innerHTML = `<div class="top"><span class="avatar">${esc(e.avatar || e.name.slice(0, 2))}</span>
        <div><b>${esc(e.name)}</b><small>${esc(e.role)} ${e.agentId ? "· 公共副本" : ""}</small></div></div>
      <p>${esc(e.soul.slice(0, 110))}…</p>
      <div class="foot"><span>${e.skills.length} 技能</span>·<span>${e.memory ? "记忆开启" : "记忆关闭"}</span>
        <span style="margin-left:auto"><button class="btn sm" data-chat="${e.id}">对话</button></span></div>`;
    c.querySelector("[data-chat]").onclick = () => { S.emp = e; S.session = null; renderNav("chat"); renderEmpPick(); renderChatHead(); loadSessions(); };
    box.appendChild(c);
  });
}

function openEmpModal() {
  const sel = $("#emp-tpl");
  sel.innerHTML = S.data.templates.map(t => `<option value="${t.id}">${esc(t.name)} · ${esc(t.desc)}</option>`).join("");
  const t = S.data.templates[0];
  $("#emp-soul").value = t ? t.soul : "";
  $("#emp-name").value = t ? t.name + "（我的）" : "";
  $("#modal-emp").hidden = false;
}
async function createEmp() {
  try {
    const emp = await api("/api/employee", {
      name: $("#emp-name").value.trim(), templateId: $("#emp-tpl").value, soul: $("#emp-soul").value,
    });
    S.data.employees.push(emp);
    if (!S.emp) S.emp = emp;
    $("#modal-emp").hidden = true;
    renderEmployees(); renderEmpPick(); renderChatHead();
    toast("数字员工已创建");
  } catch (e) { toast(e.message, true); }
}

/* ---------------- 技能页 ---------------- */
function renderSkills() {
  const box = $("#skill-cards"); box.innerHTML = "";
  S.data.skills.forEach(s => {
    const risk = { low: "低风险", medium: "中风险", high: "高风险" }[s.risk] || s.risk;
    const c = el("div", "ecard");
    c.innerHTML = `<div class="top"><span class="avatar">${esc(s.name.slice(0, 1).toUpperCase())}</span>
        <div><b>${esc(s.name)}</b><small>${esc(s.category)} · ${esc(risk)}</small></div></div>
      <p>${esc(s.desc)}</p>
      <div class="foot"><span class="badge ${s.installed ? "ok" : ""}">${s.installed ? "已装载" : "未装载"}</span>
        <span style="margin-left:auto"><button class="btn sm">${s.installed ? "查看 SKILL.md" : "装载到当前员工"}</button></span></div>`;
    c.querySelector("button").onclick = async () => {
      if (s.installed) { showSkill(s); return; }
      if (!S.emp) { toast("请先创建数字员工", true); return; }
      try {
        await api("/api/skill/install", { skillId: s.id, empId: S.emp.id });
        s.installed = true; S.emp.skills.push(s.id); renderSkills(); renderEmpPick(); renderChatHead(); toast("已装载技能");
      } catch (e) { toast(e.message, true); }
    };
    box.appendChild(c);
  });
}
function showSkill(s) {
  const d = $("#drawer"); $("#drawer-body").innerHTML =
    `<h3>${esc(s.name)} <span class="badge ${s.risk}">${esc(s.risk)}</span></h3>
     <p class="muted">${esc(s.desc)}</p><div class="pre">${esc(s.content)}</div>`;
  d.hidden = false;
}
function closeAll() { document.querySelectorAll(".modal,.drawer").forEach(x => (x.hidden = true)); }
