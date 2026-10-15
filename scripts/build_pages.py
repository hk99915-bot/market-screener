"""apps-script/Index.html → 루트 index.html (GitHub Pages 용). google.script.run 을 저장소 파일 fetch 로 대체하는 심을 넣는다.
화면은 apps-script/Index.html 에서 고치고 `python scripts/build_pages.py` 로 다시 생성."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHIM = """<script>
/* GitHub Pages 용: Apps Script 의 google.script.run 을 같은 저장소 파일 fetch 로 대체 */
(function(){
  const get = p => fetch(p + '?t=' + Date.now(), {cache: 'no-store'}).then(r => {
    if (!r.ok) throw new Error('HTTP ' + r.status + ' (' + p + ')'); return r.text(); });
  const api = {
    getData: () => get('reports/dashboard.json').then(t => JSON.parse(t)),
    getDetail: m => get('reports/detail_' + m + '.json'),
    getStock: (m, s) => get('reports/detail/' + m + '/' + encodeURIComponent(s) + '.json'),
    getMarkdown: n => get('reports/' + n + '.md').catch(() => ''),
    // live.json 은 자주 바뀌므로 Pages 재배포를 기다리지 않고 raw 에서 직접 (CDN 캐시 최대 5분)
    getLive: () => fetch('https://raw.githubusercontent.com/hk99915-bot/market-screener/main/reports/live.json?t=' + Date.now()).then(r => r.ok ? r.text() : get('reports/live.json')).catch(() => get('reports/live.json').catch(() => '')),
    getResearch: () => get('reports/research.json'),
    getDisclosures: () => get('reports/disclosures.json'),
    getMacroSeries: () => get('reports/macro_series.json'),
    getAnalysts: () => get('reports/analysts.json'),
    getMomentum: m => get('reports/momentum_' + m + '.json'),
    getMomentumBt: () => get('reports/momentum_bt.json'),
    getDaily: () => get('reports/daily_brief.json'),
  };
  function runner(ok, fail) {
    const r = { withSuccessHandler: f => runner(f, fail), withFailureHandler: f => runner(ok, f) };
    for (const k in api) r[k] = (...a) => api[k](...a).then(v => ok && ok(v), e => fail ? fail(e) : console.error(e));
    return r;
  }
  window.google = { script: { run: runner() } };
})();
</script>
"""

src = (ROOT / "apps-script" / "Index.html").read_text(encoding="utf-8")
assert src.lstrip().lower().startswith("<!doctype html>")
out = src.replace("<title>MARKET TERMINAL</title>", "<title>MARKET TERMINAL</title>\n" + SHIM, 1)
out = out.replace("<!doctype html>", "<!doctype html>\n<!-- 자동 생성: scripts/build_pages.py 로 apps-script/Index.html 에서 만든다. 직접 고치지 말 것 -->", 1)
(ROOT / "index.html").write_text(out, encoding="utf-8")
print("index.html 생성")
