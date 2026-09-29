
const { chromium } = require("playwright");
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto("http://localhost:3114/demo-compare", { waitUntil: "domcontentloaded", timeout: 30000 });
  await new Promise(res => setTimeout(res, 9000));
  const state = await page.evaluate(async () => {
    const r = await fetch("http://localhost:8199/api/v2/s09-approvals?workspace_id=default");
    const j = await r.json();
    const items = j.items.map(c => ({ id: c.id, hash: c.checkpoint_hash.slice(0,12) }));
    // verify each through the REAL verify endpoint after restart
    const verdicts = [];
    for (const it of items) {
      const v = await fetch(`http://localhost:8199/api/v2/s09-approvals/${it.id}/verify?workspace_id=default`, { method: "POST" }).then(r => r.json());
      verdicts.push(v.verified);
    }
    return { items, verdicts };
  });
  console.log("AFTER_RESTART:", JSON.stringify(state));
  await browser.close();
})();
