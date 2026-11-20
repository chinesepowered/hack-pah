// Records the CapyTeam app for the demo video with Playwright.
// The plan (demo/build/plan.json, written by make_video.py) is a list of scenes; each scene is a list of
// timed steps, and each step calls one of the app's presentation functions (web/present.js) with real data.
// usage: node demo/record.js demo/build/plan.json demo/build
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

(async () => {
  const plan = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const outDir = process.argv[3];
  const base = process.env.CAPY_URL || 'http://127.0.0.1:8787';
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, recordVideo: { dir: outDir, size: { width: 1920, height: 1080 } } });
  const t0 = Date.now();
  const page = await context.newPage();
  page.on('pageerror', e => console.log('pageerror:', e.message));
  await page.goto(`${base}/?video=1&still=1`, { waitUntil: 'networkidle' });
  const call = (fn, args) => page.evaluate(([f, a]) => {
    if (typeof window[f] !== 'function') throw new Error(`no such presentation function: ${f}`);
    window[f](...a);
  }, [fn, args || []]);

  // warm the data the proof shots need, so nothing is still loading on camera
  await page.evaluate(async () => { await Promise.all(['/api/analytics', '/api/firedrill', '/api/lessons', '/api/casebook'].map(u => fetch(u).then(r => r.json()).catch(() => null))); });
  for (const tab of ['score', 'school', 'race']) { await call('capTab', [tab]); await page.waitForTimeout(700); }
  await page.waitForFunction(() => document.querySelector('#exp')?.children.length > 0, null, { timeout: 30000 }).catch(() => console.log('warning: analytics card empty'));
  for (const s of plan.pre || []) await call(s.fn, s.args);
  await page.waitForTimeout(900);

  // sync marker: a small magenta square flashed shortly before the zero point. make_video.py finds it in the
  // recording, so the trim is exact (the recorder's own clock runs a few hundred ms ahead of the first frame).
  await page.evaluate(() => {
    const m = document.createElement('div');
    m.id = 'syncmark';
    m.style.cssText = 'position:fixed;left:0;top:0;width:20px;height:20px;background:#ff00ff;z-index:99999';
    document.body.appendChild(m);
  });
  const marked = Date.now();
  await page.waitForTimeout(240);
  await page.evaluate(() => { const m = document.getElementById('syncmark'); m.parentNode.removeChild(m); });
  await page.waitForTimeout(560);

  // the video's zero point: everything before it is trimmed off
  const start = Date.now();
  fs.writeFileSync(path.join(outDir, 'lead.txt'), String((start - t0) / 1000));
  fs.writeFileSync(path.join(outDir, 'sync.json'), JSON.stringify({ markToStart: (start - marked) / 1000 }));
  let sceneStart = start;
  for (const sc of plan.scenes) {
    const steps = [...sc.steps].sort((a, b) => a.t - b.t);
    for (const s of steps) {
      const wait = sceneStart + s.t * 1000 - Date.now();
      if (wait > 0) await page.waitForTimeout(wait);
      await call(s.fn, s.args).catch(e => console.log(`step failed in ${sc.id}: ${s.fn}: ${e.message.split('\n')[0]}`));
    }
    sceneStart += sc.seconds * 1000;
    const left = sceneStart - Date.now();
    if (left > 0) await page.waitForTimeout(left);
    else if (left < -150) console.log(`warning: scene ${sc.id} overran by ${-left} ms`);
  }
  await page.waitForTimeout(500);
  await context.close();
  await browser.close();
  console.log('recorded', plan.scenes.length, 'scenes in', ((Date.now() - start) / 1000).toFixed(1), 's');
})();
