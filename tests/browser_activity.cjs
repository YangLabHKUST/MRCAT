// Read-only browser check: simulated snapshots never write to the server.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(process.env.MRCAT_TEST_URL || 'http://127.0.0.1:18769/');
    await page.waitForFunction(() => state.snapshot && state.eventSource);
    await page.screenshot({path: '/tmp/mrcat-live-activity.png'});
    await page.evaluate(() => {
      state.eventSource.close();
      state.eventSource = null;
      state.activityConnection = 'connected';
      const now = Date.now();
      const stamp = offset => new Date(now + offset).toISOString();
      window.activityFixture = {now, stamp};
      const snapshot = structuredClone(state.snapshot);
      snapshot.active_job = {created_at: stamp(-600000), status: 'running'};
      snapshot.state.status = 'mr_running';
      snapshot.state.updated_at = stamp(-240000);
      snapshot.mr.events = [
        {type: 'code_execution', timestamp: stamp(-900000), details: {status: 'exited', returncode: 1}},
        {type: 'code_execution', timestamp: stamp(-300000), details: {
          execution_id: 'activity-test', language: 'r', status: 'exited', returncode: 1, duration_seconds: 10}},
        {type: 'evaluation', timestamp: stamp(-240000), details: {route: 'execute'}}
      ];
      state.snapshot = snapshot;
      renderHeader(snapshot);
      renderTimeline(snapshot);
      renderConversation(snapshot);
    });
    assert.equal(await page.locator('#activity-title').innerText(), 'Preparing next attempt');
    assert.match(await page.locator('#activity-detail').innerText(), /1 failed execution in this run/);
    assert.match(await page.locator('#activity-freshness').innerText(), /No new activity recorded for 4m/);
    assert.equal(await page.locator('#session-activity.is-delayed').count(), 1);
    assert.doesNotMatch(await page.locator('#conversation-feed').innerText(), /Working…/);
    const clock = await page.locator('#activity-time').innerText();
    await page.waitForFunction(previous => document.getElementById('activity-time').textContent !== previous, clock);
    assert.notEqual(await page.locator('#activity-time').innerText(), clock);
    assert.equal(await page.locator('#activity-execution').isVisible(), true);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.evaluate(() => {
      const s = state.snapshot;
      s.mr.events.push({type: 'code_execution', timestamp: new Date().toISOString(), details: {
        execution_id: 'activity-retry', language: 'r', status: 'running'}});
      s.state.updated_at = new Date().toISOString();
      renderHeader(s); renderTimeline(s);
    });
    assert.equal(await page.locator('#activity-title').innerText(), 'Retrying R code');
    assert.match(await page.locator('#timeline .active').innerText(), /Retrying R code/);
    await page.evaluate(() => {
      state.activityConnection = 'reconnecting'; renderActivity(state.snapshot);
    });
    assert.equal(await page.locator('#activity-title').innerText(), 'Connection interrupted');
    assert.match(await page.locator('#activity-detail').innerText(), /cannot be confirmed/);
    await page.evaluate(() => {
      state.activityConnection = 'connected';
      state.snapshot.active_job = null;
      state.snapshot.state.status = 'completed';
      renderHeader(state.snapshot);
    });
    assert.equal(await page.locator('#session-activity').isVisible(), false);
    assert.equal(await page.locator('#status-chip').textContent(), 'completed');
    const checks = await page.evaluate(() => {
      const {now, stamp} = activityFixture;
      const snapshot = {active_job: {created_at: stamp(-1000)}, state: {}, mr: {events: [
        {type: 'executor_handoff', timestamp: stamp(-500), details: {outcome: 'blocked'}}
      ]}};
      const review = sessionActivity(snapshot, now);
      snapshot.mr.events = [];
      const fresh = sessionActivity(snapshot, now);
      return {review: review.title, fresh: fresh.title, failures: fresh.failures};
    });
    assert.deepEqual(checks, {review: 'Review requested', fresh: 'Preparing next step', failures: 0});
    await page.reload();
    await page.waitForFunction(() => state.snapshot && state.eventSource);
    assert.deepEqual(errors, []);
    console.log('PASS: live UI, elapsed clock, recovery, current-job isolation, execution, reconnect, completion, reload; no JS errors');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
