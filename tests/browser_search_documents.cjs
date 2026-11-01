const {chromium} = require('playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');
(async () => {
  const ids = JSON.parse(fs.readFileSync('/tmp/mrcat-search-documents-browser.json', 'utf8'));
  const browser = await chromium.launch({headless: true, args:['--no-sandbox']});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1000}});
    const errors=[];page.on('pageerror', error=>errors.push(error.message));
    const base=process.env.MRCAT_TEST_URL || 'http://127.0.0.1:18771/';
    await page.route('https://example.org/**', route=>route.abort());
    await page.goto(base+'#'+ids.session);
    await page.waitForFunction(id=>state.snapshot?.session_id===id,ids.session);
    const report=page.locator('.notebook-web-search .search-report-card');
    const panel=page.locator('.notebook-scan-design .scan-design-panel');
    await report.waitFor();await panel.waitFor();
    assert.equal(await report.locator('.search-report-section').count(),6);
    assert.match(await report.innerText(),/5 sections · 7 references · openai/);
    await report.getByRole('button',{name:'Expand all',exact:true}).click();
    assert.equal(await report.locator('.search-report-section[open]').count(),6);
    assert.match(await report.innerText(),/beta=0.10[\s\S]*Sample overlap was not reported/);
    const references=report.locator('.search-reference-item');
    assert.equal(await references.count(),7);
    assert.equal(await references.first().getAttribute('href'),'https://example.org/study/1');
    assert.match(await references.first().getAttribute('data-citation-id'),/^search_.*_c1$/);
    assert.equal(await report.locator('a[href^="javascript:"]').count(),0);
    await report.getByRole('button',{name:'Show all 7 references'}).click();
    assert(await references.last().isVisible());
    await report.getByRole('button',{name:'Collapse all',exact:true}).click();
    assert.equal(await report.locator('.search-report-section[open]').count(),0);

    await page.locator('.notebook-file').filter({hasText:'research_brief.md'}).locator('.notebook-explanation').waitFor();
    assert.match(await panel.innerText(),/2 exposure traits × 2 outcome traits = 4 scan pairs/);
    assert.match(await panel.innerText(),/LDL-C[\s\S]*coronary artery disease/);
    await panel.getByRole('button',{name:'Deselect exposure: LDL cholesterol',exact:true}).click();
    await panel.getByRole('button',{name:'Deselect outcome: Stroke',exact:true}).click();
    assert.match(await panel.innerText(),/1 exposure traits × 1 outcome traits = 1 scan pairs/);
    await panel.getByRole('button',{name:'Deselect exposure: BMI',exact:true}).click();
    assert(await panel.getByRole('button',{name:'Review selected scan query'}).isDisabled());
    await panel.getByRole('button',{name:'Select exposure: BMI',exact:true}).click();
    let posts=0;page.on('request',req=>{if(req.method()==='POST') posts++;});
    await panel.getByRole('button',{name:'Review selected scan query'}).click();
    const request=await page.locator('#reply-input').inputValue();
    assert.match(request,/exposure_traits=\["BMI"\]\noutcome_traits=\["CAD"\]/);
    assert.match(request,/FinnGen European[\s\S]*cML-MA; p < 5e-8; exclude study X/);
    assert.match(request,/do not reintroduce unselected candidates/);
    assert.match(request,/Saved evidence: workspace\/outputs\/scan_design\/scan_design.json/);
    assert.equal(posts,0);
    assert.equal(await page.evaluate(()=>state.snapshot.mr.state.active_task),null);
    // The existing reply transport receives the exact selected query, not the full design.
    let sent;
    await page.route('**/api/sessions/*/reply',async route=>{
      sent=route.request().postDataJSON();
      await route.fulfill({status:200,contentType:'application/json',body:'{}'});
    });
    await page.locator('#reply-button').click();
    await page.waitForFunction(()=>!state.busy);
    assert.equal(sent.reply,request);

    // Busy-state updates must reach cached notebook cells.
    await page.evaluate(()=>{state.snapshot.active_job={job_id:'fixture'};updateComposer();});
    assert(await panel.getByRole('button',{name:'Review selected scan query'}).isDisabled());
    await page.evaluate(()=>{state.snapshot.active_job=null;updateComposer();});
    assert(!(await panel.getByRole('button',{name:'Review selected scan query'}).isDisabled()));
    await page.evaluate(()=>setNotebookView('builder'));
    await page.locator('.notebook-scan-design .scan-design-panel').waitFor();
    assert.match(await page.locator('.notebook-scan-design').innerText(),/1 exposure traits × 1 outcome traits/);
    await page.evaluate(()=>setNotebookView('task'));
    await panel.waitFor();
    assert.match(await panel.innerText(),/1 exposure traits × 1 outcome traits/);
    await page.reload();await panel.waitFor();
    assert.match(await panel.innerText(),/1 exposure traits × 1 outcome traits/);
    await page.evaluate(async id=>selectSession(id),ids.other);await panel.waitFor();
    await page.waitForFunction(id=>state.snapshot?.session_id===id,ids.other);
    assert.match(await panel.innerText(),/2 exposure traits × 2 outcome traits/);
    await page.evaluate(async id=>selectSession(id),ids.session);await panel.waitFor();
    await page.waitForFunction(id=>state.snapshot?.session_id===id,ids.session);
    assert.match(await panel.innerText(),/1 exposure traits × 1 outcome traits/);
    await panel.scrollIntoViewIfNeeded();
    await page.screenshot({path:'/tmp/mrcat-search-adaptation.png',fullPage:true});
    const firstButton=panel.locator('.candidate-select').first();
    const fits=await firstButton.evaluate(button=>button.scrollWidth<=button.clientWidth);
    assert(fits,'Selection buttons must fit in the narrow notebook');
    await report.scrollIntoViewIfNeeded();
    await report.getByRole('button',{name:'Expand all',exact:true}).click();
    await page.screenshot({path:'/tmp/mrcat-search-evidence.png',fullPage:true});
    // Unstructured answers and missing citations remain readable, without invented sections.
    const plain=await page.evaluate(()=>{
      const node=buildNotebookWebSearch({path:'workspace/plain/search.json'},state.snapshot,
        {answer:'Plain source text without headings.',citations:[],provider:'qwen'});
      return {sections:node.querySelectorAll('.search-report-section').length,text:node.textContent};
    });
    assert.equal(plain.sections,1);
    assert.match(plain.text,/Plain source text without headings/);
    assert.match(plain.text,/No source links were saved/);
    // A failed artifact fetch must not prevent the remaining document widgets from loading.
    const failSearch=async route=>{
      if(new URL(route.request().url()).searchParams.get('summary')==='workspace/outputs/web/search.json')
        await route.fulfill({status:500,contentType:'application/json',body:'{"detail":"fixture read failure"}'});
      else await route.continue();
    };
    await page.route('**/artifacts/raw?*',failSearch);
    await page.reload();
    await page.locator('.notebook-web-search .notebook-warning').waitFor();
    assert.match(await page.locator('.notebook-web-search').innerText(),/Could not load Search result/);
    await panel.waitFor();
    assert.match(await panel.innerText(),/1 exposure traits × 1 outcome traits/);
    await page.unroute('**/artifacts/raw?*',failSearch);
    await page.reload();await report.waitFor();await panel.waitFor();
    // If another cell updates the file, show the current widget only under its owner.
    await page.evaluate(()=>{
      const original=state.snapshot.mr.events.find(event=>event.type==='code_execution');
      const updated=structuredClone(original);
      updated.id='updated-scan-fixture';
      updated.details.execution_id='updated-scan-fixture';
      updated.details.generated_files=['workspace/outputs/scan_design/scan_design.json'];
      state.snapshot.mr.events.push(updated);
      renderExecutionNotebook();
    });
    await page.locator('.codeact-cell').last().locator('.notebook-scan-design .scan-design-panel').waitFor();
    assert.equal(await page.locator('.notebook-scan-design').count(),1);
    assert.match(await page.locator('.codeact-cell').first().innerText(),/scan_design.json · Updated by Cell 2/);
    assert.deepEqual(errors,[]);
    console.log('PASS: search sections/references, scan subset/empty selection, preserved constraints, native reply transport, busy state, Files view, reload and session isolation; no JS errors');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exit(1);});
