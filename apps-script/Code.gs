/**
 * Market Terminal — Apps Script 웹앱
 * GitHub private 저장소의 reports/dashboard.json 을 읽어 터미널 스타일로 표시.
 *
 * 설치
 * 1) script.google.com → 새 프로젝트 → Code.gs 와 Index.html 붙여넣기
 * 2) 프로젝트 설정 → 스크립트 속성:
 *      GITHUB_TOKEN : GitHub Fine-grained PAT (저장소 market-screener, Contents: Read-only)
 *      GITHUB_REPO  : hk99915-bot/market-screener
 * 3) 배포 → 새 배포 → 웹 앱 → 실행: 나 / 액세스: 나만 → 배포 → URL 열기
 */

function doGet() {
  return HtmlService.createHtmlOutputFromFile('Index')
    .setTitle('MARKET TERMINAL')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
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

function getStockIndex(m) { return raw_(`reports/detail/${m}/_index.json`); }
