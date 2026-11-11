// Verify presentation-only execution references against an isolated browser fixture.
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
    await page.waitForSelector('.codeact-execution-link');
    const correspondence = () => page.evaluate(() => ({
      conversation: [...document.querySelectorAll('.message-execution')].map(row => ({id: row.dataset.executionId, text: row.querySelector('.codeact-execution-status').textContent})),
      cells: [...document.querySelectorAll('.codeact-cell')].map(cell => ({id: cell.dataset.executionId,
        text: `${cell.querySelector('.codeact-cell-meta').textContent} · ${cell.querySelector('.codeact-cell-status').textContent}`})),
    }));
    const actual = await correspondence();
    assert.equal(actual.cells.length, 2);
    assert.deepEqual(actual.conversation.map(row => row.id), actual.cells.map(row => row.id));
    for (let i = 0; i < actual.cells.length; i++) {
      assert(actual.conversation[i].text.startsWith(`Cell ${i + 1} ·`));
      assert(actual.cells[i].text.startsWith(`Cell ${i + 1} ·`));
    }
    await page.reload();
    await page.waitForSelector('.codeact-execution-link');
    assert.deepEqual(await correspondence(), actual);
    await page.evaluate(() => {
      state.eventSource?.close();
      const snapshot = structuredClone(state.snapshot);
      const event = (id, type, content, details = {}) => ({id, type, content, details: {agent: 'search', ...details}});
      const execution = (id, status, returncode, content = 'Run the same tool.') => event(id, 'code_execution', content, {
        execution_id: id, language: 'python', code: 'print("fixture")', status, returncode,
        stdout: Array.from({length: 30}, (_, i) => `Output line ${i}`).join('\n'), stderr: '',
      });
      snapshot.active_job = null;
      snapshot.mr.manifest = {artifacts: {}};
      snapshot.mr.events = [event('u1', 'user_message', 'Search CAD'),
        event('thinking', 'assistant_message', 'Compare the supplied source constraints.'),
        event('guide', 'skill_loaded', 'gwas-search'),
        event('announce-a', 'assistant_message', 'Run the same tool.'), execution('attempt-a', 'exited', 1),
        event('repair', 'assistant_message', 'A different argument may resolve this error.'),
        event('announce-b', 'assistant_message', 'Run the same tool.'), execution('attempt-b', 'running', null),
        execution('attempt-c', 'exited', 0, 'Run python'),
        event('ask', 'question', 'Which population?'), event('answer', 'final', 'Here are the available results.')];
      applySnapshot(snapshot);
    });
    let mapped = await correspondence();
    assert.deepEqual(mapped.conversation.map(row => row.id), ['attempt-a', 'attempt-b', 'attempt-c']);
    assert.deepEqual(mapped.cells.map(row => row.id), ['attempt-a', 'attempt-b', 'attempt-c']);
    assert.match(mapped.conversation[0].text, /Cell 1 · Failed/);
    assert.match(mapped.conversation[1].text, /Cell 2 · Running/);
    assert.match(mapped.conversation[2].text, /Cell 3 · Completed/);
    const messages = await page.locator('#conversation-feed .message').allTextContents();
    assert.equal(messages.filter(text => text.includes('Run the same tool.')).length, 0, 'Execution descriptions belong in the notebook');
    assert.equal(await page.locator('#conversation-feed .message-execution .message-tag, #conversation-feed .message-execution .message-body').count(), 0);
    assert.match(await page.locator('#codeact-cell-attempt-a .codeact-cell-title').textContent(), /Run the same tool/);
    assert(messages.some(text => text.includes('Analysis / update') && text.includes('Compare the supplied')));
    assert(messages.some(text => text.includes('Analysis / update') && text.includes('different argument')));
    assert(messages.some(text => text.includes('Question') && text.includes('Which population?')));
    assert(messages.some(text => text.includes('Answer') && text.includes('available results')));
    assert.equal(await page.locator('.message:not(.message-execution):not(.message-skill-guide) .codeact-execution-link').count(), 0);
    const skillExecution = page.locator('.message-skill-guide.has-execution');
    assert.equal(await skillExecution.count(), 1);
    assert.equal(await skillExecution.locator('.message-execution').getAttribute('data-execution-id'), 'attempt-a');
    for (const width of [1440, 390]) {
      await page.setViewportSize({width, height: 1000});
      const skill = await skillExecution.locator('.skill-label').boundingBox();
      const cell = await skillExecution.locator('.codeact-execution-link').boundingBox();
      assert(cell.x >= skill.x + skill.width && cell.y < skill.y + skill.height, 'Cell follows the skill on the same line');
    }
    await page.setViewportSize({width: 1440, height: 1000});

    await page.evaluate(() => setNotebookView('builder'));
    assert.equal(await page.locator('.codeact-cell').count(), 0);
    await page.getByRole('button', {name: 'View Cell 3 in Execution notebook', exact: true}).click();
    await page.waitForFunction(() => {
      const cell = document.getElementById('codeact-cell-attempt-c');
      const panel = els.notebookOutput.getBoundingClientRect();
      const box = cell?.getBoundingClientRect();
      return notebook.view === 'task' && cell?.classList.contains('is-selected') &&
        document.activeElement === cell && box.top >= panel.top && box.top < panel.bottom;
    });
    const first = page.getByRole('button', {name: 'View Cell 1 in Execution notebook', exact: true});
    await first.focus();
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => document.activeElement?.id === 'codeact-cell-attempt-a');
    await page.evaluate(() => {
      const snapshot = structuredClone(state.snapshot);
      const d = snapshot.mr.events.find(e => e.id === 'attempt-b').details;
      Object.assign(d, {status: 'exited', returncode: 0, stdout: 'Updated output'});
      applySnapshot(snapshot);
    });
    mapped = await correspondence();
    assert.equal(mapped.conversation.length, 3);
    assert.match(mapped.conversation[1].text, /Cell 2 · Completed/);
    assert.match(mapped.cells[1].text, /Cell 2.*Completed/);
    assert.doesNotMatch(mapped.cells[1].text, /python/);
    assert.equal(await page.locator('.codeact-cell.is-selected').getAttribute('data-execution-id'), 'attempt-a');
    // Group only adjacent MR execution rows; prose, questions and guides stay outside.
    await page.evaluate(() => {
      const snapshot = structuredClone(state.snapshot);
      const event = (id, type, content, details = {}) => ({id, type, content, details: {agent: 'mr', task_id: 'task1', ...details}});
      const run = (id, details = {}) => event(id, 'code_execution', `Execute ${id}`, {
        execution_id: id, language: 'python', code: 'print("fixture")',
        status: 'exited', returncode: 0, ...details,
      });
      snapshot.mr.events = [event('user', 'user_message', 'Keep my question visible.'),
        run('mr-a'), run('mr-b', {returncode: 1}), run('mr-c', {status: 'running', returncode: null}),
        event('update', 'assistant_message', 'Keep this explanation visible.'), run('mr-d'),
        event('guide', 'skill_loaded', 'mr-primary'),
        run('mr-e', {task_id: 'task2'}), run('mr-f', {task_id: 'task2'}),
        event('question', 'question', 'Keep this clarification visible.'),
        run('mr-g', {task_id: 'task2'}), run('mr-h', {task_id: 'task3'}),
        run('search-a', {agent: 'search'}), run('search-b', {agent: 'search'}),
        event('final', 'final', 'Keep this answer visible.')];
      applySnapshot(snapshot);
    });
    const groups = page.locator('.conversation-executions');
    const disclosure = groups.first().locator('details');
    const toggle = disclosure.locator('summary');
    const chatCell = id => page.locator(`#conversation-feed .message-execution[data-execution-id="${id}"]`);
    assert.equal(await groups.count(), 2);
    assert.equal(await disclosure.evaluate(node => node.open), false);
    assert.equal(await toggle.innerText(), 'Show 2 more cells');
    assert.equal(await chatCell('mr-a').isVisible(), true);
    assert.equal(await chatCell('mr-b').isVisible(), false);
    assert.equal(await chatCell('mr-c').isVisible(), false);
    assert.equal(await chatCell('mr-f').isVisible(), false);
    for (const id of ['mr-d', 'mr-g', 'mr-h', 'search-a', 'search-b']) assert.equal(await chatCell(id).isVisible(), true);
    assert.equal(await groups.locator('.message:not(.message-execution)').count(), 0);
    assert.equal(await page.locator('#conversation-feed .message.user').getByText('Keep my question visible.', {exact: true}).isVisible(), true);
    for (const text of ['Keep this explanation visible.', 'Keep this clarification visible.', 'Keep this answer visible.']) {
      assert.equal(await page.locator('#conversation-feed').getByText(text, {exact: true}).isVisible(), true);
    }
    assert.equal(await page.locator('#conversation-feed .message-skill-guide').isVisible(), true);
    assert.equal(await page.locator('.message-skill-guide.has-execution').count(), 0, 'Do not attach executions from a different task');
    assert.equal(await page.locator('.codeact-cell').count(), 10);
    await toggle.focus();
    await page.keyboard.press('Enter');
    assert.equal(await chatCell('mr-b').isVisible(), true);
    await chatCell('mr-b').getByRole('button').click();
    assert.equal(await page.locator('.codeact-cell.is-selected').getAttribute('data-execution-id'), 'mr-b');
    await page.evaluate(() => {
      const snapshot = structuredClone(state.snapshot);
      const event = snapshot.mr.events.find(e => e.id === 'mr-c');
      Object.assign(event.details, {status: 'exited', returncode: 0});
      const added = structuredClone(event);
      added.id = added.details.execution_id = 'mr-new';
      snapshot.mr.events.splice(4, 0, added);
      applySnapshot(snapshot);
    });
    assert.equal(await disclosure.evaluate(node => node.open), true);
    assert.equal(await toggle.innerText(), 'Hide 3 more cells');
    assert.match(await chatCell('mr-c').innerText(), /Completed/);
    await toggle.click();
    await page.evaluate(() => renderConversation(state.snapshot));
    assert.equal(await disclosure.evaluate(node => node.open), false);
    assert.equal(await chatCell('mr-new').isVisible(), false);
    await page.setViewportSize({width: 390, height: 844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.setViewportSize({width: 1440, height: 1000});

    if (process.env.MRCAT_CELLS_SCREENSHOT) await page.screenshot({path: process.env.MRCAT_CELLS_SCREENSHOT, fullPage: true});
    await page.evaluate(async id => selectSession(id), ids.proposal);
    await page.waitForSelector('details[data-current-plan="true"]');
    assert.equal(await page.locator('.codeact-execution-link').count(), 0);
    assert.equal(await page.locator('.codeact-cell').count(), 0);
    assert.deepEqual(errors, []);
    console.log('PASS: shared cell numbers, exact execution IDs, retries, missing/duplicate announcements, analysis labels, keyboard and cross-tab navigation, streaming status, MR-only execution groups, visible prose, mobile layout, reload and Plan isolation');
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exit(1);});
