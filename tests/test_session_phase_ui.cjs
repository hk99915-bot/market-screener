// 10/21 겸이 '왜 홈에 closed kr이 자꾸 뜨나' — 장 상태·제목·지난 값 판정 (apps-script/Index.html mkPhase · tab_market.html stInfo/intradayPanel)
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const idx=fs.readFileSync(path.join(__dirname,'../apps-script/Index.html'),'utf8');
const mkt=fs.readFileSync(path.join(__dirname,'../apps-script/tab_market.html'),'utf8');
const helpers=idx.slice(idx.indexOf('const HOL='),idx.indexOf('/* 데이터 신선도 배지'));
const ns=idx.slice(idx.indexOf('function nextSlot('),idx.indexOf('function asofTag('));
const panel=mkt.slice(mkt.indexOf('function intradayPanel('),mkt.indexOf('function marketView('));
const K=t=>new Date(Date.parse(t.replace(' ','T')+':00+09:00'));   // KST 문자열 → Date
function ctx(now,state){
  const c={D:{state},esc:x=>String(x),num:x=>String(x),pct:x=>String(x),sgn:x=>String(x),tgHtml:x=>String(x),closeNote:()=>'',asofTag:()=>'',NOW:now};
  vm.createContext(c);
  // Date.now / new Date() 를 고정
  vm.runInContext(`const _D=Date; Date=class extends _D{constructor(...a){ super(...(a.length?a:[NOW.getTime()])); } static now(){ return NOW.getTime(); } };`+helpers+ns+panel,c);
  return c;
}
const ST={
  intraday_snapshot:{at:'2026-10-20 13:34',value:{flows:{KOSPI:{'외국인':1}},snap:{},notes:['n']}},
  close_snapshot:{at:'2026-10-20 15:49',value:{flows:{KOSPI:{'외국인':2}},snap:{},kospi:1,kospi_chg:0}},
  close_KR:{at:'2026-10-20 16:27',value:'c'}, premarket_kr:{at:'2026-10-21 09:07',value:'p'}, intraday_kr:{at:'2026-10-20 13:35',value:'i'},
  close_US:{at:'2026-10-20 06:55',value:'u'}, intraday_us:{at:'2026-10-20 22:55',value:'iu'}, premarket_us:{at:'2026-10-20 21:54',value:'pu'},
};
// 장 상태
let c=ctx(K('2026-10-21 10:28'),ST);
assert.equal(c.mkPhase('KR').ph,'live'); assert.equal(c.mkPhase('KR').last,'2026-10-20');
assert.equal(c.mkPhase('US').ph,'post'); assert.equal(c.mkPhase('US').today,'2026-10-20');   // 10:28 KST = 21:28 ET 전날
assert.equal(c.mkDayOf('US','2026-10-20 06:55'),'2026-10-19');   // 06:55 KST 마감 코멘트 = 전날 미장
assert.equal(ctx(K('2026-10-09 10:00'),ST).mkPhase('KR').ph,'off');   // 한글날 휴장
assert.equal(ctx(K('2026-10-25 10:00'),ST).mkPhase('KR').ph,'off');   // 일요일
assert.equal(ctx(K('2026-10-06 08:00'),ST).mkPhase('KR').last,'2026-10-02');   // 10/5 개천절 대체 휴장 → 직전 = 10/2(금)
// A. 장중 첫 판단(10:30) 전: 'CLOSE KR' 이 아니라 'INTRADAY KR' + 대기 문구 + 날짜
let h=c.intradayPanel();
assert(!h.includes('CLOSE KR'),h.slice(0,200)); assert(h.includes('INTRADAY KR')); assert(h.includes('오늘 장중 판단 대기 · 직전 값 = 10/20 마감')); assert(h.includes('opacity:.5'));
// 오늘 장중 판단이 나오면 정상 INTRADAY (대기 문구 없음)
const today={...ST,intraday_snapshot:{...ST.intraday_snapshot,at:'2026-10-21 10:31'}};
h=ctx(K('2026-10-21 10:40'),today).intradayPanel(); assert(h.includes('INTRADAY KR')&&!h.includes('대기 · 직전'));
// 오늘 15:49 마감 스냅샷 → CLOSE KR
h=ctx(K('2026-10-21 16:00'),{...today,close_snapshot:{...ST.close_snapshot,at:'2026-10-21 15:49'}}).intradayPanel(); assert(h.includes('CLOSE KR'));
// 장 전(08:30): CLOSE 대신 날짜 붙은 직전 마감
h=ctx(K('2026-10-21 08:30'),ST).intradayPanel(); assert(h.includes('KR 직전 마감 (10/20)')&&!h.includes('CLOSE KR'));
// B. 홈 블록: 장중엔 close_KR = 지난 값(어제 마감 10/20), premarket_kr 오늘 = 유효, US close 는 10/19 미장 → 10/20 마감분 대기
let i=c.stInfo('close_KR'); assert.equal(i.old,true); assert.equal(i.ttl,'어제 마감 KR (10/20)');
assert.equal(c.stInfo('premarket_kr').old,false); assert.equal(c.stInfo('intraday_kr').old,true);
i=c.stInfo('close_US'); assert.equal(i.old,true); assert.equal(i.ttl,'CLOSE US (10/19 미장)'); assert(i.tag.includes('10/20 마감분 대기'));
assert.equal(c.stInfo('intraday_us').old,true);
assert(c.pre('close_KR','CLOSE KR').includes('어제 마감 KR (10/20)'));
// 오늘 16:27 마감 코멘트 → CLOSE KR 유효
assert.equal(ctx(K('2026-10-21 16:30'),{...ST,close_KR:{at:'2026-10-21 16:27',value:'c'}}).stInfo('close_KR').old,false);
// 월요일 장중: 금요일 마감은 '직전 마감'
assert.equal(ctx(K('2026-10-26 10:00'),{...ST,close_KR:{at:'2026-10-23 16:27',value:'c'}}).stInfo('close_KR').ttl,'직전 마감 KR (10/23)');
// 미장 정규장 중(23:00 KST)엔 그날 intraday_us 유효, 07:00 KST 새 마감 코멘트는 유효
assert.equal(ctx(K('2026-10-21 23:30'),{...ST,intraday_us:{at:'2026-10-21 23:25',value:'x'}}).stInfo('intraday_us').old,false);
assert.equal(ctx(K('2026-10-22 07:10'),{...ST,close_US:{at:'2026-10-22 06:55',value:'x'}}).stInfo('close_US').old,false);
console.log('session phase: KR/US phase, holidays, CLOSE only for today close, old blocks dated passed');
