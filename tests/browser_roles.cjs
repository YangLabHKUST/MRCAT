// Run against browser_fixture.py; all records use deterministic local models.
const {chromium} = require('playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');
(async () => {
  const ids = JSON.parse(fs.readFileSync('/tmp/mrcat-browser-roles.json', 'utf8'));
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    const base = process.env.MRCAT_TEST_URL || 'http://127.0.0.1:18769/';
    await page.goto(base + '#' + ids.completed);
    await page.waitForFunction(id => state.snapshot?.session_id === id, ids.completed);
    assert.match(await page.locator('#conversation-feed').innerText(), /Report Agent[\s\S]*Review passed/i);
    assert.equal(await page.evaluate(() => state.snapshot.mr.state.task_history[0].task_id), 'task1');
    assert.equal(await page.evaluate(() => state.snapshot.mr.state.active_task), null);
    assert.equal(await page.locator('#provider-select').inputValue(), 'openai');
    const report = await page.evaluate(() => state.snapshot.final_report);
    assert.match(report.summary, /^workspace\/reports\/.+\/final_summary.md$/);
    const response = await page.request.get(base + `api/sessions/${ids.completed}/artifacts/raw?summary=${encodeURIComponent(report.summary)}`);
    assert.equal(response.status(), 200);
    assert.match(await response.text(), /0\.2/);
    await page.screenshot({path: process.env.MRCAT_ROLES_SCREENSHOT || '/tmp/mrcat-roles-browser.png', fullPage: true});

    await page.evaluate(async id => selectSession(id), ids.blocked);
    await page.waitForFunction(id => state.snapshot?.session_id === id, ids.blocked);
    assert.equal(await page.evaluate(() => state.snapshot.state.status), 'waiting_user');
    assert.equal(await page.evaluate(() => state.snapshot.mr.state.task_history.length), 0);
    assert.match(await page.locator('#conversation-feed').innerText(), /analysis is unfinished/);
    assert.equal(await page.locator('.mr-summary-download').count(), 1);
    assert.doesNotMatch(await page.locator('#conversation-feed').innerText(), /END_FINAL_SUMMARY/);

    await page.evaluate(async id => selectSession(id), ids.search);
    await page.waitForSelector('.notebook-search-results .gwas-search-shortlist-table');
    assert.match(await page.locator('.notebook-search-results').innerText(), /fixture-cad/);
    assert.match(await page.locator('.notebook-search-results').innerText(), /Supplemental coronary atherosclerosis/);
    assert.match(await page.locator('.codeact-cell').innerText(), /Search Agent/);
    assert.equal(await page.locator('details[data-current-plan="true"]').count(), 0);
    await page.reload();
    await page.waitForSelector('.notebook-search-results .gwas-search-shortlist-table');
    assert.equal(await page.evaluate(() => state.snapshot.mr.state.active_task), null);

    await page.evaluate(async id => selectSession(id), ids.proposal);
    await page.waitForSelector('details[data-current-plan="true"]');
    assert.match(await page.locator('details[data-current-plan="true"] > summary').innerText(), /Proposed plan/);
    assert.match(await page.locator('.codeact-plan').innerText(), /gwas-qc[\s\S]*gwas-pair-prepare[\s\S]*mr-cml-ma/);
    assert.equal(await page.locator('.codeact-cell').count(), 0);
    assert.equal(await page.evaluate(() => state.snapshot.mr.state.pending.kind), 'plan_confirmation');
    await page.reload();
    await page.waitForSelector('details[data-current-plan="true"]');
    assert.equal(await page.evaluate(() => state.snapshot.mr.events.filter(e => e.type === 'plan_updated').length), 1);
    await page.setViewportSize({width: 820, height: 1000});
    if (process.env.MRCAT_NARROW_SCREENSHOT) {
      await page.screenshot({path: process.env.MRCAT_NARROW_SCREENSHOT, fullPage: true});
    }
    assert.deepEqual(errors, []);
    console.log('PASS: accepted report and download, blocked MR, Search results and reload, plan confirmation, session navigation, no JavaScript errors');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
