// Run with Playwright installed: NODE_PATH=<node_modules> node tests/browser_plan.cjs
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(process.env.MRCAT_TEST_URL || 'http://127.0.0.1:7869/');
    await page.waitForSelector('details[data-current-plan="true"] .codeact-plan');
    await page.evaluate(() => state.eventSource?.close());
    // Preserve a screenshot of the actual saved session before injecting browser-only fixtures.
    await page.getByRole('button', {name: 'View current plan', exact: true}).click();
    const waitForPlan = async selector => page.waitForFunction(selector => {
      const node = document.querySelector(selector);
      if (!node || !node.open) return false;
      const card = node.getBoundingClientRect();
      const feed = document.getElementById('conversation-feed').getBoundingClientRect();
      return card.top >= feed.top - 1 && card.top < feed.bottom;
    }, selector, {timeout: 3000});
    await waitForPlan('details[data-current-plan="true"]');
    if (process.env.MRCAT_PLAN_SCREENSHOT) {
      await page.screenshot({path: process.env.MRCAT_PLAN_SCREENSHOT, fullPage: true});
    }
    await page.evaluate(() => {
      const snapshot = structuredClone(state.snapshot);
      const event = (id, type, content) => ({id, type, content, details: {}});
      snapshot.active_job = null;
      snapshot.state.status = 'completed';
      snapshot.mr.events = [event('u1', 'user_message', 'Hello'), event('p1', 'plan_updated', 'Greet the user.'),
        event('u2', 'user_message', 'Analyze BMI and T2D'), event('p2', 'plan_updated', 'Inspect BMI and T2D inputs, run analysis, and check the evidence.'),
        ...Array.from({length: 30}, (_, i) => event(`progress-${i}`, 'assistant_message', `Saved execution progress ${i}.`))];
      applySnapshot(snapshot);
      els.conversationFeed.scrollTop = els.conversationFeed.scrollHeight;
    });
    await page.getByRole('button', {name: 'View current plan', exact: true}).click();
    await waitForPlan('details[data-plan-id="p2"]');
    assert.match(await page.locator('details[data-current-plan="true"] .codeact-plan').innerText(), /BMI and T2D/);
    assert(await page.locator('details[data-plan-id="p2"]').evaluate(node => {
      const r = node.getBoundingClientRect();
      const feed = document.getElementById('conversation-feed').getBoundingClientRect();
      return node.open && r.top >= feed.top - 1 && r.top < feed.bottom;
    }), 'Plan navigation must reveal the latest plan in the conversation viewport');
    await page.locator('details[data-plan-id="p2"] > summary').click();
    await page.evaluate(() => applySnapshot(state.snapshot));
    assert.equal(await page.locator('details[data-plan-id="p2"]').evaluate(node => node.open), false,
      'Snapshot updates must preserve a manually collapsed plan');
    await page.getByRole('button', {name: 'View current plan', exact: true}).click();
    assert(await page.locator('details[data-plan-id="p2"]').evaluate(node => node.open));
    await page.evaluate(() => {
      const snapshot = structuredClone(state.snapshot);
      snapshot.active_job = {status: 'running'};
      snapshot.state.active_agent = 'mr';
      snapshot.mr.events.push({id: 'route3', type: 'manager_route', content: '', details: {route: 'mr', action: 'revise'}});
      snapshot.mr.events.push({id: 'u3', type: 'user_message', content: 'Add sensitivity analysis', details: {}});
      applySnapshot(snapshot);
    });
    assert.equal(await page.locator('#timeline button strong').innerText(), 'Planning…');
    assert.deepEqual(errors, []);
    console.log('PASS: current plan, greeting-to-analysis, navigation after long output, collapse persistence, pending plan, no JS errors');
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error); process.exit(1);});
