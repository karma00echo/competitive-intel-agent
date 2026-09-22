/* Read-only audit projections from the existing API. No simulated events. */
(() => {
  if (!['home','audit'].includes(page)) return;
  function disclosure(title, value, id) {
    const d=node('details',undefined,'audit-tool');if(id)d.dataset.auditId=id;
    d.append(node('summary',title),node('pre',JSON.stringify(value,null,2)));return d;
  }
  function mode(run) {
    if(!run.final_state) return '运行中 · Provider 请核对工具轨迹';
    if(run.provider_summary?.search_provider==='serper')return '真实 Serper 搜索 · 事实提取跳过';
    return run.fact_extraction_status?'Fixture 离线演示 · 非实时研究':'历史默认 Provider 标记 · 请核对工具轨迹，不推断真实或演示模式';
  }
  if(page==='home') {
    let offset=0,failed=false;
    async function load(next=0) {
      const target=$('audit-history'),prev=$('audit-prev'),more=$('audit-next');prev.disabled=more.disabled=true;
      try {
        const data=await api(`/api/runs?limit=20&offset=${next}`);offset=next;failed=false;more.textContent='下一页';target.replaceChildren();
        for(const run of data.items) {
          const row=node('article',undefined,'audit-row'),name=node('div'),status=node('div'),meta=node('div');
          const state=run.final_state||run.current_state;
          name.append(link(run.competitor,`/developer/runs/${run.run_id}`),node('p',`#${run.run_id} · ${run.run_mode||'尚未选择模式'}`));
          const badge=node('span',stateLabels[state]||state,'status');badge.dataset.state=state;
          status.append(badge,node('p',mode(run)));
          meta.append(node('small',fmtTime(run.started_at)),node('p',`${run.tool_call_count} 次调用 · ${run.warning_count} 警告 · ${run.error_count} 错误`));
          row.append(name,status,meta);target.append(row);
        }
        if(!data.items.length)empty(target,'暂无运行记录。可从首页发起分析。');
        $('audit-page').textContent=`第 ${offset/20+1} 页`;prev.disabled=offset===0;more.disabled=data.items.length<20||offset>=10000;
      } catch(e) {failed=true;empty(target,`运行历史读取失败：${e.message}`);prev.disabled=offset===0;more.disabled=false;more.textContent='重试当前页';}
    }
    $('audit-prev').onclick=()=>load(Math.max(0,offset-20));$('audit-next').onclick=()=>load(failed?offset:offset+20);load();return;
  }
  let timer, reads=0;
  function render(data) {
    const run=data.run,state=run.final_state||run.current_state;
    const open=new Set(Array.from(document.querySelectorAll('[data-audit-id][open]')).map(d=>d.dataset.auditId));
    $('audit-title').textContent=run.competitor;
    $('audit-subtitle').textContent=`运行 #${run.run_id} · ${run.run_mode||'待选择模式'} · ${fmtTime(run.started_at)}`;
    $('audit-state').textContent=stateLabels[state]||state;$('audit-state').dataset.state=state;
    const provider=$('audit-provider');provider.replaceChildren();
    const p=data.provider_summary||{};
    for(const [label,value] of [['搜索',run.final_state?p.search_provider:'待审计确认'],['网页抓取',run.final_state?p.fetch_mode:'待审计确认'],['Agent',p.agent_provider],['事实 Provider',p.fact_provider],['事实提取',data.fact_extraction_status||'未记录'],['工具调用',run.tool_call_count]]) {
      const item=node('div');item.append(node('small',label),node('strong',value??'未记录'));provider.append(item);
    }
    const links=$('audit-links');links.replaceChildren(link('在对话中回放',`/?run=${run.run_id}`));
    if(data.report)links.append(link('查看报告',`/reports/${data.report.report_id}`));
    if(run.competitor_id)links.append(link('竞品档案',`/competitors/${run.competitor_id}`));
    const warnings=$('audit-warnings');warnings.replaceChildren(node('p',mode(run)));
    const issues=[...(run.warnings||[]),...(run.errors||[])];
    if(issues.length){const detail=node('details',undefined,'audit-tool');detail.dataset.auditId='warnings';detail.append(node('summary',`${run.warnings?.length||0} 条警告 · ${run.errors?.length||0} 条错误（展开查看）`));issues.forEach(item=>detail.append(node('p',human(item))));warnings.append(detail);}
    if(run.fact_extraction_reason)warnings.append(node('small',run.fact_extraction_reason));
    const events=$('audit-events');events.replaceChildren();
    for(const event of data.events){const item=node('article',undefined,'audit-event');item.dataset.status=event.status;
      item.append(node('h3',event.display_name),node('small',`${event.status} · 尝试 ${event.attempt}`),node('p',`${fmtTime(event.started_at)} → ${fmtTime(event.finished_at)}`));
      if(event.error_message)item.append(node('p',`${event.error_code||''} ${event.error_message}`,'error'));
      item.append(disclosure('事件记录',event,`event-${event.event_id}`));events.append(item);
    }
    if(!data.events.length)empty(events,'尚无已记录的阶段事件。');
    const tools=$('audit-tools');tools.replaceChildren();
    for(const call of data.tool_calls){const item=disclosure(`#${call.call_index} · ${call.display_name||call.tool_name} · ${call.status}`,call,`tool-${call.tool_call_id}`);
      item.insertBefore(node('p',`${call.provider||'Provider 未记录'} · ${call.duration_ms??'—'} ms · ${call.retryable?'可重试':'不可重试'}`),item.lastChild);tools.append(item);
    }
    if(!data.tool_calls.length)empty(tools,'尚无工具调用记录。');
    const evidence=$('audit-evidence');evidence.replaceChildren();
    data.sources.forEach(s=>{const item=disclosure(`${s.source_type} · ${s.verification_status}`,s,`source-${s.source_id}`);if(s.url)item.append(link('原始来源',s.url));evidence.append(item)});
    data.facts.forEach(f=>{const item=disclosure(f.display_value,f,`fact-${f.fact_id}`);item.append(link('原始来源',f.source_url));evidence.append(item)});
    if(!data.sources.length&&!data.facts.length)empty(evidence,'本次没有可展示的来源或事实证据。');
    const result=$('audit-result');result.replaceChildren();
    if(data.report)result.append(node('h3',data.report.title),node('p',data.report.executive_summary),link('阅读完整报告',`/reports/${data.report.report_id}`));
    else result.append(node('p',run.final_state?'本次未生成报告；不代表没有变化。':'运行尚未生成报告。'));
    result.append(disclosure('运行摘要与变化记录',{run,changes:data.changes},'result'));
    document.querySelectorAll('[data-audit-id]').forEach(d=>{d.open=open.has(d.dataset.auditId)});
  }
  async function refresh(){clearTimeout(timer);$('audit-retry').hidden=true;$('audit-error').hidden=true;
    try{const data=await api(`/api/workspace/runs/${resourceId}`);render(data);
      if(!data.run.final_state){if(++reads<600)timer=setTimeout(refresh,1500);else throw new Error('自动读取已达上限，任务可能仍在执行。');}
    }catch(e){$('audit-error').textContent=`读取状态失败：${e.message}`;$('audit-error').hidden=false;$('audit-retry').hidden=false;}
  }
  $('audit-retry').onclick=()=>{reads=0;refresh()};window.addEventListener('pagehide',()=>clearTimeout(timer));window.addEventListener('pageshow',e=>{if(e.persisted)refresh()});refresh();
})();
