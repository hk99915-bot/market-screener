/**
 * 텔레그램 '내 선택은?' 버튼 웹훅 (보드 tg-pick-buttons, 2026-10-20)
 *
 * 왜: 대결 메시지의 깃허브 이슈 링크(issues/new 프리필)는 폰 텔레그램 내장 브라우저에 깃허브 로그인이 없어
 *     아무것도 안 됐다(pick 이슈 0건). 그래서 버튼을 누르면 → 텔레그램이 이 웹앱(doPost)을 부르고 →
 *     여기서 저장소 주인 토큰으로 'pick YYYY-MM-DD' 이슈를 대신 연다 → 기존 pick.yml 이 그대로 기록·채점한다.
 *
 * 설치 위치: Scheduler.gs 가 들어 있는 GAS 프로젝트(GH_TOKEN 재사용). 터미널 웹앱(Code.gs)은 '나만' 접근이라 텔레그램이 못 부른다.
 *   이 프로젝트의 다른 파일과 이름이 겹치지 않게 모든 이름에 tg 접두를 붙였다. doPost 는 프로젝트에 하나만 있어야 한다.
 *   절차: docs/telegram_pick_buttons.md
 *
 * 스크립트 속성(프로젝트 설정 → 스크립트 속성)
 *   TG_BOT_TOKEN      : 텔레그램 봇 토큰 (answerCallbackQuery·답장용)
 *   TG_WEBHOOK_SECRET : 아무 긴 임의 문자열 (setWebhook 때 URL ?s= 와 secret_token 둘 다에 같은 값)
 *   TG_OWNER_CHAT_ID  : 겸이 텔레그램 사용자 id (숫자). 이 사람이 누른 버튼·보낸 글만 처리
 *   GH_TOKEN          : (기존) 저장소 주인 계정의 fine-grained PAT — Issues: Read and write 권한을 추가해야 이슈를 열 수 있다
 *   GH_ISSUE_TOKEN    : (선택) 이슈 전용 PAT 를 따로 쓰고 싶으면. 있으면 GH_TOKEN 보다 우선
 *
 * 보안
 *   - GAS 웹앱은 HTTP 헤더를 읽을 수 없다(e 에 headers 가 없음). 그래서 X-Telegram-Bot-Api-Secret-Token 은 e.headers 가
 *     있을 때만 보고, 실제 검증은 웹훅 URL 의 ?s=<TG_WEBHOOK_SECRET> 로 한다(텔레그램만 이 URL 을 안다).
 *   - 누른 사람(from.id)이 TG_OWNER_CHAT_ID 와 다르면 아무것도 안 한다. 이슈는 주인 PAT 로 열리므로 pick.yml 의
 *     'issue.user == repository_owner' 조건은 그대로 통과하고, 조건을 넓힐 필요가 없다.
 *   - 같은 update 재전송은 처리한 최대 update_id(스크립트 속성 TG_LAST_UPDATE_ID, 자동 기록)로 영구 차단,
 *     같은 버튼 연타는 CacheService 10분으로 한 번만 처리.
 *
 * 형식(파이썬 screener/duel.py pick_cb·parse_pick_cb·parse_pick_text 와 같은 규칙 — tests/test_tg_pick_buttons.py 가 node 로 대조)
 *   callback_data "p|2026-10-21|K|069500|o" → 이슈 'pick 2026-10-21' / 본문 '069500 1000000 시가'
 *   callback_data "p|2026-10-21|U|SPY|s"    → 이슈 'pick-us 2026-10-21' / 본문 'SPY 1000000'
 *   callback_data "p|…|cash|…"              → 본문 '현금'      ·   "h|K" / "h|U" → 직접 입력 안내 답장
 *   텍스트 'pick 005930 시가' · 'pick 현금' · 'pick-us QQQ 5일' → 오늘(KST)·미장 세션(ET) 날짜로 같은 이슈
 *   텍스트 'ask 퀀트 accum 백필 언제 돼?' → 이슈 'ask 퀀트' / 본문 '<내용>' → .github/workflows/ask.yml 이 요청 장부
 *     (docs/desk_kb/rounds/_requests.json)에 from='겸이' 로 추가 후 이슈 닫기 (10/21 사내 메신저 — scripts/ask.py parse_ask_text 와 같은 규칙)
 */

const TG_REPO = 'hk99915-bot/market-screener';
const TG_NOTIONAL = 1000000;
const TG_CB_EXIT = { K: { o: '시가', c: '종가', '5': '5일' }, U: { s: '', '5': '5일' } };
const TG_CODE_RE = { K: /^[0-9A-Za-z]{6}$/, U: /^[A-Za-z][A-Za-z.\-]{0,5}$/ };
const TG_TEXT_CODE_RE = { K: /^(?:[0-9A-Za-z]{6}|[A-Za-z.]{1,6})$/, U: TG_CODE_RE.U };   // apply_issue 와 같은 규칙
const TG_DEDUP_SEC = 600;   // 10분
// 데스크 키 → 이름 (scripts/round_collect.py DESKS 와 같아야 함 — tests/test_watchdog.py 가 대조)
const TG_DESKS = { pb: 'PB', quant: '퀀트', bonds: '채권', frm: '리스크', backtest: '백테스트', life: 'LIFE', alloc: '자산배분', macro: '매크로', ops: '운영', pm: 'PM', health: '헬스', cio: 'CIO', derivs: '파생', analyst: '애널', dev: '개발', edu: '교육', data: '데이터', verify: '검증', eval: '평가', peer: '피어리뷰', behavior: '행동', audit: '감사', maint: '유지보수', uxui: 'UXUI', hf: 'HF' };
const TG_ASK_USAGE = '형식: ask <데스크> <내용> — 데스크: ' + Object.keys(TG_DESKS).map(function (k) { return TG_DESKS[k]; }).join(' ');
const TG_HELP = {
  K: '✍️ 직접 입력: 이 채팅에 이렇게 보내 줘 (15:30 전)\n'
    + 'pick 005930 시가   ← 종가 진입 → 다음날 시가 청산\n'
    + 'pick 005930 1000000 종가   ← 다음날 종가 청산\n'
    + 'pick 005930 5일   ← 5일 뒤 종가\n'
    + 'pick 현금',
  U: '✍️ 직접 입력: 이 채팅에 이렇게 보내 줘 (미장 시작 09:30 ET 전)\n'
    + 'pick-us QQQ   ← 시가 진입 → 당일 종가 청산\n'
    + 'pick-us QQQ 1000000 5일   ← 5거래일째 종가\n'
    + 'pick-us 현금',
};
const TG_TEXT_USAGE = '형식: pick 종목코드 [금액] [시가|종가|5일] · pick 현금 · pick-us TICKER [금액] [5일]';

// ── 순수 함수 (GAS 서비스 안 씀 → node 로 테스트) ─────────────────────────────────────────

/** callback_data → {title, body} 또는 null (screener/duel.py parse_pick_cb 와 같음). */
function tgParseCallback_(data) {
  const p = String(data || '').split('|');
  if (p.length !== 5 || p[0] !== 'p' || !/^\d{4}-\d{2}-\d{2}$/.test(p[1]) || !TG_CB_EXIT[p[2]]
      || !Object.prototype.hasOwnProperty.call(TG_CB_EXIT[p[2]], p[4])) return null;
  const d = p[1], m = p[2], code = p[3], ex = p[4];
  const title = (m === 'K' ? 'pick ' : 'pick-us ') + d;
  if (code === 'cash') return { title: title, body: '현금' };
  if (!TG_CODE_RE[m].test(code)) return null;
  const body = [m === 'K' ? code : code.toUpperCase(), String(TG_NOTIONAL), TG_CB_EXIT[m][ex]].filter(Boolean).join(' ');
  return { title: title, body: body };
}

/** 텍스트 → {title, body} · {error} · null(pick 아님) (screener/duel.py parse_pick_text 와 같음). */
function tgParseText_(text, krDate, usDate) {
  const t = String(text || '').trim();
  const m = /^\/?(pick-us|pick)(?=\s|$)\s*([\s\S]*)$/i.exec(t);
  if (!m) return null;
  const us = m[1].toLowerCase() === 'pick-us';
  const restAll = m[2].trim();
  const rest = restAll ? restAll.split(/\r?\n/)[0].trim() : '';
  const title = us ? 'pick-us ' + usDate : 'pick ' + krDate;
  if (rest.indexOf('현금') === 0 || rest.toLowerCase() === 'cash') return { title: title, body: '현금' };
  const toks = rest.replace(/,/g, '').split(/\s+/).filter(Boolean);
  if (!toks.length || !TG_TEXT_CODE_RE[us ? 'U' : 'K'].test(toks[0])) return { error: TG_TEXT_USAGE };
  if (us) toks[0] = toks[0].toUpperCase();
  return { title: title, body: toks.join(' ') };
}

/** 텍스트 → {title:'ask <데스크이름>', body} · {error} · null(ask 아님) (scripts/ask.py parse_ask_text 와 같음). */
function tgParseAsk_(text) {
  const t = String(text || '').trim();
  const m = /^\/?ask(?=\s|$)\s*([\s\S]*)$/i.exec(t);
  if (!m) return null;
  const rest = m[1].trim();
  const sp = rest.search(/\s/);
  const head = sp < 0 ? rest : rest.slice(0, sp), body = sp < 0 ? '' : rest.slice(sp).trim();
  let name = null;
  Object.keys(TG_DESKS).forEach(function (k) { if (k === head.toLowerCase() || TG_DESKS[k] === head) name = TG_DESKS[k]; });
  if (!name || !body) return { error: TG_ASK_USAGE };
  return { title: 'ask ' + name, body: body };
}

/** update_id 는 봇마다 단조 증가 → 이미 처리한 최대값 이하면 재전송. */
function tgIsNewUpdate_(updateId, lastSeen) {
  const last = Number(lastSeen);
  return !(lastSeen != null && lastSeen !== '' && isFinite(last) && Number(updateId) <= last);
}

/** 비밀값 확인: 헤더(있으면) 또는 URL ?s= . 둘 다 없으면 거부. */
function tgSecretOk_(e, secret) {
  if (!secret) return false;
  const h = (e && e.headers) || {};
  const hv = h['X-Telegram-Bot-Api-Secret-Token'] || h['x-telegram-bot-api-secret-token'];
  if (hv) return hv === secret;
  const q = (e && e.parameter) || {};
  return q.s === secret;
}

/** 업데이트 하나를 '할 일' 로 바꾼다 (부작용 없음). owner = TG_OWNER_CHAT_ID 문자열. */
function tgPlan_(upd, owner, krDate, usDate) {
  if (!upd || !owner) return { kind: 'ignore', why: 'no-owner' };
  const cq = upd.callback_query;
  if (cq) {
    if (String((cq.from || {}).id) !== owner) return { kind: 'ignore', why: 'not-owner' };
    const chat = cq.message && cq.message.chat ? String(cq.message.chat.id) : owner;
    const data = String(cq.data || '');
    const h = /^h\|([KU])$/.exec(data);
    if (h) return { kind: 'help', cqId: cq.id, chat: chat, text: TG_HELP[h[1]] };
    const is = tgParseCallback_(data);
    if (!is) return { kind: 'bad', cqId: cq.id, chat: chat, text: '알 수 없는 버튼이야 (메시지가 오래됐을 수 있어)' };
    return { kind: 'issue', cqId: cq.id, chat: chat, key: 'tgp:' + data, issue: is };
  }
  const msg = upd.message;
  if (msg && typeof msg.text === 'string') {
    if (String((msg.from || {}).id) !== owner) return { kind: 'ignore', why: 'not-owner' };
    const chat = String(msg.chat.id);
    const is = tgParseText_(msg.text, krDate, usDate) || tgParseAsk_(msg.text);
    if (!is) return { kind: 'ignore', why: 'not-pick' };
    if (is.error) return { kind: 'reply', chat: chat, text: is.error };
    return { kind: 'issue', chat: chat, key: 'tgt:' + is.title + '|' + is.body, issue: is };
  }
  return { kind: 'ignore', why: 'other-update' };
}

// ── GAS 진입점 ─────────────────────────────────────────────────────────────────────────

function doPost(e) {
  try {
    tgHandle_(e);
  } catch (err) {
    console.error('TelegramHook 오류: ' + (err && err.stack || err));
  }
  return ContentService.createTextOutput('ok');   // 항상 200 계열로 끝내 텔레그램 재전송을 줄인다
}

function tgHandle_(e) {
  const props = PropertiesService.getScriptProperties();
  if (!tgSecretOk_(e, props.getProperty('TG_WEBHOOK_SECRET'))) { console.warn('비밀값 불일치 — 무시'); return; }
  tgProcess_(JSON.parse((e.postData && e.postData.contents) || '{}'), props);
}

/** 업데이트 하나 처리 — 웹훅(doPost)과 폴링(tgPoll) 공용. update_id 중복은 여기서 영구 차단. */
function tgProcess_(upd, props) {
  const cache = CacheService.getScriptCache();
  if (upd.update_id != null) {   // 텔레그램 재전송(같은 update_id) 한 번만
    // GAS 웹앱 응답은 302 리다이렉트라 텔레그램이 '실패'로 보고 같은 update 를 ~11분 간격으로 계속 다시 보낸다
    // (10/21 00:41·00:52·01:03 같은 pick 3번). 10분 캐시로는 못 막아서, 처리한 최대 update_id 를 스크립트 속성에 영구 저장.
    const lock = LockService.getScriptLock();
    lock.waitLock(10000);
    try {
      if (!tgIsNewUpdate_(upd.update_id, props.getProperty('TG_LAST_UPDATE_ID'))) return;
      props.setProperty('TG_LAST_UPDATE_ID', String(upd.update_id));
    } finally {
      lock.releaseLock();
    }
  }
  const now = new Date();
  const plan = tgPlan_(upd, String(props.getProperty('TG_OWNER_CHAT_ID') || '').trim(),
    Utilities.formatDate(now, 'Asia/Seoul', 'yyyy-MM-dd'), Utilities.formatDate(now, 'America/New_York', 'yyyy-MM-dd'));
  if (plan.kind === 'ignore') return;
  if (plan.kind === 'help' || plan.kind === 'bad' || plan.kind === 'reply') {
    if (plan.cqId) tgApi_('answerCallbackQuery', { callback_query_id: plan.cqId });
    tgApi_('sendMessage', { chat_id: plan.chat, text: plan.text });
    return;
  }
  // plan.kind === 'issue'
  if (cache.get(plan.key)) {
    if (plan.cqId) tgApi_('answerCallbackQuery', { callback_query_id: plan.cqId, text: '이미 접수됨 (10분 안 같은 선택)' });
    return;
  }
  cache.put(plan.key, '1', TG_DEDUP_SEC);
  const res = tgCreateIssue_(plan.issue.title, plan.issue.body);
  if (res.ok) {
    if (plan.cqId) tgApi_('answerCallbackQuery', { callback_query_id: plan.cqId, text: '기록 접수 ✅' });
    const isAsk = plan.issue.title.indexOf('ask ') === 0;
    tgApi_('sendMessage', { chat_id: plan.chat, text: isAsk
      ? '📮 요청 접수 ✅ 겸이 → ' + plan.issue.title.slice(4) + ': ' + plan.issue.body + '\n장부 반영은 1~2분 뒤 이슈 답글로, 매일 00:07 요약의 📮 사내 메신저 절에 나와.'
      : '기록 접수 ✅ ' + plan.issue.title + ' · ' + plan.issue.body + '\n반영 결과(마감·쿨다운 확인)는 1~2분 뒤 따로 와. 바꾸고 싶으면 다른 버튼을 누르면 마지막 것이 남아.' });
  } else {
    cache.remove(plan.key);   // 실패면 다시 누를 수 있게
    if (plan.cqId) tgApi_('answerCallbackQuery', { callback_query_id: plan.cqId, text: '기록 실패 ❌ ' + res.code, show_alert: true });
    tgApi_('sendMessage', { chat_id: plan.chat, text: '기록 실패 ❌ GitHub ' + res.code + ' — 토큰 권한(Issues 쓰기) 확인. 급하면 메시지의 링크로 제출.' });
  }
}

function tgCreateIssue_(title, body) {
  const props = PropertiesService.getScriptProperties();
  const token = props.getProperty('GH_ISSUE_TOKEN') || props.getProperty('GH_TOKEN');
  if (!token) return { ok: false, code: 'GH_TOKEN 없음' };
  const r = UrlFetchApp.fetch('https://api.github.com/repos/' + TG_REPO + '/issues', {
    method: 'post', contentType: 'application/json', muteHttpExceptions: true,
    headers: { Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json' },
    payload: JSON.stringify({ title: title, body: body + '\n\n(텔레그램 버튼)' }),
  });
  const code = r.getResponseCode();
  if (code !== 201) console.error('이슈 생성 실패 ' + code + ': ' + r.getContentText().slice(0, 200));
  return { ok: code === 201, code: code };
}

function tgApi_(method, payload) {
  const token = PropertiesService.getScriptProperties().getProperty('TG_BOT_TOKEN');
  if (!token) { console.error('TG_BOT_TOKEN 없음'); return null; }
  const r = UrlFetchApp.fetch('https://api.telegram.org/bot' + token + '/' + method, {
    method: 'post', contentType: 'application/json', muteHttpExceptions: true, payload: JSON.stringify(payload),
  });
  if (r.getResponseCode() !== 200) console.error('텔레그램 ' + method + ' ' + r.getResponseCode() + ': ' + r.getContentText().slice(0, 200));
  return r;
}

// ── 폴링 모드 (10/21 02시) ──────────────────────────────────────────────────────────────
// GAS 웹앱은 응답이 항상 302 리다이렉트라 텔레그램 웹훅이 '실패'로 보고 재시도·백오프한다
// (getWebhookInfo last_error "Wrong response from the webhook: 302 Found", pending 쌓임 → 답장이 수십 분 늦음).
// 그래서 웹훅을 끄고 1분 시간 트리거가 getUpdates 로 가져온다: 지연 ≤1분, 재전송·중복 없음(offset).
// 설치: 편집기에서 tgInstallPolling 1회 실행. 되돌리기: tgUninstallPolling → tgSetWebhook.

/** 1분 트리거: 밀린 업데이트를 순서대로 처리. 동시에 두 번 돌지 않게 잠금. */
function tgPoll() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) return;
  try {
    const props = PropertiesService.getScriptProperties();
    const last = Number(props.getProperty('TG_LAST_UPDATE_ID') || 0);
    const r = tgApi_('getUpdates', { offset: last ? last + 1 : 0, timeout: 0, limit: 50, allowed_updates: ['callback_query', 'message'] });
    const j = r ? JSON.parse(r.getContentText()) : null;
    if (!j || !j.ok) { console.error('getUpdates 실패: ' + (j && j.description || 'no response')); return; }
    lock.releaseLock();   // tgProcess_ 가 update_id 저장 때 같은 잠금을 다시 잡는다
    (j.result || []).forEach(function (u) {
      try { tgProcess_(u, props); } catch (err) { console.error('tgPoll 처리 오류: ' + (err && err.stack || err)); }
    });
  } finally {
    try { lock.releaseLock(); } catch (e2) {}
  }
}

/** 편집기에서 1회 실행: 웹훅 해제(밀린 업데이트는 버리지 않음) + tgPoll 5분 트리거 설치(기존 tgPoll 트리거는 지우고 다시 — 1분짜리 교체).
 *  한도 계산(10/21): 무료 계정 트리거 총 실행시간 ≈ 90분/일. 1분 = 1440회 × 실행 2~3초 ≈ 48~72분 + tick 288회 ≈ 5~10분 → 한도 근처
 *  (10/21 08:40·08:50 tick 미발송 의심 원인) · 5분 = 288회 × 2~3초 ≈ 10~15분 → tick 포함 약 25분 이내. 버튼 반응은 최대 5분 늦어진다. */
function tgInstallPolling() {
  tgApi_('deleteWebhook', { drop_pending_updates: false });
  ScriptApp.getProjectTriggers().forEach(function (t) { if (t.getHandlerFunction() === 'tgPoll') ScriptApp.deleteTrigger(t); });
  ScriptApp.newTrigger('tgPoll').timeBased().everyMinutes(5).create();
  tgPoll();
  console.log('폴링 설치 완료 — 트리거 tgPoll 5분. 웹훅 상태: ' + tgApi_('getWebhookInfo', {}).getContentText());
}

/** 되돌리기: tgPoll 트리거 삭제 (그다음 tgSetWebhook 실행하면 웹훅 모드). */
function tgUninstallPolling() {
  ScriptApp.getProjectTriggers().forEach(function (t) { if (t.getHandlerFunction() === 'tgPoll') ScriptApp.deleteTrigger(t); });
  console.log('tgPoll 트리거 삭제');
}

/** 편집기에서 실행: 웹훅 상태 확인(토큰은 로그에 안 찍음). last_error_message 가 비어 있으면 정상. */
function tgWebhookInfo() {
  const r = tgApi_('getWebhookInfo', {});
  const j = r ? JSON.parse(r.getContentText()).result || {} : {};
  console.log(JSON.stringify({ url_set: !!j.url, pending: j.pending_update_count, last_error: j.last_error_message || '', last_error_date: j.last_error_date || '' }));
}

/** 편집기에서 실행: 웹훅 등록. TG_WEBHOOK_URL(배포 URL, …/exec) 스크립트 속성을 먼저 넣는다. 토큰을 채팅·브라우저 주소창에 붙일 필요 없음. */
function tgSetWebhook() {
  const props = PropertiesService.getScriptProperties();
  const url = props.getProperty('TG_WEBHOOK_URL'), secret = props.getProperty('TG_WEBHOOK_SECRET');
  if (!url || !secret) throw new Error('TG_WEBHOOK_URL · TG_WEBHOOK_SECRET 스크립트 속성을 먼저 넣어줘');
  const r = tgApi_('setWebhook', { url: url + (url.indexOf('?') < 0 ? '?' : '&') + 's=' + encodeURIComponent(secret),
    secret_token: secret.replace(/[^A-Za-z0-9_-]/g, '').slice(0, 256), allowed_updates: ['callback_query', 'message'] });
  console.log(r ? r.getContentText() : '실패');
}

/** 롤백: 웹훅 해제 (버튼은 눌러도 반응 없음 → 링크로 제출). */
function tgDeleteWebhook() {
  const r = tgApi_('deleteWebhook', { drop_pending_updates: true });
  console.log(r ? r.getContentText() : '실패');
}

if (typeof module !== 'undefined') {   // node 테스트용 (GAS 에서는 module 이 없어 무시)
  module.exports = { tgIsNewUpdate_, tgParseCallback_, tgParseText_, tgParseAsk_, tgSecretOk_, tgPlan_, TG_HELP, TG_DESKS };
}
