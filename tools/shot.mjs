import { chromium } from "playwright-core";
import fs from "node:fs";
import path from "node:path";

const BASE = process.env.BASE || "http://127.0.0.1:8787";
const USER = process.env.DC_USER || "admin";
const PASS = process.env.DC_PASS || "admin123";
const OUT = process.env.OUT || path.resolve("../docs/screenshots");
const ONLY = process.env.ONLY ? process.env.ONLY.split(",") : null;
const CHROME = process.env.CHROME || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";

fs.mkdirSync(OUT, { recursive: true });

const PAGES = [
  ["/chat", "01-chat"],
  ["/employees", "02-employees"],
  ["/skills", "03-skills"],
  ["/files", "04-files"],
  ["/tasks", "05-tasks"],
  ["/admin", "06-admin-overview"],
  ["/admin/users", "07-admin-users"],
  ["/admin/agents", "08-admin-public-agents"],
  ["/admin/data", "09-admin-data-security"],
  ["/admin/knowledge", "10-admin-knowledge"],
  ["/admin/channels", "11-admin-channels"],
  ["/admin/audit", "12-admin-audit"],
];

const browser = await chromium.launch({
  executablePath: CHROME,
  headless: true,
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--font-render-hinting=none"],
});
const ctx = await browser.newContext({ viewport: { width: 1512, height: 950 }, deviceScaleFactor: 1.5, locale: "zh-CN" });
const page = await ctx.newPage();
page.on("console", (m) => {
  if (m.type() === "error") console.log("[console.error]", m.text().slice(0, 300));
});
page.on("pageerror", (e) => console.log("[pageerror]", String(e).slice(0, 300)));

await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
await page.screenshot({ path: path.join(OUT, "00-login.png") });
console.log("login page ok");

await page.fill('input[placeholder="username"]', USER);
await page.fill('input[type="password"]', PASS);
await page.click('button[type="submit"]');
await page.waitForURL("**/chat**", { timeout: 20000 });
await page.waitForTimeout(1800);
console.log("logged in:", page.url());

for (const [route, name] of PAGES) {
  if (ONLY && !ONLY.includes(name)) continue;
  await page.goto(`${BASE}${route}`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1600);
  await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: false });
  console.log("shot", name);
}

// 场景截图：在会话页点一个示例问题，等产物出来
if (!ONLY || ONLY.includes("20-scenario-A")) {
  await page.goto(`${BASE}/chat`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1200);
  const candidates = [
    "帮我分析下上季度各区域工时效率情况",
    "帮我分析下上季度工时分布",
    "各区域工时",
  ];
  let clicked = false;
  for (const c of candidates) {
    const el = page.getByText(c, { exact: false }).first();
    if (await el.count()) {
      await el.click();
      clicked = true;
      break;
    }
  }
  if (!clicked) {
    const ta = page.locator("textarea").first();
    if (await ta.count()) {
      await ta.fill("帮我分析下上季度各区域工时效率情况");
      await ta.press("Enter");
      clicked = true;
    }
  }
  if (clicked) {
    console.log("scenario triggered, waiting artifacts...");
    try {
      await page.waitForSelector("canvas", { timeout: 120000 });
      await page.waitForTimeout(3500);
      await page.screenshot({ path: path.join(OUT, "20-scenario-A-dashboard.png") });
      await page.evaluate(() => window.scrollTo(0, 999999));
      const scroller = page.locator(".overflow-y-auto").first();
      await scroller.evaluate((el) => (el.scrollTop = el.scrollHeight)).catch(() => {});
      await page.waitForTimeout(1200);
      await page.screenshot({ path: path.join(OUT, "21-scenario-A-report.png") });
      console.log("scenario shots ok");
    } catch (e) {
      console.log("scenario wait failed:", String(e).slice(0, 200));
      await page.screenshot({ path: path.join(OUT, "20-scenario-A-error.png") });
    }
  }
}

await browser.close();
console.log("done ->", OUT);
