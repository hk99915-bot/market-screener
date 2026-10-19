const assert=require('node:assert/strict'),vm=require('node:vm');
const fs=require('node:fs'),path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../apps-script/tab_my.html'),'utf8');
const req=html.slice(html.indexOf('let MYRUN_ID='),html.indexOf('// 결재 #3 레짐'));
const run=html.slice(html.indexOf('function myRun(){'),html.indexOf('function myRender'));
function env(){
 const timers=new Map();let tid=0;const out={innerHTML:'',insertAdjacentHTML(){}},input={value:'fixture'};
 const c={MYD:{},MYX:{KOSPI:Array(25).fill([0,1])},HEDGES:[],BENCH:[],window:{},Number,Map,Error,Array,
 setTimeout:(f,ms)=>{timers.set(++tid,{f,ms});return tid;},clearTimeout:id=>timers.delete(id),
 $:id=>id==='#myout'?out:id==='#myta'?input:null,esc:x=>String(x),loadIndex:f=>f(),
 myParse:()=>[{key:'fixture'}],myResolve:()=>({m:'KR',s:'000001'}),myRender:()=>{out.innerHTML='RESULT';}};
 const requests=[];
 function runner(ok,fail){return new Proxy({withSuccessHandler:f=>runner(f,fail),withFailureHandler:f=>runner(ok,f)},{get:(o,k)=>k in o?o[k]:(...args)=>requests.push({method:k,args,ok,fail})});}
 c.google={script:{run:runner()}};vm.createContext(c);vm.runInContext(req+'\n'+run,c);
 return {c,out,input,requests,timers,fire:ms=>{for(const [id,t] of [...timers])if(t.ms===ms){timers.delete(id);t.f();}}};
}
{
 const e=env();e.c.loadIndex=()=>{};e.c.myRun();e.fire(45000);assert(e.out.innerHTML.includes('지연'));assert.equal(e.input.value,'fixture');
}
{
 const e=env();e.c.myRender=()=>{throw Error('render');};e.c.myRun();e.requests[0].ok(JSON.stringify({close:100}));assert(e.out.innerHTML.includes('표시 중 오류'));assert(!e.out.innerHTML.includes('불러오는 중'));
}
{
 const e=env();e.c.myRun();e.fire(12000);assert(e.out.innerHTML.includes('보유 종목 시세'));e.requests[0].ok(JSON.stringify({close:100}));assert(e.out.innerHTML.includes('보유 종목 시세'));
}
{
 const e=env();e.c.myRun();e.c.myRun();e.requests[0].ok(JSON.stringify({close:100}));assert(!e.out.innerHTML.includes('RESULT'));e.requests[1].ok(JSON.stringify({close:100}));assert.equal(e.out.innerHTML,'RESULT');
}
{
 const e=env();let done=0;const list=Array.from({length:9},(_,i)=>['KR',String(i)]);e.c.myFetch(list.concat(list),()=>done++);assert.equal(e.requests.length,4);
 let k=0;while(k<e.requests.length){e.requests[k++].ok(JSON.stringify({close:100}));}assert.equal(k,9);assert.equal(done,1);
}
console.log('MY loading: hung index, render error, timeout, stale callback, bounded/deduplicated fetch passed');

{
 const shell=fs.readFileSync(path.join(__dirname,'../apps-script/Index.html'),'utf8');
 const math=shell.slice(shell.indexOf('const mean='),shell.indexOf('let SG='));
 for(const ratio of [false,true]){
  const out={innerHTML:''}; const c={window:{},document:{addEventListener(){}},localStorage:{getItem:()=>ratio?'1':'0'},$:()=>out,esc:String,num:(x)=>Number(x).toLocaleString('en-US'),pct:(x)=>String(x),shortNm:x=>x,console,Date,setTimeout,clearTimeout};
  vm.createContext(c);vm.runInContext(math+'\n'+html.match(/<script>([\s\S]*)<\/script>/)[1],c);
  vm.runInContext(`
   const dates=Array.from({length:251},(_,i)=>new Date(Date.UTC(2025,0,i+1)).toISOString().slice(0,10));
   MYX={KOSPI:dates.map((d,i)=>[d,100+i]),USDKRW:dates.map(d=>[d,1300]),SPX:dates.map((d,i)=>[d,100+i])};
   MYD={'KR:005930':{name:'fixture',close:110,c1y:dates.map((d,i)=>[d,100+i/25]),drivers:{score:0.2}}};
   myRender([{r:{m:'KR',s:'005930'},qty:2,avg:100}], [{cash:'KRW',amt:100,book:'isa'}],[]);
  `,c);
  assert(out.innerHTML.includes('PB 의견'));assert(out.innerHTML.includes('스트레스 테스트'));
  if(!ratio)assert(out.innerHTML.includes('20원'));
 }
}
console.log('MY real renderer: ratio and amount modes passed');
