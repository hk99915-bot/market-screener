// STUDY 모듈 렌더 스모크: 빌드된 index.html 의 스크립트를 브라우저처럼 한 스코프로 이어 eduModule 을 실제 모듈로 실행 (10/17 멈춤 재발 방지)
const fs = require('fs');
const H = fs.readFileSync('index.html', 'utf8');
const js = (H.match(/<script>([\s\S]*?)<\/script>/g) || []).map(b => b.replace(/<\/?script>/g, '')).join('\n;\n');
const i = js.indexOf('const esc=s=>'); const escLine = js.slice(i, js.indexOf('\n', i));
const t = js.slice(js.indexOf('function citeFmt('), js.indexOf('function eduView('));
const EDONE = {}; const eduChips = () => ''; const escA = s => String(s);
eval(escLine + '\n' + t + '\n;globalThis.eduModule=eduModule;');
let n = 0;
for (const f of fs.readdirSync('content/study').filter(f => f.startsWith('track_'))) {
  const S = JSON.parse(fs.readFileSync('content/study/' + f, 'utf8'));
  for (const m of (S.modules || S)) { eduModule(m); n++; }
}
console.log('rendered', n);
