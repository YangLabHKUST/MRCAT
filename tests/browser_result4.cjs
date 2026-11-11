// Run against the exported site served by a plain static HTTP server.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');

(async () => {
  const base = process.env.MRCAT_TEST_URL || 'http://127.0.0.1:7891';
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
  try {
    const page = await browser.newPage({viewport: {width: 1600, height: 1000}});
    const errors = [], failures = [], apiCalls = [], writes = [], analytics = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('response', r => { if (r.status() >= 400) failures.push(`${r.status()} ${r.url()}`); });
    page.on('request', r => {
      if (new URL(r.url()).pathname.startsWith('/api/')) apiCalls.push(r.url());
      if (!['GET', 'HEAD'].includes(r.method())) {
        // Cloudflare injects its own page-performance beacon on the public host.
        const url = new URL(r.url());
        if (url.origin === new URL(base).origin && url.pathname === '/cdn-cgi/rum') analytics.push(r.url());
        else writes.push(r.url());
      }
    });
    await page.goto(base);
    await page.waitForSelector('.viewing-example');
    await page.waitForFunction(() => state.example?.snapshot?.state?.status === 'completed');
    assert.equal(await page.locator('#status-chip').innerText(), 'Read only');
    assert.equal(await page.locator('#example-navigation button').count(), 4);
    assert.equal(await page.locator('#provider-select').isVisible(), false);
    assert.equal(await page.locator('#reply-form').isVisible(), false);
    assert.equal(await page.locator('#new-chat-button').isVisible(), false);
    const expected = await page.evaluate(() => state.example.snapshot.mr.events.filter(e => e.type === 'code_execution').length);
    assert.equal(await page.locator('.codeact-cell').count(), expected);
    assert.equal(await page.locator('.notebook-file-name:visible').count(), 0, 'Default notebook hides original filenames');
    assert.equal(await page.locator('.codeact-result > .notebook-file').count(), 0, 'No duplicate raw result files');
    const executionSteps = page.locator('.codeact-execution-group');
    assert.equal(await executionSteps.evaluate(node => node.open), false);
    await executionSteps.locator(':scope > summary').click();
    const executionDetails = page.locator('.codeact-execution-details').first();
    if (!await executionDetails.evaluate(node => node.open)) await executionDetails.locator(':scope > summary').click();
    assert.equal(await executionDetails.locator('.codeact-code').isVisible(), true);
    assert.ok((await executionDetails.locator('.codeact-code').innerText()).length > 0);
    const counts = [];
    for (let i = 1; i <= 3; i++) {
      await page.locator('#example-navigation button').nth(i).click();
      assert.equal(await page.locator('#example-navigation button').nth(i).getAttribute('aria-pressed'), 'true');
      counts.push(await page.locator('.codeact-cell').count());
    }
    assert.ok(counts[0] > 0 && counts[1] > 0);
    const [report] = await Promise.all([
      page.waitForEvent('popup'),
      page.locator('#example-navigation a').click(),
    ]);
    await report.waitForLoadState('load');
    assert.match(await report.locator('body').innerText(), /FinnGen/);
    assert.ok(await report.locator('img').count() > 0);
    assert.equal(await report.evaluate(() => [...document.images].every(i => i.complete && i.naturalWidth > 0)), true);
    await report.close();
    await page.locator('#example-navigation button').first().click();
    await page.reload();
    await page.waitForSelector('.viewing-example');
    await page.waitForTimeout(1200);
    assert.equal(await page.locator('.codeact-cell').count(), expected);
    assert.equal(await page.locator('#status-chip').innerText(), 'Read only');
    await page.evaluate(async () => {
      let rejected = false;
      try { await requestJson('/api/sessions', {method: 'POST'}); } catch { rejected = true; }
      if (!rejected) throw new Error('Recording allowed a write');
    });
    const assets = await page.evaluate(() => Object.values(state.example.files).flatMap(f => [f.path, f.preview].filter(Boolean)));
    // Every published download/preview resolves, independently of lazy UI rendering.
    for (let i = 0; i < assets.length; i += 12) {
      await Promise.all(assets.slice(i, i + 12).map(async path => {
        const r = await page.request.head(`${base}/static/examples/result4/${path}`);
        assert.equal(r.status(), 200, path);
      }));
    }
    const table = await page.evaluate(() => Object.keys(state.example.files).find(p => p.endsWith('.xlsx')));
    assert.ok(table);
    const preview = await page.evaluate(async path => await loadTableArtifact(state.snapshot, path), table);
    assert.ok(preview.sheets.length > 0);
    if (process.env.MRCAT_SCREENSHOT) await page.screenshot({path: process.env.MRCAT_SCREENSHOT});
    await page.setViewportSize({width: 390, height: 844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.deepEqual(errors, []);
    assert.deepEqual(failures, []);
    assert.deepEqual(apiCalls, []);
    assert.deepEqual(writes, []);
    console.log(JSON.stringify({status: 'passed', executions: expected, stages: counts,
      assets: assets.length, apiCalls: apiCalls.length, writes: writes.length,
      cloudflareAnalytics: analytics.length, errors}));
  } finally {
    await browser.close();
  }
})().catch(e => {console.error(e); process.exit(1);});
