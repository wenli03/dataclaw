import { chromium } from "playwright-core";
import path from "node:path";
import fs from "node:fs";

const BASE = process.env.BASE || "http://127.0.0.1:8788";
const OUT = process.env.OUT || path.resolve("../docs/screenshots-lean");
fs.mkdirSync(OUT, { recursive: true });
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";

const browser = await chromium.launch({ executablePath: CHROME, headless: true, args: ["--no-sandbox"] });
const ctx = await browser.newContext({ viewport: { width: 1512, height: 950 }, deviceScaleFactor: 1.5, locale: "zh-CN" });
const page = await ctx.newPage();
const errors = [];
page.on("console", m => { if (m.type() === "error") errors.push(m.text().slice(0, 200)); });
page.on("pageerror", e => errors.push(String(e).slice(0, 200)));

const shot = name => page.screenshot({ path: path.join(OUT, name + ".png") });

// 登录
await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
await page.waitForTimeout(500);
await shot("30-login");

async function login(u, p) {
  await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
  await page.fill("#u", u);
  await page.fill("#p", p);
  await page.click("#go");
  await page.waitForURL("**/app", { timeout: 15000 });
  await page.waitForTimeout(1200);
}

await login("admin", "admin123");
await shot("31-app");

// 会话页 + 触发工时分析
await page.fill("#input", "帮我分析下上季度各区域工时效率情况");
await page.click("#send");
try {
  await page.waitForSelector("canvas", { timeout: 60000 });
  await page.waitForTimeout(2000);
  const c = page.locator("canvas").first();
  await c.scrollIntoViewIfNeeded().catch(() => {});
  await page.waitForTimeout(600);
  await shot("32-chat-dashboard");
  await page.locator("h1, .report").first().scrollIntoViewIfNeeded().catch(() => {});
  await page.waitForTimeout(600);
  await shot("33-chat-report");
} catch (e) {
  console.log("chat wait failed", String(e).slice(0, 120));
  await shot("32-chat-error");
}

// 员工 / 技能
await page.click('.nav[data-view="employees"]');
await page.waitForTimeout(700);
await shot("34-employees");
await page.click('.nav[data-view="skills"]');
await page.waitForTimeout(700);
await shot("35-skills");

// 管理后台
await page.goto(`${BASE}/admin`, { waitUntil: "networkidle" });
await page.waitForTimeout(1200);
await shot("36-admin-overview");
await page.click('.nav[data-tab="data"]');
await page.waitForTimeout(1000);
await shot("37-admin-data");
await page.locator("#pv-go").scrollIntoViewIfNeeded().catch(() => {});
await page.click("#pv-go");
await page.waitForTimeout(1200);
await shot("38-admin-sql-preview");
await page.click('.nav[data-tab="audit"]');
await page.waitForTimeout(800);
await shot("39-admin-audit");
await page.click('.nav[data-tab="agents"]');
await page.waitForTimeout(700);
await shot("40-admin-agents");

// 法务：合同审查 + HITL
await login("legal", "123456");
await page.fill("#input", "请按照公司标准合同规则审查这份合同");
await page.click("#send");
try {
  await page.waitForSelector("#modal-approve:not([hidden])", { timeout: 30000 });
  await page.waitForTimeout(400);
  await shot("41-hitl-approval");
  await page.click("#ap-yes");
  await page.waitForTimeout(3500);
  await page.locator(".redlines").first().scrollIntoViewIfNeeded().catch(() => {});
  await page.waitForTimeout(500);
  await shot("42-contract");
} catch (e) {
  console.log("approval flow failed", String(e).slice(0, 120));
  await shot("41-contract-error");
}

console.log("console errors:", errors.length ? errors : "none");
await browser.close();
console.log("done ->", OUT);
