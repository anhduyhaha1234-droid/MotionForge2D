
const { chromium } = require("playwright");
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const bad = [];
  page.on("response", r => { if (r.status() >= 400) bad.push(r.status() + " " + r.url()); });
  await page.goto("http://localhost:3114/demo-compare", { waitUntil: "domcontentloaded", timeout: 30000 });
  await new Promise(res => setTimeout(res, 12000));
  console.log("BAD:", JSON.stringify(bad, null, 1));
  const state = await page.evaluate(() => ({
    apprLoading: !!document.querySelector('[data-testid="approval-loading"]'),
    apprError: document.querySelector('[data-testid="approval-error"]')?.textContent?.slice(0,150) ?? null,
    corrErr: document.querySelector('[data-testid="correction-error"]')?.textContent?.slice(0,150) ?? null,
    configSel: document.querySelector('[data-testid="approval-config-select"]')?.value ?? "none",
    segSel: (document.querySelector('[data-testid="correction-segment-select"]')?.textContent || "").slice(0,80),
  }));
  console.log("STATE:", JSON.stringify(state, null, 1));
  await browser.close();
})();
