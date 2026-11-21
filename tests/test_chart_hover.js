globalThis.window={};let listeners={},svgs=[];
globalThis.document={addEventListener:(kind,fn)=>listeners[kind]=fn,querySelectorAll:selector=>selector==='[data-chart-cursor]'?svgs.map(s=>s.cursor):svgs};
if(typeof load==='function')load('src/hk_quote/web/chart-hover.js');else require('node:vm').runInThisContext(require('node:fs').readFileSync('src/hk_quote/web/chart-hover.js','utf8'));
function assert(ok,message){if(!ok)throw Error(message)}
function node(dataset={}){return {dataset,attrs:{},setAttribute(k,v){this.attrs[k]=v}}}
function chart(size){
 const labels=Array.from({length:4},()=>({textContent:''}));
 const children={'[data-hover-vertical]':node(),'[data-hover-horizontal]':node(),'[data-hover-dot]':node(),'[data-hover-box]':node({boxWidth:260})};
 const cursor=node();cursor.querySelector=s=>children[s];cursor.querySelectorAll=()=>labels;
 const values=[[1794885300,30,50,82.2,200,false,'futu'],[1794885360,300,80,82.4,0,true,'local']];
 const svg={cursor,children,labels,dataset:{priceChart:'HK.02206',chartSize:size,chartValues:JSON.stringify(values)},viewBox:{baseVal:{width:480,height:230}},querySelector:()=>cursor,getScreenCTM:()=>({inverse:()=>({})}),createSVGPoint:()=>({x:0,y:0,matrixTransform(){return {x:(this.x-100)/2,y:(this.y-20)/2}}})};
 return svg;
}
for(const size of ['small','large']){
 let svg=chart(size);svgs=[svg];
 const move=x=>listeners.pointermove({target:{closest:()=>svg},clientX:x*2+100,clientY:120});
 move(30);assert(svg.labels[1].textContent.includes('82.200'),'price absent');assert(svg.labels[2].textContent.includes('200'),'volume absent');assert(svg.labels[0].textContent.includes('HKT'),'timezone absent');assert(svg.children['[data-hover-vertical]'].attrs.x1===30,'scaled cursor misplaced');
 svg=chart(size);svgs=[svg];window.ChartHover.restore();assert(svg.cursor.attrs.display==='inline','refresh lost hover');
 move(300);assert(svg.labels[1].textContent.includes('沿用前价'),'synthetic price not marked');assert(svg.labels[2].textContent.includes('未知'),'synthetic volume misrepresented');
 listeners.pointermove({target:{closest:()=>null}});assert(svg.cursor.attrs.display==='none','cursor did not hide');
}
assert(window.ChartHover.nearest([[1,10],[2,30]],24)[0]===2,'nearest minute mismatch');
if(typeof print==='function')print('Small/large chart hover, scaling, refresh and synthetic-data checks passed');else console.log('Chart hover checks passed');
