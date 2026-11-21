/* Run from the repository root with Node.js or the JavaScriptCore shell. */
globalThis.window={};
if(typeof load==='function')load('src/hk_quote/web/broker-analysis.js');
else require('node:vm').runInThisContext(require('node:fs').readFileSync('src/hk_quote/web/broker-analysis.js','utf8'));
function assert(condition,message){if(!condition)throw Error(message)}
class SummaryRoot{
 constructor(){this.nodes=[];this.scrollers=[];this.writes=0}
 set innerHTML(value){
  this.writes++;
  this.nodes=[...value.matchAll(/data-broker-disclosure="([^"]+)"/g)].map(m=>({tagName:'DETAILS',dataset:{brokerDisclosure:m[1]},open:false,querySelectorAll:()=>this.scrollers}));
  this.scrollers=[...value.matchAll(/class="table-scroll"/g)].map(()=>({scrollLeft:0,scrollTop:0}));
 }
 querySelectorAll(selector){return (selector==='[data-broker-disclosure]'||selector==='details')?this.nodes:this.scrollers}
}
const row={code:'HK.02206',side:'bid',name:'测试券商',ids:['1234'],changed_alerts:1,alerts:2,eligible_alerts:3,clue_alerts:0};
const render=window.BrokerView.renderSummary;
for(const page of ['dashboard','analysis']){
 const root=new SummaryRoot();render(root,[row],row.code);
 assert(!root.nodes[0].open,page+': first render must stay collapsed');
 root.nodes[0].open=true;root.scrollers[0].scrollLeft=150;root.scrollers[0].scrollTop=20;
 render(root,[{...row}],row.code);
 assert(root.writes===1,page+': unchanged polling must reuse DOM');
 assert(root.nodes[0].open,page+': polling closed disclosure');
 render(root,[{...row,alerts:3}],row.code);
 assert(root.writes===2&&root.nodes[0].open,page+': changed data lost expanded state');
 assert(root.scrollers[0].scrollLeft===150&&root.scrollers[0].scrollTop===20,page+': scroll position lost');
 root.nodes[0].open=false;
 render(root,[],row.code);
 assert(!root.nodes[0].open,page+': user collapse must persist with empty data');
 root.nodes[0].open=true;
 render(root,[row],'HK.02065');
 assert(root.nodes[0].open,page+': filtering to no data must not force collapse');
}
if(typeof print==='function')print('Disclosure refresh regression checks passed for both pages');
else console.log('Disclosure refresh regression checks passed for both pages');
// Nested panels with the same label must retain state independently per record.
for(const attribute of ['id','analysisId','behaviorId']){
 const tree={nodes:[],querySelectorAll(){return this.nodes},set innerHTML(version){
  const ids=version==='first'?['1','2']:['2','3','1'];this.nodes=[];
  for(const id of ids){
   const scroll={scrollLeft:0,scrollTop:0};
   const parent={tagName:'DETAILS',dataset:{[attribute]:id},parentElement:this,open:false,querySelectorAll:()=>[scroll]};
   const child={tagName:'DETAILS',dataset:{},parentElement:parent,open:false,querySelector:()=>({textContent:'查看买1／卖1在场名单与规则'}),querySelectorAll:()=>[scroll],scroll};
   this.nodes.push(parent,child);
  }
 }};
 window.BrokerView.replaceContent(tree,'first');
 tree.nodes[0].open=true;tree.nodes[1].open=true;tree.nodes[1].scroll.scrollLeft=120;
 window.BrokerView.replaceContent(tree,'changed');
 const panel=id=>tree.nodes.find(n=>n.parentElement.dataset?.[attribute]===id);
 assert(panel('1').open,attribute+': nested panel closed after refresh/reorder');
 assert(panel('1').scroll.scrollLeft===120,attribute+': nested table scroll lost');
 assert(!panel('2').open,attribute+': another record inherited expanded state');
 assert(!panel('3').open,attribute+': new record inherited expanded state');
 panel('1').open=false;
 window.BrokerView.replaceContent(tree,'changed-again');
 assert(!panel('1').open,attribute+': manual collapse was not preserved');
}
if(typeof print==='function')print('Nested disclosures passed for raw alerts, analysis and behavior records');
