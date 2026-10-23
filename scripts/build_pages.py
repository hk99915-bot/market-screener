"""apps-script/Index.html → 루트 index.html (GitHub Pages 용). google.script.run 을 저장소 파일 fetch 로 대체하는 심을 넣는다.
화면은 apps-script/Index.html(공용 셸) + apps-script/tab_*.html(탭별) 에서 고치고 `python scripts/build_pages.py` 로 다시 생성.
Index.html 의 `<?!= include('tab_x') ?>` 는 GAS 에서 Code.gs include() 가, 여기서는 resolve_includes() 가 같은 파일 내용으로 바꾼다."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "apps-script"
INCLUDE = re.compile(r"<\?!=\s*include\(\s*['\"]([\w.-]+)['\"]\s*\)\s*\?>")


def resolve_includes(src: str, read=None, _seen: tuple = ()) -> str:
    """`<?!= include('name') ?>` → apps-script/name.html 내용 (GAS HtmlService include 와 같은 결과). 중첩 허용, 순환은 오류.
    read(name) 은 파일 내용을 돌려주는 함수 (기본: apps-script/<name>.html 읽기 — 검사 스크립트는 git 리비전에서 읽을 때 바꿔 쓴다)."""
    if read is None:
        read = lambda n: (SRC_DIR / f"{n}.html").read_text(encoding="utf-8")

    def rep(m: re.Match) -> str:
        name = m.group(1)
        if name in _seen:
            raise RuntimeError(f"include 순환: {' → '.join(_seen + (name,))}")
        try:
            body = read(name)
        except FileNotFoundError:
            raise FileNotFoundError(f"include('{name}') 대상 apps-script/{name}.html 없음") from None
        return resolve_includes(body, read, _seen + (name,))
    return INCLUDE.sub(rep, src)


def includes_of(src: str) -> list[str]:
    return INCLUDE.findall(src)


def screen_source(read=None) -> str:
    """셸 + 탭 파일을 합친 '한 장짜리' 원본 (옛 단일 Index.html 과 같은 꼴)."""
    shell = (SRC_DIR / "Index.html").read_text(encoding="utf-8") if read is None else read("Index")
    return resolve_includes(shell, read)


def build(src: str) -> str:
    assert src.lstrip().lower().startswith("<!doctype html>")
    assert not INCLUDE.search(src), "include 가 남아 있음"
    out = src.replace("<title>MARKET TERMINAL</title>", "<title>MARKET TERMINAL</title>\n" + SHIM, 1)
    return out.replace("<!doctype html>", "<!doctype html>\n<!-- 자동 생성: scripts/build_pages.py 로 apps-script/Index.html + tab_*.html 에서 만든다. 직접 고치지 말 것 -->", 1)

SHIM = """<script>
/* GitHub Pages 용: Apps Script 의 google.script.run 을 같은 저장소 파일 fetch 로 대체 */
(function(){
  const get = p => fetch(p + '?t=' + Date.now(), {cache: 'no-store'}).then(r => {
    if (!r.ok) throw new Error('HTTP ' + r.status + ' (' + p + ')'); return r.text(); });
  // 자주 바뀌는 시세·운영 파일은 Pages 재배포를 기다리지 않고 raw 에서 직접 (CDN 캐시 최대 5분). pages.yml paths-ignore 와 짝 (감사 10/21 #3)
  const raw = p => fetch('https://raw.githubusercontent.com/hk99915-bot/market-screener/main/' + p + '?t=' + Date.now()).then(r => r.ok ? r.text() : get(p)).catch(() => get(p));
  const api = {
    getData: () => get('reports/dashboard.json').then(t => JSON.parse(t)),
    getStock: (m, s) => get('reports/detail/' + m + '/' + encodeURIComponent(s) + '.json'),
    getMarkdown: n => get('reports/' + n + '.md').catch(() => ''),
    getLive: () => raw('reports/live.json').catch(() => ''),
    getResearch: () => get('reports/research.json'),
    getDisclosures: () => get('reports/disclosures.json'),
    getMacroSeries: () => get('reports/macro_series.json'),
    getAnalysts: () => get('reports/analysts.json'),
    getResearchViews: () => get('reports/research_views.json'),
    getResearchSynthesis: () => get('reports/research_synthesis.json'),
    getMomentum: m => get('reports/momentum_' + m + '.json'),
    getMomentumBt: () => get('reports/momentum_bt.json'),
    getDaily: () => get('reports/daily_brief.json'),
    getDailyIndex: () => get('reports/daily_hist/_index.json'),
    getDailyAt: (d) => get('reports/daily_hist/' + d + '.json'),
    getStockIndex: m => get('reports/detail/' + m + '/_index.json'),
    getPortfolios: () => get('reports/portfolios.json'),
    getSignals: () => get('reports/signal_scores.json'),
    getMacroView: () => get('reports/macro_view.json'),
    getCommodities: () => get('reports/commodities.json'),
    getGeopolitics: () => get('reports/views/geopolitics.json'),
    getGeoNews: () => get('reports/geo_news.json'),
    getChainSeries: () => get('reports/chains.json'),
    getEvents: () => raw('reports/events_stats.json'),
    getMacroHist: () => get('reports/macro_hist.json'),
    getStudy: () => get('reports/studies/crash_rebound.json'),
    getLab: () => get('reports/lab.json'),
    getIsaLab: () => get('reports/isa_lab_returns.json'),
    getResearchBoard: () => get('reports/research_board.json'),
    getBoard: () => get('ops/board.json'),
    getTeam: () => raw('ops/team.json'),
    getLocks: () => raw('ops/locks.json'),
    getChangelog: () => get('reports/changelog.json'),
    getOpsDaily: (d) => get('reports/ops/daily/' + d + '.md').catch(() => ''),
    getOpsRuns: () => get('reports/ops/runs.json'),
    getHealth: () => get('reports/health.json'),
    getBonds: () => get('reports/bonds.json'),
    getJapan: () => get('reports/japan.json'),
    getStudyGuide: () => get('content/study.json'),
    getDerivs: () => get('reports/derivs.json'),
    getDerivHist: () => get('data/deriv/daily.csv'),
    getDerivSignals: () => get('reports/studies/derivs_signals.json'),
    getGammaStudy: () => get('reports/studies/gamma_regime.json'),
    getMacroReleases: () => get('reports/macro_releases.json'),
    getEnglishLatest: () => get('reports/english/latest.json'),
    getEnglishAt: (d) => get('reports/english/' + d + '.json'),
    getEnglishIndex: () => get('reports/english/index.json'),
    getCalendar: () => get('reports/calendar.json'),
    getPeers: (mk) => get('reports/peers_' + mk + '.json'),
    getDecisions: () => get('reports/decisions.json'),
    getCommittee: () => get('reports/committee.json'),
    getCommitteeUS: () => get('reports/committee_us.json'),
    getArchIndex: (k) => get('reports/archive/' + k + '/_index.json'),
    getArchAt: (k, d) => get('reports/archive/' + k + '/' + d + '.json'),
    getChains: () => get('reports/chains_view.json'),
    getViews: () => get('reports/views.json'),
    getValuation: () => get('reports/valuation.json'),
    getDotplot: () => get('reports/dotplot.json'),
    getFreshness: () => get('reports/freshness.json'),
    getAccum: () => get('reports/accum.json'),
    getUsAccum: () => get('reports/us_accum.json'),
    getCooldown: () => get('ops/cooldown.json'),
    getRenego: () => get('ops/renego.json'),
    // 🔒 비공개 사담방 — 공개 Pages 엔 토큰이 없다. 10/23 겸이 선택: "이 폰에만 토큰 저장" → 이 기기 브라우저 localStorage('pbPrivTok')에만 두고
    //    GitHub contents API 로 직접 읽는다(저장소·채팅·서버로 안 감). 권장 토큰: fine-grained · pb-private 하나 · Contents 읽기 전용 · 만료 있음.
    getPrivate: (name) => {
      let tok = ''; try { tok = localStorage.getItem('pbPrivTok') || ''; } catch (e) {}
      if (name !== 'chat') return Promise.resolve(JSON.stringify({ _err: '허용 안 된 이름' }));
      if (!tok) return Promise.resolve(JSON.stringify({ _need_token: true }));
      return fetch('https://api.github.com/repos/hk99915-bot/pb-private/contents/chat/private_chat.json?ref=main', {
        headers: { Authorization: 'Bearer ' + tok, Accept: 'application/vnd.github.raw', 'X-GitHub-Api-Version': '2022-11-28' }, cache: 'no-store',
      }).then(r => r.ok ? r.text() : JSON.stringify({ _err: 'GitHub ' + r.status + (r.status === 401 || r.status === 404 ? ' — 토큰 만료·권한(pb-private Contents 읽기) 확인' : ''), _need_token: r.status === 401 }))
        .catch(e => JSON.stringify({ _err: String(e).slice(0, 100) }));
    },
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


def main() -> int:
    src = screen_source()
    (ROOT / "index.html").write_text(build(src), encoding="utf-8")
    print(f"index.html 생성 (include {len(includes_of((SRC_DIR / 'Index.html').read_text(encoding='utf-8')))}개 인라인)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
