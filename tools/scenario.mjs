import { chromium } from "playwright-core";
const BASE = process.env.BASE || "http://127.0.0.1:8899";
const USER = process.env.DC_USER || "admin";
const PASS = process.env.DC_PASS || "admin123";
const Q = process.env.Q || "工时效率分析";
const browser = await chromium.launch({
  executablePath: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  headless: true, args: ["--no-sandbox"],
});
const ctx = await browser.newContext({ viewport: { width: 1512, height: 950 }, deviceScaleFactor: 1.5, locale: "zh-CN" });
const page = await ctx.newPage();
page.on("console", (m) => { if (m.type() === "error") console.log("[console.error]", m.text().slice(0, 300)); });
page.on("pageerror", (e) => console.log("[pageerror]", String(e).slice(0, 400)));
page.on("response", async (r) => {
  if (r.url().includes("/messages")) {
    console.log("[resp]", r.status(), r.url().replace(BASE, ""), "ct=", (r.headers()["content-type"] || "").slice(0, 40));
    try { const t = await r.text(); console.log("  stream head:", t.slice(0, 300).replace(/\n/g, "\\n")); } catch (e) { console.log("  (stream read failed)", String(e).slice(0,120)); }
  }
});
await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
await page.fill('input[placeholder="username"]', USER);
await page.fill('input[type="password"]', PASS);
await page.click('button[type="submit"]');
await page.waitForURL("**/chat**");
await page.waitForTimeout(1500);
// 点击示例问句
const card = page.getByText(Q, { exact: false }).first();
console.log("card count", await page.getByText(Q, { exact: false }).count());
await card.click();
console.log("clicked, waiting...");
for (let i = 0; i < 12; i++) {
  await page.waitForTimeout(5000);
  const canvases = await page.locator("canvas").count();
  const body = await page.locator("body").innerText();
  console.log(`t+${(i + 1) * 5}s canvas=${canvases} textLen=${body.length} tail=${body.slice(-160).replace(/\n/g, " | ")}`);
  if (canvases > 0) break;
}
await page.screenshot({ path: "debug-chat.png", fullPage: false });
await browser.close();
