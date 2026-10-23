/* DataClaw Lean · 管理后台 */
const $ = (s, r = document) => r.querySelector(s);
const el = (t, c, h) => { const e = document.createElement(t); if (c) e.className = c; if (h != null) e.innerHTML = h; return e; };
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const A = { data: null };

async function api(path, body, method) {
  const r = await fetch(path, {
    method: method || (body === undefined ? "GET" : "POST"),
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (r.status === 401) { location.href = "/login"; throw new Error("未登录"); }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error?.message || "请求失败");
  return j;
}
function toast(m, bad) {
  const t = $("#toast"); t.textContent = m; t.hidden = false;
  t.style.background = bad ? "#be123c" : "#171a23";
  clearTimeout(t._t); t._t = setTimeout(() => (t.hidden = true), 2600);
}

(async function boot() {
  try { A.data = await api("/api/admin"); } catch (e) { return; }
  const me = await api("/api/me");
  $("#me-name").textContent = me.user.name; $("#me-role").textContent = me.user.dept;
  $("#me-avatar").textContent = me.user.name.slice(-2);
  document.querySelectorAll(".nav[data-tab]").forEach(a => a.onclick = e => { e.preventDefault(); tab(a.dataset.tab); });
  $("#logout").onclick = async () => { await api("/api/logout", {}); location.href = "/login"; };
  $("#pf-add").onclick = addPolicy;
  $("#pv-go").onclick = preview;
  $("#kn-go").onclick = () => knowledge($("#kn-q").value);
  $("#au-result").onchange = renderAudit;
  renderStats(); renderAgents(); renderPolicies(); renderDocs(); renderAudit(); preview();
})();

function tab(name) {
  document.querySelectorAll(".nav[data-tab]").forEach(a => a.classList.toggle("on", a.dataset.tab === name));
  document.querySelectorAll(".view").forEach(v => v.classList.toggle("on", v.id === "tab-" + name));
}

/* ---------------- 总览 ---------------- */
function renderStats() {
  const s = A.data.stats, box = $("#stats");
  const items = [
    ["数字员工", s.employees], ["会话", s.sessions], ["消息", s.messages], ["技能", s.skills],
    ["策略", s.policies], ["审计", s.audits], ["越权拦截", A.data.denied], ["用户", s.users],
  ];
  box.innerHTML = items.map(([k, v]) => `<div class="stat"><small>${k}</small><b>${v}</b></div>`).join("");
  $("#risk-box").innerHTML = `<div class="stat" style="border:0;padding:0"><small>拦截次数（denied）</small><b style="color:#be123c">${A.data.denied}</b></div>
    <p class="muted tiny">所有 denied 均可在「审计日志」按结果筛选复核。Agent 权限严格继承自绑定用户。</p>
    <div class="pre">${esc(JSON.stringify(A.data.trend.map(t => `${t.date}: ${t.count}`), null, 0))}</div>`;
  const dom = $("#trend");
  if (dom && window.echarts) {
    echarts.init(dom).setOption({
      grid: { left: 40, right: 16, top: 16, bottom: 30 },
      xAxis: { type: "category", data: A.data.trend.map(t => t.date) },
      yAxis: { type: "value" },
      series: [{ type: "bar", data: A.data.trend.map(t => t.count), itemStyle: { color: "#5b57e8", borderRadius: [6, 6, 0, 0] }, barWidth: 18 }],
      tooltip: { trigger: "axis" },
    });
  }
}

/* ---------------- 公共员工 ---------------- */
function renderAgents() {
  const box = $("#agent-cards"); box.innerHTML = "";
  A.data.agents.forEach(g => {
    const c = el("div", "ecard");
    c.innerHTML = `<div class="top"><span class="avatar">${esc(g.avatar)}</span>
        <div><b>${esc(g.name)}</b><small>${esc(g.role)} · v${g.version}</small></div></div>
      <p>${esc(g.desc)}</p>
      <div class="foot"><span>${(g.skills || []).length} 技能</span>·<span>${g.assignees} 人已分配</span>
        <span style="margin-left:auto"><button class="btn sm" data-assign="${g.id}">分配</button></span></div>`;
    c.querySelector("[data-assign]").onclick = () => assign(g);
    box.appendChild(c);
  });
}
async function assign(g) {
  const cands = A.data.users.filter(u => u.username !== "admin");
  const name = prompt(`把「${g.name}」分配给谁？输入账号：\n可选：${cands.map(u => u.username).join("、")}`, cands[0]?.username || "");
  if (!name) return;
  const u = A.data.users.find(x => x.username === name.trim());
  if (!u) { toast("找不到该账号", true); return; }
  try {
    const r = await api("/api/agent/assign", { agentId: g.id, userId: u.id });
    toast(r.created ? `已分配给 ${u.name}` : `${u.name} 已分配过`);
    A.data = await api("/api/admin"); renderAgents();
  } catch (e) { toast(e.message, true); }
}

/* ---------------- 数据安全 ---------------- */
function renderPolicies() {
  const box = $("#policy-table");
  box.innerHTML = `<table class="list"><thead><tr><th>主体</th><th>资源</th><th>动作</th><th>脱敏</th><th>行过滤</th><th></th></tr></thead><tbody>
    ${A.data.policies.map(p => `<tr><td>${esc(p.who)}</td><td>${esc(p.resource)}</td>
      <td><span class="badge ${p.action === "deny" ? "high" : "low"}">${esc(p.action)}</span></td>
      <td>${esc(p.mask || "—")}</td><td>${esc(p.rowFilter || "—")}</td>
      <td><button class="link" data-del="${p.id}">删除</button></td></tr>`).join("")}</tbody></table>`;
  box.querySelectorAll("[data-del]").forEach(b => b.onclick = async () => {
    await api(`/api/policy?id=${b.dataset.del}`, undefined, "DELETE").catch(e => toast(e.message, true));
    A.data = await api("/api/admin"); renderPolicies(); toast("策略已删除");
  });
}
async function addPolicy() {
  const p = { who: $("#pf-who").value, resource: $("#pf-res").value, action: $("#pf-act").value,
    mask: $("#pf-mask").value || "none", rowFilter: $("#pf-row").value.trim() };
  try {
    await api("/api/policy", p);
    A.data = await api("/api/admin"); renderPolicies(); toast("策略已保存");
  } catch (e) { toast(e.message, true); }
}
async function preview() {
  const sql = $("#pv-sql").value;
  try {
    const r = await api("/api/guard/preview", { sql, as: $("#pv-as").value });
    const rules = (r.rules || []).map(x => `· ${x.type}: ${x.detail}`).join("\n");
    const cols = (r.columns || []).join(", ");
    const rows = (r.rows || []).slice(0, 8);
    $("#pv-out").innerHTML = r.ok
      ? `<div class="muted tiny" style="margin:10px 0 4px">原始 SQL</div><div class="pre">${esc(r.original)}</div>
         <div class="muted tiny" style="margin:6px 0 4px">改写后 SQL</div><div class="pre">${esc(r.sql)}</div>
         <div class="muted tiny" style="margin:6px 0 4px">规则（${(r.rules || []).length}）</div><div class="pre">${esc(rules)}</div>
         <p class="tiny muted">返回 ${r.rowCount} 行 · ${r.ms}ms · 列：${esc(cols)} · 脱敏：${(r.masked || []).join(", ") || "无"}</p>
         <div class="scroll"><table class="list"><thead><tr>${(r.columns || []).map(c => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>
         ${rows.map(row => `<tr>${(r.columns || []).map(c => `<td>${esc(String(row[c] ?? ""))}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`
      : `<div class="badge high" style="margin-top:10px">已拒绝</div><p>${esc(r.denied || "")}</p>
         <div class="pre">${esc(r.sql)}</div>`;
  } catch (e) { toast(e.message, true); }
}

/* ---------------- 知识 ---------------- */
function renderDocs() {
  $("#docs").innerHTML = A.data.docs.map(d => `<div style="padding:8px 0;border-bottom:1px solid var(--line)">
    <b>${esc(d.name)}</b><br><small class="muted">${esc(d.type)} · ${d.text.length} 字</small></div>`).join("");
}
async function knowledge(q) {
  const r = await api("/api/knowledge/search", { q });
  $("#kn-out").innerHTML = (r.items || []).length
    ? r.items.map(i => `<div style="margin-top:10px"><b>${esc(i.doc)}</b> <span class="badge">${i.score} 分</span>
        <p class="muted tiny">${esc(i.snippet)}</p></div>`).join("")
    : `<p class="empty">没有命中：知识库中可能没有相关内容</p>`;
}

/* ---------------- 审计 ---------------- */
function renderAudit() {
  const filter = $("#au-result").value;
  const rows = A.data.audits.filter(a => !filter || a.result === filter);
  $("#audit-table").innerHTML = `<table class="list"><thead><tr><th>时间</th><th>操作人</th><th>动作</th><th>对象</th><th>风险</th><th>结果</th></tr></thead><tbody>
    ${rows.map(a => `<tr><td class="tiny">${esc(a.ts.replace("T", " ").slice(5, 19))}</td><td>${esc(a.actor)}</td>
      <td>${esc(a.action)}</td><td>${esc(a.target)}</td>
      <td><span class="badge ${esc(a.risk)}">${esc(a.risk)}</span></td>
      <td><span class="badge ${a.result === "denied" ? "denied" : "ok"}">${esc(a.result)}</span></td></tr>`).join("")}
    </tbody></table>`;
}
