globalThis.window={BrokerView:{detail:()=>''}};load('src/hk_quote/web/behavior.js');
const base={code:'HK.02206',started_at:1795068227,updated_at:1795068314,phase:'resolved',evidence:{},signals:[],alert_ids:[]};
const rows=[{...base,id:1,type:'LIFT',history:[{ts:base.started_at,type:'LIFT',phase:'observing'}]}, {...base,id:2,type:'LIFT',history:[{ts:base.started_at,type:'LIFT',phase:'confirmed'}]}, {...base,id:3,type:'DUMP',history:[{ts:base.started_at,type:'DUMP',phase:'confirmed'}]}, {...base,id:4,code:'HK.02065',type:'DUMP',history:[]}];
function check(code,type,phase,total,confirmed){const html=window.BehaviorView.render(rows,{},code,type,phase);if(!html.includes(`共 ${total} 条 · 曾确认 ${confirmed} 条 · 仅观察 ${total-confirmed} 条`))throw Error('Counts mismatch '+phase);if((html.match(/data-behavior-id=/g)||[]).length!==total)throw Error('List mismatch '+phase);return html;}
const html=check('HK.02206','','',3,2);if(!html.includes('已结束 · 观察结束')||!html.includes('曾确认：疑似主动拉升'))throw Error('Separate confirmation/state missing');
check('HK.02206','LIFT','',2,1);check('HK.02206','','confirmed',2,2);check('HK.02206','','unconfirmed',1,0);check('HK.02206','','active',0,0);check('HK.02206','','ended',3,2);
rows[0].type='SUPPORT';rows[0].history.push({ts:base.started_at+2,type:'DUMP',phase:'confirmed'});
const changed=check('HK.02206','SUPPORT','',1,1);if(!changed.includes('曾确认：疑似砸盘'))throw Error('Confirmed type transition hidden');
print('Behavior counts, filters, ended observations and transitions passed');
