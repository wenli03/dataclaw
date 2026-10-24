import { chromium } from "playwright-core";
import fs from "node:fs";
import path from "node:path";

const BASE = process.env.BASE || "http://127.0.0.1:8787";
const OUT = path.resolve("../docs/screenshots-manual");
fs.mkdirSync(OUT, { recursive: true });
const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const CONTRACT = path.resolve("../docs/samples/技术服务合同（演示样例）.docx");

const browser = await chromium.launch({ executablePath: CHROME, headless: true, args: ["--no-sandbox"] });
const errors = [];

async function newPage() {
  const ctx = await browser.newContext({ viewport: { width: 1512, height: 950 }, deviceScaleFactor: 1.5, locale: "zh-CN" });
  const page = await ctx.newPage();
  page.on("console", m => { if (m.type() === "error") errors.push("console: " + m.text().slice(0, 200)); });
  page.on("pageerror", e => errors.push("pageerror: " + String(e).slice(0, 200)));
  return { ctx, page };
}

async function login(page, u, p) {
  await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
  await page.locator("input").nth(0).fill(u);
  await page.locator("input").nth(1).fill(p);
  await page.getByRole("button", { name: /进入工作台/ }).click();
  await page.waitForURL("**/chat**", { timeout: 20000 });
  await page.waitForTimeout(1500);
}

async function shot(page, name, opts = {}) {
  await page.waitForTimeout(opts.wait ?? 300);
  await page.screenshot({ path: path.join(OUT, name + ".png"), fullPage: !!opts.fullPage });
  console.log("shot", name);
}

async function shotEl(page, name, locator) {
  await locator.first().scrollIntoViewIfNeeded().catch(() => {});
  await page.waitForTimeout(700);
  await locator.first().screenshot({ path: path.join(OUT, name + ".png") });
  console.log("shot(el)", name);
}

async function ask(page, text) {
  const ta = page.locator("textarea").first();
  await ta.fill(text);
  await page.getByRole("button", { name: /^发送$/ }).click();
}

/* ================= 数据分析师：工时分析 ================= */
{
  const { ctx, page } = await newPage();
  await login(page, "analyst", "123456");
  await page.goto(`${BASE}/chat/emp_analyst_1`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1200);
  await shot(page, "21-analyst-chat-empty");

  await ask(page, "帮我分析下上季度各区域工时效率情况");
  await page.waitForSelector('[data-artifact-kind="dashboard"]', { timeout: 60000 });
  await page.waitForSelector('[data-artifact-kind="report"]', { timeout: 60000 });
  await page.waitForTimeout(2500);

  // 滚动到回答开始
  await page.locator('[data-artifact-kind="dashboard"]').first().scrollIntoViewIfNeeded().catch(() => {});
  await page.waitForTimeout(800);
  await shot(page, "22-analyst-answer");

  await shotEl(page, "23-analyst-dashboard", page.locator('[data-artifact-kind="dashboard"]'));
  await shotEl(page, "24-analyst-report", page.locator('[data-artifact-kind="report"]'));

  // 展开「自然语言问数」步骤，展示 SQL 改写与脱敏
  const stepBtn = page.getByRole("button", { name: /执行自然语言问数/ }).first();
  if (await stepBtn.count()) {
    await stepBtn.scrollIntoViewIfNeeded().catch(() => {});
    await stepBtn.click();
    await page.waitForTimeout(700);
    await shotEl(page, "25-analyst-step-sql", page.locator('[data-artifact-kind="dashboard"]').first().locator("xpath=ancestor::div[contains(@class,'min-w-0')][1]"));
    await shot(page, "25b-analyst-step-sql-view");
  }

  // 员工详情：记忆（自动沉淀）
  await page.goto(`${BASE}/employees`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1200);
  const editBtn = page.getByRole("button", { name: "编辑", exact: true }).first();
  if (await editBtn.count()) {
    await editBtn.click();
    await page.waitForTimeout(1000);
    const memoryTitle = page.getByText(/^记忆（/).first();
    if (await memoryTitle.count()) {
      await memoryTitle.scrollIntoViewIfNeeded().catch(() => {});
      await page.waitForTimeout(500);
    }
    await shot(page, "26-analyst-memory");
  }
  await ctx.close();
}

/* ================= 销售：拜访指南 ================= */
{
  const { ctx, page } = await newPage();
  await login(page, "sales", "123456");
  await page.goto(`${BASE}/chat/emp_sales_1`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1200);
  await shot(page, "31-sales-chat-empty");

  await ask(page, "我要拜访上海鼎信智能科技有限公司，帮我准备一份拜访指南");
  await page.waitForSelector('[data-artifact-kind="html"]', { timeout: 60000 });
  await page.waitForTimeout(1800);
  await page.locator('[data-artifact-kind="html"]').first().scrollIntoViewIfNeeded().catch(() => {});
  await page.waitForTimeout(700);
  await shot(page, "32-sales-answer");
  await shotEl(page, "33-sales-guide", page.locator('[data-artifact-kind="html"]'));

  const stepBtn = page.getByRole("button", { name: /客户 360/ }).first();
  if (await stepBtn.count()) {
    await stepBtn.scrollIntoViewIfNeeded().catch(() => {});
    await stepBtn.click();
    await page.waitForTimeout(700);
    await shot(page, "34-sales-row-filter");
  }
  await ctx.close();
}

/* ================= 法务：合同审查 + HITL ================= */
{
  const { ctx, page } = await newPage();
  await login(page, "legal", "123456");
  await page.goto(`${BASE}/chat/emp_legal_1`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1200);
  await shot(page, "41-legal-chat-empty");

  // 上传合同
  await page.locator('input[type="file"]').setInputFiles(CONTRACT);
  await page.waitForTimeout(1200);
  await shot(page, "42-legal-attachment");

  await ask(page, "请按照公司标准合同规则审查这份合同");
  await page.waitForSelector("text=需要你的确认", { timeout: 60000 });
  await page.waitForTimeout(800);
  await shot(page, "43-legal-approval");

  await page.getByRole("button", { name: /批准并继续/ }).click();
  await page.waitForSelector('[data-artifact-kind="docx"]', { timeout: 60000 });
  await page.waitForTimeout(2000);
  await page.locator('[data-artifact-kind="docx"]').first().scrollIntoViewIfNeeded().catch(() => {});
  await page.waitForTimeout(800);
  await shot(page, "44-legal-answer");
  await shotEl(page, "45-legal-redlines", page.locator('[data-artifact-kind="docx"]'));

  // 展开合同解析/风险分析步骤
  const stepBtn = page.getByRole("button", { name: /风险分级|逐条比对/ }).first();
  if (await stepBtn.count()) {
    await stepBtn.scrollIntoViewIfNeeded().catch(() => {});
    await stepBtn.click();
    await page.waitForTimeout(700);
    await shot(page, "46-legal-risk-steps");
  }
  await ctx.close();
}

console.log("console errors:", errors.length ? errors : "none");
await browser.close();
console.log("done ->", OUT);
