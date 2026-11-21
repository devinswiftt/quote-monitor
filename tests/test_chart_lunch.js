const source=typeof readFile==='function'?readFile('src/hk_quote/web/app.js'):require('node:fs').readFileSync('src/hk_quote/web/app.js','utf8');
let captured,chartBars={},names={};
const esc=v=>String(v),when=t=>new Date(t*1000).toLocaleString('sv-SE',{timeZone:'Asia/Hong_Kong'});
const BehaviorView={markers:()=>''},ChartHover={attributes:(bars,x)=>{captured={bars,x};return ''},frame:()=>''};
const code=source.slice(source.indexOf('function chartTradingTime('),source.indexOf('\nfunction drawChart'));
const render=new Function('chartBars','names','esc','when','BehaviorView','ChartHover','behaviorRows',code+';return chartSvg;')(chartBars,names,esc,when,BehaviorView,ChartHover,[]);
const ts=time=>Date.parse('2026-11-17T'+time+':00+08:00')/1000;
chartBars.TEST=['11:58','11:59','12:00','12:30','13:00','13:01'].map(t=>({time:ts(t),open:82,close:82,volume:100}));
for(const large of [false,true]){
 const html=render('TEST',large);
 if(captured.bars.length!==4)throw Error('Lunch data included');
 const before=captured.x(ts('11:59'))-captured.x(ts('11:58'));
 const across=captured.x(ts('13:00'))-captured.x(ts('11:59'));
 if(Math.abs(before-across)>1e-6)throw Error('Lunch gap was not compressed');
 if(html.includes('12:00')||html.includes('12:30'))throw Error('Lunch label included');
 if(!html.includes('13:00'))throw Error('Afternoon session missing');
}
chartBars.TEST=[{time:ts('13:00'),open:82,close:82,volume:100}];
if(render('TEST').includes('NaN'))throw Error('Single minute axis is invalid');
if(typeof print==='function')print('Small/large lunch compression, labels and single-minute checks passed');else console.log('Lunch axis checks passed');
