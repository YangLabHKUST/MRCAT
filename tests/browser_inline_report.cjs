// Run with browser_fixture.py; all added report content stays in the browser.
const {chromium} = require('playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');

(async () => {
  const ids = JSON.parse(fs.readFileSync('/tmp/mrcat-browser-roles.json', 'utf8'));
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
  try {
    const page = await browser.newPage({viewport: {width: 1600, height: 1050}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(`${process.env.MRCAT_TEST_URL || 'http://127.0.0.1:18769'}#${ids.completed}`);
    const frame = page.locator('.message-report-html .report-inline-frame');
    await frame.waitFor();
    const report = page.frameLocator('.report-inline-frame');
    await report.locator('.report-title').waitFor();
    assert.equal(await frame.count(), 1);
    assert.match(await page.locator('.message-report-html > .message-tag').innerText(), /Report Agent · Answer/);
    assert.match(await report.locator('body').innerText(), /0\.2/);
    await page.waitForFunction(() => [...document.querySelector('.report-inline-frame').contentDocument.images].every(image => image.complete && image.naturalWidth > 0));
    assert(await report.locator('img').count() > 0);
    const assertFullHeight = () => page.waitForFunction(() => {
      const frame = document.querySelector('.report-inline-frame');
      return frame.contentDocument.documentElement.scrollHeight <= frame.clientHeight + 2;
    });
    await assertFullHeight();
    await page.evaluate(() => {
      state.eventSource?.close();
      const snapshot = structuredClone(state.snapshot);
      snapshot.final_report.html += `<!-- ${'x'.repeat(300000)} --><p id="complete-report">End of complete report</p><script>parent.reportScriptRan = true</script>`;
      renderConversation(snapshot);
    });
    await report.locator('#complete-report').waitFor({state: 'attached'});
    assert.equal(await page.evaluate(() => window.reportScriptRan), undefined, 'Report scripts must not execute');
    await assertFullHeight();
    await page.setViewportSize({width: 1200, height: 900});
    await assertFullHeight();
    await page.locator('.message-report-html').evaluate(node => node.scrollIntoView({block: 'start'}));
    if (process.env.MRCAT_REPORT_SCREENSHOT) await page.screenshot({path: process.env.MRCAT_REPORT_SCREENSHOT});

    // An older answer must use its own artifact, not the latest report payload.
    const older = 'workspace/reports/older/scientific_report.html';
    await page.route('**/artifacts/raw?**', async route => {
      const path = new URL(route.request().url()).searchParams.get('summary');
      if (path === older) return route.fulfill({contentType: 'text/html', body: '<h1>Earlier report</h1><p>Earlier result</p>'});
      return route.continue();
    });
    await page.evaluate(path => {
      const snapshot = structuredClone(state.snapshot);
      snapshot.mr.manifest.artifacts[snapshot.mr.run_id].files.push({path, kind: 'html'});
      snapshot.mr.events.unshift({type: 'final', details: {agent: 'report'}, content: `Reviewed report\n\n[Open report](${path})`});
      renderConversation(snapshot);
    }, older);
    await page.frameLocator('.report-inline-frame').first().getByRole('heading', {name: 'Earlier report'}).waitFor();
    assert.equal(await frame.count(), 2);
    assert.match(await page.frameLocator('.report-inline-frame').last().locator('body').innerText(), /0\.2/);

    await page.route('**/artifacts/raw?**', route => route.fulfill({status: 404, body: 'Not found'}));
    await page.evaluate(path => {
      const snapshot = structuredClone(state.snapshot);
      snapshot.mr.manifest.artifacts[snapshot.mr.run_id].files.push({path, kind: 'html'});
      snapshot.mr.events = [{type: 'final', details: {agent: 'report'}, content: `[Open report](${path})`}];
      renderConversation(snapshot);
    }, older);
    await page.getByText('Report preview unavailable.', {exact: true}).waitFor();
    assert.equal(await page.getByRole('link', {name: 'Open full report ↗', exact: true}).count(), 1);
    await page.evaluate(() => {
      const snapshot = structuredClone(state.snapshot);
      snapshot.mr.events = [{type: 'final', details: {agent: 'report'}, content: 'Draft — review has not passed\n\n[Open report](workspace/reports/draft/scientific_report_draft.html)'}];
      renderConversation(snapshot);
    });
    assert.equal(await frame.count(), 0, 'Drafts must not become final report previews');
    assert.match(await page.locator('#conversation-feed').innerText(), /Draft — review has not passed/);
    assert.deepEqual(errors, []);
    console.log('PASS: full HTML in Report Agent answer, embedded images, large reports, automatic height, script isolation, per-answer report identity, fallback and draft distinction');
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error); process.exit(1);});
