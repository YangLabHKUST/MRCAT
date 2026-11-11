/* Runs against browser_demo_fixture.py. All outputs there are synthetic. */
const {chromium} = require('playwright');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('dialog', async dialog => { errors.push(dialog.message()); await dialog.dismiss(); });
    page.setDefaultTimeout(15000);
    const url = process.env.MRCAT_TEST_URL || 'http://127.0.0.1:18796';
    await page.goto(url);
    await page.waitForFunction(() => liveDemoCatalog !== null);
    assert.equal(await page.locator('#reply-form').isVisible(), true);
    assert.equal(await page.locator('[data-demo-step]').count(), 4);
    assert.equal(await page.locator('[data-demo-step="local"]').isDisabled(), false);
    const choose = async id => {
      await page.locator('#live-demo-suggestions').evaluate(el => { el.open = true; });
      await page.locator(`[data-demo-step="${id}"]`).click();
      assert.equal(await page.locator('#reply-input').inputValue(),
        await page.evaluate(id => liveDemoCatalog.steps.find(s => s.id === id).prompt, id));
    };
    const send = async (message, status = 'completed') => {
      await page.locator('#reply-input').fill(message);
      await page.locator('#reply-button').click();
      await page.waitForFunction(({message, status}) => !state.busy
        && state.snapshot?.state.status === status
        && state.snapshot.mr.events.some(e => e.type === 'user_message' && e.content === message), {message, status});
    };
    await choose('literature');
    assert.equal(await page.evaluate(() => state.currentSessionId), null);
    await send('Find recent MR studies on BMI and diabetes.');
    console.log('PASS: suggestion edited and sent through the chat input');
    const sid = await page.evaluate(() => state.currentSessionId);
    await choose('local');
    assert.equal(await page.locator('#live-demo-attachment').isVisible(), true);
    assert.deepEqual(await page.evaluate(() => state.snapshot.state.study_setup), {});
    console.log('PASS: dataset selection cancelled without changing the session');
    await page.locator('#live-demo-attachment button').click();
    await send('What do these findings mean?');
    assert.deepEqual(await page.evaluate(() => state.snapshot.state.study_setup), {});
    for (const [id, message] of [
      ['online', 'Run MR using online GWAS data and explain the estimates.'],
      ['local', 'Analyze these local files with IVW first.'],
      ['followup', 'Compare the local results using MR-APSS.'],
    ]) {
      if (id === 'online') await choose('local');
      await choose(id);
      if (id === 'online') {
        assert.equal(await page.locator('#live-demo-attachment').isVisible(), false);
        assert.equal(await page.evaluate(() => liveDemoSelection), null);
      }
      const submission = page.waitForRequest(request => request.method() === 'POST');
      await send(message, 'waiting_user');
      const posted = await submission;
      assert.equal(await page.evaluate(() => state.currentSessionId), sid);
      if (id === 'local' || id === 'followup') {
        assert.equal(await page.evaluate(() => state.snapshot.state.study_setup.exposures[0].file_ref), 'workspace/inputs/bmi_mrapss.gz');
      }
      if (id === 'online') {
        assert.deepEqual(await page.evaluate(() => state.snapshot.state.study_setup), {});
        assert.equal(new URL(posted.url()).pathname, `/api/sessions/${sid}/mr/reply`);
        assert.equal(posted.postDataJSON().reply, message);
      }
      await send('Yes, go ahead.');
      await page.reload();
      await page.waitForFunction(() => state.snapshot?.state.status === 'completed');
      assert.equal(await page.evaluate(() => state.currentSessionId), sid);
    }
    console.log('PASS: edited online/local requests and MR-APSS follow-up');
    assert.equal(await page.locator('.codeact-cell').count() > 0, true);
    await page.setViewportSize({width: 390, height: 844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.equal(await page.locator('#reply-input').isVisible(), true);
    await page.setViewportSize({width: 1440, height: 1000});
    await choose('local');
    await page.locator('#new-chat-button').click();
    assert.equal(await page.evaluate(() => state.currentSessionId), null);
    assert.equal(await page.locator('#live-demo-attachment').isVisible(), false);
    await send('Explain MR assumptions in a new conversation.');
    const secondSid = await page.evaluate(() => state.currentSessionId);
    assert.notEqual(secondSid, sid);
    assert.equal(await page.evaluate(() => state.sessions.length), 2);
    await page.evaluate(sid => selectSession(sid), sid);
    await page.waitForFunction(sid => state.snapshot?.state.session_id === sid, sid);
    assert.equal(await page.locator('.codeact-cell').count() > 0, true);
    console.log('PASS: New chat creates a separate session and preserves the previous session');
    const other = await browser.newContext();
    const visitor = await other.newPage();
    await visitor.goto(url);
    await visitor.waitForFunction(() => liveDemoCatalog !== null);
    assert.equal(await visitor.evaluate(() => state.currentSessionId), null);
    // A visitor may start directly with an edited local-data question.
    await visitor.locator('[data-demo-step="local"]').click();
    await visitor.locator('#reply-input').fill('Run IVW on these files.');
    await visitor.locator('#reply-button').click();
    await visitor.waitForFunction(() => state.snapshot?.state.status === 'waiting_user');
    assert.notEqual(await visitor.evaluate(() => state.currentSessionId), sid);
    assert.equal(await visitor.evaluate(() => state.snapshot.state.study_setup.analysis_request), 'Run IVW on these files.');
    if (process.env.MRCAT_TEST_SCREENSHOT) await page.screenshot({path: process.env.MRCAT_TEST_SCREENSHOT});
    assert.deepEqual(errors, []);
    console.log('PASS: editable suggestions, free text, removable dataset selection, plan replies, local-first start, reload, mobile and visitor isolation');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
