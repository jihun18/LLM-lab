// Isolated browser verification: no real Ollama, user server or Wiki mutation.
const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const html = fs.readFileSync(path.join(__dirname, '..', 'privAI.html'), 'utf8');
  const output = path.join(__dirname, '..', 'benchmark-results', 'answer-ui-preview');
  fs.mkdirSync(output, {recursive: true});
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const page = await browser.newPage({viewport: {width: 1000, height: 900}});
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  let scenario = 'partial';
  const sources = [{source: '02-Framework-Comparison.md', heading: '구현 비교'}];
  const missing = ['Django의 역할 (검색 근거 부족)'];
  const raw = '검색된 Wiki 원문에서 확인한 항목:\n- FastAPI의 역할: 주력 REST API\n  [출처: 02-Framework-Comparison.md#구현 비교]\n- Flask의 역할: 최소 비교군\n  [출처: 02-Framework-Comparison.md#구현 비교]\n\n확인하지 못한 항목:\n- Django의 역할 (검색 근거 부족)\n해당 근거 문서를 보완해주세요. 질문 전체가 해결된 것은 아닙니다.';
  await page.route('**/*', async route => {
    const u = new URL(route.request().url());
    let data;
    if (u.pathname === '/') return route.fulfill({contentType: 'text/html', body: html});
    if (u.pathname === '/health') data = {framework: 'FastAPI', status: 'ok'};
    else if (u.pathname === '/models') data = {models: [{name: 'qwen3:1.7b'}], default: 'qwen3:1.7b'};
    else if (u.pathname === '/knowledge/status') data = {files_indexed: 15, chunks_indexed: 60, embedding_model: '화면 검증용', semantic_threshold: 0.44};
    else if (u.pathname === '/rag/chat/stream' || u.pathname === '/chat/stream') {
      const partial = scenario === 'partial' || scenario === 'mobile';
      const verification = partial ? {method: 'deterministic_requirement_copy', passed: null, missing_items: missing,
        issues: missing, display_label: '일부 항목 원문 추출 · 미확인 항목 있음'} :
        scenario === 'blocked' ? {passed: false, method: 'no_evidence', issues: null} :
        {passed: null, method: 'source_attached_semantic_review_needed'};
      const answer = partial ? raw : scenario === 'blocked' ? 'Wiki에서 근거를 찾지 못했습니다.' : '출처가 있어도 의미는 검토해야 합니다.';
      const events = [{sources: scenario === 'blocked' ? [] : sources}, {content: answer, done: false, verification}];
      if (scenario !== 'incomplete') events.push({done: true, verification, elapsed_seconds: .01, tokens_per_second: null});
      // Deliberately no trailing newline: final buffered event must be consumed.
      return route.fulfill({contentType: 'application/x-ndjson', body: events.map(JSON.stringify).join('\n')});
    } else return route.fulfill({status: 404, body: ''});
    return route.fulfill({contentType: 'application/json', body: JSON.stringify(data)});
  });
  async function submit(which) {
    scenario = which;
    await page.goto('http://privai.test/');
    await page.waitForFunction(() => document.querySelector('#model').options.length > 0);
    if (which === 'plain') await page.locator('#ragMode').uncheck();
    await page.locator('#prompt').fill('FastAPI와 Flask의 역할과 Django의 역할도 알려줘.');
    await page.locator('#send').click();
    await page.waitForFunction(() => !document.querySelector('#send').disabled);
    return page.locator('#messages > .assistant').last();
  }
  try {
    let card = await submit('partial');
    assert.equal(await card.locator('.confirmed h3').textContent(), '원문에서 확인한 내용');
    assert.ok(!(await card.locator('.confirmed').textContent()).includes('Django'));
    assert.ok((await card.locator('.missing').textContent()).includes('Django'));
    assert.ok((await card.locator('.answer-status').textContent()).includes('부분 답변'));
    await card.locator('summary', {hasText: '참고 근거'}).click();
    assert.equal(await card.locator('details[open]').count(), 1);
    await page.screenshot({path: path.join(output, 'partial-desktop.png'), fullPage: true});
    await card.locator('summary', {hasText: '전체 응답 원문 보기'}).click();
    assert.equal(await card.locator('details').last().locator('p').textContent(), raw);
    card = await submit('review');
    assert.equal(await card.locator('.confirmed').count(), 0);
    assert.ok((await card.textContent()).includes('의미 검토 필요'));
    card = await submit('blocked');
    assert.equal(await card.locator('.confirmed').count(), 0);
    assert.ok((await card.locator('.answer-status').textContent()).includes('답변 보류'));
    card = await submit('incomplete');
    assert.ok((await card.textContent()).includes('응답이 완료되기 전에'));
    assert.equal(await card.locator('.answer-status').count(), 0);
    card = await submit('plain');
    assert.equal(await card.locator('.answer-status').count(), 0);
    assert.equal(await card.textContent(), '출처가 있어도 의미는 검토해야 합니다.');
    await page.setViewportSize({width: 390, height: 844});
    card = await submit('mobile');
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
    const badge = await card.locator('.answer-status').boundingBox();
    const box = await page.locator('#messages').boundingBox();
    assert.ok(badge.y >= box.y && badge.y + badge.height <= box.y + box.height);
    await page.screenshot({path: path.join(output, 'partial-mobile.png'), fullPage: true});
    assert.deepEqual(errors, []);
    console.log('Browser checks passed: partial/source/raw/review/blocked/incomplete/EOF/mobile; screenshots: ' + output);
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
