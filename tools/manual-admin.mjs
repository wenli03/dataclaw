import { chromium } from "playwright-core";
import fs from "node:fs";
import path from "node:path";

const BASE = process.env.BASE || "http://127.0.0.1:8787";
const OUT = path.resolve("../docs/screenshots-manual");
fs.mkdirSync(OUT, { recursive: true });
const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const XLSX = path.resolve("../docs/samples/工时与客户明细（演示样例）.xlsx");

const browser = await chromium.launch({ executablePath: CHROME, headless: true, args: ["--no-sandbox"] });
const ctx = await browser.newContext({ viewport: { width: 1512, height: 950 }, deviceScaleFactor: 1.5, locale: "zh-CN" });
const page = await ctx.newPage();
const errors = [];
page.on("console", m => { if (m.type() === "error") errors.push("console: " + m.text().slice(0, 200)); });
page.on("pageerror", e => errors.push("pageerror: " + String(e).slice(0, 200)));

const shot = async (name, opts = {}) => {
  await page.waitForTimeout(opts.wait ?? 300);
  await page.screenshot({ path: path.join(OUT, name + ".png"), fullPage: !!opts.fullPage });
  console.log("shot", name);
};

async function mark(locator, n, color = "#e11d48") {
  const box = await locator.first().boundingBox();
  if (!box) return;
  await page.evaluate(({ box, n, color }) => {
    document.querySelectorAll(".__m").forEach(e => e.remove());
    const d = document.createElement("div");
    d.className = "__m";
    d.style.cssText = `position:fixed;left:${box.x - 4}px;top:${box.y - 4}px;width:${box.width + 8}px;height:${box.height + 8}px;border:2.5px solid ${color};border-radius:9px;z-index:99998;pointer-events:none;box-shadow:0 0 0 3px rgba(225,29,72,.14)`;
    const b = document.createElement("div");
    b.className = "__m";
    b.style.cssText = `position:fixed;left:${box.x - 11}px;top:${box.y - 11}px;min-width:22px;height:22px;padding:0 5px;border-radius:11px;background:${color};color:#fff;font:600 12px/22px system-ui;text-align:center;z-index:99999;box-shadow:0 2px 6px rgba(0,0,0,.25)`;
    b.textContent = String(n);
    document.body.append(d, b);
  }, { box, n, color });
  await page.waitForTimeout(120);
}
async function clearMarks() { await page.evaluate(() => document.querySelectorAll(".__m").forEach(e => e.remove())); }

async function login(u, p) {
  await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
  await page.locator("input").nth(0).fill(u);
  await page.locator("input").nth(1).fill(p);
  await page.getByRole("button", { name: /进入工作台/ }).click();
  await page.waitForURL("**/chat**", { timeout: 20000 });
  await page.waitForTimeout(1200);
}

// ---------- ensure an Excel datasource exists (演示新能力) ----------
const lr = await fetch(`${BASE}/api/auth/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: "admin", password: "admin123" }) });
const tok = (await lr.json()).token;
const H = { "Content-Type": "application/json", Authorization: "Bearer " + tok };
const src = await (await fetch(`${BASE}/api/datasources`, { headers: H })).json();
if (!(src.items || []).some(x => x.name.includes("Excel 工时样例"))) {
  const cr = await fetch(`${BASE}/api/datasources`, { method: "POST", headers: H, body: JSON.stringify({ name: "Excel 工时样例（演示）", type: "excel", database: XLSX, config: { path: XLSX }, description: "从 Excel 直接接入：自动建表、识别敏感列、复用同一套 SQL 网关" }) });
  console.log("excel datasource", cr.status, (await cr.json()).id);
} else {
  console.log("excel datasource exists");
}

// ---------- 1. 登录 ----------
await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
await page.waitForTimeout(500);
await shot("01-login");
await mark(page.locator(".grid.grid-cols-2.gap-2 button").first(), 1);
await mark(page.getByRole("button", { name: /进入工作台/ }), 2);
await shot("02-login-annotated");
await clearMarks();

await login("admin", "admin123");

// ---------- 2. 运营总览 ----------
await page.goto(`${BASE}/admin`, { waitUntil: "networkidle" });
await page.waitForTimeout(1600);
await shot("03-admin-overview", { wait: 300 });

// ---------- 3. 用户与角色 ----------
await page.goto(`${BASE}/admin/users`, { waitUntil: "networkidle" });
await page.waitForTimeout(900);
await shot("04-admin-users");

// ---------- 4. 公共员工 + 分配 ----------
await page.goto(`${BASE}/admin/agents`, { waitUntil: "networkidle" });
await page.waitForTimeout(1000);
await shot("05-admin-public-agents");
const assignBtn = page.getByRole("button", { name: "分配", exact: true }).first();
if (await assignBtn.count()) {
  await assignBtn.click();
  await page.waitForTimeout(700);
  await shot("06-admin-public-agent-assign");
  await page.keyboard.press("Escape").catch(() => {});
  const cancel = page.getByRole("button", { name: /取消|关闭/ }).first();
  if (await cancel.count()) await cancel.click().catch(() => {});
  await page.waitForTimeout(400);
}

// ---------- 5. 数据安全：数据源 + 元数据 ----------
await page.goto(`${BASE}/admin/data`, { waitUntil: "networkidle" });
await page.waitForTimeout(1200);
await shot("07-admin-datasources");
// 新增数据源弹窗
const addDs = page.getByRole("button", { name: /新增数据源/ }).first();
if (await addDs.count()) {
  await addDs.click();
  await page.waitForTimeout(500);
  const typeSel = page.locator("select").filter({ has: page.locator("option", { hasText: "EXCEL" }) }).first();
  if (await typeSel.count()) await typeSel.selectOption({ label: "EXCEL" }).catch(() => {});
  await page.getByPlaceholder("如 工时数仓").fill("业务 Excel 接入").catch(() => {});
  await page.locator('input[placeholder="dataclaw"]').fill(XLSX).catch(() => {});
  const desc = page.locator("textarea").last();
  if (await desc.count()) await desc.fill("从 Excel 直接接入：自动建表、识别敏感列、复用同一套 SQL 网关").catch(() => {});
  await shot("08-admin-datasource-modal");
  const cancel = page.getByRole("button", { name: "取消", exact: true }).first();
  if (await cancel.count()) await cancel.click().catch(() => {});
  await page.waitForTimeout(400);
}

// 选中 Excel 数据源，展示表元数据
const excelCard = page.locator('[role="button"]').filter({ hasText: "Excel 工时样例" }).first();
if (await excelCard.count()) {
  await excelCard.click();
  await page.waitForTimeout(900);
  await shot("09-admin-excel-metadata");
}

// 访问策略
const tabPolicies = page.getByRole("tab", { name: /访问策略/ }).first();
if (await tabPolicies.count()) {
  await tabPolicies.click();
} else {
  await page.getByText("访问策略", { exact: true }).first().click().catch(() => {});
}
await page.waitForTimeout(1000);
await shot("10-admin-policies");

// SQL 改写预览（demo 数据源 + 以 analyst 身份）
await page.getByText("数据源与元数据", { exact: true }).first().click().catch(() => {});
await page.waitForTimeout(700);
const demoCard = page.locator('[role="button"]').filter({ hasText: "demo" }).first();
if (await demoCard.count()) { await demoCard.click(); await page.waitForTimeout(500); }
const tabPreview = page.getByRole("tab", { name: /SQL 改写预览/ }).first();
if (await tabPreview.count()) await tabPreview.click();
else await page.getByText("SQL 改写预览", { exact: true }).first().click().catch(() => {});
await page.waitForTimeout(700);
const userSel = page.locator("select").filter({ has: page.locator("option", { hasText: "林知微" }) }).first();
if (await userSel.count()) {
  const opts = await userSel.locator("option").allTextContents();
  const hit = opts.find(o => o.includes("林知微"));
  if (hit) await userSel.selectOption({ label: hit });
}
await page.locator("textarea").first().fill("select * from worktime_fact limit 5");
await page.getByRole("button", { name: /执行预览/ }).click();
await page.waitForTimeout(1500);
await shot("11-admin-sql-preview");

// Excel 数据源的预览（新页面：默认以管理员身份，避免沿用上一段的分析师身份）
const p2 = await ctx.newPage();
await p2.goto(`${BASE}/admin/data`, { waitUntil: "networkidle" });
await p2.waitForTimeout(1300);
const excelCard2 = p2.locator('[role="button"]').filter({ hasText: "Excel 工时样例" }).first();
if (await excelCard2.count()) {
  await excelCard2.click();
  await p2.waitForTimeout(700);
}
await p2.getByText("SQL 改写预览", { exact: true }).first().click().catch(() => {});
await p2.waitForTimeout(700);
const sel2 = p2.locator("select").filter({ has: p2.locator("option", { hasText: "林知微" }) }).first();
if (await sel2.count()) await sel2.selectOption({ index: 0 });
await p2.waitForTimeout(300);
await p2.locator("textarea").first().fill('select * from "工时明细" limit 5');
await p2.getByRole("button", { name: /执行预览/ }).click();
await p2.waitForTimeout(1500);
await p2.screenshot({ path: path.join(OUT, "12-admin-excel-preview.png") });
console.log("shot 12-admin-excel-preview");
await p2.close();

// ---------- 6. 知识中台 ----------
await page.goto(`${BASE}/admin/knowledge`, { waitUntil: "networkidle" });
await page.waitForTimeout(1000);
await shot("13-admin-knowledge");
const searchInput = page.locator('input[placeholder*="检索"], input[placeholder*="搜索"]').first();
if (await searchInput.count()) {
  await searchInput.fill("合同审查 付款 违约金");
  const btn = page.getByRole("button", { name: /检索|搜索/ }).first();
  if (await btn.count()) await btn.click();
  await page.waitForTimeout(1200);
  await shot("14-admin-knowledge-search");
}

// ---------- 7. 渠道接入 ----------
await page.goto(`${BASE}/admin/channels`, { waitUntil: "networkidle" });
await page.waitForTimeout(1000);
await shot("15-admin-channels");

// ---------- 8. 审计日志（筛选 denied） ----------
await page.goto(`${BASE}/admin/audit`, { waitUntil: "networkidle" });
await page.waitForTimeout(1200);
await shot("16-admin-audit");
const resultSel = page.locator("select").filter({ has: page.locator("option", { hasText: "已拒绝" }) }).first();
if (await resultSel.count()) {
  await resultSel.selectOption({ label: "已拒绝" });
  await page.waitForTimeout(1200);
  await shot("17-admin-audit-denied");
}

// ---------- 9. 技能超市 + 技能详情 ----------
await page.goto(`${BASE}/skills`, { waitUntil: "networkidle" });
await page.waitForTimeout(1000);
await shot("18-skills-market");
const firstSkill = page.getByRole("button", { name: "查看", exact: true }).first();
if (await firstSkill.count()) {
  await firstSkill.click();
  await page.waitForTimeout(1000);
  await shot("19-skill-detail");
  await page.keyboard.press("Escape").catch(() => {});
}

// ---------- 10. 新建员工弹窗 ----------
await page.goto(`${BASE}/employees`, { waitUntil: "networkidle" });
await page.waitForTimeout(900);
const newEmp = page.getByRole("button", { name: /新建员工/ }).first();
if (await newEmp.count()) {
  await newEmp.click();
  await page.waitForTimeout(700);
  await shot("20-new-employee");
}

console.log("console errors:", errors.length ? errors : "none");
await browser.close();
console.log("done ->", OUT);
