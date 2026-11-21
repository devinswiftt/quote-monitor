globalThis.window={};load('src/hk_quote/web/broker-analysis.js');
const value={status:'interval',reason:'共享区间',note:'非成交归属',from_source:'2026-11-19 10:00:00',to_source:'2026-11-19 10:01:00',before_id:1,after_id:2,before_delay:20,after_delay:30,related:['#1','B2'],candidates:[{name:'凯基<测试>',before_net:-100,after_net:-600,delta:-500,meaning:'净卖量增加／净买量减少',aligned:true,queue_context:['ask']}],unmatched:[{name:'富途证券',status:'终点未知'}]};
let html=window.BrokerView.attribution(value);
for(const word of ['获取延迟','共享区间','-500','凯基&lt;测试&gt;','卖1在场','终点未知','尚未取得该日收盘后'])if(!html.includes(word))throw Error('Missing '+word);
value.closing_review={source:'2026-11-19 16:05:00',changes:[{name:'凯基',event_after_net:-600,closing_net:null,delta_since_event:null}]};html=window.BrokerView.attribution(value);if(!html.includes('收盘后末次快照复核')||!html.includes('不可算'))throw Error('Closing view incorrect');
if(!window.BrokerView.attribution({status:'waiting',reason:'等待新快照'}).includes('等待新快照'))throw Error('Waiting missing');
print('Delayed broker rendering: shared interval, timestamps, escaping, missing values, queue and closing review passed');
