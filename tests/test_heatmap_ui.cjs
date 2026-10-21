const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../apps-script/tab_market.html'),'utf8');
const code=html.slice(html.indexOf('function heatSource('),html.indexOf('setInterval(()=>{if(view'));
const c={};vm.createContext(c);vm.runInContext(code,c);
const base={asof:'2026-10-19',rows:[{s:'A',r1:0,r5:0.2,mc:10},{s:'B',r1:0.5,mc:20}]};
const live={trade_date:'2026-10-20',session:'LIVE',asof:'2026-10-21 00:12 KST',collected:1,expected:2,rows:[{s:'A',r1:0.1}]};
const r=c.heatSource('US','r1',base,live);assert.equal(r.rows.length,1);assert.equal(r.rows[0].r1,0.1);assert(r.label.includes('1/2'));
assert.equal(c.heatSource('US','r5',base,live).rows,base.rows);
assert.equal(c.heatSource('KR','r1',base,live).rows[0].r1,0.1);   // 10/21 maint-heatmap: KR 도 장중 1D 피드(heatmap_KR.json)
assert.equal(c.heatSource('KR','r1',base,null).rows,base.rows);   // 피드 없으면 종가 그대로 (+ 배지 STALE)
assert.equal(c.heatSource('US','r1',base,{...live,trade_date:'2026-10-16'}).rows,base.rows);
assert.equal(base.rows[0].r1,0);
// 10/21 maint-heatmap: 기준 HH:MM · 다음 갱신 · 장중 지난 값 STALE
const K=t=>Date.parse(t.replace(' ','T')+':00+09:00');
const c3={asofTag:(at,times,days,ids)=>`기준 ${at} · 다음 갱신 ${times[0]}@${days.join('')} [${ids[0]}]`,MKTZ:{KR:'Asia/Seoul',US:'America/New_York'},
  tzParts:(tz,t)=>{const f=new Intl.DateTimeFormat('en-CA',{timeZone:tz,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(t),g=k=>(f.find(x=>x.type===k)||{}).value;return {ds:`${g('year')}-${g('month')}-${g('day')}`,hm:(+g('hour')%24)*60+(+g('minute'))};}};
vm.createContext(c3);vm.runInContext(code,c3);
const lkr={trade_date:'2026-10-21',session:'LIVE',asof:'2026-10-21 10:52 KST',collected:2,expected:2,rows:[{s:'A',r1:0.04}]};
let b1=c3.heatBadge('KR','r1',lkr,{live:true},'live',K('2026-10-21 10:58'));
assert(b1.includes('기준 2026-10-21 10:52')&&b1.includes('다음 갱신 11:00@3')&&b1.includes('[heatmap_kr]')&&!b1.includes('STALE'),b1);
b1=c3.heatBadge('KR','r1',lkr,{live:true},'live',K('2026-10-21 11:20'));
assert(b1.includes('⚠ STALE · 장중 미갱신 (28분 전)'),b1);
b1=c3.heatBadge('KR','r1',null,{live:false},'live',K('2026-10-21 10:58'));   // 오늘 아침 PB 가 본 상태: 피드 없음 → 전일 종가 + STALE
assert(b1.includes('기준 —')&&b1.includes('장중 미갱신'),b1);
assert(!c3.heatBadge('KR','r5',null,{live:false},'live',K('2026-10-21 10:58')).includes('STALE'));   // 5D 는 마감 기준이라 STALE 아님
assert(!c3.heatBadge('KR','r1',lkr,{live:true},'post',K('2026-10-21 18:00')).includes('STALE'));
assert(c3.heatBadge('KR','r1',lkr,{live:true},'post',K('2026-10-21 18:00')).includes('다음 갱신 09:05@12345'));
const lus={trade_date:'2026-10-20',session:'LIVE',asof:'2026-10-21 02:57 KST',rows:[]};
assert(c3.heatBadge('US','r1',lus,{live:true},'pre',K('2026-10-21 10:58')).includes('다음 갱신 22:45@12345'));   // EDT: 09:30 ET = 22:30 KST + 15분
assert(c3.heatBadge('US','r1',lus,{live:true},'live',K('2026-10-21 23:01')).includes('23:15'));
// 10/21 toss-sectors: 토스 섹터 중분류 우선·폴백·다중 소속·심볼 정규화
const code2=html.slice(html.indexOf('let TSEC=null'),html.indexOf('function heatView('));
const c2={TOSS_BASE:'x/'};vm.createContext(c2);vm.runInContext(code2+';this.setT=v=>{TSEC=v;TSEC_MAP={};};this.setSrc=v=>{HMSRC=v;};',c2);
c2.setT({source:'toss',date:'2026-10-21',sectors:[{id:'S1',name:'IT',depth:0,parent:null},{id:'S11',name:'반도체',depth:1,parent:'S1'},{id:'S111',name:'메모리',depth:2,parent:'S11'},{id:'S12',name:'전자부품',depth:1,parent:'S1'}],
  members:{KR:{'A005930':['S111','S12'],'000660':['S111']},US:{'BRK.B':['S12']}}});
const rows=[{s:'005930',g:'반도체 테마',mc:1},{s:'000660',g:'반도체 테마',mc:1},{s:'035420',g:'인터넷',mc:1}];
const hg=c2.heatGroups('KR',rows);assert.equal(hg.nT,2);
assert.equal(hg.rows.map(r=>r.s+':'+r.g).join(','),'005930:반도체,005930:전자부품,000660:반도체,035420:인터넷');
assert.equal(c2.heatGroups('US',[{s:'BRK-B',g:'금융',mc:1}]).rows[0].g,'전자부품');
c2.setSrc('old');assert.equal(c2.heatGroups('KR',rows).nT,0);
c2.setSrc('toss');c2.setT(null);assert.equal(c2.heatGroups('KR',rows).rows,rows);
console.log('heatmap: current coverage, no stale mixing, 5D/KR unchanged, toss sectors d1+fallback passed');
