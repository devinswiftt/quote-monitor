globalThis.window={BrokerView:{detail:()=>'<p>券商证据</p>'}};
load('src/hk_quote/web/behavior.js');
const r={id:21,code:'HK.02206',started_at:1795068227,updated_at:1795068314,type:'DUMP',phase:'resolved',source:'live',history:[{ts:1795068227,type:'DUMP',phase:'observing'},{ts:1795068230,type:'DUMP',phase:'confirmed'}],evidence:{price_from:110.9,price_to:109.1,window_seconds:60,amount:423030},alert_ids:[],signals:[]};
let html=window.BehaviorView.journal(r,{'HK.02206':'新荷花'});
for(const word of ['data-id="B21"','疑似砸盘','新荷花','曾达到确认条件','42.30 万港元','行为监控可独立触发','事件过程'])if(!html.includes(word))throw Error('Missing '+word);
r.history=r.history.slice(0,1);html=window.BehaviorView.journal(r,{});
if(!html.includes('仅观察，未达到确认条件'))throw Error('Observation mislabeled');
print('Journal rendering passed');
