/* Controlled chat UI. No model simulation, no database access, no automatic POST on replay. */
(() => {
  'use strict';
  if (!['chat', 'history'].includes(page)) return;
  const views = window.IntelligenceViews, key = 'ci.conversations.v1';
  let conversations = [], current = null, revision = 0, sending = false;
  const timers = new Set();
  try {
    const saved = JSON.parse(localStorage.getItem(key) || '[]');
    if (Array.isArray(saved)) conversations = saved.filter(c => typeof c.id === 'string' && typeof c.title === 'string' && Array.isArray(c.messages)).slice(0,30);
  } catch { /* Storage is optional; never block a real task. */ }
  function persist() {
    try { localStorage.setItem(key, JSON.stringify(conversations.slice(0,30))); }
    catch { if ($('chat-error')) { $('chat-error').hidden = false; $('chat-error').textContent = '浏览器存储不可用，对话不能在刷新后恢复。运行仍可通过 History 查看。'; } }
  }
  function stopPolling() { revision++; timers.forEach(clearTimeout); timers.clear(); }
  function schedule(fn) { const timer=setTimeout(()=>{timers.delete(timer);fn();},1500);timers.add(timer); }
  function message(role, text) {
    const box=node('article',undefined,`chat-message ${role}`);
    box.append(node('h2',role==='user'?'You':'Agent'));
    if(text) box.append(node('p',text));
    $('chat-thread').append(box); return box;
  }
  function showConversation() {
    $('chat-welcome').hidden=true; $('chat-shortcuts').hidden=true; $('chat-conversation').hidden=false;
  }
  function ensureConversation(question) {
    if (current) return;
    current={id:crypto.randomUUID(),title:question.slice(0,80),messages:[]};
    conversations.unshift(current);conversations=conversations.slice(0,30);
    history.pushState(null,'',`/?conversation=${encodeURIComponent(current.id)}`);
  }
  function summaryLinks(box, data) {
    const actions=node('div',undefined,'card-actions');
    actions.append(link(`运行 #${data.run.run_id} · 完整审计`, `/developer/runs/${data.run.run_id}`));
    if(data.run.competitor_id) actions.append(link('竞品档案与来源',`/competitors/${data.run.competitor_id}`));
    if(data.report) actions.append(link('查看报告',`/reports/${data.report.report_id}`));
    box.append(actions);
  }
  async function watchWorkflow(box,record,epoch){
    if(epoch!==revision||!box.isConnected)return;
    try{
      const data=await api(`/api/analyst/workflows/${record.runId}`);
      if(epoch!==revision)return;
      box.replaceChildren(node('h2','Agent · 竞品分析'),node('p',`#${record.runId} · ${data.phase} · ${data.status} · ${data.elapsed_seconds||0}s`));
      box.append(node('p','真实业务工作流；结果是否完整以证据和最终状态为准。'),link('运行审计',`/developer/runs/${record.runId}`));
      if(data.task)box.append(node('pre',JSON.stringify(data.task,null,2)));
      if(data.discovery)box.append(node('p',`候选选择：${(data.discovery.selected||[]).join('、')} · ${data.discovery.status}`));
      for(const product of data.products||[])box.append(node('p',`${product.name} · ${product.status} · ${product.research.fact_count} 条事实 · ${(product.issues||[]).join(' / ')}`));
      box.append(node('pre',JSON.stringify({budget:data.budget,issues:data.issues},null,2)));
      if(data.status==='RUNNING'){schedule(()=>watchWorkflow(box,record,epoch));return;}
      if(data.report_id){
        const report=await api(`/api/reports/${data.report_id}`);if(epoch!==revision)return;
        box.append(node('h3',`${report.report_type} · ${data.analysis_complete?'已完成所选范围':'部分结果，请核对信息缺口'}`));
        const content=report.content_json, matrix=content.matrix;
        const table=node('table'),head=node('tr');['产品','维度','状态','事实'].forEach(v=>head.append(node('th',v)));table.append(head);
        for(const product of matrix.products)for(const [dimension,cell] of Object.entries(product.cells)){
          const tr=node('tr');[product.name,dimension,cell.status,cell.fact_ids.map(id=>JSON.stringify(matrix.facts[id].value)).join('；')].forEach(v=>tr.append(node('td',v)));table.append(tr);
        }box.append(table,node('h3','综合结论 · 分析推断'));
        for(const finding of content.conclusions)box.append(node('p',finding.text),node('small',finding.evidence_ids.join(', ')));
        if(!content.conclusions.length)box.append(node('p','无法形成受证据支持的综合结论。'));
        const details=node('details');details.append(node('summary','来源引用与信息缺口'));
        for(const [id,evidence] of Object.entries(matrix.evidence))details.append(node('p',`${id} · ${evidence.quote}`),link(evidence.url,evidence.url));
        details.append(node('pre',JSON.stringify({gaps:matrix.gaps,limitations:content.limitations},null,2)));box.append(details);
        box.append(link('查看正式报告记录',`/reports/${data.report_id}`),link('导出 Markdown',`/api/reports/${data.report_id}/download`));
      }else box.append(node('p','本次没有生成报告。澄清或缺失证据不能视为分析成功。'));
    }catch(error){if(epoch===revision)box.append(node('p',`读取失败：${error.message}。可从 History 重新查看，不会重启任务。`));}
  }
  function renderRun(box,data,record) {
    const expanded=box.querySelector('details')?.open || false;
    const run=data.run, state=run.final_state||run.current_state;
    box.replaceChildren(node('h2',`Agent · ${run.competitor}`));
    if(state==='PARTIAL_SUCCESS') box.append(node('p',`PARTIAL_SUCCESS · ${run.confirmed_fact_count} 条可展示事实，${run.failed_source_count||0} 个失败/部分失败来源。仅部分证据，观察保持 PENDING；未建立基线或执行变化检测。`,'chat-notice'));
    const provider=record.provider || data.provider_summary.search_provider;
    const llm=record.factProvider==='openai_compatible'||data.provider_summary.fact_provider==='openai_compatible';
    box.append(node('p',provider==='serper'?(llm?'真实搜索 / 真实网页 / LLM 原文证据提取。':'真实 Serper 搜索 / 真实网页；事实提取跳过。'):provider==='fixture'?'Fixture 离线演示 · 不是实时竞品研究结果。':'历史运行 · Provider 以完整审计记录为准。','chat-notice'));
    box.append(node('p',`#${run.run_id} · ${stateLabels[state]||state} · ${run.tool_call_count} 次工具调用`,'chat-status'));
    if(run.final_state) {
      box.append(node('p',`已验证来源 ${run.verified_source_count} · 抓取成功 ${run.page_fetch_success_count} / 失败 ${run.page_fetch_failure_count} · 本次确认事实 ${run.confirmed_fact_count}`));
      box.append(node('p',`事实提取：${data.fact_extraction_status||'未记录'}。${run.fact_extraction_reason||''}`));
      if(data.report) box.append(node('p',data.report.executive_summary));
      else box.append(node('p','本次没有生成报告；不代表没有变化。'));
    }
    for(const warning of [...(run.warnings||[]),...(run.errors||[])]) box.append(node('p',human(warning),'chat-notice'));
    summaryLinks(box,data);
    const details=node('details');details.open=expanded;details.append(node('summary','执行详情 · 已记录的阶段、工具与证据'));
    if(!data.events.length) details.append(node('p','尚无已记录的执行事件。'));
    data.events.forEach(e=>details.append(node('p',`${e.display_name} · ${e.status} · ${fmtTime(e.started_at)}${e.error_message?' · '+e.error_message:''}`)));
    data.tool_calls.forEach(call=>{
      const detail=node('details');detail.append(node('summary',`${call.display_name||call.tool_name} · ${call.status}`),node('pre',JSON.stringify({input:call.input,output:call.output,error:call.error_message},null,2)));details.append(detail);
    });
    details.append(node('h3','来源记录（当前档案，非历史网页快照）'));
    data.sources.forEach(source=>details.append(views.sourceCard(source)));
    details.append(node('h3','本次事实证据'));
    data.facts.forEach(f=>{const item=node('div');item.append(node('p',f.display_value),node('blockquote',f.evidence_excerpt),link('来源',f.source_url),node('small',`置信度 ${f.confidence}`));details.append(item)});
    if(!data.facts.length) details.append(node('p','本次无已保存的事实证据，不补写推断。'));
    box.append(details);
  }
  async function watchRun(box,record,epoch,attempt=0) {
    if(epoch!==revision||!box.isConnected) return;
    if(!record.workflowChecked){record.workflowChecked=true;try{await api(`/api/analyst/workflows/${record.runId}`);record.workflow=true;}catch{/* Legacy run. */}}
    if(record.workflow)return watchWorkflow(box,record,epoch);
    try {
      const data=await api(`/api/workspace/runs/${record.runId}`);
      if(epoch!==revision||!box.isConnected) return;
      renderRun(box,data,record);
      if(!data.run.final_state) {
        if(attempt<600) schedule(()=>watchRun(box,record,epoch,attempt+1));
        else paused('已达到页面轮询上限；任务可能仍在服务器执行。');
      }
    } catch(error) { if(epoch===revision&&box.isConnected) paused(`读取运行失败：${error.message}。这不表示任务完成或没有变化。`); }
    function paused(text) {
      box.append(node('p',text));const retry=node('button','重新读取状态');retry.type='button';
      retry.onclick=()=>{retry.disabled=true;watchRun(box,record,epoch);};box.append(retry,link('完整运行记录',`/developer/runs/${record.runId}`));
    }
  }
  function confirmAnalysis(box,command,record,epoch) {
    box.append(node('p',`将为「${command.name}」创建或刷新档案。请确认数据模式后启动；不会打开 Developer 表单。`));
    const modes=node('div',undefined,'chat-mode'),label=node('label','数据模式 '),mode=node('select');mode.setAttribute('aria-label','数据模式');
    for(const [value,text] of [['serper','真实搜索 · 跳过事实提取'],['llm','真实搜索 + LLM 证据提取（付费）'],['fixture','Fixture 离线演示 · 非实时研究']]) {const option=node('option',text);option.value=value;mode.append(option)}
    const note=node('p',undefined,'chat-notice');
    function explain(){note.textContent=mode.value==='llm'?'将公开网页正文发送给服务端配置的模型服务，会产生 API 费用。只保存有原文证据的事实；失败不会切换到演示数据。':mode.value==='serper'?'真实搜索和抓取会访问公开网页并写入运行记录；本次明确跳过事实提取。':'Fixture 会使用固定离线样例并写入数据库。仅供演示，不是该产品当前真实事实。';}
    mode.onchange=explain;explain();label.append(mode);
    const start=node('button','确认并开始分析');start.type='button';modes.append(label,start);box.append(modes,note);
    start.onclick=async()=>{
      if(epoch!==revision||record.started) return;
      record.started=true;record.provider=mode.value==='llm'?'serper':mode.value;record.factProvider=mode.value==='llm'?'openai_compatible':'fixture';persist();start.disabled=true;mode.disabled=true;
      note.textContent='正在创建运行，请勿重复提交…';
      try {
        const accepted=await api('/api/analyses',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({competitor_name:command.name,language:'zh',locale:'zh-CN',search_provider:record.provider,fact_provider:record.factProvider,skip_fact_extraction:mode.value==='serper',max_tool_calls:20})});
        record.runId=accepted.run_id;persist();
        if(epoch===revision) watchRun(box,record,epoch);
      } catch(error) {
        record.error=`创建运行未确认：${error.message}。为避免重复任务，请先在 History 核对后再发起新请求。`;persist();
        if(epoch===revision){note.textContent=record.error;box.append(link('查看 History','/history'));}
      }
    };
  }
  async function answer(box,record,epoch) {
    if(record.workflow){
      if(record.runId)return watchWorkflow(box,record,epoch);
      if(record.started||record.error){box.append(node('p',record.error||'启动响应未保存，请先检查 History；不会自动重发。'),link('History','/history'));return;}
      try{
        const ready=await api('/api/analyst/workflows/readiness');
        if(epoch!==revision)return;
        if(!ready.ready){box.append(node('p',`尚不能启动：${ready.blockers.join(' · ')}。正式迁移和付费测试需单独批准。`));return;}
        box.append(node('p',`将使用真实外部服务。共享上限：${ready.limits.searches} 次搜索、${ready.limits.fetches} 次网页请求、${ready.limits.models} 次模型调用、${ready.limits.tokens} 预留 Token、$${ready.limits.cost_microusd/1000000} 预留费用。预留值不是实际账单。`));
        const button=node('button','确认费用上限并开始真实分析');button.type='button';box.append(button);
        button.onclick=async()=>{button.disabled=true;record.started=true;persist();try{
          const accepted=await api('/api/analyst/workflows',{method:'POST',body:JSON.stringify({text:record.text,allow_paid:true})});
          record.runId=accepted.run_id;persist();if(epoch===revision)watchWorkflow(box,record,epoch);
        }catch(error){record.error=`启动未确认：${error.message}。请先检查 History 后再提交。`;persist();box.append(node('p',record.error));}};
      }catch(error){box.append(node('p',`准备检查失败：${error.message}`));}
      return;
    }
    if(record.runId) return watchRun(box,record,epoch);
    if(record.error){box.append(node('p',record.error),link('查看 History','/history'));return;}
    if(record.started){box.append(node('p','上次启动的响应未保存。请先在 History 核对运行；刷新不会重新提交。'),link('查看 History','/history'));return;}
    try {
      const command=await api(`/api/analyst/command?text=${encodeURIComponent(record.text)}`);
      if(epoch!==revision) return;
      if(command.action==='unsupported'){box.append(node('p',command.message));return;}
      if(command.action==='capability'){box.append(node('p','使用受控命令而非自由多轮 LLM Agent。支持真实搜索 + LLM 原文证据提取（需配置并明确选择），也可以跳过提取。Fixture 不用于真实网页。每条输入独立解析，不会推断“它”等多轮指代。'));return;}
      if(command.action==='analyze'){confirmAnalysis(box,command,record,epoch);return;}
      if(command.action==='run'){record.runId=command.run_id;persist();return watchRun(box,record,epoch);}
      let competitor=null;
      if(command.name){const data=await api(`/api/competitors?search=${encodeURIComponent(command.name)}&limit=100`);competitor=data.items.find(item=>[item.name,item.normalized_name].some(value=>value.toLowerCase()===command.name.toLowerCase()));if(epoch!==revision)return;if(!competitor){box.append(node('p','未找到该竞品档案。可以输入“分析 产品名”建立档案。'));return;}}
      box.append(node('p','以下是已有记录的确定性查询，不是新的实时研究；历史数据可能包含 Fixture 演示，请通过运行记录核对。','chat-notice'));
      const result=node('div');box.append(result);
      if(command.action==='signals'){
        const suffix=competitor?`?competitor_id=${competitor.competitor_id}`:'';
        const data=await api(`/api/signals?limit=5${competitor?`&competitor_id=${competitor.competitor_id}`:''}`);
        if(epoch!==revision)return;views.fill(result,data.items,views.signalCard,'暂无已记录的变化；不等于竞品没有变化。');box.append(link('查看全部变化',`/signals${suffix}`));return;
      }
      const data=await api(`/api/competitors/${competitor.competitor_id}/intelligence?limit=100${command.action==='pricing'?'&fact_category=Pricing':''}`);
      if(epoch!==revision)return;
      if(command.action==='pricing')views.fill(result,data.facts.filter(f=>['PRICE','PLAN'].includes(f.category)),views.factCard,'暂无已确认的公开价格；不能解释为免费。');
      if(command.action==='sources')views.fill(result,data.sources,views.sourceCard,'尚无来源记录。');
      if(command.action==='report')views.fill(result,data.reports.filter(r=>r.report_type!=='PARTIAL_EVIDENCE').slice(0,1),views.reportCard,'尚无正式报告。');
      box.append(link('完整竞品档案',`/competitors/${competitor.competitor_id}`));
    }catch(error){if(epoch===revision)box.append(node('p',`请求失败：${error.message}。没有生成研究结论。`));}
  }
  async function restore() {
    stopPolling();sending=false;$('chat-send').disabled=false;$('chat-thread').replaceChildren();
    const params=new URLSearchParams(location.search),id=params.get('conversation'),run=params.get('run');
    current=conversations.find(c=>c.id===id)||null;
    const visible=Boolean(current||run||id);$('chat-welcome').hidden=visible;$('chat-shortcuts').hidden=visible;$('chat-conversation').hidden=!visible;
    if(current) {for(const record of current.messages.slice(0,60)){if(typeof record.text!=='string')continue;message('user',record.text);const box=message('agent');answer(box,record,revision);}}
    else if(run&&/^\d+$/.test(run)) {const box=message('agent','系统运行回放（不重启任务）。');watchRun(box,{runId:Number(run)},revision);}
    else if(id||run) message('agent','此对话在本浏览器不可用，或运行 ID 无效。请从 History 打开运行记录。');
  }
  async function historyPage() {
    const target=$('chat-history');
    if(!conversations.length)empty(target,'本浏览器尚无对话记录。');
    conversations.forEach(c=>{const row=node('article');row.append(link(c.title,`/?conversation=${encodeURIComponent(c.id)}`),node('small',` · ${c.messages.length} 条请求`));target.append(row)});
    let offset=0;
    async function load(){const button=$('chat-more');button.disabled=true;try{
      const data=await api(`/api/runs?limit=20&offset=${offset}`);
      if(!data.items.length&&offset===0)empty($('chat-runs'),'数据库尚无运行记录。');
      data.items.forEach(r=>{const row=node('article');row.append(link(`${r.competitor} · #${r.run_id}`,`/?run=${r.run_id}`),node('p',`${r.final_state||r.current_state} · ${fmtTime(r.started_at)}`),link('Developer 审计',`/developer/runs/${r.run_id}`));$('chat-runs').append(row)});
      offset+=data.items.length;button.hidden=data.items.length<20||offset>10000;
    }catch(e){$('chat-runs').append(node('p',`运行记录加载失败：${e.message}`));}finally{button.disabled=false;}}
    $('chat-more').onclick=load;await load();
  }
  if(page==='history'){historyPage();return;}
  $('chat-form').onsubmit=async event=>{
    event.preventDefault();const text=$('chat-input').value.trim();if(!text||sending)return;
    if(current?.messages.length>=60){message('agent','本段对话已达到 60 条请求上限，请新建分析。');return;}
    sending=true;$('chat-send').disabled=true;ensureConversation(text);showConversation();
    const record={text,workflow:$('chat-mode').value==='workflow'};current.messages.push(record);persist();$('chat-input').value='';message('user',text);const box=message('agent');
    const epoch=revision;await answer(box,record,epoch);if(epoch===revision){sending=false;$('chat-send').disabled=false;$('chat-input').focus();}
  };
  $('chat-input').onkeydown=event=>{if((event.ctrlKey||event.metaKey)&&event.key==='Enter'){event.preventDefault();$('chat-form').requestSubmit();}};
  document.querySelectorAll('[data-prompt]').forEach(button=>button.onclick=()=>{$('chat-mode').value='legacy';$('chat-input').value=button.dataset.prompt;$('chat-input').focus();});
  window.addEventListener('popstate',restore);
  window.addEventListener('pagehide',stopPolling);
  window.addEventListener('pageshow',event=>{if(event.persisted)restore();});
  restore();
})();
