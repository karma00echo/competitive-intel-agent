// Execute the production renderer against a minimal DOM, without HTTP or a browser.
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
class Element {
  constructor(tag,text=''){this.tag=tag;this.value=String(text);this.children=[];this.events={};this.style={};this.dataset={};this.open=false;}
  set textContent(value){this.value=String(value);this.children=[];}
  get textContent(){return this.value+this.children.map(c=>c.textContent).join('');}
  append(...items){this.children.push(...items);}
  addEventListener(name,callback){this.events[name]=callback;}
  scrollIntoView(){this.scrolled=true;}
}
const document={body:{dataset:{page:'offline-test'}},createElement:tag=>new Element(tag),createTextNode:text=>new Element('#text',text)};
const context={document};vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),context);
const report=JSON.parse(fs.readFileSync(0,'utf8')),target=new Element('main');
context.renderCompetitiveReading(target,report);
const view=report.content_json.presentation;
const sections=target.children.filter(e=>e.tag==='section');
assert.equal(sections.length,view.sections.length);
for(let i=0;i<sections.length;i++){
  const rendered=sections[i],source=view.sections[i];
  assert.equal(rendered.children[0].textContent,source.heading);
  assert.deepEqual(rendered.children.filter(e=>e.tag==='p').map(e=>e.textContent),source.paragraphs);
  const table=rendered.children.find(e=>e.tag==='table');
  if(source.headers)assert.deepEqual(table.children.map(r=>r.children.map(c=>c.textContent)),[source.headers,...source.rows]);
}
const details=target.children.filter(e=>e.tag==='details');
assert.equal(details.length,2);assert.equal(details[0].open,false);assert.equal(details[1].open,false);
function descendants(root){return [root,...root.children.flatMap(descendants)];}
const citation=sections.flatMap(descendants).find(e=>e.tag==='a');
assert.ok(citation);let prevented=false;citation.events.click({preventDefault(){prevented=true;}});
assert.equal(prevented,true);assert.equal(details[0].open,true);
assert.ok(descendants(details[0]).some(e=>e.scrolled));
assert.ok(!sections.some(s=>s.textContent.includes('claim-')));
assert.ok(!descendants(target).some(e=>e.tag==='script'));
console.log('production renderer: text parity, citations, collapsed audit and safe text passed');
