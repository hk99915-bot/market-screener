// STUDY 모듈 렌더 스모크: 빌드된 index.html 의 스크립트를 브라우저처럼 한 스코프로 이어 eduModule 을 실제 모듈로 실행 (10/17 멈춤 재발 방지)
const fs = require('fs');
const H = fs.readFileSync('index.html', 'utf8');
const js = (H.match(/<script>([\s\S]*?)<\/script>/g) || []).map(b => b.replace(/<\/?script>/g, '')).join('\n;\n');
// esc 가 의존하는 한 줄 헬퍼(10/27 front 214dc7ed: noNuna)도 같이 — 없으면 esc 줄만
const line = k => { const i = js.indexOf(k); return i < 0 ? '' : js.slice(i, js.indexOf('\n', i)); };
const escLine = line('const noNuna=s=>') + '\n' + line('const esc=s=>');
const t = js.slice(js.indexOf('function citeFmt('), js.indexOf('function eduView('));
const EDONE = {}; const EDQ = []; const eduChips = () => ''; const escA = s => String(s);
eval(escLine + '\n' + t + '\n;globalThis.eduModule=eduModule;');
let n = 0;
for (const f of fs.readdirSync('content/study').filter(f => f.startsWith('track_'))) {
  const S = JSON.parse(fs.readFileSync('content/study/' + f, 'utf8'));
  for (const m of (S.modules || S)) { eduModule(m); n++; }
}
console.log('rendered', n);
