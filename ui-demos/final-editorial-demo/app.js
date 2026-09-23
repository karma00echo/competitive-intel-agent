/* Isolated, offline UI demo. No APIs, storage, or live research calls. */
(() => {
  'use strict';
  const data = window.editorialContent;
  const paths = {
    home:'M3 10 12 3l9 7M5 9v11h14V9M9 20v-7h6v7',
    pulse:'M2 12h5l3-7 4 14 3-7h5', folder:'M3 6h7l2 2h9v12H3z',
    book:'M12 5v16M12 6C8 3 5 3 2 4v15c4-1 7 0 10 2 3-2 6-3 10-2V4c-3-1-6-1-10 2',
    spark:'m12 2 2.5 7.5L22 12l-7.5 2.5L12 22l-2.5-7.5L2 12l7.5-2.5zM3 3v3M1.5 4.5h3',
    code:'m8 6-6 6 6 6m8-12 6 6-6 6m-3-15-2 18',
    file:'M5 2h9l5 5v15H5zM14 2v6h5M8 12h8M8 16h6',
    history:'M3 4v6h6M3 10a9 9 0 1 1 0 6M12 7v6l4 2',
    search:'M16 16l6 6M19 10a9 9 0 1 1-18 0 9 9 0 0 1 18 0',
    edit:'m3 17-1 5 5-1L21 7l-4-4zM14 6l4 4',
    check:'M8 12l3 3 6-7M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
    text:'M3 5h18M3 10h12M3 15h18M3 20h10',
    compare:'M8 3v18M16 3v18M3 8h10M11 16h10m-3-3 3 3-3 3M6 5 3 8l3 3',
    download:'M12 2v13m-5-5 5 5 5-5M3 16v6h18v-6',
    globe:'M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0M2 12h20M12 2c-6 5-6 15 0 20 6-5 6-15 0-20',
    sliders:'M3 5h18M3 12h18M3 19h18M8 3v4M16 10v4M10 17v4',
    'arrow-right':'M4 12h16m-7-7 7 7-7 7', 'arrow-up':'M12 21V3m-7 7 7-7 7 7',
    bell:'M5 9a7 7 0 0 1 14 0c0 9 3 9 3 10H2c0-1 3-1 3-10M9 22h6M12 1v2',
    close:'m5 5 14 14M5 19 19 5', menu:'M3 5h18M3 12h18M3 19h18'
  };
  const icon = name => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name] || paths.file}"/></svg>`;
  const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const $ = id => document.getElementById(id);
  function fillQuery(value) {
    $('query').value = value;
    $('query').setCustomValidity('');
    $('query').focus();
  }
  function sampleBrief() {
    return '# Competitive intelligence · Sample brief\n\nDESIGN PREVIEW — MOCK CONTENT, NOT VERIFIED INTELLIGENCE\n\n## Companies\n' + data.competitors.map(c => `- ${c.name}: ${c.category}`).join('\n') + '\n\n## Research checklist\n- Verify official sources\n- Capture evidence, collection time, and confidence\n- Mark missing information as unknown\n';
  }
  document.querySelectorAll('[data-icon]').forEach(el => { el.outerHTML = icon(el.dataset.icon); });
  for (const [group, entries] of Object.entries(data.navigation)) {
    $(`${group}-nav`).innerHTML = entries.map(([target,label,symbol]) => `<a class="nav-item" href="#${target}">${icon(symbol)}<span>${escape(label)}</span></a>`).join('');
  }
  $('cards').innerHTML = data.cards.map(card => `<a class="feature-card" href="#${card.target}"><span class="card-icon">${icon(card.icon)}</span><h2>${escape(card.title)}</h2><p>${escape(card.description)}</p><span class="card-arrow">${icon('arrow-right')}</span></a>`).join('');
  let expanded = false;
  function renderSuggestions() {
    $('suggestion-list').innerHTML = data.suggestions.slice(0,expanded ? undefined : 4).map(([title,subtitle,query]) => `<button class="suggestion" data-query="${escape(query)}">${icon('file')}<span><strong>${escape(title)}</strong><small>${escape(subtitle)}</small></span></button>`).join('');
    $('more').innerHTML = `${expanded ? 'Show less' : 'See more'} ${icon('arrow-right')}`;
  }
  renderSuggestions();
  $('more').onclick = () => { expanded = !expanded; renderSuggestions(); };
  $('suggestion-list').onclick = event => { const button = event.target.closest('[data-query]'); if(button) fillQuery(button.dataset.query); };
  let toastTimer;
  function toast(message) { $('toast').textContent = message; $('toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { $('toast').hidden = true; },4500); }
  function show(title,html) { $('detail-title').textContent = title; $('detail-content').innerHTML = html; $('detail').hidden = false; $('detail').focus({preventScroll:true}); $('detail').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth',block:'nearest'}); }
  const record = (title,body,status='') => `<article class="record"><h3>${escape(title)}</h3><p>${escape(body)}</p>${status ? `<small>${escape(status)}</small>` : ''}</article>`;
  const note = '<p>Illustrative content for this design preview. These are not verified competitive findings.</p>';
  function route() {
    const target = location.hash.slice(1) || 'home';
    document.querySelectorAll('.nav-item,.top-nav a').forEach(a => { const active = a.hash === `#${target}`; a.classList.toggle('active',active); if(active) a.setAttribute('aria-current','page'); else a.removeAttribute('aria-current'); });
    document.querySelector('.workspace').classList.remove('menu-open'); $('menu').setAttribute('aria-expanded','false');
    const views = {
      competitors: () => show('Tracked competitors',note + data.competitors.map(c => record(c.name,c.category,c.note)).join('')),
      signals: () => show('Recent signals',note + data.signals.map(s => record(s.title,s.description,s.status)).join('')),
      reports: () => show('Intelligence library',note + data.reports.map(r => record(r.title,r.description,'Sample report outline')).join('')),
      evidence: () => show('Evidence notebook', '<p>No verified evidence has been collected in this demo. A confirmed finding requires a source URL, quoted evidence, collection time, and confidence.</p>' + record('Source → Evidence → Finding','Use this space to inspect the original source and understand what it supports.','Preview · empty evidence state')),
      notes: () => show('Research notes',record('Questions worth exploring','How do competitors communicate plan limits? What changed in their positioning? Which claims still need a primary source?','Sample research prompts')),
      developer: () => show('Developer workspace','<p>This standalone preview has no live runs or tool traces. The production AgentRunner, persistence layer, and APIs are unchanged.</p>'),
      'fact-check': () => show('Check a finding', '<p>Select a source-backed finding to review its evidence, collection time, and confidence. No confirmed findings are available in this demo.</p>'),
      analyst: () => { $('detail').hidden = true; $('query').focus(); },
      summarize: () => { $('detail').hidden = true; fillQuery('Summarize the Notion competitor report'); },
      compare: () => { $('detail').hidden = true; fillQuery('Compare Notion and Asana pricing'); },
      export: () => show('Export a sample brief', '<p>Download a Markdown outline with clearly labeled sample content, or select and copy the text below.</p><label for="export-preview">Sample Markdown</label><textarea id="export-preview" class="export-preview" readonly spellcheck="false">' + escape(sampleBrief()) + '</textarea><button class="detail-action" id="download">Download sample .md</button>'),
      home: () => { $('detail').hidden = true; }
    };
    (views[target] || views.home)();
  }
  window.addEventListener('hashchange',route);
  // Repeated clicks on the current destination still reopen its panel.
  document.addEventListener('click',event => { const a = event.target.closest('a[href^="#"]'); if(a && a.hash === location.hash) { event.preventDefault(); route(); } });
  $('close-detail').onclick = () => { $('detail').hidden = true; location.hash = 'home'; document.querySelector('.feature-card').focus(); };
  $('new').onclick = () => { location.hash = 'home'; route(); fillQuery(''); };
  $('menu').onclick = () => { const open = document.querySelector('.workspace').classList.toggle('menu-open'); $('menu').setAttribute('aria-expanded',String(open)); };
  ['web-toggle','evidence-toggle'].forEach(id => { $(id).onclick = () => $(id).setAttribute('aria-pressed',String($(id).getAttribute('aria-pressed') !== 'true')); });
  $('notifications').onclick = () => toast('You are viewing sample content. No live monitoring notifications.');
  $('profile').onclick = () => toast('Universal Competitive Intelligence Agent · Editorial design preview');
  $('analyst-form').onsubmit = event => {
    event.preventDefault(); const query = $('query').value.trim();
    if(!query) { $('query').setCustomValidity('Enter a product name or a question.'); $('query').reportValidity(); return; }
    const web = $('web-toggle').getAttribute('aria-pressed') === 'true';
    const evidence = $('evidence-toggle').getAttribute('aria-pressed') === 'true';
    show('Your analysis, outlined', `<p><strong>${escape(query)}</strong></p><p>Preview only — no search was run and no facts were generated.</p>${record('01 · Identify the product','Resolve the product name and discover relevant official sources.')}${record('02 · Review the evidence',`${web ? 'Discover public sources' : 'Use available material'}; ${evidence ? 'attach source URL, evidence text, collection time, and confidence' : 'keep unsupported statements unconfirmed'}.`)}${record('03 · Build the brief',`Focus: ${$('focus').value}. Length: ${$('length').value}. Compare supported findings and mark missing information as unknown.`)}`);
  };
  $('query').oninput = () => $('query').setCustomValidity('');
  $('query').onkeydown = event => { if((event.ctrlKey || event.metaKey) && event.key === 'Enter') { event.preventDefault(); $('analyst-form').requestSubmit(); } };
  document.addEventListener('keydown',event => {
    if((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); $('search').focus(); }
    if(event.altKey && event.key.toLowerCase() === 'n') { event.preventDefault(); $('new').click(); }
    if(event.key === 'Escape') { $('search-results').hidden = true; document.querySelector('.workspace').classList.remove('menu-open'); $('menu').setAttribute('aria-expanded','false'); }
  });
  $('search').oninput = () => {
    const term = $('search').value.trim().toLowerCase(); $('search-results').hidden = !term;
    const entries = [...data.navigation.primary.map(([target,label]) => ({target,label})),...data.competitors.map(c => ({target:'competitors',label:c.name}))];
    const found = entries.filter(e => e.label.toLowerCase().includes(term));
    $('search-results').innerHTML = found.length ? found.map(e => `<a href="#${e.target}">${escape(e.label)}</a>`).join('') : '<p>No matches in the demo workspace.</p>';
  };
  $('search-results').onclick = event => { if(event.target.closest('a')) { $('search-results').hidden = true; $('search').value = ''; } };
  document.addEventListener('click',event => { if(!event.target.closest('.search-wrap')) $('search-results').hidden = true; });
  $('detail-content').onclick = event => {
    if(event.target.id !== 'download') return;
    const url = URL.createObjectURL(new Blob([sampleBrief()],{type:'text/markdown;charset=utf-8'}));
    const a = document.createElement('a'); a.href = url; a.download = 'sample-competitive-brief.md';
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url),30000);
    toast('Download requested. If no file appears, copy the Markdown preview.');
  };
  route();
})();
