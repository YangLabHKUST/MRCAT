// Run against result_fixture.py artifacts served by the real MRCAT backend.
const {chromium} = require('playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');
(async () => {
  const {session_id: id} = JSON.parse(fs.readFileSync('/tmp/mrcat-result-session.json'));
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto((process.env.MRCAT_TEST_URL || 'http://127.0.0.1:18789/') + '#' + id);
    await page.locator('.mr-method-result-table').waitFor();
    const cell = page.locator('#codeact-cell-result-cell');
    assert.equal(await cell.locator('.codeact-result').count(), 4, 'Multiple saved responses share one cell; nested records are not duplicated');
    assert.match(await cell.locator('.mr-method-result-table').innerText(), /Beta[\s\S]*IVW[\s\S]*0\.2/);
    assert.doesNotMatch(await cell.locator('.codeact-result').allInnerTexts().then(parts => parts.join(' ')), /Effect scale:|Input scale:|effect scale.*unknown/i);
    assert.match(await cell.locator('.skill-retention-values').innerText(), /1,000[\s\S]*800/);
    assert.match(await cell.locator('.skill-pair-retention').innerText(), /800[\s\S]*2/);
    assert.equal(await cell.locator('.codeact-execution-details').evaluate(node => node.open), false);
    await cell.getByRole('button', {name: 'Clumped SNPs', exact: true}).click();
    await page.waitForFunction(() => document.querySelector('.codeact-data .spreadsheet-table')?.textContent.includes('rs1'));
    await cell.locator('.primary-scatter svg').first().waitFor();
    await page.waitForFunction(() => /3 plotted quantiles/.test(document.querySelector('.qc-status')?.textContent));
    assert.match(await cell.locator('[data-result-path="workspace/broken/response.json"]').innerText(), /Result preview unavailable/);
    await cell.locator('.codeact-execution-details > summary').click();
    assert.match(await cell.locator('.codeact-stream-stderr').innerText(), /A diagnostic message/);
    assert.match(await cell.locator('header').innerText(), /Completed/);
    await page.evaluate(() => {
      state.eventSource?.close();
      window.testCell = document.getElementById('codeact-cell-result-cell');
      const snapshot = structuredClone(state.snapshot);
      snapshot.mr.events.push({id:'update', type:'assistant_message', content:'Reviewing the result.', details:{agent:'mr'}});
      applySnapshot(snapshot);
    });
    assert(await page.evaluate(() => window.testCell === document.getElementById('codeact-cell-result-cell')), 'Unrelated updates preserve the mounted cell');
    assert.equal(await cell.getByRole('button', {name:'Clumped SNPs', exact:true}).getAttribute('aria-pressed'), 'true');
    await cell.locator('.codeact-execution-details > summary').click();
    await page.evaluate(() => els.notebookOutput.scrollTop = 0);
    await page.screenshot({path: '/tmp/mrcat-notebook-restore/results-desktop.png', fullPage: true});
    await page.setViewportSize({width: 900, height: 1000});
    await page.screenshot({path: '/tmp/mrcat-notebook-restore/results-narrow.png', fullPage: true});
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'No page overflow');
    assert.deepEqual(errors, []);
    console.log('PASS: MRCAT response records, multiple outputs per cell, QC retention, pair flow, MR beta/CI, compressed data preview, interactive QC and scatter, malformed result fallback, stream separation and stable previews');
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exit(1);});
