// Execute the shipped UI and fetch helper against an in-memory DOM/HTTP boundary.
// No browser, database or network connection is created.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const mode=process.argv[2]||'success',requests=[],storage=new Map(),elements=new Map();
class Element {
 constructor(tag,text){this.tag=tag;this.textContent=text||'';this.children=[];this.isConnected=true;this.value='';}
 append(...items){this.children.push(...items);}
 replaceChildren(...items){this.children=items;}
 focus(){}
 setAttribute(){}
 querySelector(){return null;}
}
const get=id=>{if(!elements.has(id))elements.set(id,new Element('div'));return elements.get(id);};
const document={body:{dataset:{page:'chat'}},getElementById:get,createElement:t=>new Element(t),querySelectorAll:()=>[]};
const location={search:''},window={IntelligenceViews:{},addEventListener(){}};
let release;
const pending=new Promise(resolve=>release=resolve);
async function fetch(url,options){
 const wire=new Request('http://offline.invalid'+url,options);
 const entry={url,method:wire.method,contentType:wire.headers.get('content-type'),body:await wire.text()};requests.push(entry);
 if(entry.method==='POST'){
  await pending;
  if(mode==='timeout')throw new Error('response lost after acceptance');
  return {ok:true,json:async()=>({data:{run_id:42}})};
 }
 if(url.endsWith('/readiness'))return {ok:true,json:async()=>({data:{ready:mode!=='blocked',blockers:['PAID_WORKFLOW_DISABLED'],limits:{searches:18,fetches:24,models:13,tokens:250000,cost_microusd:1000000}}})};
 return {ok:true,json:async()=>({data:{status:'FAILED',phase:'DONE',products:[],issues:[],budget:{},report_id:null}})};
}
const context=vm.createContext({document,window,location,history:{pushState(a,b,url){location.search=url.slice(1);}},localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},crypto:{randomUUID:()=> 'offline-conversation'},fetch,URLSearchParams,setTimeout,clearTimeout,console});
const app=fs.readFileSync('src/competitive_intel/web/static/app.js','utf8');
const chat=fs.readFileSync('src/competitive_intel/web/static/chat.js','utf8');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
async function main(){
 assert.equal(new Request('http://offline.invalid',{method:'POST',body:'{}'}).headers.get('content-type'),'text/plain;charset=UTF-8');
 vm.runInContext(app,context);vm.runInContext(chat,context);
 get('chat-mode').value='workflow';get('chat-input').value=process.argv[3]||'比较豆包和 Kimi 的核心功能与定价策略，并生成竞品分析报告。';
 await get('chat-form').onsubmit({preventDefault(){}});
 assert.equal(requests.filter(x=>x.method==='POST').length,0,'No request before explicit fee consent');
 const all=e=>[e,...e.children.flatMap(all)];
 const button=all(get('chat-thread')).find(e=>e.tag==='button'&&e.textContent==='确认费用上限并开始真实分析');
 if(mode==='blocked'){assert.equal(button,undefined);console.log(JSON.stringify({mode,requests}));return;}
 assert.ok(button);
 const first=button.onclick();await button.onclick();await flush();
 assert.equal(requests.filter(x=>x.method==='POST').length,1,'Double confirmation must send once');
 release();await first;await flush();await button.onclick();
 const saved=JSON.parse(storage.get('ci.conversations.v1'))[0].messages[0];
 assert.equal(saved.started,true);
 if(mode==='timeout'){assert.ok(saved.error);assert.equal(saved.runId,undefined);}else assert.equal(saved.runId,42);
 // Reload persisted conversation: no automatic POST, including uncertain acceptance.
 vm.runInContext(chat,context);await flush();await flush();
 assert.equal(requests.filter(x=>x.method==='POST').length,1);
 const post=requests.find(x=>x.method==='POST');assert.equal(post.contentType,'application/json');
 assert.equal(JSON.parse(post.body).allow_paid,true);
 console.log(JSON.stringify({mode,requests}));
}
main().catch(e=>{console.error(e);process.exitCode=1;});
