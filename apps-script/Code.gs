/**
 * Market Terminal — Apps Script 웹앱
 * GitHub private 저장소의 reports/dashboard.json 을 읽어 터미널 스타일로 표시.
 *
 * 설치
 * 1) script.google.com → 새 프로젝트 → Code.gs 붙여넣기, 그리고 HTML 파일을 하나씩 만들어 붙여넣기:
 *      Index.html(공용 셸) + apps-script/tab_*.html 전부 (파일 이름은 확장자 없이 tab_daily 처럼; 목록은 ops/README.md)
 *    Index.html 의 <?!= include('tab_daily') ?> 를 아래 include() 가 같은 이름의 HTML 파일 내용으로 바꾼다.
 * 2) 프로젝트 설정 → 스크립트 속성:
 *      GITHUB_TOKEN : GitHub Fine-grained PAT (저장소 market-screener, Contents: Read-only)
 *      GITHUB_REPO  : hk99915-bot/market-screener
 * 3) 배포 → 새 배포 → 웹 앱 → 실행: 나 / 액세스: 나만 → 배포 → URL 열기
 */

function doGet() {
  // 템플릿으로 평가해야 <?!= include('tab_x') ?> 가 풀린다 (createHtmlOutputFromFile 은 그대로 출력)
  return HtmlService.createTemplateFromFile('Index').evaluate()
    .setTitle('MARKET TERMINAL')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

// 탭 파일 끼워 넣기 — Index.html 의 <?!= include('tab_daily') ?> 가 이 함수를 부른다. 파일이 없으면 GAS 가 오류를 낸다 (이름 확인).
function include(name) {
  return HtmlService.createHtmlOutputFromFile(name).getContent();
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

function getDetail(market) {
  // 종목 상세 묶음 (KR | US). 1MB 안팎이라 브라우저에 한 번만 내려보내고 클라이언트가 캐시.
  return raw_(`reports/detail_${market}.json`);
}

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
