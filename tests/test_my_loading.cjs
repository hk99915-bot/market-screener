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
