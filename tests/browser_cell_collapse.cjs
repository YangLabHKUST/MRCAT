const {chromium} = require('playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
  try {
    const ids = JSON.parse(fs.readFileSync('/tmp/mrcat-browser-roles.json', 'utf8'));
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(`${process.env.MRCAT_TEST_URL || 'http://127.0.0.1:18769'}#${ids.notebook}`);
    await page.waitForSelector('.codeact-cell');
    assert.equal(await page.locator('.codeact-cell:visible').count(), 2, 'Table and report stay visible');
    assert.equal(await page.evaluate(() => focusNotebookArtifact('workspace/report.md')), true);
    assert.equal(await page.locator('.codeact-cell.is-selected').isVisible(), true);
    await page.evaluate(() => {
      state.eventSource?.close();
      const snapshot = structuredClone(state.snapshot);
      snapshot.mr.manifest = {artifacts: {}};
      snapshot.mr.events = ['done', 'live', 'error'].map((id, i) => ({
        id, type: 'code_execution', content: `Run .coding_agent/step_00${i}.py`,
        details: {execution_id: id, agent: 'mr', language: 'python', code: 'print("test")',
          status: id === 'live' ? 'running' : 'exited', returncode: id === 'error' ? 1 : id === 'live' ? null : 0,
          stdout: 'Initial output', stderr: id === 'error' ? 'Test error' : '', generated_files: []},
      }));
      resetExecutionNotebook();
      applySnapshot(snapshot);
    });
    const group = page.locator('.codeact-execution-group');
    const toggle = group.locator(':scope > summary');
    assert.equal(await toggle.innerText(), 'Execution steps (3)');
    assert.equal(await page.locator('.codeact-cell:visible').count(), 0);
    const update = (id, changes) => page.evaluate(({id, changes}) => {
      const snapshot = structuredClone(state.snapshot);
      Object.assign(snapshot.mr.events.find(event => event.id === id).details, changes);
      applySnapshot(snapshot);
    }, {id, changes});
    await update('live', {stdout: 'New streamed output'});
    assert.equal(await group.evaluate(node => node.open), false, 'Streaming cannot expand the group');
    await page.evaluate(() => {
      const snapshot = structuredClone(state.snapshot);
      const event = structuredClone(snapshot.mr.events[0]);
      event.id = event.details.execution_id = 'next';
      snapshot.mr.events.push(event);
      applySnapshot(snapshot);
    });
    assert.equal(await toggle.innerText(), 'Execution steps (4)');
    assert.equal(await page.locator('.codeact-cell:visible').count(), 0);
    await toggle.click();
    assert.equal(await page.locator('.codeact-cell:visible').count(), 4);
    assert.match(await page.locator('#codeact-cell-live').innerText(), /New streamed output/);
    await update('live', {status: 'exited', returncode: 0});
    assert.equal(await group.evaluate(node => node.open), true, 'Updates preserve manual expansion');
    await toggle.click();
    await update('error', {stderr: 'Updated error'});
    assert.equal(await group.evaluate(node => node.open), false);
    await page.evaluate(() => focusCodeExecution('done'));
    assert.equal(await page.locator('#codeact-cell-done').isVisible(), true);
    await page.evaluate(() => setNotebookView('builder'));
    await page.evaluate(() => focusCodeExecution('live'));
    assert.equal(await page.locator('#codeact-cell-live').isVisible(), true);
    await toggle.click();
    await page.route('**/artifacts/raw?**summary=workspace%2Ffigure.png*', route => route.fulfill({
      contentType: 'image/png', body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1sAAAAASUVORK5CYII=', 'base64'),
    }));
    await page.evaluate(() => {
      const snapshot = structuredClone(state.snapshot);
      snapshot.mr.manifest = {artifacts: {test: {files: [
        {path: 'workspace/summary.csv', kind: 'table'}, {path: 'workspace/figure.png', kind: 'image'},
      ]}}};
      snapshot.mr.events.find(event => event.id === 'done').details.generated_files = ['workspace/summary.csv'];
      snapshot.mr.events.find(event => event.id === 'next').details.generated_files = ['workspace/figure.png'];
      applySnapshot(snapshot);
    });
    assert.equal(await group.evaluate(node => node.open), false);
    assert.equal(await toggle.innerText(), 'Execution steps (2)');
    assert.equal(await page.locator('#notebook-output > #codeact-cell-done .codeact-data').isVisible(), true);
    assert.equal(await page.locator('#notebook-output > #codeact-cell-next .codeact-figures').isVisible(), true);
    assert.equal(await page.locator('.codeact-cell:visible').count(), 2, 'New table and figure leave the folded process group');
    await page.locator('#notebook-latest').click();
    assert.equal(await page.locator('.codeact-cell.is-selected').getAttribute('data-execution-id'), 'next');
    await page.setViewportSize({width: 390, height: 844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.deepEqual(errors, []);
    console.log('PASS: grouped process cells, always-visible tables and figures, output arrival, streaming, manual state and navigation');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
