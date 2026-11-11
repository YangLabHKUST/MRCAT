/* Run against browser_demo_fixture.py --public-example; no model calls. */
const {chromium} = require('playwright');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
  try {
    const base = process.env.MRCAT_TEST_URL || 'http://127.0.0.1:18797';
    const alice = await browser.newContext();
    const bob = await browser.newContext();
    const errors = [];
    let exampleId;
    for (const context of [alice, bob]) {
      const page = await context.newPage();
      page.on('pageerror', error => errors.push(error.message));
      await page.goto(base);
      await page.waitForFunction(() => state.snapshot && PUBLIC_DEMO_SESSIONS.has(state.currentSessionId));
      const sid = await page.evaluate(() => state.currentSessionId);
      if (exampleId) assert.equal(sid, exampleId);
      exampleId = sid;
      assert.match(await page.locator('.session-row').first().innerText(), /Public example/);
      assert.equal(await page.locator('#reply-input').isDisabled(), true);
      assert.equal(await page.locator('#reply-button').isDisabled(), true);
      assert.equal(await page.locator('#fork-session-button').isDisabled(), true);
      assert.equal(await page.locator('[data-demo-step="local"]').isDisabled(), true);
      assert.equal(await page.locator('#status-chip').innerText(), 'Read only');
      assert.equal(await page.locator('.codeact-cell').count(), 1);
      await page.waitForFunction(() => document.querySelector('#notebook-output')?.textContent.includes('synthetic.csv'));
      const artifact = await page.request.get(`${base}/api/sessions/${sid}/artifacts/raw?summary=workspace/synthetic.csv`);
      assert.equal(artifact.status(), 200);
      await page.reload();
      await page.waitForFunction(() => state.snapshot && isReadOnlySession());
      await page.locator('#new-chat-button').click();
      assert.equal(await page.locator('#reply-input').isDisabled(), false);
      assert.equal(await page.locator('[data-demo-step="local"]').isDisabled(), false);
    }
    const page = alice.pages()[0];
    await page.locator('#reply-input').fill('Explain the assumptions.');
    await page.locator('#reply-button').click();
    await page.waitForFunction(() => !state.busy && state.snapshot && !isReadOnlySession());
    const privateId = await page.evaluate(() => state.currentSessionId);
    assert.notEqual(privateId, exampleId);
    const listing = await (await bob.request.get(`${base}/api/sessions`)).json();
    assert.deepEqual(listing.sessions.map(row => row.session_id), [exampleId]);
    assert.equal((await bob.request.get(`${base}/api/sessions/${privateId}`)).status(), 404);
    await page.evaluate(sid => selectSession(sid), exampleId);
    await page.waitForFunction(() => state.snapshot && isReadOnlySession());
    assert.equal(await page.locator('#reply-input').isDisabled(), true);
    assert.deepEqual(errors, []);
    console.log('PASS: two new visitors share a live read-only example; New chat stays private and writable');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
