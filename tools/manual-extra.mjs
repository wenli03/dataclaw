import { chromium } from "playwright-core";
import path from "node:path";

const BASE = "http://127.0.0.1:8787";
const OUT = path.resolve("../docs/screenshots-manual");
const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const browser = await chromium.launch({ executablePath: CHROME, headless: true, args: ["--no-sandbox"] });
const ctx = await browser.newContext({ viewport: { width: 1512, height: 950 }, deviceScaleFactor: 1.5, locale: "zh-CN" });
const page = await ctx.newPage();
const errs = [];
page.on("pageerror", e => errs.push(String(e).slice(0, 200)));

async function login(u, p) {
  await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
  await page.locator("input").nth(0).fill(u);
  await page.locator("input").nth(1).fill(p);
  await page.getByRole("button", { name: /进入工作台/ }).click();
  await page.waitForURL("**/chat**", { timeout: 20000 });
  await page.waitForTimeout(1200);
}

// 1. 管理员：以销售身份预览 CRM 行级过滤
await login("admin", "admin123");
await page.goto(`${BASE}/admin/data`, { waitUntil: "networkidle" });
await page.waitForTimeout(1300);
const demo = page.locator('[role="button"]').filter({ hasText: "demo" }).first();
if (await demo.count()) await demo.click();
await page.getByText("SQL 改写预览", { exact: true }).first().click().catch(() => {});
await page.waitForTimeout(700);
const sel = page.locator("select").filter({ has: page.locator("option", { hasText: "程景舟" }) }).first();
if (await sel.count()) {
  const opts = await sel.locator("option").allTextContents();
  const hit = opts.find(o => o.includes("程景舟"));
  if (hit) await sel.selectOption({ label: hit });
}
await page.locator("textarea").first().fill("select * from crm_customer limit 50");
await page.getByRole("button", { name: /执行预览/ }).click();
await page.waitForTimeout(1600);
await page.screenshot({ path: path.join(OUT, "27-admin-sql-rowfilter-sales.png") });
console.log("shot 27-admin-sql-rowfilter-sales");

// 2. 分析师：员工详情里的自动记忆（选对员工）
await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
await page.locator("input").nth(0).fill("analyst");
await page.locator("input").nth(1).fill("123456");
await page.getByRole("button", { name: /进入工作台/ }).click();
await page.waitForURL("**/chat**", { timeout: 20000 });
await page.goto(`${BASE}/employees`, { waitUntil: "networkidle" });
await page.waitForTimeout(1200);
const card = page.locator('[class*="card"]').filter({ hasText: "工时分析助手" }).first();
const edit = card.getByRole("button", { name: "编辑", exact: true }).first();
if (await edit.count()) {
  await edit.click();
  await page.waitForTimeout(1200);
  const memoryTitle = page.getByText(/^记忆（/).first();
  if (await memoryTitle.count()) {
    await memoryTitle.scrollIntoViewIfNeeded().catch(() => {});
    await page.waitForTimeout(500);
  }
  await page.screenshot({ path: path.join(OUT, "26-analyst-memory.png") });
  console.log("shot 26-analyst-memory");
}

console.log("errors", errs.length ? errs : "none");
await browser.close();
