/**
 * Market Terminal — Apps Script 웹앱
 * GitHub private 저장소의 reports/dashboard.json 을 읽어 터미널 스타일로 표시.
 *
 * 설치
 * 1) script.google.com → 새 프로젝트 → Code.gs 붙여넣기. (10/22~ 화면 HTML 은 GitHub 에서 직접 읽으므로 붙여넣기 불필요 —
 *    아래 HTML 파일은 GitHub 접근 실패 때 대체용으로만 쓰인다.) 예전 방식:
 *      Index.html(공용 셸) + apps-script/tab_*.html 전부 (파일 이름은 확장자 없이 tab_daily 처럼; 목록은 ops/README.md)
 *    Index.html 의 <?!= include('tab_daily') ?> 를 아래 include() 가 같은 이름의 HTML 파일 내용으로 바꾼다.
 * 2) 프로젝트 설정 → 스크립트 속성:
 *      GITHUB_TOKEN : GitHub Fine-grained PAT (저장소 market-screener, Contents: Read-only)
 *      GITHUB_REPO  : hk99915-bot/market-screener
 * 3) 배포 → 새 배포 → 웹 앱 → 실행: 나 / 액세스: 나만 → 배포 → URL 열기
 */

function doGet() {
  // 템플릿으로 평가해야 <?!= include('tab_x') ?> 가 풀린다 (createHtmlOutputFromFile 은 그대로 출력)
  // 10/22 겸이 "업데이트될 때마다 gas 업데이트하는 게 귀찮은데": 화면(Index·tab_*)은 GitHub main 의 apps-script/ 에서 직접 읽는다
  // → HTML 붙여넣기·새 버전 배포 불필요. GitHub 실패 시 이 프로젝트 안의 같은 이름 파일로 대체(예전 방식).
  return HtmlService.createTemplate(html_('Index')).evaluate()
    .setTitle('MARKET TERMINAL')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

// 탭 파일 끼워 넣기 — Index.html 의 <?!= include('tab_daily') ?> 가 이 함수를 부른다. 파일이 없으면 GAS 가 오류를 낸다 (이름 확인).
function include(name) {
  return html_(name);
}

// apps-script/<name>.html — GitHub(5분 캐시) 우선, 실패하면 GAS 프로젝트 안 파일. 캐시는 키당 100KB 제한이라 90KB 조각으로 나눠 저장.
function html_(name) {
  const cache = CacheService.getScriptCache(), key = 'html2:' + name;
  try {
    const n = Number(cache.get(key + ':n') || 0);
    if (n > 0) {
      const parts = cache.getAll(Array.from({ length: n }, (_, i) => key + ':' + i));
      const txt = Array.from({ length: n }, (_, i) => parts[key + ':' + i]).join('');
      if (txt && Array.from({ length: n }, (_, i) => parts[key + ':' + i]).every(x => x != null)) return txt;
    }
  } catch (e) {}
  try {
    const txt = raw_('apps-script/' + name + '.html');
    try {
      const CH = 90000, n = Math.ceil(txt.length / CH), o = {};
      for (let i = 0; i < n; i++) o[key + ':' + i] = txt.slice(i * CH, (i + 1) * CH);
      o[key + ':n'] = String(n);
      cache.putAll(o, 300);
    } catch (e) {}
    return txt;
  } catch (e) {
    return HtmlService.createHtmlOutputFromFile(name).getContent();
  }
}

function raw_(path) {
  // raw.githubusercontent.com 은 1MB 제한이 없음 (detail_*.json 은 1MB 넘음)
  const props = PropertiesService.getScriptProperties();
  const token = props.getProperty('GITHUB_TOKEN');
  const repo = props.getProperty('GITHUB_REPO') || 'hk99915-bot/market-screener';
  if (!token) throw new Error('GITHUB_TOKEN 스크립트 속성이 없습니다');
  const res = UrlFetchApp.fetch(`https://raw.githubusercontent.com/${repo}/main/${path}`, {
    muteHttpExceptions: true, headers: { Authorization: 'token ' + token },
  });
  if (res.getResponseCode() !== 200) {
    throw new Error(`GitHub ${res.getResponseCode()} (${path}): ${res.getContentText().slice(0, 150)}`);
  }
  return res.getContentText();
}

function getData() { return JSON.parse(raw_('reports/dashboard.json')); }

function getMarkdown(name) {
  try { return raw_(`reports/${name}.md`); } catch (e) { return ''; }
}

function getLive() {
  try { return raw_('reports/live.json'); } catch (e) { return ''; }
}

function getResearch() { return raw_('reports/research.json'); }

function getDisclosures() { return raw_('reports/disclosures.json'); }

function getStock(market, sym) { return raw_(`reports/detail/${market}/${sym}.json`); }

function getMacroSeries() { return raw_('reports/macro_series.json'); }

function getAnalysts() { return raw_('reports/analysts.json'); }
function getResearchViews() { return raw_('reports/research_views.json'); }   // 비종목 리포트 (RESEARCH › 리서치 kind 필터)
function getResearchSynthesis() { return raw_('reports/research_synthesis.json'); }   // 리서치 종합 (RESEARCH 맨 위, 애널 research-synthesis)

function getMomentum(m) { return raw_(`reports/momentum_${m}.json`); }
function getMomentumBt() { return raw_('reports/momentum_bt.json'); }

function getDaily() { return raw_('reports/daily_brief.json'); }
function getDailyIndex() { return raw_('reports/daily_hist/_index.json'); }
function getDailyAt(d) { return raw_('reports/daily_hist/' + d + '.json'); }

function getStockIndex(m) { return raw_(`reports/detail/${m}/_index.json`); }

function getPortfolios() { return raw_('reports/portfolios.json'); }
function getSignals() { return raw_('reports/signal_scores.json'); }
function getMacroView() { return raw_('reports/macro_view.json'); }
function getChainSeries() { return raw_('reports/chains.json'); }
function getEvents() { return raw_('reports/events_stats.json'); }
function getMacroHist() { return raw_('reports/macro_hist.json'); }
function getStudy() { return raw_('reports/studies/crash_rebound.json'); }
function getLab() { return raw_('reports/lab.json'); }
function getIsaLab() { return raw_('reports/isa_lab_returns.json'); }   // QUANT › ISA 실험실 (screener/isa_lab.py)
function getResearchBoard() { return raw_('reports/research_board.json'); }   // QUANT › 연구 보드 (scripts/research_board.py ← ops/research_pipeline.json)
// SYSTEM 탭 (운영): 작업 보드·잠금·변경 이력·작업내역 보고·워크플로 실행 통계·자가점검
function getBoard() { return raw_('ops/board.json'); }
function getTeam() { return raw_('ops/team.json'); }
function getLocks() { return raw_('ops/locks.json'); }
function getChangelog() { return raw_('reports/changelog.json'); }
function getOpsDaily(d) { try { return raw_('reports/ops/daily/' + d + '.md'); } catch (e) { return ''; } }
function getOpsRuns() { return raw_('reports/ops/runs.json'); }
function getHealth() { return raw_('reports/health.json'); }
function getBonds() { return raw_('reports/bonds.json'); }
function getJapan() { return raw_('reports/japan.json'); }
function getStudyGuide() { return raw_('content/study.json'); }
function getDerivs() { return raw_('reports/derivs.json'); }
function getDerivHist() { return raw_('data/deriv/daily.csv'); }
function getDerivSignals() { return raw_('reports/studies/derivs_signals.json'); }
function getGammaStudy() { return raw_('reports/studies/gamma_regime.json'); }
function getMacroReleases() { return raw_('reports/macro_releases.json'); }
function getEnglishLatest() { return raw_('reports/english/latest.json'); }
function getEnglishAt(d) { return raw_('reports/english/' + d + '.json'); }
function getEnglishIndex() { return raw_('reports/english/index.json'); }
function getCalendar() { return raw_('reports/calendar.json'); }
function getDecisions() { return raw_('reports/decisions.json'); }
function getCommittee() { return raw_('reports/committee.json'); }
function getCommitteeUS() { return raw_('reports/committee_us.json'); }
function getArchIndex(k) { return raw_('reports/archive/' + k + '/_index.json'); }
function getArchAt(k, d) { return raw_('reports/archive/' + k + '/' + d + '.json'); }
function getPeers(mk) { return raw_('reports/peers_' + (mk === 'US' ? 'US' : 'KR') + '.json'); }
function getChains() { return raw_('reports/chains_view.json'); }
function getViews() { return raw_('reports/views.json'); }
function getValuation() { return raw_('reports/valuation.json'); }   // 반도체 밸류에이션 바스켓 (RESEARCH 탭)
function getDotplot() { return raw_('reports/dotplot.json'); }   // 기명 점도표 (운용회의 카드 점 띠)
function getFreshness() { return raw_('reports/freshness.json'); }   // 데이터 신선도 배지 (상단 헤더, 10/17 재발방지대책)
function getAccum() { return raw_('reports/accum.json'); }   // KR 매집 스캔 (MARKET › ACCUM, screener/accum.py 18:37) — contracts.py 등록
function getUsAccum() { return raw_('reports/us_accum.json'); }   // US 매집 흔적 (screener/us_accum.py) — contracts.py 등록
function getCooldown() { return raw_('ops/cooldown.json'); }   // 결재 #14 포상·장외 매도 시각 (모의 베팅 30분 쿨다운 카운트다운)
function getRenego() { return raw_('ops/renego.json'); }   // 재협상 카운터 (규칙 id·날짜·횟수만) — 주문표 ⛔ '재협상 2회째' + 사유 칸
// 🔒 비공개 사담방 (10/23 겸이 "비공개사담방") — pb-private 의 허용 목록 파일만 읽는다. 스크립트 속성 PRIVATE_TOKEN(pb-private Contents 읽기 전용 PAT) 없으면 빈 문자열.
function getPrivate(name) {
  const OK = { chat: 'chat/private_chat.json' };
  const path = OK[name];
  const token = PropertiesService.getScriptProperties().getProperty('PRIVATE_TOKEN');
  if (!path) return JSON.stringify({ _err: '허용 안 된 이름' });
  if (!token) return JSON.stringify({ _err: 'PRIVATE_TOKEN 스크립트 속성 없음(이름 철자 확인)' });
  try {
    const res = UrlFetchApp.fetch('https://raw.githubusercontent.com/hk99915-bot/pb-private/main/' + path, {
      muteHttpExceptions: true, headers: { Authorization: 'token ' + token },
    });
    const c = res.getResponseCode();
    if (c === 200) return res.getContentText();
    return JSON.stringify({ _err: 'GitHub ' + c + (c === 404 || c === 401 ? ' — 토큰 저장소 범위(pb-private)·Contents 읽기 권한·만료 확인' : '') });
  } catch (e) { return JSON.stringify({ _err: String(e).slice(0, 120) }); }
}
