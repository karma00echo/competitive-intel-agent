/* Product views are DOM/textContent projections, never HTML from evidence. */
(() => {
  const root = $("product-content");
  const title = (heading, subtitle) => { $("product-title").textContent = heading; $("product-subtitle").textContent = subtitle; };
  const fail = error => { $("product-error").hidden = false; $("product-error").textContent = error.message; };
  const safe = fn => (...args) => Promise.resolve(fn(...args)).catch(fail);
  const section = (label, target, url) => {
    const box = node("section", undefined, "product-section"), head = node("div", undefined, "section-title");
    head.append(node("h2", label)); if (url) head.append(link("View all →", url));
    box.append(head, target); return box;
  };
  const badge = (text, warning = false) => node("span", text, `tag${warning ? " warning" : ""}`);
  function actions(card, entries) {
    const bar = node("div", undefined, "card-actions");
    for (const [label, href] of entries) if (href) bar.append(link(label, href));
    card.append(bar);
  }
  function competitorCard(item, attention = false) {
    const card = node("article", undefined, `intel-card${attention ? " attention-card" : ""}`);
    card.append(badge(item.status, item.warnings.length > 0), node("h3", item.name));
    card.append(node("small", `Last checked ${fmtTime(item.last_checked)}`));
    if (attention) card.append(node("small", `Last attempt ${fmtTime(item.last_attempt)}`));
    else card.append(node("p", `${item.signals_30d} signals / 30 days · ${item.verified_source_count} verified sources`));
    if (item.warnings.length) { const list = node("ul"); item.warnings.forEach(reason => list.append(node("li", reason))); card.append(list); }
    actions(card, [["Review competitor", item.competitor_id ? `/competitors/${item.competitor_id}` : null],
      ["Latest report", item.report_id ? `/reports/${item.report_id}` : null],
      ["View run ↗", item.run_id ? `/developer/runs/${item.run_id}` : null]]);
    return card;
  }
  function signalCard(item) {
    const card = node("article", undefined, "intel-card signal-card"), head = node("div", undefined, "signal-head");
    head.append(badge(item.category), badge(item.change_type, item.status === "needs_review"), node("time", fmtTime(item.detected_at)));
    card.append(head, node("h3", item.competitor), node("small", item.summary));
    const values = node("div", undefined, "signal-values");
    if (item.change_type === "UNCOMPARABLE") values.append(node("span", "Comparison unavailable — review source evidence."));
    else if (item.change_type === "ADDED") values.append(node("span", item.new_value));
    else if (item.change_type === "REMOVED") values.append(node("del", item.old_value));
    else values.append(node("del", item.old_value), node("span", ` → ${item.new_value}`));
    card.append(values);
    const evidence = node("details"); evidence.append(node("summary", "View evidence"), node("blockquote", item.evidence_excerpt || "No evidence excerpt recorded."));
    if (item.source_url) evidence.append(link(item.source_url, item.source_url));
    else evidence.append(node("small", "No source URL recorded for this change."));
    card.append(evidence);
    actions(card, [["Competitor profile", `/competitors/${item.competitor_id}`], ["Source ↗", item.source_url], ["Developer details", `/developer/runs/${item.run_id}`]]);
    return card;
  }
  function fill(target, items, renderer, message = "No matching records.") {
    target.replaceChildren(); if (!items.length) empty(target, message); else items.forEach(item => target.append(renderer(item)));
  }
  function pager(target, offset, hasMore, reload, size = 20) {
    const bar = node("div", undefined, "pager"), prev = node("button", "Previous"), next = node("button", "Next");
    prev.disabled = offset === 0; next.disabled = !hasMore || offset + size > 10000;
    prev.addEventListener("click", safe(() => reload(Math.max(0, offset - size))));
    next.addEventListener("click", safe(() => reload(offset + size)));
    bar.append(prev, node("small", `Page ${Math.floor(offset / size) + 1}`), next); target.append(bar);
  }
  async function commandCenter(offset = 0) {
    const data = await api(`/api/command-center?limit=12&offset=${offset}`);
    root.replaceChildren(); const metrics = node("div", undefined, "metrics");
    for (const [label, value, time] of [["Tracked competitors", data.metrics.competitor_count], ["Signals in last 30 days", data.metrics.signals_30d], ["Last successful check", fmtTime(data.metrics.last_successful_refresh), true], ["Items needing attention", data.metrics.attention_count]]) {
      const metric = node("div", undefined, `metric${time ? " time" : ""}`); metric.append(node("small", label), node("strong", value)); metrics.append(metric);
    }
    const attention = node("div", undefined, "intel-grid"), signals = node("div"), competitors = node("div", undefined, "intel-grid");
    fill(attention, data.attention, item => competitorCard(item, true), "No outstanding actions in the latest records.");
    fill(signals, data.recent_signals, signalCard, "No recorded changes yet.");
    fill(competitors, data.competitors, item => competitorCard(item), "Start with a competitor name in Analyst.");
    root.append(metrics, section("Needs Attention", attention), section("Recent Signals · latest recorded", signals, "/signals"), section("Competitor overview", competitors, "/competitors"));
    pager(root, offset, Math.max(data.metrics.competitor_count, data.metrics.attention_count) > offset + 12, commandCenter, 12);
  }
  function field(form, label, values, name, type) {
    const holder = node("label", label), input = node(values ? "select" : "input"); input.name = name;
    if (values) values.forEach(([value, text]) => { const option = node("option", text); option.value = value; input.append(option); });
    else input.type = type || "text";
    holder.append(input); form.append(holder); return input;
  }
  async function signalsPage() {
    title("Signals", "Recorded changes, linked to evidence. Status reflects verification, not strategic severity.");
    const form = node("form", undefined, "product-filters"), list = node("div"), paging = node("div");
    const competitors = await api("/api/competitors?limit=100&sort=name_asc");
    const selector = field(form, "Competitor", [["", "All competitors"], ...competitors.items.map(item => [item.competitor_id, item.name])], "competitor_id");
    selector.value = new URLSearchParams(location.search).get("competitor_id") || "";
    field(form, "Signal type", [["", "All types"], ...["Pricing", "Product", "Feature", "Positioning", "Website", "Source", "Other"].map(x => [x,x])], "category");
    field(form, "Change", [["", "All changes"], ...["ADDED", "MODIFIED", "REMOVED", "UNCOMPARABLE"].map(x => [x,x])], "change_type");
    field(form, "From", null, "start", "date"); field(form, "Through", null, "end", "date");
    field(form, "Status", [["", "All statuses"], ["confirmed", "Confirmed"], ["needs_review", "Needs review"]], "status");
    const apply = node("button", "Apply filters"); apply.type = "submit"; form.append(apply);
    root.replaceChildren(form, list, paging);
    async function load(offset = 0) {
      const params = new URLSearchParams(); for (const [key,value] of new FormData(form)) if (value) params.set(key,value);
      params.set("offset", offset); params.set("limit",20);
      const data = await api(`/api/signals?${params}`); fill(list, data.items, signalCard); paging.replaceChildren(); pager(paging, offset, data.has_more, load);
    }
    form.addEventListener("submit", safe(event => { event.preventDefault(); return load(); })); await load();
  }
  function reportCard(item) {
    const card = node("article", undefined, "intel-card");
    card.append(badge(item.report_type === "BASELINE" ? "Initial profile" : "Change report"), node("h3", item.name), node("small", fmtTime(item.generated_at)), node("p", `${item.run_status} · ${item.change_count} recorded changes · ${item.status}`));
    if (item.status === "GENERATED") actions(card, [["View report", `/reports/${item.id}`], ["Markdown ↓", `/api/reports/${item.id}/download?format=markdown`]]);
    actions(card, [["View run", `/developer/runs/${item.run_id}`]]); return card;
  }
  async function reportsPage(offset = 0) {
    title("Reports", "Evidence-backed profiles and change reports. Markdown export available.");
    const data = await api(`/api/reports?offset=${offset}`), list = node("div", undefined, "intel-grid");
    fill(list, data.items, reportCard, "No generated reports yet."); root.replaceChildren(list); pager(root, offset, data.has_more, reportsPage);
  }
  async function competitorsPage(offset = 0) {
    title("Competitors", "Your monitored products, sources and intelligence history.");
    const data = await api(`/api/command-center?limit=20&offset=${offset}`), list = node("div", undefined, "intel-grid");
    fill(list, data.competitors, item => competitorCard(item)); root.replaceChildren(list); pager(root, offset, data.metrics.competitor_count > offset + 20, competitorsPage);
  }
  function factCard(item) {
    const card = node("article", undefined, "intel-card"); card.append(badge(item.category), node("p", item.display_value), node("small", `Collected ${fmtTime(item.collected_at)} · Confidence ${item.confidence}`));
    const details = node("details"); details.append(node("summary", "Evidence"), node("blockquote", item.evidence_excerpt)); card.append(details);
    if (item.source_url) actions(card, [["Source ↗", item.source_url]]); return card;
  }
  function sourceCard(item) {
    const card = node("article", undefined, "intel-card"); card.append(badge(item.source_type), node("h3", item.verification_status), link(item.url || "Unavailable URL", item.url));
    card.append(node("p", `Latest fetch: ${item.latest_snapshot_status || "Not fetched"}`), node("small", fmtTime(item.latest_fetched_at))); return card;
  }
  async function profilePage() {
    let profile = await api(`/api/competitors/${resourceId}/intelligence?limit=100`);
    const item = profile.competitor;
    title(item.name, `${item.official_domain || "Official domain unconfirmed"} · ${item.status} · Last checked ${fmtTime(item.last_checked)}`);
    const tabs = node("div", undefined, "profile-tabs"), content = node("div"); tabs.setAttribute("role", "tablist");
    root.replaceChildren(tabs, content);
    let revision = 0;
    async function drawFacts(target, category, offset = 0) {
      const data = await api(`/api/competitors/${resourceId}/intelligence?limit=20&offset=${offset}${category ? `&fact_category=${category}` : ""}`);
      const list = node("div", undefined, "intel-grid");
      fill(list, data.facts, factCard, "No verified facts available yet."); target.replaceChildren(list);
      pager(target, offset, data.has_more_facts, next => drawFacts(target, category, next));
    }
    async function select(name, offset = 0) {
      const request = ++revision;
      tabs.querySelectorAll("button").forEach(button => button.setAttribute("aria-selected", String(button.textContent === name)));
      content.replaceChildren(node("p", "Loading…", "empty")); location.hash = name.toLowerCase();
      if (["Signals", "History", "Pricing", "Overview"].includes(name)) {
        const params = new URLSearchParams({competitor_id:resourceId,offset,limit:20});
        if (name === "History") params.set("history","true"); if (name === "Pricing") params.set("category","Pricing");
        const changes = await api(`/api/signals?${params}`); if (request !== revision) return;
        content.replaceChildren();
        if (["Overview", "Pricing"].includes(name)) {
          const facts = node("div");
          content.append(section(name === "Pricing" ? "Current pricing" : "Current structured facts",facts));
          await drawFacts(facts, name === "Pricing" ? "Pricing" : null);
          if (request !== revision) return;
        }
        const list = node("div"); fill(list, changes.items, signalCard); content.append(section(name === "History" ? "Change history" : "Recent changes",list));
        pager(content, offset, changes.has_more, next => select(name,next));
        if (name === "Overview") {
          const sources=node("div",undefined,"intel-grid"),reports=node("div");
          fill(sources,profile.sources.filter(s=>s.verification_status==="VERIFIED"),sourceCard);
          fill(reports,profile.reports.slice(0,1),reportCard);content.append(section("Verified sources",sources),section("Latest report",reports));
        }
      } else {
        const data = await api(`/api/competitors/${resourceId}/intelligence?limit=100&offset=${offset}`); if (request !== revision) return;
        content.replaceChildren(); const list=node("div",undefined,"intel-grid");
        if(name==="Features") {content.append(list);await drawFacts(list,"Feature");return;}
        if(name==="Sources") fill(list,data.sources,sourceCard);
        if(name==="Reports") fill(list,data.reports,reportCard);
        content.append(list);pager(content,offset,name==="Sources"?data.has_more_sources:data.has_more_reports,next=>select(name,next),100);
      }
    }
    const names=["Overview","Signals","Pricing","Features","Sources","History","Reports"];
    names.forEach(name=>{const button=node("button",name);button.setAttribute("role","tab");button.addEventListener("click",safe(()=>select(name)));tabs.append(button)});
    await select(names.find(name=>`#${name.toLowerCase()}`===location.hash)||"Overview");
  }
  // Shared evidence renderers: chat queries use the same product projections.
  window.IntelligenceViews = {fill, signalCard, factCard, sourceCard, reportCard};
  if (!root) return;
  const loaders={"command-center":commandCenter,signals:signalsPage,competitors:competitorsPage,reports:reportsPage,"intelligence-profile":profilePage};
  if(loaders[page])safe(loaders[page])();
})();
