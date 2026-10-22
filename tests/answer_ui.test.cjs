const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '..', 'privAI.html'), 'utf8');
const script = html.match(/<script id="answer-ui">([\s\S]*?)<\/script>/)[1];
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.className = ''; this.textContent = '';
    this.classList = {add: name => {this.className += ' ' + name;}}; }
  append(el) { this.children.push(el); }
  replaceChildren() { this.children = []; this.textContent = ''; }
}
const context = {document: {createElement: tag => new Element(tag)}};
vm.runInNewContext(script, context);
const ui = context.AnswerUI;
const sources = [{source: 'roles.md', heading: '역할'}];
const missing = ['Other의 역할 (검색 근거 부족)'];
const verification = {method: 'deterministic_requirement_copy', passed: null, missing_items: missing};
const text = '검색된 Wiki 원문에서 확인한 항목:\n- Tool의 역할: API\n  [출처: roles.md#역할]\n\n확인하지 못한 항목:\n- Other의 역할 (검색 근거 부족)\n질문 전체가 해결된 것은 아닙니다.';
const flatten = node => [node.textContent, ...node.children.map(flatten)].join('\n');

test('partial copy splits confirmed evidence without calling full answer verified', () => {
  const p = ui.plan(text, verification, sources);
  assert.equal(p.kind, 'partial');
  assert.ok(p.confirmed.includes('Tool의 역할: API'));
  assert.ok(!p.confirmed.includes('Other의 역할'));
  assert.match(p.scope, /전체가 해결된 것은 아닙니다/);
});
test('role conflict labels are preserved', () => {
  const p = ui.plan(text, {...verification, missing_items: ['Other의 역할 (원문 값 충돌)']}, sources);
  assert.match(p.missing[0], /원문 값 충돌/);
});
test('failed verification never promotes copied content to confirmed', () => {
  const p = ui.plan(text, {...verification, passed: false}, sources);
  assert.equal(p.kind, 'blocked'); assert.equal(p.confirmed, '');
});
test('model text imitating headings is not recognized as verified source extraction', () => {
  const p = ui.plan(text, {passed: null, method: 'source_attached_semantic_review_needed'}, sources);
  assert.equal(p.kind, 'review'); assert.equal(p.confirmed, '');
});
test('missing sources or unsupported body layout do not get a confirmed heading', () => {
  assert.equal(ui.plan(text, verification, []).confirmed, '');
  assert.equal(ui.plan('그냥 답변', verification, sources).confirmed, '');
  assert.equal(ui.plan('검색된 Wiki 원문에서 확인한 항목:\n응답 중단', verification, sources).confirmed, '');
});
test('full copy still states limitations instead of universal accuracy', () => {
  const p = ui.plan('검색된 Wiki 원문에서 확인한 항목:\n- Tool: API', {...verification, passed: true, missing_items: []}, sources);
  assert.equal(p.kind, 'copied'); assert.match(p.scope, /보장하지 않습니다/);
});
test('numeric success is not labeled full semantic verification', () => {
  const p = ui.plan('숫자 답변', {passed: true, method: 'numeric_subset_semantic_review_needed'}, sources);
  assert.equal(p.kind, 'review'); assert.match(p.scope, /전체의 의미 정확성을 보장하지 않습니다/);
});
test('missing arrays and malformed issues cannot crash the renderer', () => {
  const out = new Element('div');
  ui.render(out, '안내', {passed: false, issues: null, missing_items: 'not-an-array'}, null);
  assert.match(flatten(out), /답변 보류/);
});
test('HTML and untrusted sources are always text and raw answer remains accessible', () => {
  const out = new Element('div');
  ui.render(out, '<img src=x onerror=alert(1)>', {passed: null}, [{source: '<script>', heading: '제목'}]);
  assert.match(flatten(out), /<img/);
  assert.match(flatten(out), /전체 응답 원문 보기/);
  assert.equal(out.children.filter(x => x.tag === 'img' || x.tag === 'script').length, 0);
});
test('CRLF source copy is supported and full original stays unmodified', () => {
  const raw = text.replace(/\n/g, '\r\n'); const out = new Element('div');
  ui.render(out, raw, verification, sources);
  assert.equal(out.children.at(-1).children.at(-1).textContent, raw);
  assert.match(flatten(out), /원문에서 확인한 내용/);
});
test('only Korean UI labels are present in the presentation script', () => {
  assert.ok(!/[\u3040-\u30ff]/u.test(script));
});

const noEvidence = '요청한 판단을 뒷받침하는 명시적 근거를 확인하지 못했습니다.\n\n기존 속도표로 USB 이전 후 결과를 보장하지 않습니다.\n\n확인하지 못한 항목:\n- Other의 역할 (검색 근거 부족)\n확인한 항목만 답했으며 질문 전체가 해결된 것은 아닙니다.';
test('no copied facts gets an insufficient-evidence label, not a partial answer', () => {
  const p = ui.plan(noEvidence, verification, []);
  assert.equal(p.kind, 'insufficient'); assert.equal(p.confirmed, '');
  assert.match(p.label, /근거 부족/); assert.ok(!p.label.includes('부분 답변'));
  assert.match(p.scope, /확인된 원문 항목이 없습니다/);
});
test('known missing footer appears once outside collapsed details; raw is preserved', () => {
  const out = new Element('div');
  ui.render(out, noEvidence, verification, []);
  const visible = out.children.filter(x => x.tag !== 'details').map(flatten).join('\n');
  assert.equal(visible.split(missing[0]).length - 1, 1);
  assert.ok(!visible.includes('확인하지 못한 항목:'));
  assert.match(visible, /USB 이전 후/);
  assert.equal(out.children.at(-1).children.at(-1).textContent, noEvidence);
});
test('unrecognized footer prose must not be silently hidden', () => {
  const raw = noEvidence + '\n추가 경고를 꼭 읽어주세요.';
  assert.equal(ui.plan(raw, verification, []).displayText, raw);
});
test('missing citations cannot promote a heading imitation to confirmed facts', () => {
  const p = ui.plan(text, verification, []);
  assert.equal(p.kind, 'insufficient'); assert.equal(p.confirmed, '');
});
test('failed verification keeps its blocked label and full explanation', () => {
  const p = ui.plan(noEvidence, {...verification, passed: false}, []);
  assert.equal(p.kind, 'blocked'); assert.equal(p.displayText, noEvidence);
});
