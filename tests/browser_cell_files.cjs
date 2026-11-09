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
    await page.waitForSelector('.codeact-cell');
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
    await page.locator('.codeact-cell .codeact-artifacts > summary').click();
    await csv.locator('summary').click();
    await csv.locator('.spreadsheet-table').waitFor();
    assert.match(await csv.innerText(), /A\s+2/);
    const md = page.locator('.codeact-cell .notebook-file[data-path="workspace/report.md"]');
    if (!await md.evaluate(node => node.open)) await md.locator('summary').click();
    await md.locator('.notebook-explanation').waitFor();
    assert.match(await md.innerText(), /Synthetic data only/);
    await page.reload();
    await page.waitForSelector('.codeact-cell');
    assert.deepEqual(await correspondence(), original);

    await page.locator('#notebook-builder-tab').click();
    const report = page.locator('.codeact-artifact-entry').filter({has: page.locator('[data-path="workspace/report.md"]')});
    await report.getByRole('button', {name: 'View Cell 2 in Execution Notebook'}).click();
    assert.equal(await page.locator('.codeact-cell.is-selected').getAttribute('data-execution-id'), original[1].id);

    await page.route('**/artifacts/raw?**summary=workspace%2Ffigure.svg*', route => route.fulfill({
      contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="80"><rect width="100" height="80" fill="teal"/></svg>',
    }));
    await page.evaluate(() => {
      state.eventSource?.close();
      const snapshot = structuredClone(state.snapshot);
      const cells = snapshot.mr.events.filter(e => e.type === 'code_execution');
      cells[0].details.generated_files.push('workspace/figure.svg', 'workspace/deleted.txt', 'workspace/inputs/private.csv');
      const retry = structuredClone(cells[0]);
      retry.id = 'retry';
      Object.assign(retry.details, {execution_id: 'retry', status: 'exited', returncode: 1,
        generated_files: ['workspace/summary.csv', 'workspace/summary.csv'], stdout: '', stderr: 'Synthetic failure'});
      snapshot.mr.events.push(retry);
      const files = Object.values(snapshot.mr.manifest.artifacts)[0].files;
      files.splice(0, files.length, ...files.filter(file => !file.path.endsWith('/final_summary.md')));
      files.push({path: 'workspace/figure.svg', kind: 'image'}, {path: 'workspace/unattributed.txt', kind: 'file'},
        {path: 'workspace/inputs/private.csv', kind: 'file'});
      applySnapshot(snapshot);
    });
    const mapped = await correspondence();
    assert.deepEqual(mapped.map(cell => cell.files), [['workspace/figure.svg'], ['workspace/report.md'], ['workspace/summary.csv']]);
    const firstCell = page.locator('.codeact-cell').first();
    assert.match(await firstCell.innerText(), /summary.csv · Updated by Cell 3/);
    assert.match(await firstCell.innerText(), /deleted.txt · File no longer available/);
    assert.equal(await firstCell.locator('img').count(), 1);
    await firstCell.locator('img').scrollIntoViewIfNeeded();
    await page.waitForFunction(() => document.querySelector('.codeact-cell img')?.naturalWidth === 100);
    assert.equal(await page.locator('#notebook-output [data-path="workspace/inputs/private.csv"]').count(), 0);
    assert.match(await page.locator('#notebook-output > .codeact-artifacts').innerText(), /Other files[\s\S]*No generating cell recorded[\s\S]*unattributed.txt/);
    await firstCell.getByRole('button', {name: 'View Cell 3 in Execution Notebook'}).click();
    assert.equal(await page.locator('.codeact-cell.is-selected').getAttribute('data-execution-id'), 'retry');
    assert.match(await page.locator('.codeact-cell').last().innerText(), /Failed/);
    await page.locator('#notebook-builder-tab').click();
    assert.equal(await page.locator('.notebook-file').count(), 4);
    const summary = page.locator('.codeact-artifact-entry').filter({has: page.locator('[data-path="workspace/summary.csv"]')});
    assert.match(await summary.innerText(), /Last generated or updated by Cell 3/);
    await summary.getByRole('button').click();
    assert.equal(await page.locator('.codeact-cell.is-selected').getAttribute('data-execution-id'), 'retry');

    await page.evaluate(async id => selectSession(id), ids.search);
    await page.locator('.codeact-cell .notebook-search-results .gwas-search-shortlist-table').waitFor();
    assert.equal(await page.locator('#notebook-output > .notebook-search-results').count(), 0);
    await page.locator('#notebook-builder-tab').click();
    await page.locator('.notebook-search-results .gwas-search-shortlist-table').waitFor();
    assert.equal(await page.locator('.notebook-search-results').count(), 1);
    assert.deepEqual(errors, []);
    console.log('PASS: per-cell files, CSV/Markdown/image/search previews, reload, Files navigation, retries, overwrites, deleted/unattributed files and input exclusion');
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exit(1);});
