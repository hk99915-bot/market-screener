/**
 * Market Screener 예약 실행기 (GitHub 예약 실행이 몇 시간씩 밀리거나 빠져서 대신 사용)
 *
 * 5분마다 tick() 이 돌면서, 아래 시간표에서 "지금 시각 ~ 20분 전" 사이에 걸린 작업을
 * GitHub Actions 에 workflow_dispatch 로 요청한다. 같은 날 같은 작업은 한 번만.
 *
 * 설치 (1회)
 * 0) 반드시 개인 구글 계정에서 (회사 계정 금지 — 토큰이 들어감)
 * 1) GitHub → Settings → Developer settings → Fine-grained tokens → Generate new token
 *    - Repository access: Only select → hk99915-bot/market-screener
 *    - Permissions: Actions = Read and write (그 외 없음)
 * 2) script.google.com → 새 프로젝트 → 이 코드 붙여넣기
 * 3) 프로젝트 설정 → 스크립트 속성 → GH_TOKEN = 위 토큰
 * 4) 편집기에서 함수 install 선택 → 실행 (권한 허용) → 끝. 이후 5분마다 자동 실행
 *    확인: 함수 tickTest 실행 → 로그에 오늘 시간표와 실행 여부가 찍힘
 * 갱신 (코드만 바뀐 경우): 기존 프로젝트에서 전체 선택 → 이 파일로 교체 → 저장 → tickTest 실행.
 *    install 은 다시 안 해도 됨(트리거는 함수 이름 tick 으로 걸려 있음). 체크리스트: docs/schedule_table.md 맨 위
 * 이중화(10/21): 노트북 tools/dispatch/dispatch.py 가 이 SCHEDULE 표를 그대로 읽어 같은 슬롯을 +2분부터 보낸다(GAS 가 이미 보냈으면 안 보냄).
 *    둘 다 보내도 scripts/slot_guard.py 가 먼저 만들어진 run 만 실행. 표를 바꾸면 노트북은 git pull 만 하면 된다.
 */
const REPO = 'hk99915-bot/market-screener';
const WEEKDAY = [1, 2, 3, 4, 5];        // 월~금 (KST)
const US_DAYS = [2, 3, 4, 5, 6];        // 화~토 새벽 (미장 마감 기준)
const EVERY = [0, 1, 2, 3, 4, 5, 6];

// [KST 시각, 워크플로 파일, inputs, 요일]
const SCHEDULE = [
  ['02:00', 'backfill.yml', { market: 'ALL', commit: 'true' }, EVERY],
  ['03:30', 'fin.yml', { commit: 'true' }, EVERY],
  ['03:52', 'briefing.yml', { mode: 'intraday_us', commit: 'true' }, US_DAYS],
  // ['07:10', 'briefing.yml', { mode: 'valuation' }, US_DAYS],      // 반도체 밸류에이션 바스켓 — 06:52 미장 마감 스크리너 뒤(10/17 순서 수정). GitHub cron(10 22 UTC)만 사용, 백업 예약은 켜지 않음 (텔레그램 중복 방지)
  ['06:52', 'briefing.yml', { mode: 'screen_us', commit: 'true' }, US_DAYS],
  ['08:40', 'live.yml', { commit: 'true' }, WEEKDAY],
  ['08:50', 'briefing.yml', { mode: 'premarket_kr', commit: 'true' }, WEEKDAY],
  ['10:30', 'briefing.yml', { mode: 'intraday_kr', commit: 'true' }, WEEKDAY],
  ['11:35', 'briefing.yml', { mode: 'committee', commit: 'true' }, WEEKDAY],          // 점심 운용회의 (겸이 점심 11:30~12:50)
  ['13:30', 'briefing.yml', { mode: 'intraday_kr', commit: 'true' }, WEEKDAY],
  ['14:15', 'briefing.yml', { mode: 'committee', commit: 'true' }, WEEKDAY],          // '판정 전' 운용회의 (장중 세션)
  ['14:25', 'briefing.yml', { mode: 'rebound', commit: 'true' }, WEEKDAY],            // 반등일 판정 알림 (코스피 vs 전일 종가 +0.5%, 비율만)
  ['15:05', 'briefing.yml', { mode: 'crash_check', commit: 'true' }, WEEKDAY],        // 급락일 종가 매수 신호 (코스피 장중 ≤ −4.5% → 15:20 동시호가 안내, 비율만)
  ['15:45', 'briefing.yml', { mode: 'close_kr', commit: 'true' }, WEEKDAY],
  ['16:20', 'screener.yml', { market: 'KR', no_send: 'false', commit: 'true' }, WEEKDAY],
  ['16:40', 'deriv_hist.yml', { task: 'run', days: '0', commit: 'true' }, WEEKDAY],   // 수급·파생 일별 이력 (중복 실행돼도 같은 날짜 덮어쓰기라 무해)
  ['19:10', 'briefing.yml', { mode: 'reports', commit: 'true' }, WEEKDAY],
  ['20:52', 'briefing.yml', { mode: 'premarket_us', commit: 'true' }, WEEKDAY],
  ['21:52', 'briefing.yml', { mode: 'premarket_us', commit: 'true' }, WEEKDAY],
  ['23:20', 'live.yml', { commit: 'true' }, WEEKDAY],   // 미장 루프 시작 — 겨울(EST, 11/02~) 23:20 · 여름(EDT, 3월 둘째 일요일~) 22:20 로 되돌림(보드 live-us-dst-march)
  ['22:52', 'briefing.yml', { mode: 'intraday_us', commit: 'true' }, WEEKDAY],
];
// 결정 C (docs/schedule_table.md): 이 표의 슬롯은 GAS 가 '주 실행 주체'. 같은 시각 GitHub cron 은 대기(fallback) —
// scripts/slot_guard.py 가 예정 +12분까지 기다렸다가 이 dispatch 가 있으면 건너뛴다. 그래서 WINDOW_MIN 은 12 보다 작아야 한다.
// commit: 'true' — 워크플로는 수동 실행을 기본 읽기 전용(커밋 안 함)으로 돌린다. 예약 실행기만 커밋 권한을 명시.
// 슬롯을 더하거나 빼면 tests/test_schedule_single.py 가 워크플로 쪽 가드와 맞는지 검사한다.

const SCHEDULER_VERSION = '2026-10-30 겨울시간 · 이중화';   // tickTest 첫 줄에 찍힘 — 붙여넣기 확인용
const WINDOW_MIN = 10;   // 예정 시각 이후 이 시간 안에만 실행 (cron 대기 12분보다 짧게 — 늦게 깨어나도 몰아서 보내지 않음)

function kstNow_() {
  const s = Utilities.formatDate(new Date(), 'Asia/Seoul', 'yyyy-MM-dd HH:mm u');
  const [d, hm, u] = s.split(' ');
  const [h, m] = hm.split(':').map(Number);
  return { date: d, min: h * 60 + m, dow: Number(u) % 7 };   // u: 1=월 … 7=일 → 0=일
}

function dispatch_(wf, inputs) {
  const token = PropertiesService.getScriptProperties().getProperty('GH_TOKEN');
  if (!token) throw new Error('GH_TOKEN 스크립트 속성이 없습니다');
  const res = UrlFetchApp.fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${wf}/dispatches`, {
    method: 'post', contentType: 'application/json', muteHttpExceptions: true,
    headers: { Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json' },
    payload: JSON.stringify({ ref: 'main', inputs: inputs }),
  });
  return res.getResponseCode();   // 204 = 성공
}

function tick() {
  const now = kstNow_();
  const props = PropertiesService.getScriptProperties();
  for (const [t, wf, inputs, days] of SCHEDULE) {
    if (days.indexOf(now.dow) < 0) continue;
    const [h, m] = t.split(':').map(Number);
    const at = h * 60 + m;
    if (now.min < at || now.min >= at + WINDOW_MIN) continue;
    const key = `done|${now.date}|${t}|${wf}|${JSON.stringify(inputs)}`;
    if (props.getProperty(key)) continue;
    const code = dispatch_(wf, inputs);
    console.log(`${now.date} ${t} ${wf} ${JSON.stringify(inputs)} → ${code}`);
    if (code === 204) props.setProperty(key, '1');
  }
  cleanup_(props, now.date);
}

function cleanup_(props, today) {
  const all = props.getProperties();
  for (const k in all) if (k.startsWith('done|') && k.split('|')[1] < today) props.deleteProperty(k);
}

function install() {
  // tick 트리거만 지우고 다시 만든다 — 같은 프로젝트의 tgPoll(TelegramHook.gs) 트리거는 건드리지 않는다(10/21: 예전엔 전부 지워 텔레그램 버튼이 죽음)
  ScriptApp.getProjectTriggers().forEach(t => { if (t.getHandlerFunction() === 'tick') ScriptApp.deleteTrigger(t); });
  ScriptApp.newTrigger('tick').timeBased().everyMinutes(5).create();
  console.log('설치 완료: 5분마다 tick 실행 · 트리거 ' + ScriptApp.getProjectTriggers().map(t => t.getHandlerFunction()).join(','));
}

function tickTest() {
  const now = kstNow_();
  console.log(`예약기 버전 ${SCHEDULER_VERSION} · 창 ${WINDOW_MIN}분`);
  console.log(`지금 KST ${now.date} ${Math.floor(now.min / 60)}:${String(now.min % 60).padStart(2, '0')} 요일 ${now.dow}`);
  for (const [t, wf, inputs, days] of SCHEDULE) {
    const key = `done|${now.date}|${t}|${wf}|${JSON.stringify(inputs)}`;
    console.log(`${t} ${wf} ${JSON.stringify(inputs)} 오늘대상=${days.indexOf(now.dow) >= 0} 실행됨=${!!PropertiesService.getScriptProperties().getProperty(key)}`);
  }
}
