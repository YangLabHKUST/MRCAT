// Verify execution provenance with real previews and controlled retry/overwrite events.
const {chromium} = require('playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');
(async () => {
  const ids = JSON.parse(fs.readFileSync('/tmp/mrcat-browser-roles.json', 'utf8'));
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto((process.env.MRCAT_TEST_URL || 'http://127.0.0.1:18789/') + '#' + ids.notebook);
    await page.waitForSelector('.codeact-cell', {state: 'attached'});
    await page.evaluate(async id => selectSession(id), ids.notebook);
    await page.waitForFunction(id => state.snapshot?.session_id === id, ids.notebook);
    await page.waitForSelector('.codeact-cell .notebook-file', {state: 'attached'});
    const correspondence = () => page.locator('.codeact-cell').evaluateAll(cells => cells.map(cell => ({
      id: cell.dataset.executionId,
      files: [...cell.querySelectorAll('.notebook-file')].map(file => file.dataset.path),
    })));
    const original = await correspondence();
    assert.deepEqual(original.map(cell => cell.files), [['workspace/summary.csv'], ['workspace/report.md']]);
    assert((await page.locator('#notebook-output > .codeact-artifacts .notebook-file').evaluateAll(files => files.map(file => file.dataset.path))).every(path => path.endsWith('/final_summary.md')));
    const csv = page.locator('.codeact-cell .notebook-file[data-path="workspace/summary.csv"]');
    await csv.locator('..').locator(':scope > summary').click();
    await csv.locator('summary').click();
    await csv.locator('.spreadsheet-table').waitFor();
    assert.match(await csv.innerText(), /A\s+2/);
    const md = page.locator('.codeact-cell .notebook-file[data-path="workspace/report.md"]');
    await md.locator('..').locator(':scope > summary').click();
    if (!await md.evaluate(node => node.open)) await md.locator('summary').click();
    await md.locator('.notebook-explanation').waitFor();
    assert.match(await md.innerText(), /Synthetic data only/);
    await page.reload();
    await page.waitForSelector('.codeact-cell', {state: 'attached'});
    assert.deepEqual(await correspondence(), original);

    await page.locator('#notebook-builder-tab').click();
    const report = page.locator('.codeact-artifact-entry').filter({has: page.locator('[data-path="workspace/report.md"]')});
    await report.getByRole('button', {name: 'View Cell 2 in Execution notebook'}).click();
    assert.equal(await page.locator('.codeact-cell.is-selected').getAttribute('data-execution-id'), original[1].id);

    await page.route('**/artifacts/raw?**summary=workspace%2Ffigure.png*', route => route.fulfill({
      contentType: 'image/png', body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAGQAAABQCAIAAABga0e4AAAAv0lEQVR4nO3QQQkAIADAQDW50a3gXiLcJRibY+/BnfU64CdmBWYFZgVmBWYFZgVmBWYFZgVmBWYFZgVmBWYFZgVmBWYFZgVmBWYFZgVmBWYFZgVmBWYFZgVmBWYFZgVmBWYFZgVmBWYFZgVmBWYFZgVmBWYFZgVmBWYFZgVmBWYFZgVmBWYFZgVmBWYFZgVmBWYFZgVmBWYFZgVmBWYFZgVmBWYFZgVmBWYFZgVmBWYFZgVmBWYFZgVmBWYFZgUH18UBoLnIQwkAAAAASUVORK5CYII=', 'base64'),
    }));
    await page.evaluate(() => {
      state.eventSource?.close();
      const snapshot = structuredClone(state.snapshot);
      const cells = snapshot.mr.events.filter(e => e.type === 'code_execution');
      cells[0].details.generated_files.push('workspace/figure.png', 'workspace/deleted.txt', 'workspace/inputs/private.csv');
      const retry = structuredClone(cells[0]);
      retry.id = 'retry';
      Object.assign(retry.details, {execution_id: 'retry', status: 'exited', returncode: 1,
        generated_files: ['workspace/summary.csv', 'workspace/summary.csv'], stdout: '', stderr: 'Synthetic failure'});
      snapshot.mr.events.push(retry);
      const files = Object.values(snapshot.mr.manifest.artifacts)[0].files;
      files.splice(0, files.length, ...files.filter(file => !file.path.endsWith('/final_summary.md')));
      files.push({path: 'workspace/figure.png', kind: 'image'}, {path: 'workspace/unattributed.txt', kind: 'file'},
        {path: 'workspace/inputs/private.csv', kind: 'file'});
      applySnapshot(snapshot);
    });
    const mapped = await correspondence();
    assert.deepEqual(mapped.map(cell => cell.files), [['workspace/figure.png'], ['workspace/report.md'], ['workspace/summary.csv']]);
    const firstCell = page.locator('.codeact-cell').first();
    assert.equal(await firstCell.locator('.codeact-artifacts').evaluate(node => node.open), false);
    await firstCell.locator('.codeact-artifacts > summary').click();
    assert.match(await firstCell.innerText(), /summary.csv · Updated by Cell 3/);
    assert.match(await firstCell.innerText(), /deleted.txt · File no longer available/);
    assert.equal(await firstCell.locator('img').count(), 1);
    await firstCell.locator('img').scrollIntoViewIfNeeded();
    await page.waitForFunction(() => document.querySelector('.codeact-cell img')?.naturalWidth === 100);
    assert.equal(await page.locator('#notebook-output [data-path="workspace/inputs/private.csv"]').count(), 0);
    await page.locator('#notebook-output > .codeact-artifacts > summary').click();
    assert.match(await page.locator('#notebook-output > .codeact-artifacts').innerText(), /Other output files[\s\S]*Saved file · Cell link unavailable[\s\S]*unattributed.txt/);
    await firstCell.getByRole('button', {name: 'View Cell 3 in Execution notebook'}).click();
    assert.equal(await page.locator('.codeact-cell.is-selected').getAttribute('data-execution-id'), 'retry');
    assert.match(await page.locator('.codeact-cell').last().innerText(), /Failed/);
    await page.locator('#notebook-builder-tab').click();
    assert.equal(await page.locator('.notebook-file').count(), 4);
    const summary = page.locator('.codeact-artifact-entry').filter({has: page.locator('[data-path="workspace/summary.csv"]')});
    assert.match(await summary.innerText(), /Last generated or updated by Cell 3/);
    await summary.getByRole('button').click();
    assert.equal(await page.locator('.codeact-cell.is-selected').getAttribute('data-execution-id'), 'retry');

    // Internal files remain accessible without being mixed into result outputs.
    await page.route('**/artifacts/raw?**', route => {
      const path = new URL(route.request().url()).searchParams.get('summary');
      if (path?.includes('/.coding_agent/')) return route.fulfill({contentType: 'text/plain', body: 'print("Saved working script")'});
      return route.fallback();
    });
    const internal = 'workspace/outputs/task1/sensitivity/.coding_agent/step_029.py';
    const ownedInternal = 'workspace/outputs/task1/sensitivity/.coding_agent/helper.py';
    await page.evaluate(({internal, ownedInternal}) => {
      const snapshot = structuredClone(state.snapshot);
      const files = Object.values(snapshot.mr.manifest.artifacts)[0].files;
      files.push(...[internal, ownedInternal, 'workspace/analysis.py'].map(path => ({path, kind: 'file'})));
      snapshot.mr.events.find(e => e.type === 'code_execution').details.generated_files.push(ownedInternal, 'workspace/analysis.py');
      applySnapshot(snapshot);
    }, {internal, ownedInternal});
    const processFilesPanel = page.locator('#notebook-output > .codeact-process-files');
    assert.equal(await processFilesPanel.evaluate(node => node.open), false);
    assert.equal(await processFilesPanel.locator('.notebook-file').count(), 2);
    assert.equal(await page.locator('.codeact-cell .notebook-file[data-path*="/.coding_agent/"]').count(), 0);
    assert.equal(await page.locator('.codeact-cell .notebook-file[data-path="workspace/analysis.py"]').count(), 1);
    assert.doesNotMatch(await page.locator('#notebook-output').innerText(), /helper.py · File no longer available/);
    await processFilesPanel.locator(':scope > summary').click();
    const script = processFilesPanel.locator(`[data-path="${internal}"]`);
    await script.locator('summary').click();
    await page.waitForFunction(path => [...document.querySelectorAll('.notebook-file')].find(n => n.dataset.path === path)?.innerText.includes('Saved working script'), internal);
    assert.ok(await script.getByRole('link', {name: 'Download'}).getAttribute('href'));
    assert.doesNotMatch(await processFilesPanel.innerText(), /Cell link unavailable|No generating cell recorded/);
    await page.evaluate(() => {
      state.snapshot.mr.events.push({id: 'unrelated', type: 'assistant_message', content: 'Status update', details: {}});
      renderExecutionNotebook();
    });
    assert.equal(await script.evaluate(node => node.open), true);
    await page.locator('#notebook-builder-tab').click();
    assert.equal(await processFilesPanel.evaluate(node => node.open), true);
    assert.equal(await processFilesPanel.locator('.notebook-file').count(), 2);
    assert.match(await page.locator('#notebook-status').innerText(), /5 output files · 2 process files/);
    assert.equal(await page.locator('#notebook-output > .codeact-artifacts [data-path*="/.coding_agent/"]').count(), 0);
    await processFilesPanel.locator(':scope > summary').click();
    assert.equal(await page.evaluate(path => focusNotebookArtifact(path), ownedInternal), true);
    assert.equal(await processFilesPanel.evaluate(node => node.open), true);
    assert.equal(await processFilesPanel.locator(`[data-path="${ownedInternal}"]`).evaluate(node => node.open), true);

    await page.evaluate(async id => selectSession(id), ids.search);
    await page.waitForFunction(id => state.snapshot?.session_id === id, ids.search);
    await page.locator('.codeact-cell .notebook-search-results .gwas-search-shortlist-table').waitFor();
    assert.equal(await page.locator('#notebook-output > .notebook-search-results').count(), 0);
    await page.locator('#notebook-builder-tab').click();
    await page.locator('.notebook-search-results .gwas-search-shortlist-table').waitFor();
    assert.equal(await page.locator('.notebook-search-results').count(), 1);
    assert.deepEqual(errors, []);
    console.log('PASS: per-cell files, CSV/Markdown/image/search previews, reload, Files navigation, retries, overwrites, deleted/unattributed files and input exclusion');
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exit(1);});
