// Records the CapyTeam app scene by scene (timed to the narration) with Playwright.
// usage: node demo/record.js demo/build/scenes.json demo/build
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

(async () => {
  const scenes = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const outDir = process.argv[3];
  const base = process.env.CAPY_URL || 'http://127.0.0.1:8787';
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, recordVideo: { dir: outDir, size: { width: 1920, height: 1080 } } });
  const t0 = Date.now();
  const page = await context.newPage();
  page.on('pageerror', e => console.log('pageerror:', e.message));
  await page.goto(`${base}/?video=1&still=1`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1200);
  fs.writeFileSync(path.join(outDir, 'lead.txt'), String((Date.now() - t0) / 1000));

  const sessions = await (await fetch(`${base}/api/sessions?limit=400`)).json();
  const firstOf = prefix => (sessions.find(s => s.session_id.startsWith(prefix)) || sessions.find(s => s.session_id.includes(prefix)) || {}).session_id;
  let lastReplay = null;

  for (const sc of scenes) {
    const ms = Math.round(sc.seconds * 1000);
    const [kind, arg] = sc.action.split(':');
    const start = Date.now();
    if (kind === 'town') {
      await page.evaluate(() => window.capTab('town'));
      if (arg && arg !== lastReplay) {
        const has = sessions.some(s => s.session_id.startsWith(arg));
        const prefix = has ? arg : 'day3';
        await page.evaluate(() => window.capReset && window.capReset());
        // pick a speed so the replay roughly fills the remaining scenes that use it
        const span = scenes.filter(s => s.action === sc.action).reduce((a, s) => a + s.seconds, 0);
        await page.evaluate(([p, sp]) => { window.capReplay(p, sp); }, [prefix, Math.max(1.2, 60 / Math.max(10, span))]);
        lastReplay = arg;
      }
    } else if (kind === 'shifts') {
      await page.evaluate(() => window.capTab('shifts'));
      await page.waitForTimeout(900);
      const id = firstOf(arg);
      if (id) await page.evaluate(i => window.capTranscript(i), id);
    } else if (kind === 'school' || kind === 'score' || kind === 'race') {
      await page.evaluate(k => window.capTab(k), kind);
      await page.waitForTimeout(900);
      if (arg) await page.evaluate(id => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'center' }), arg);
      else await page.evaluate(() => window.scrollTo({ top: 0 }));
    }
    await page.evaluate(([t, d]) => window.capCaption(t, d), [sc.caption, Math.max(2500, ms - 600)]);
    // gentle scroll on long pages halfway through the scene
    if ((kind === 'school' || kind === 'score') && !arg) {
      await page.waitForTimeout(Math.round(ms * 0.55));
      await page.evaluate(() => window.scrollBy({ top: 380, behavior: 'smooth' }));
    }
    const left = ms - (Date.now() - start);
    if (left > 0) await page.waitForTimeout(left);
  }
  await page.waitForTimeout(400);
  await context.close();
  await browser.close();
  console.log('recorded', scenes.length, 'scenes in', ((Date.now() - t0) / 1000).toFixed(1), 's');
})();
