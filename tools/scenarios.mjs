import { chromium } from "playwright-core";
import path from "node:path";
import fs from "node:fs";

const BASE = process.env.BASE || "http://127.0.0.1:8899";
const OUT = process.env.OUT || path.resolve("../docs/screenshots");
fs.mkdirSync(OUT, { recursive: true });
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";

async function session(user, pass) {
  const browser = await chromium.launch({ executablePath: CHROME, headless: true, args: ["--no-sandbox"] });
  const ctx = await browser.newContext({ viewport: { width: 1512, height: 950 }, deviceScaleFactor: 1.5, locale: "zh-CN" });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => console.log("[pageerror]", String(e).slice(0, 300)));
  page.on("console", (m) => { if (m.type() === "error") console.log("[console.error]", m.text().slice(0, 200)); });
  await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
  await page.fill('input[placeholder="username"]', user);
  await page.fill('input[type="password"]', pass);
  await page.click('button[type="submit"]');
  await page.waitForURL("**/chat**");
  await page.waitForTimeout(1200);
  return { browser, page };
}

async function trigger(page, label) {
  const el = page.getByText(label, { exact: true }).first();
  if (!(await el.count())) throw new Error(`找不到示例卡片: ${label}`);
  await el.click();
  console.log("triggered:", label);
}

/* ---------- A: 工时分析 ---------- */
{
  const { browser, page } = await session("analyst", "123456");
  await trigger(page, "工时效率分析");
  await page.waitForSelector("canvas", { timeout: 120000 });
  await page.waitForTimeout(3500);
  // 滚到大屏第一个图表
  await page.locator("canvas").first().scrollIntoViewIfNeeded().catch(() => {});
  await page.waitForTimeout(800);
  await page.screenshot({ path: path.join(OUT, "20-scenario-A-dashboard.png") });
  console.log("A dashboard ok");
  await page.locator("text=深度分析报告").last().scrollIntoViewIfNeeded().catch(() => {});
  await page.waitForTimeout(800);
  await page.screenshot({ path: path.join(OUT, "21-scenario-A-report.png") });
  console.log("A report ok");
  await browser.close();
}

/* ---------- B: 销售情报 ---------- */
{
  const { browser, page } = await session("sales", "123456");
  await trigger(page, "拜访前准备");
  await page.waitForTimeout(1200);
  // 等 iframe 或产物卡出现
  await page.waitForSelector("iframe", { timeout: 120000 }).catch(() => {});
  await page.waitForTimeout(2500);
  await page.locator("iframe").first().scrollIntoViewIfNeeded().catch(() => {});
  await page.waitForTimeout(600);
  await page.screenshot({ path: path.join(OUT, "22-scenario-B-guide.png") });
  console.log("B ok");
  await browser.close();
}

/* ---------- C: 合同审查（含 HITL） ---------- */
{
  const { browser, page } = await session("legal", "123456");
  await trigger(page, "审查合同");
  await page.waitForTimeout(2500);
  // 审批弹窗
  const approveBtn = page.getByRole("button", { name: /批准|同意|允许/ }).first();
  const hasApproval = await approveBtn.count();
  console.log("approval dialog:", hasApproval > 0);
  if (hasApproval) {
    await page.screenshot({ path: path.join(OUT, "24-scenario-C-approval.png") });
    await approveBtn.click();
  }
  await page.waitForTimeout(3000);
  const dl = page.getByText(/下载修订版|修订版合同/).first();
  await dl.scrollIntoViewIfNeeded().catch(() => {});
  await page.waitForTimeout(800);
  await page.screenshot({ path: path.join(OUT, "23-scenario-C-contract.png") });
  console.log("C ok");
  await browser.close();
}

console.log("all scenarios captured ->", OUT);
