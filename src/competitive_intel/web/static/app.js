const $=(id)=>document.getElementById(id);
const page=document.body.dataset.page;
const resourceId=document.body.dataset.resourceId;
const terminal=new Set(["COMPLETED","COMPLETED_WITH_WARNINGS","FAILED"]);
const stateLabels={INITIALIZING:"初始化",PROFILE_LOOKUP:"查询竞品档案",MODE_SELECTION:"选择运行模式",SOURCE_DISCOVERY:"发现来源",SOURCE_VALIDATION:"验证来源",PAGE_FETCHING:"抓取页面",SNAPSHOT_PERSISTENCE:"保存快照",FACT_EXTRACTION:"提取事实",FACT_PERSISTENCE:"保存事实",HISTORY_LOOKUP:"查找历史基线",FACT_COMPARISON:"比较事实",CHANGE_PERSISTENCE:"保存变化",REPORT_GENERATION:"生成报告",REPORT_PERSISTENCE:"保存报告",RUN_SUMMARY:"汇总运行",COMPLETED:"已完成",COMPLETED_WITH_WARNINGS:"带警告完成",FAILED:"失败"};
const stages=Object.keys(stateLabels);
function node(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=String(text);if(cls)e.className=cls;return e}
function link(text,href){const a=node("a",text);a.href=/^(https?:\/\/|\/)/i.test(href||"")?href:"#";return a}
function fmtTime(value){return value?new Date(value).toLocaleString("zh-CN"):"—"}
function human(value){if(value===null||value===undefined)return"—";if(Array.isArray(value))return value.map(human).join("、");if(typeof value==="object")return Object.entries(value).map(([k,v])=>`${k}：${human(v)}`).join("；");return String(value)}
async function api(url,options){const response=await fetch(url,options);const data=await response.json();if(!response.ok)throw new Error(data.error_message||"请求失败");return data.data??data}
function empty(target,text="暂无数据"){target.replaceChildren(node("div",text,"empty"))}
function listItem(title,subtitle,href,meta=[]){const box=node("div",undefined,"list-item");box.append(href?link(title,href):node("strong",title));if(subtitle)box.append(node("p",subtitle));const row=node("div",undefined,"meta");meta.forEach(x=>row.append(node("span",x)));box.append(row);return box}
function metrics(target,items){target.replaceChildren();items.forEach(([label,value])=>{const box=node("div",undefined,"metric");box.append(node("strong",value??"—"),node("span",label));target.append(box)})}

async function loadHome(){
  try{const h=await api("/api/health");$("health").textContent=`数据库：${h.database_status==="available"?"正常":"不可用"} · 活动任务 ${h.active_task_count}`}catch{$("health").textContent="服务状态不可用"}
  try{const data=await api("/api/runs?limit=8");const target=$("recent-runs");target.replaceChildren();data.items.forEach(r=>target.append(listItem(r.competitor,`${r.run_mode||"待选择"} · ${stateLabels[r.final_state||r.current_state]||r.current_state}`,`/runs/${r.run_id}`,[fmtTime(r.started_at),`工具 ${r.tool_call_count}`])));if(!data.items.length)empty(target)}catch(e){empty($("recent-runs"),e.message)}
  try{const data=await api("/api/competitors?limit=12");const target=$("competitors");target.replaceChildren();data.items.forEach(c=>target.append(listItem(c.name,c.official_homepage||"尚无已验证主页",`/competitors/${c.competitor_id}`,[`来源 ${c.verified_source_count}`,`事实 ${c.current_fact_count}`])));if(!data.items.length)empty(target)}catch(e){empty($("competitors"),e.message)}
  const provider=$("search-provider"),skip=$("skip-facts"),notice=$("provider-notice");
  function mode(){const real=provider.value==="serper";skip.checked=real;skip.disabled=real;notice.textContent=real?"真实搜索与真实网页抓取；由于真实 Fact Provider 尚未接入，事实提取将强制跳过。":"Fixture 模式完全离线，适合稳定演示。";notice.className=`notice wide${real?" warn":""}`}
  provider.addEventListener("change",mode);mode();
  $("analysis-form").addEventListener("submit",async(event)=>{event.preventDefault();const error=$("form-error");error.hidden=true;const button=event.target.querySelector("button");button.disabled=true;button.textContent="正在创建运行…";try{const language=$("language").value;const accepted=await api("/api/analyses",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({competitor_name:$("competitor-name").value,language,locale:language==="zh"?"zh-CN":"en-US",search_provider:provider.value,fact_provider:"fixture",agent_provider:"fixture",fixture_scenario:$("fixture-scenario").value,skip_fact_extraction:skip.checked,max_tool_calls:20})});location.href=`/runs/${accepted.run_id}`}catch(e){error.textContent=e.message;error.hidden=false;button.disabled=false;button.textContent="开始分析"}});
}

function progressFor(state){const i=stages.indexOf(state);return Math.max(4,Math.round((i+1)/stages.length*100))}
async function loadRun(){
  let attempts=0;
  async function refresh(){
    attempts++;
    try{
      const [run,eventData,callData]=await Promise.all([api(`/api/runs/${resourceId}`),api(`/api/runs/${resourceId}/events`),api(`/api/runs/${resourceId}/tool-calls`)]);
      $("run-title").textContent=`${run.competitor} · #${run.run_id}`;
      const state=run.final_state||run.current_state;$("run-state").textContent=stateLabels[state]||state;$("run-state").dataset.state=state;$("progress").firstElementChild.style.width=`${progressFor(state)}%`;
      metrics($("run-summary"),[["运行模式",run.run_mode],["官方来源",run.verified_source_count],["抓取成功",run.page_fetch_success_count],["抓取失败",run.page_fetch_failure_count],["确认事实",run.confirmed_fact_count],["修改事实",run.change_summary?.modified_count??0],["工具调用",run.tool_call_count]]);
      const warning=$("run-warning");if(run.fact_extraction_status==="SKIPPED"){warning.hidden=false;warning.className="notice warn";warning.textContent="真实搜索：已完成；真实网页抓取：已完成；事实提取：已跳过。原因：真实内容需要真实 Fact Provider。"}else if(run.warnings?.length){warning.hidden=false;warning.className="notice warn";warning.textContent=run.warnings.join("；")}else warning.hidden=true;
      const events=$("events");events.replaceChildren();eventData.items.forEach(item=>{const box=node("div",undefined,"timeline-item");box.append(node("strong",stateLabels[item.stage]||item.stage),node("span",`${item.status} · ${fmtTime(item.started_at)}`));events.append(box)});
      const calls=$("tool-calls");calls.replaceChildren();callData.items.forEach(item=>calls.append(listItem(item.tool_name,item.error_message||item.status,null,[`#${item.call_index}`,item.duration_ms?`${item.duration_ms} ms`:""])));
      const result=$("run-result");result.replaceChildren();if(run.report_id)result.append(link("查看正式报告",`/reports/${run.report_id}`));else result.append(node("p",terminal.has(state)?"本次运行没有生成报告。":"报告将在运行完成后显示。","empty"));
      if(!terminal.has(state)&&attempts<600)setTimeout(refresh,1000);
    }catch(e){$("run-warning").hidden=false;$("run-warning").textContent=e.message;if(attempts<10)setTimeout(refresh,1000)}
  }refresh();
}

async function loadCompetitor(){
  try{
    const [detail,facts,sources,changes,reports,runs]=await Promise.all([api(`/api/competitors/${resourceId}`),api(`/api/competitors/${resourceId}/facts`),api(`/api/competitors/${resourceId}/sources`),api(`/api/competitors/${resourceId}/changes?limit=20`),api(`/api/competitors/${resourceId}/reports`),api(`/api/runs?competitor_id=${resourceId}&limit=20`)]);
    $("competitor-title").textContent=detail.name;metrics($("competitor-overview"),[["官方域名",detail.official_domain],["已验证来源",detail.source_statistics.verified],["成功快照",detail.snapshot_statistics.successful],["当前事实",facts.items.length]]);
    const groups={};facts.items.forEach(f=>(groups[f.category]??=[]).push(f));const ft=$("facts");ft.replaceChildren();Object.entries(groups).forEach(([category,items])=>{const box=node("div",undefined,"fact-group");box.append(node("h3",category));items.forEach(f=>{const row=node("div",undefined,"fact");row.append(node("strong",f.display_value),node("small",`${f.fact_key} · 置信度 ${f.confidence}`),link("查看来源",f.source_url));box.append(row)});ft.append(box)});if(!facts.items.length)empty(ft,"当前没有已确认事实");
    const st=$("sources");st.replaceChildren();sources.items.forEach(s=>st.append(listItem(s.source_type,s.url,s.url,[s.verification_status,s.latest_snapshot_status||"无快照",fmtTime(s.latest_fetched_at)])));if(!sources.items.length)empty(st);
    const ct=$("changes");ct.replaceChildren();changes.items.forEach(c=>ct.append(listItem(`${c.fact_key} · ${c.change_type}`,`${c.old_display_value} → ${c.new_display_value}`,null,[fmtTime(c.detected_at)])));if(!changes.items.length)empty(ct);
    const rt=$("reports");rt.replaceChildren();reports.items.forEach(r=>rt.append(listItem(r.summary.title||`报告 #${r.report_id}`,r.report_type,`/reports/${r.report_id}`,[fmtTime(r.created_at)])));if(!reports.items.length)empty(rt);
    const rh=$("competitor-runs");rh.replaceChildren();runs.items.forEach(r=>rh.append(listItem(`#${r.run_id} · ${stateLabels[r.final_state||r.current_state]||r.current_state}`,r.run_mode,`/runs/${r.run_id}`,[fmtTime(r.started_at)])));if(!runs.items.length)empty(rh);
  }catch(e){$("competitor-title").textContent="加载失败";empty($("facts"),e.message)}
}

async function loadReport(){
  try{const r=await api(`/api/reports/${resourceId}`);$("report-title").textContent=r.title;$("report-meta").textContent=`${r.report_type} · ${fmtTime(r.created_at)}`;$("report-summary").textContent=r.executive_summary;$("report-download").href=`/api/reports/${resourceId}/download?format=markdown`;const target=$("report-content");target.replaceChildren();(r.content_json.sections||[]).forEach(section=>{const box=node("section",undefined,"report-section");box.append(node("h2",section.heading));const items=Array.isArray(section.items)?section.items:[section.items];items.forEach(item=>box.append(node("div",human(item),"report-item")));target.append(box)})}catch(e){$("report-title").textContent="报告加载失败";$("report-summary").textContent=e.message}
}
if(page==="home")loadHome();if(page==="run")loadRun();if(page==="competitor")loadCompetitor();if(page==="report")loadReport();
