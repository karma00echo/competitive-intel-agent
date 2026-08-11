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
const workspaceToolLabels={
  get_competitor_profile:"查询竞品档案",discover_competitor_sources:"发现官方来源",
  refresh_verified_sources:"抓取已验证来源",extract_competitor_facts:"提取结构化事实",
  get_previous_fact_baseline:"查询历史基线",compare_competitor_facts:"比较历史事实",
  generate_competitor_report:"生成分析报告",finalize_run_summary:"汇总运行结果",
  skip_fact_extraction:"跳过事实提取"
};
const messageLabels={
  USER_REQUEST:"用户",AGENT_PLAN:"执行计划",MODE_SELECTED:"模式",
  SOURCE_DISCOVERY_RESULT:"来源",FETCH_RESULT:"抓取",FACT_EXTRACTION_RESULT:"事实",
  CHANGE_RESULT:"变化",REPORT_RESULT:"报告",WARNING:"警告",ERROR:"错误",
  FINAL_SUMMARY:"结果"
};
let workspaceRuns=[],workspaceCompetitors=[],selectedWorkspaceRun=null,workspacePolls=0;

function workspaceStatus(state){
  if(state==="COMPLETED")return"success";
  if(state==="COMPLETED_WITH_WARNINGS")return"warning";
  if(state==="FAILED")return"failed";
  return"running";
}
function makeBadge(text,state){
  const badge=node("span",text,"run-badge");
  badge.dataset.tone=workspaceStatus(state);
  return badge;
}
function renderConversationList(){
  const query=($("workspace-search").value||"").trim().toLocaleLowerCase();
  const target=$("workspace-runs");target.replaceChildren();
  workspaceRuns.filter(run=>`${run.competitor} ${run.run_id} ${run.run_mode}`.toLocaleLowerCase().includes(query)).forEach(run=>{
    const item=node("button",undefined,"conversation-item");
    item.type="button";item.dataset.runId=run.run_id;
    if(Number(selectedWorkspaceRun)===Number(run.run_id))item.classList.add("selected");
    const top=node("div",undefined,"conversation-top");
    top.append(node("strong",run.competitor),makeBadge(stateLabels[run.final_state||run.current_state]||run.current_state,run.final_state||run.current_state));
    const provider=run.provider_summary?.search_provider||"fixture";
    item.append(top,node("span",`${run.run_mode||"待选择"} · ${fmtTime(run.started_at)}`),node("small",`${provider} · ${run.report_id?"有报告":"无报告"}`));
    item.addEventListener("click",()=>selectWorkspaceRun(run.run_id,true));
    target.append(item);
  });
  if(!target.children.length)empty(target,"没有匹配的分析会话");
}
function renderCompetitorList(){
  const query=($("workspace-search").value||"").trim().toLocaleLowerCase();
  const target=$("workspace-competitors");target.replaceChildren();
  workspaceCompetitors.filter(item=>item.name.toLocaleLowerCase().includes(query)).forEach(item=>{
    const row=node("button",undefined,"compact-item");row.type="button";
    row.append(node("strong",item.name),node("small",`${item.verified_source_count} 来源 · ${item.current_fact_count} 事实`));
    row.addEventListener("click",()=>item.latest_run_id?selectWorkspaceRun(item.latest_run_id,true):location.assign(`/competitors/${item.competitor_id}`));
    target.append(row);
  });
  if(!target.children.length)empty(target,"暂无竞品档案");
}
function statGrid(items){
  const grid=node("div",undefined,"result-metrics");
  items.forEach(([label,value])=>{const box=node("div");box.append(node("strong",value??0),node("span",label));grid.append(box)});
  return grid;
}
function renderResultCard(kind,data){
  const card=node("div",undefined,"result-card");
  if(kind==="sources"){
    const counts={VERIFIED:0,PENDING_CONFIRMATION:0,REJECTED:0};data.sources.forEach(s=>counts[s.verification_status]=(counts[s.verification_status]||0)+1);
    card.append(statGrid([["官方域名",data.competitor?.official_domain||"待确认"],["已验证",counts.VERIFIED],["待确认",counts.PENDING_CONFIRMATION],["已拒绝",counts.REJECTED]]));
    data.sources.slice(0,8).forEach(s=>card.append(listItem(s.source_type,s.url,s.url,[s.verification_status,s.latest_snapshot_status||"无快照"])));
  }else if(kind==="fetch"){
    card.append(statGrid([["成功页面",data.run.page_fetch_success_count],["失败页面",data.run.page_fetch_failure_count],["页面变化",data.run.page_comparison_summary?.PAGE_CHANGED||0],["未变化",data.run.page_comparison_summary?.UNCHANGED||0],["快照",data.run.snapshot_count]]));
  }else if(kind==="facts"){
    const counts={};data.facts.forEach(f=>counts[f.category]=(counts[f.category]||0)+1);
    card.append(statGrid(Object.entries(counts).map(([k,v])=>[k,v])));
    data.facts.slice(0,10).forEach(f=>card.append(listItem(f.display_value,f.evidence_excerpt,f.source_url,[f.category,`置信度 ${f.confidence}`])));
  }else if(kind==="changes"){
    data.changes.slice(0,10).forEach(change=>{
      const changeBox=node("div",undefined,"change-card");
      changeBox.append(node("strong",`${change.fact_key} · ${change.change_type}`),node("p",`${change.old_display_value} → ${change.new_display_value}`));
      if(change.evidence_excerpt)changeBox.append(node("small",`证据：${change.evidence_excerpt}`));
      card.append(changeBox);
    });
    if(!data.changes.length)card.append(node("p","本次没有确认的事实变化。","empty"));
  }else if(kind==="report"&&data.report){
    card.append(node("strong",data.report.title),node("p",data.report.executive_summary));
    const summary=data.report.change_summary||{};
    card.append(statGrid([["新增",summary.added_count||0],["修改",summary.modified_count||0],["移除",summary.removed_count||0],["不可比较",summary.uncomparable_count||summary.unknown_count||0]]));
    const actions=node("div",undefined,"card-actions");
    actions.append(link("查看报告",`/reports/${data.report.report_id}`),link("下载 Markdown",data.report.download_url));
    card.append(actions);
  }
  return card;
}
function renderMessageStream(data){
  const target=$("message-stream");target.replaceChildren();
  data.messages.forEach(message=>{
    const wrap=node("article",undefined,`agent-message message-${message.type.toLocaleLowerCase()}`);
    const head=node("div",undefined,"message-head");
    head.append(node("span",messageLabels[message.type]||message.type),node("strong",message.title));
    wrap.append(head,node("p",message.text));
    if(message.card)wrap.append(renderResultCard(message.card,data));
    target.append(wrap);
  });
  if(!data.messages.length)empty(target,"该运行尚无可展示的审计消息");
  target.scrollTop=target.scrollHeight;
}
function traceItem(title,status,time,description){
  const item=node("div",undefined,"trace-item");
  const head=node("div",undefined,"trace-item-head");head.append(node("strong",title),makeBadge(status,status));
  item.append(head,node("small",fmtTime(time)));
  if(description)item.append(node("p",description));
  return item;
}
function renderTrace(data){
  const timeline=$("trace-timeline");timeline.replaceChildren();
  data.events.forEach(event=>timeline.append(traceItem(event.display_name,event.status,event.started_at,event.error_message||`尝试 ${event.attempt}`)));
  if(!data.events.length)empty(timeline,"暂无状态事件");
  const tools=$("trace-tools");tools.replaceChildren();
  data.tool_calls.forEach(call=>{
    const details=node("details",undefined,"tool-detail");
    const summary=node("summary");summary.append(node("strong",call.display_name||workspaceToolLabels[call.tool_name]||call.tool_name),makeBadge(call.status,call.status==="FAILED"?"FAILED":"COMPLETED"));
    const meta=node("p",`${call.duration_ms??0} ms · ${call.provider} · ${call.retryable?"可重试":"不可重试"}`);
    const payload=JSON.stringify({input:call.input,output:call.output},null,2);
    details.append(summary,meta,node("pre",payload.slice(0,2000)+(payload.length>2000?"\n… 已截断":"")));
    tools.append(details);
  });
  if(!data.tool_calls.length)empty(tools,"暂无工具调用");
  const evidence=$("trace-evidence");evidence.replaceChildren();
  data.sources.forEach(source=>evidence.append(listItem(source.source_type,source.evidence_excerpt||source.url,source.url,[source.verification_status,source.latest_snapshot_status||"无快照"])));
  if(!data.sources.length)empty(evidence,"暂无来源证据");
  const details=$("trace-details");details.replaceChildren();
  details.append(statGrid([
    ["运行模式",data.run.run_mode||"—"],["当前状态",stateLabels[data.run.current_state]||data.run.current_state],
    ["工具调用",data.run.tool_call_count],["开始",fmtTime(data.run.started_at)],
    ["结束",fmtTime(data.run.finished_at)],["事实提取",data.fact_extraction_status||"待执行"]
  ]));
  const providers=node("p",`搜索：${data.provider_summary.search_provider} · 抓取：${data.provider_summary.fetch_mode} · Agent：${data.provider_summary.agent_provider} · 事实：${data.provider_summary.fact_provider}`,"trace-provider");
  details.append(providers);
}
function renderWorkspaceRun(data,historical){
  const run=data.run,state=run.final_state||run.current_state;
  $("workspace-title").textContent=`${run.competitor} 竞品情报 Agent`;
  $("workspace-kicker").textContent=historical?"历史运行回放":"当前分析运行";
  $("workspace-subtitle").textContent=`${run.provider_summary.search_provider==="serper"?"真实搜索 · 真实网页抓取":"Fixture 全流程"} · ${run.run_mode||"待选择"} · #${run.run_id}`;
  $("workspace-state").textContent=stateLabels[state]||state;$("workspace-state").dataset.state=state;
  $("workspace-progress").firstElementChild.style.width=`${run.progress_percent}%`;
  renderMessageStream(data);renderTrace(data);renderConversationList();
}
async function selectWorkspaceRun(runId,historical=true){
  selectedWorkspaceRun=Number(runId);workspacePolls=0;
  async function refresh(){
    try{
      const data=await api(`/api/workspace/runs/${selectedWorkspaceRun}`);
      renderWorkspaceRun(data,historical);
      const state=data.run.final_state||data.run.current_state;
      if(!terminal.has(state)&&workspacePolls++<600)setTimeout(refresh,1000);
    }catch(error){$("command-feedback").textContent=error.message}
  }
  refresh();
}
function openAnalysis(name="",scenario="default"){
  $("workspace-competitor-name").value=name;$("workspace-scenario").value=scenario;
  $("analysis-dialog").showModal();$("workspace-competitor-name").focus();
}
function findCompetitor(name){
  const normalized=name.trim().toLocaleLowerCase();
  return workspaceCompetitors.find(item=>item.name.toLocaleLowerCase()===normalized);
}
async function handleCommand(raw){
  const input=raw.trim(),feedback=$("command-feedback");
  let match=input.match(/^(?:分析|重新分析)\s+(.+)$/i);
  if(match){openAnalysis(match[1]);return}
  match=input.match(/^打开运行\s+(\d+)$/i);
  if(match){selectWorkspaceRun(Number(match[1]),true);return}
  match=input.match(/^查看\s+(.+?)\s+最新报告$/i);
  if(match){
    const competitor=findCompetitor(match[1]);if(!competitor){feedback.textContent="未找到该竞品档案。";return}
    const reports=await api(`/api/competitors/${competitor.competitor_id}/reports`);
    if(reports.items.length)location.assign(`/reports/${reports.items[0].report_id}`);else feedback.textContent="该竞品尚无正式报告。";return;
  }
  match=input.match(/^查看\s+(.+?)\s+最近变化$/i);
  if(match){
    const competitor=findCompetitor(match[1]);if(!competitor){feedback.textContent="未找到该竞品档案。";return}
    location.assign(`/competitors/${competitor.competitor_id}#changes`);return;
  }
  if(/^为什么本次没有提取事实[？?]?$/i.test(input)){
    feedback.textContent="真实网页内容不会使用 Fixture 事实。真实 FactExtractionProvider 尚未接入时，本次事实提取会明确跳过。";return;
  }
  feedback.textContent="当前版本仅支持竞品分析、刷新、报告和运行查询。真实自然语言 AgentProvider 尚未接入。";
}
async function loadWorkspace(){
  if(window.matchMedia("(max-width: 1050px)").matches){
    $("workspace-trace").classList.add("collapsed");
    $("trace-toggle").setAttribute("aria-expanded","false");
  }
  try{
    const [runs,competitors]=await Promise.all([api("/api/runs?limit=50"),api("/api/competitors?limit=50")]);
    workspaceRuns=runs.items;workspaceCompetitors=competitors.items;
    renderConversationList();renderCompetitorList();
    if(workspaceRuns.length)selectWorkspaceRun(workspaceRuns[0].run_id,true);
  }catch(error){$("command-feedback").textContent=error.message}
  $("workspace-search").addEventListener("input",()=>{renderConversationList();renderCompetitorList()});
  $("new-analysis").addEventListener("click",()=>openAnalysis());
  $("close-analysis").addEventListener("click",()=>$("analysis-dialog").close());
  $("workspace-provider").addEventListener("change",()=>{
    const real=$("workspace-provider").value==="serper";
    $("workspace-scenario").disabled=real;
    $("workspace-provider-notice").textContent=real?"真实搜索：启用；真实抓取：启用；真实事实提取：未接入；本次事实提取：跳过。":"Fixture 模式使用固定离线数据，可演示完整事实与变化流程。";
    $("workspace-provider-notice").className=`notice${real?" warn":""}`;
  });
  $("workspace-analysis-form").addEventListener("submit",async event=>{
    event.preventDefault();const error=$("workspace-form-error");error.hidden=true;
    const provider=$("workspace-provider").value,language=$("workspace-language").value;
    try{
      const accepted=await api("/api/analyses",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({
        competitor_name:$("workspace-competitor-name").value,language,locale:language==="zh"?"zh-CN":"en-US",
        search_provider:provider,fact_provider:"fixture",agent_provider:"fixture",
        fixture_scenario:$("workspace-scenario").value,skip_fact_extraction:provider==="serper",max_tool_calls:20
      })});
      $("analysis-dialog").close();
      workspaceRuns.unshift({run_id:accepted.run_id,competitor:$("workspace-competitor-name").value,current_state:"INITIALIZING",run_mode:null,started_at:new Date().toISOString(),provider_summary:{search_provider:provider},tool_call_count:0});
      selectWorkspaceRun(accepted.run_id,false);
    }catch(exception){error.textContent=exception.message;error.hidden=false}
  });
  $("command-form").addEventListener("submit",event=>{event.preventDefault();handleCommand($("command-input").value).catch(error=>$("command-feedback").textContent=error.message)});
  document.querySelectorAll("[data-command]").forEach(button=>button.addEventListener("click",()=>{
    const command=button.dataset.command,current=workspaceRuns.find(run=>Number(run.run_id)===Number(selectedWorkspaceRun));
    if(command==="new")openAnalysis();
    if(command==="refresh"&&current)openAnalysis(current.competitor,"unchanged");
    if(command==="report"&&current)handleCommand(`查看 ${current.competitor} 最新报告`);
    if(command==="changes"&&current)handleCommand(`查看 ${current.competitor} 最近变化`);
  }));
  document.querySelectorAll("[data-trace-tab]").forEach(button=>button.addEventListener("click",()=>{
    document.querySelectorAll("[data-trace-tab]").forEach(item=>item.classList.toggle("active",item===button));
    document.querySelectorAll(".trace-panel").forEach(panel=>panel.classList.toggle("active",panel.id===`trace-${button.dataset.traceTab}`));
  }));
  $("trace-toggle").addEventListener("click",()=>{const collapsed=$("workspace-trace").classList.toggle("collapsed");$("trace-toggle").setAttribute("aria-expanded",String(!collapsed))});
}

if(page==="home")loadHome();if(page==="run")loadRun();if(page==="competitor")loadCompetitor();if(page==="report")loadReport();if(page==="workspace")loadWorkspace();
