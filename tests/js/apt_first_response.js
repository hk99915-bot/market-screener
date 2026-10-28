// 인적성 채점 사전 커밋(req-dev-826c4bf0): 첫 응답 고정 · 고른 보기 c 저장 · 응답 전 해설 숨김 · 내보내기 6번째 칸
const fs = require('fs');
const H = fs.readFileSync('apps-script/tab_study.html', 'utf8');
const cut = (a, b) => H.slice(H.indexOf(a), H.indexOf(b));
const code = cut('function aptItem(', 'function aptTally(') + '\n' + cut('function eduSyncPayload(', 'function eduSync(){');
const esc = s => String(s), escA = s => String(s), eduKst = () => '2026-10-28', eduPut = () => {};
const EDONE = {}, ENGS = [], OPS = [], EDQ = []; let APTS = {}, APTT = null; const aptTally = () => {};
const els = [];
const mk = (attrs) => ({ dataset: attrs, style: {}, disabled: false, onclick: null, open: false, closest() { return card; }, querySelector() { return det; } });
const det = mk({}); det.style.display = 'none';
const card = det;
const btns = [0, 1, 2].map(i => mk({ ch: 'N1', i: String(i) }));
const doc = { querySelectorAll: s => (s.includes('data-ch') ? btns : []), querySelector: () => null, body: { contains: () => true } };
global.document = doc; global.window = global;
eval(code + ';globalThis.aptItem=aptItem;globalThis.aptBind=aptBind;globalThis.eduSyncPayload=eduSyncPayload;');
const assert = require('assert');
const x = { id: 'N1', q: 'q', choices: ['a', 'b', 'c'], a: 1, exp: 'e' };
// ③ 응답 전 해설 details 숨김, 응답 뒤엔 열림
assert(/<details[^>]*display:none/.test(aptItem(x, 'N1')), 'details hidden before answer');
APTS = { N1: { ok: 1, t: null, c: 1 } };
assert(!/display:none/.test(aptItem(x, 'N1').match(/<details[^>]*>/)[0]), 'details shown after answer');
APTS = {};
aptBind([[x, 'N1']]);
// ① 첫 응답 고정
btns[0].onclick();
assert.deepStrictEqual([APTS.N1.ok, APTS.N1.c], [false, 0]);
assert.strictEqual(det.style.display, '');
btns[1].onclick();   // 재클릭(정답) — 덮어쓰면 안 됨
assert.deepStrictEqual([APTS.N1.ok, APTS.N1.c], [false, 0], 'first response kept');
assert(btns.every(b => b.disabled), 'buttons locked');
// ② 내보내기 apt 6번째 칸 = c
const row = JSON.parse(eduSyncPayload().body.match(/```json\n([\s\S]*?)\n```/)[1]).apt[0];
assert.strictEqual(row.length, 6); assert.strictEqual(row[5], 0); assert.strictEqual(row[4], 'K');
console.log('apt ok');
