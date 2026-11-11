// Uses browser_fixture.py; all extra workflow and plot data is synthetic and local.
const {chromium} = require('playwright');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const assert = require('node:assert/strict');

(async () => {
  const ids = JSON.parse(fs.readFileSync('/tmp/mrcat-browser-roles.json', 'utf8'));
  const base = process.env.MRCAT_TEST_URL || 'http://127.0.0.1:18816';
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'mrcat-snp-browser-'));
  const plotPath = path.join(dir, 'mrapss_mrplot.png');
  const helper = path.resolve(__dirname, '../skills/mr-apss/scripts/mrapss/export_mrapss_plot.R');
  execFileSync(process.env.RSCRIPT_BIN || 'Rscript', ['-e', `
    source(${JSON.stringify(helper)})
    fit <- list(MRdat=data.frame(SNP=paste0('rs', 101:106),
      b.exp=c(-.08,-.03,.02,.055,.08,.12), b.out=c(-.04,.015,.005,.025,.02,.065),
      se.exp=rep(.007,6), se.out=rep(.006,6), pval.exp=c(1e-8,1e-7,1e-9,1e-11,1e-9,1e-10)),
      post=list(Pi=c(.9,.2,.8,.95,.7,.97)), beta=.4, beta.se=.08)
    export_mrapss_plot(MRAPSS::MRplot(fit, exposure='Synthetic exposure', outcome='Synthetic outcome'), fit, ${JSON.stringify(plotPath)})
  `], {stdio: 'pipe'});
  const points = JSON.parse(fs.readFileSync(plotPath.replace('.png', '.plot.json'))).points;
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
  try {
    const page = await browser.newPage({viewport: {width: 1600, height: 1050}});
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.route('**/artifacts/raw?**', async route => {
      const ref = new URL(route.request().url()).searchParams.get('summary');
      if (ref === 'workspace/mrapss_mrplot.png') return route.fulfill({contentType: 'image/png', body: fs.readFileSync(plotPath)});
      if (ref === 'workspace/mrapss_mrplot.plot.json') return route.fulfill({contentType: 'application/json', body: fs.readFileSync(plotPath.replace('.png', '.plot.json'))});
      return route.continue();
    });
    await page.goto(base + '#' + ids.notebook);
    await page.waitForSelector('.codeact-cell');
    assert.equal(await page.locator('#provider-select').isVisible(), false);
    await page.locator('.sidebar-settings > summary').click();
    assert.equal(await page.locator('#provider-select').isVisible(), true);
    await page.locator('.sidebar-settings > summary').click();
    await page.getByLabel('Session actions', {exact: true}).click();
    assert.equal(await page.locator('#fork-session-button').isVisible(), true);
    await page.getByLabel('Session actions', {exact: true}).click();
    await page.evaluate(() => {
      state.eventSource?.close();
      const snapshot = structuredClone(state.snapshot);
      const cells = snapshot.mr.events.filter(e => e.type === 'code_execution');
      const items = [
        {step_id: 'fit', title: 'Run MR-APSS', skill_id: 'mr-apss', reuse_from: []},
        {step_id: 'review', title: 'Review the saved results', skill_id: null, reuse_from: []},
        {step_id: 'report', title: 'Write the scientific report', skill_id: null, reuse_from: []},
      ];
      const plan = items.map((item, i) => `${i + 1}. [${item.step_id}] ${item.title}${i === 0 ? '. Inspect the SNP estimates and their uncertainty.' : ''}`).join('\n');
      snapshot.mr.state.active_task = {task_id: 'task_ui', status: 'running', plan, plan_items: items,
        completed_items: {fit: {item: items[0], execution_ids: [cells[0].details.execution_id]}},
        current_item_id: 'review', item_execution_ids: [cells[1].details.execution_id]};
      snapshot.active_job = {status: 'running'};
      snapshot.state.active_agent = 'mr';
      snapshot.mr.events = [{id: 'plan_ui', type: 'plan_updated', content: plan, details: {task_id: 'task_ui'}}, ...cells];
      cells.forEach(e => {e.details.task_id = 'task_ui';});
      cells[0].content = 'Run MR-APSS · Synthetic interaction fixture';
      const paths = ['workspace/mrapss_mrplot.png', 'workspace/mrapss_mrplot.plot.json'];
      cells[0].details.generated_files.push(...paths);
      Object.values(snapshot.mr.manifest.artifacts)[0].files.push(...paths.map(path => ({path, kind: path.endsWith('.png') ? 'image' : 'json'})));
      applySnapshot(snapshot);
    });
    await page.waitForSelector('.mrapss-snp');
    const steps = page.locator('.readable-plan-step');
    assert.equal(await steps.count(), 3);
    assert(await steps.first().locator('.readable-plan-step-title').evaluate(node => parseFloat(getComputedStyle(node).fontSize) >= 20));
    assert.equal(await page.locator('.readable-plan-meta').innerText(), '1 / 3 completed');
    assert.deepEqual(await page.locator('.readable-plan-status').allTextContents(), ['Completed', 'Running', 'Pending']);
    assert.equal(await page.locator('.codeact-cell').count(), 2, 'Every execution remains visible');
    await page.getByRole('button', {name: 'View outputs for Run MR-APSS', exact: true}).click();
    assert.equal(await page.locator('.codeact-cell.is-selected').count(), 1);
    assert.match(await page.locator('.codeact-cell.is-selected h4').first().innerText(), /MR-APSS/);
    const point = page.getByRole('button', {name: 'Inspect SNP rs103', exact: true});
    const plot = page.locator('.mrapss-explorer');
    const tooltip = plot.locator('.mrapss-tooltip');
    await page.waitForFunction(() => document.querySelector('.mrapss-canvas img')?.naturalWidth > 0);
    const heightBeforeHover = await plot.evaluate(node => node.offsetHeight);
    await point.hover();
    assert.match(await tooltip.innerText(), /rs103/);
    assert.equal(await tooltip.evaluate(node => getComputedStyle(node).position), 'absolute');
    assert.equal(await plot.evaluate(node => node.offsetHeight), heightBeforeHover, 'Hover must not add a panel beneath the plot');
    assert.equal(await page.locator('.mrapss-inspector').count(), 0);
    await page.locator('#notebook-title').hover();
    assert.equal(await tooltip.isVisible(), false, 'Hover details close when leaving the point');
    await point.click();
    assert.equal(await point.getAttribute('aria-pressed'), 'true');
    assert.match(await tooltip.innerText(), /Pinned/);
    await page.locator('#notebook-title').hover();
    assert.equal(await tooltip.isVisible(), true, 'Click keeps the floating details pinned');
    await page.setViewportSize({width: 1200, height: 900});
    await point.evaluate(node => {
      const notebook = document.querySelector('#notebook-output');
      notebook.scrollTop += node.getBoundingClientRect().bottom - notebook.getBoundingClientRect().bottom + 20;
    });
    await page.waitForFunction(() => {
      const tooltip = document.querySelector('.mrapss-tooltip');
      const rect = tooltip.getBoundingClientRect();
      const notebook = document.querySelector('#notebook-output').getBoundingClientRect();
      return !tooltip.hidden && rect.top >= Math.max(0, notebook.top) && rect.bottom <= Math.min(innerHeight, notebook.bottom);
    });
    await page.setViewportSize({width: 1600, height: 1050});
    assert.equal(await page.locator('.mrapss-highlight:not([hidden])').count(), 2);
    await page.getByRole('button', {name: 'Zoom in MR-APSS plot', exact: true}).click();
    assert.equal(await page.locator('.mrapss-zoom-label').innerText(), '150%');
    const location = await point.evaluate(node => {
      const dot = node.getBoundingClientRect(), img = node.parentElement.querySelector('img').getBoundingClientRect();
      return {x: (dot.x + dot.width / 2 - img.x) / img.width, y: (dot.y + dot.height / 2 - img.y) / img.height};
    });
    assert(Math.abs(location.x - points[2].x) < .001 && Math.abs(location.y - points[2].y) < .001,
      'The target stays aligned with measured PNG coordinates after zoom');
    for (let i = 0; i < 5; i++) await page.getByRole('button', {name: 'Zoom in MR-APSS plot', exact: true}).click();
    assert.equal(await page.locator('.mrapss-zoom-label').innerText(), '400%');
    assert(await page.locator('.mrapss-viewport').evaluate(node => node.scrollHeight <= node.clientHeight + 1), 'The full-height plot has no internal vertical scrollbar, even when zoomed');
    await page.getByRole('button', {name: 'Reset view', exact: true}).click();
    await point.focus();
    await page.keyboard.press('Enter');
    assert.equal(await point.getAttribute('aria-pressed'), 'true', 'Keyboard selection works');
    await page.keyboard.press('Escape');
    assert.equal(await point.getAttribute('aria-pressed'), 'false');
    assert.equal(await tooltip.isVisible(), false);
    await steps.nth(0).locator('summary').click();
    await page.evaluate(() => applySnapshot(state.snapshot));
    assert.equal(await steps.nth(0).locator('details').evaluate(node => node.open), true);
    if (process.env.MRCAT_UI_SCREENSHOT) {
      await page.getByRole('button', {name: 'View current plan', exact: true}).click();
      await point.click();
      await page.evaluate(() => focusNotebookElement(document.querySelector('.mrapss-explorer')));
      await page.screenshot({path: process.env.MRCAT_UI_SCREENSHOT, fullPage: true});
    }
    // Paused work and previous revisions must not acquire invented progress.
    await page.evaluate(() => {
      const snapshot = structuredClone(state.snapshot);
      snapshot.active_job = null;
      snapshot.mr.state.active_task.status = 'paused';
      applySnapshot(snapshot);
    });
    assert.equal(await page.locator('.readable-plan-status').nth(1).innerText(), 'Paused');
    await page.evaluate(() => {
      const snapshot = structuredClone(state.snapshot);
      snapshot.mr.state.active_task.plan += '\nChanged revision';
      applySnapshot(snapshot);
    });
    assert.deepEqual(await page.locator('.readable-plan-status').allTextContents(), ['Planned', 'Planned', 'Planned']);
    assert.equal(await page.locator('.readable-plan-output').count(), 0);
    // An older PNG without the sidecar remains a normal figure, with no guessed points.
    await page.evaluate(() => {
      const snapshot = structuredClone(state.snapshot);
      Object.values(snapshot.mr.manifest.artifacts)[0].files = Object.values(snapshot.mr.manifest.artifacts)[0].files.filter(f => !f.path.endsWith('.plot.json'));
      applySnapshot(snapshot);
    });
    assert.equal(await page.locator('.mrapss-snp').count(), 0);
    assert.equal(await page.locator('figure[data-path="workspace/mrapss_mrplot.png"] img').count(), 1);
    await page.setViewportSize({width: 390, height: 844});
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'No mobile page overflow');
    await page.locator('.sidebar-settings > summary').click();
    assert(await page.locator('#provider-select').isVisible());
    assert.deepEqual(errors, []);
    console.log('PASS: sidebar controls, genuine plan progress, output navigation, all execution cells, SNP hover/click/keyboard/zoom, revision safety, legacy PNG, mobile layout');
  } finally {
    await browser.close();
    fs.rmSync(dir, {recursive: true, force: true});
  }
})().catch(error => {console.error(error); process.exit(1);});
