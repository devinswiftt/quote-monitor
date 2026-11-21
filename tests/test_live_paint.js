const source=readFile('src/hk_quote/web/app.js'),nodes=new Map(),timers=[];let clock=1000,stream;
const node=id=>{if(!nodes.has(id))nodes.set(id,{value:'',dataset:{},events:{},addEventListener(k,f){this.events[k]=f}});return nodes.get(id)};
const document={hidden:false,addEventListener(){},querySelectorAll:()=>[],querySelector:()=>null,getElementById:node};
class EventSource{constructor(){stream=this;this.readyState=1}}
class FakeDate extends Date{static now(){return clock}}
const body=source.slice(0,source.lastIndexOf('refresh();setInterval'));
const api=new Function('document','EventSource','setTimeout','clearTimeout','Date',body+`;let draws=0,queues=0;drawChart=()=>draws++;updateQueue=()=>queues++;stockData=[{code:'US.QQQ'}];return {connect:connectLive,flush:flushLivePaint,bar:()=>chartBars['US.QQQ'][0],draws:()=>draws,queues:()=>queues};`)(document,EventSource,fn=>{timers.push(fn);return timers.length},()=>{},FakeDate);
node('quote-symbol').value='US.QQQ';api.connect();
function tick(i){stream.onmessage({data:JSON.stringify({kind:'tick',code:'US.QQQ',ts:1000+i*.001,sequence:String(i),price:100+i*.01,amount:100,volume:1})})}
for(let i=1;i<=100;i++)tick(i);
if(timers.length!==1||api.draws()!==0)throw Error('One timer per batch required');
if(api.bar().volume!==100)throw Error('Trades dropped before paint');
api.flush();if(api.draws()!==1)throw Error('First batch not painted');
for(let i=101;i<=150;i++)tick(i);
api.flush();if(api.draws()!==1||api.bar().volume!==150)throw Error('Chart paint not bounded or aggregation dropped');
clock+=201;api.flush();if(api.draws()!==2)throw Error('Latest aggregate not eventually painted');
node('quote-symbol').value='HK.02206';tick(151);clock+=201;api.flush();if(api.draws()!==2||api.bar().volume!==151)throw Error('Offscreen stock repaint or event loss');
node('quote-symbol').value='US.QQQ';document.hidden=true;tick(152);api.flush();if(api.draws()!==2)throw Error('Hidden tab painted');
print('Tick aggregation preserved; DOM batches bounded; unselected and hidden charts skip paint');
