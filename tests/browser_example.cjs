// Uses browser_fixture.py. The test intercepts only the packaged recording;
// fixture data is never written into the distributed example.
const {chromium} = require('playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');

(async () => {
  const ids = JSON.parse(fs.readFileSync('/tmp/mrcat-browser-roles.json', 'utf8'));
  const base = process.env.MRCAT_TEST_URL || 'http://127.0.0.1:18795';
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
    const errors = [], writes = [], exampleApi = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => {
      if (request.method() !== 'GET') writes.push(request.url());
      if (request.url().includes('/api/sessions/example-result4')) exampleApi.push(request.url());
    });
    const response = await page.request.get(`${base}/api/sessions/${ids.notebook}`);
    const snapshot = JSON.parse(JSON.stringify(await response.json()).replaceAll(ids.notebook, 'example-result4'));
    const paths = snapshot.mr.manifest.artifacts['example-result4'].files.map(file => file.path);
    const recording = {title: "Result 4 · Recorded example", report_path: paths[0], snapshot, files: Object.fromEntries(paths.map(path => [path, {
      path: `files/${path}`, preview: `files/${path}.preview.json`,
    }])),
      stages: ['Literature', '1 · Online data', '2 · Local files', '3 · MR-APSS'].map((title, index) => ({
        title, description: 'Synthetic browser-test recording', start: index % 2, end: index % 2 + 1,
      }))};
    await page.route('**/static/examples/result4/recording.json', route => route.fulfill({json: recording}));
    await page.route('**/static/examples/result4/files/**', async route => {
      const path = decodeURI(new URL(route.request().url()).pathname.split('/files/')[1]);
      const preview = path.endsWith('.preview.json');
      const artifact = await page.request.get(`${base}/api/sessions/${ids.notebook}/artifacts/${preview ? 'spreadsheet' : 'raw'}?summary=${encodeURIComponent(preview ? path.slice(0, -13) : path)}`);
      await route.fulfill({response: artifact});
    });
    await page.goto(base);
    await page.waitForFunction(() => state.snapshot !== null);
    await page.locator('#result4-example-button').click();
    await page.waitForSelector('.viewing-example');
    assert.equal(await page.locator('#example-navigation button').count(), 4);
    assert.match(await page.locator('#session-title').innerText(), /Recorded example/);
    assert.equal(await page.locator('#fork-session-button').isDisabled(), true);
    assert.equal(await page.locator('#reply-form').isVisible(), false);
    assert.equal(await page.locator('#study-setup-panel').isVisible(), false);
    assert.equal(await page.locator('.codeact-cell').count(), 1);
    await page.waitForFunction(() => document.querySelector('#notebook-output table')?.textContent.includes('A'));
    await page.locator('#example-navigation button').last().click();
    assert.equal(await page.locator('#example-navigation button').last().getAttribute('aria-pressed'), 'true');
    assert.equal(await page.locator('.codeact-cell').count(), 1);
    assert.match(await page.locator('#notebook-output').innerText(), /report\.md/);
    await page.reload();
    await page.waitForSelector('.viewing-example');
    await page.waitForTimeout(1100);
    assert.equal(await page.locator('#status-chip').innerText(), 'Read only');
    await page.evaluate(async () => {
      let rejected = false;
      try { await requestJson('/api/sessions', {method: 'POST'}); } catch { rejected = true; }
      if (!rejected) throw new Error('Example permitted a write');
    });
    await page.setViewportSize({width: 390, height: 844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.locator('#new-chat-button').click();
    assert.equal(await page.locator('#reply-input').isDisabled(), false);
    assert.equal(await page.locator('#example-navigation').isVisible(), false);
    assert.equal(await page.evaluate(() => state.example), null);
    await page.evaluate(id => selectSession(id), ids.notebook);
    await page.waitForFunction(id => state.snapshot?.session_id === id, ids.notebook);
    assert.deepEqual(writes, []);
    assert.deepEqual(exampleApi, []);
    assert.deepEqual(errors, []);
    console.log('PASS: example stages, read-only behavior, reload, mobile layout and return to live sessions');
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exit(1);});
