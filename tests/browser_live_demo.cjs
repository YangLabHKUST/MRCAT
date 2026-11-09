/* Runs against browser_demo_fixture.py. All outputs there are synthetic. */
const {chromium} = require('playwright');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(process.env.MRCAT_TEST_URL || 'http://127.0.0.1:18796');
    await page.waitForFunction(() => liveDemoCatalog !== null);
    assert.equal(await page.locator('[data-demo-step]').count(), 4);
    assert.equal(await page.locator('#reply-form').isVisible(), false);
    assert.equal(await page.locator('[data-demo-step="online"]').isDisabled(), true);
    const clickStep = async id => {
      await page.waitForFunction(id => !document.querySelector(`[data-demo-step="${id}"]`).disabled, id);
      await page.locator(`[data-demo-step="${id}"]`).click();
      assert.equal(await page.locator('#live-demo-preview').getAttribute('open'), '');
      await page.locator('#live-demo-send').click();
    };
    await clickStep('literature');
    await page.waitForFunction(() => state.snapshot?.state.status === 'completed');
    const sid = await page.evaluate(() => state.currentSessionId);
    for (const id of ['online', 'local', 'followup']) {
      await clickStep(id);
      await page.waitForSelector('#live-demo-confirm:not([hidden])');
      assert.equal(await page.evaluate(() => state.currentSessionId), sid);
      if (id === 'local') {
        assert.equal(await page.evaluate(() => state.snapshot.state.study_setup.exposures[0].file_ref), 'workspace/inputs/bmi_mrapss.gz');
      }
      await page.locator('#live-demo-confirm').click();
      await page.waitForFunction(() => state.snapshot?.state.status === 'completed' && !state.busy);
      await page.reload();
      await page.waitForFunction(() => state.snapshot?.state.status === 'completed');
      assert.equal(await page.evaluate(() => state.currentSessionId), sid);
    }
    assert.equal(await page.locator('.codeact-cell').count() > 0, true);
    assert.match(await page.locator('#live-demo-progress').innerText(), /guided requests have finished/);
    await page.setViewportSize({width: 390, height: 844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    const other = await browser.newContext();
    const visitor = await other.newPage();
    await visitor.goto(process.env.MRCAT_TEST_URL || 'http://127.0.0.1:18796');
    await visitor.waitForFunction(() => liveDemoCatalog !== null);
    assert.equal(await visitor.evaluate(() => state.currentSessionId), null);
    assert.deepEqual(errors, []);
    console.log('PASS: literature, online/local plans, follow-up in the same session, reload, outputs, mobile and visitor isolation');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
