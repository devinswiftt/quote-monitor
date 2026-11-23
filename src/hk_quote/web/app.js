const $=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=(v,code='')=>v==null?'—':(Number(v)/10000).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2})+(String(code).startsWith('US.')?' 万美元':' 万港元');
const when=(t,code='')=>t?new Date(t*1000).toLocaleString('sv-SE',{timeZone:String(code).startsWith('US.')?'America/New_York':'Asia/Hong_Kong'}):'时间未知';
let marketStage='',usConnectionState=null;
let loggedOut=false;
let defaultQuoteSymbol='';
let recordFollowsQuote=true;
let page=1,pageSize=20,pageAnchor=null,pageBehaviorAnchor=null,pageInfo={pages:1},requestVersion=0;
let behaviorRows=[],records=[],names={},total=0,busy=false,stockData=[],livePrices={},chartBars={},liveStream=null,connectionState=null;
const title=a=>`${a.name||names[a.code]||a.code} ${a.code}`;
const labels={BUY:'疑似主动买入',SELL:'疑似主动卖出',VOLUME:'异常成交放大',depth:'盘口变化'};
function motionSummary(a){
 const m=a.motion;if(!m)return '';
 return `<div class="time">${Number(a.window_seconds||3)} 秒量价证据：${Number(a.price-m.change).toFixed(3)} → ${Number(a.price).toFixed(3)} · ${m.change_pct>=0?'+':''}${Number(m.change_pct).toFixed(3)}% · 动态价格门槛 ${Number(m.price_threshold_pct).toFixed(3)}% · 单向推进 ${Math.round(m.efficiency*100)}% · ${m.steps} 次采样价变化${m.spread_available?' · 已计入买卖价差':' · 盘口价差不可用，仅按成交波动判断'}</div>`;
}
function brokers(rows){return rows?.length?`<table><thead><tr><th>编号</th><th>券商名称</th><th>档位</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(r.id)}</td><td>${esc(r.name)}</td><td>${esc(r.position)}</td></tr>`).join('')}</tbody></table>`:'<p class="muted">暂无经纪队列数据</p>'}
function draw(){
 const opened=new Set([...document.querySelectorAll('.record[open]')].map(x=>x.dataset.id));
 const stock=$('record-symbol').value,direction=$('direction').value,date=$('date').value,search=$('search').value.trim().toLowerCase();
 $('activity-analysis-link').hidden=stock.startsWith('US.');
 $('activity-analysis-link').href='/api/report?'+new URLSearchParams({code:stock,date}).toString();
 const filtered=records.filter(a=>(!stock||a.code===stock)&&(!direction||(direction==='trade'?['BUY','SELL','VOLUME'].includes(a.kind||a.signal):direction==='behavior'?a.entry_type==='behavior':(a.kind||a.signal)===direction))&&(!date||when(a.ts,a.code).startsWith(date))&&(!search||JSON.stringify({...a,name:a.name||names[a.code]}).toLowerCase().includes(search)));
 $('count').textContent=total?`${(page-1)*pageSize+1}–${(page-1)*pageSize+filtered.length} / ${total}`:'0 条';
 BrokerView.replaceContent($('records'),filtered.map(a=>{
  if(a.entry_type==='behavior')return BehaviorView.journal(a.behavior,names);
  const kind=a.kind||a.signal,b=a.broker_context,us=a.code.startsWith('US.'),symbol=us?'US$':'HK$',unit=us?'美元':'港元';
  const brokerDetail=us?'<p class="broker-note">美股数据不提供港股式成交券商身份；价格方向反映走势，成交方向字段仅作补充，不代表机构身份。</p>':b?.bid||b?.ask?`<p class="broker-note">${esc(b.note)}<br>快照接收时间 ${esc(when(b.captured_at))} · 距触发 ${esc(b.age_seconds)} 秒 ${b.status==='stale'?'· 快照较旧，仅供背景参考':''}</p><div class="broker-grid"><div><h3>买盘经纪队列</h3>${brokers(b.bid)}</div><div><h3>卖盘经纪队列</h3>${brokers(b.ask)}</div></div>`:'<p class="broker-note">此记录未保存经纪队列。旧记录无法事后补齐，或当时权限／数据不可用。</p>';
  const priceLine=a.amount!=null?`<div class="time">触发成交价：${a.price!=null?symbol+' '+Number(a.price).toFixed(3):'旧记录未保存'} · 上次异动成交价：${a.previous_price!=null?symbol+' '+Number(a.previous_price).toFixed(3):'未记录／首次异动'} · ${a.price_delta_pct!=null?'较上次异动 '+(a.price_delta>=0?'+':'')+Number(a.price_delta).toFixed(3)+' '+unit+'（'+(a.price_delta_pct>=0?'+':'')+Number(a.price_delta_pct).toFixed(2)+'%）':a.previous_alert_id?'上次记录未保存价格':'无可比较的上次记录'}</div>`:'';
  const profile=a.participation;
  const inferenceText=a.amount==null||us?'':BrokerView.detail(profile);
  return `<details class="record" data-id="${a.id}" ${opened.has(String(a.id))?'open':''}><summary><div><div class="title"><span class="pill ${kind==='SELL'?'sell':kind==='depth'?'depth':''}">${esc(a.signal_label||labels[kind]||kind)}</span>${esc(title(a))}</div><div class="time">${esc(when(a.ts,a.code))}${us?' ET':''}　${esc(a.level||'系统提醒')}　#${a.id}</div>${priceLine}${motionSummary(a)}${BrokerView.notice(a)}${(a.related_behaviors||[]).length?`<div class="time">关联行为 ${(a.related_behaviors||[]).map(r=>`B${r.id} ${esc(BehaviorView.labels[r.type]||r.type)}`).join(' · ')} · 同一行为的成交证据</div>`:''}</div><div class="money">${a.amount!=null?money(a.amount,a.code):'盘口状态'}<small>${a.threshold!=null?'触发门槛 '+money(a.threshold,a.code):esc(a.message||'')}　⌄</small></div></summary><div class="detail">${a.amount!=null?`<div class="metrics"><span>${['percentile','rolling_joint'].includes(a.threshold_method)?'门槛来源：P'+Math.round((a.threshold_quantile||.99)*100)+' × '+(a.threshold_multiplier||1.2)+'（'+a.threshold_profile.samples+(a.threshold_method==='rolling_joint'?' 个滚动采样窗口）':' 个非空窗口）'):'门槛来源：旧版均值规则'}</span><span>放大 ${a.multiple==null?'无有效基线':a.multiple+' 倍'}</span><span>方向集中度 ${Math.round((a.direction_ratio||0)*100)}%</span><span>方向覆盖率 ${Math.round((a.coverage||0)*100)}%</span><span>有效盘口 ${a.depth} 档</span>${a.previous_price!=null?`<span>上次异动 #${a.previous_alert_id}：${symbol} ${Number(a.previous_price).toFixed(3)} · ${esc(when(a.previous_alert_time,a.code))}</span>`:''}</div>`:''}${inferenceText}${brokerDetail}</div></details>`;
 }).join('')||'<div class="empty">暂无符合筛选条件的异动记录。行情监听继续运行。</div>');
 $('page-label').textContent=`第 ${page} / ${pageInfo.pages} 页 · 共 ${total} 条`;
 $('page-first').disabled=$('page-prev').disabled=page<=1;
 $('page-next').disabled=page>=pageInfo.pages;
}
function rememberPrice(e){
 const old=livePrices[e.code];
 if(!old||e.ts>old.ts||(e.ts===old.ts&&(e.received_at||0)>(old.received_at||0)))livePrices[e.code]=e;
}
function priceTime(code){if(code.startsWith('US.')){const e=livePrices[code],s=usConnectionState;return e?(s?.state==='connected'?'':'历史／预热数据 · ')+'行情更新 '+esc(when(e.ts,code))+' ET':'等待美股实时推送'}const e=livePrices[code];return e?(connectionState?.state==='connected'?'':'历史／预热数据 · ')+'行情更新 '+esc(new Date(e.ts*1000).toLocaleTimeString('zh-CN',{timeZone:'Asia/Hong_Kong',hour12:false}))+' HKT':'等待报价推送'}
let expandedChart=null;
function chartTradingTime(ts,code=''){
 if(String(code).startsWith('US.'))return ts;
 const local=ts+8*3600,day=Math.floor(local/86400),seconds=local-day*86400;
 return day*82800+seconds-Math.max(0,Math.min(3600,seconds-12*3600));
}
function isDarkStock(stock){
 const quote=stock?.quote;
 return quote?.dark_status==='TRADING' && new Date(quote.ts*1000).toLocaleDateString('sv-SE',{timeZone:'Asia/Hong_Kong'})===new Date().toLocaleDateString('sv-SE',{timeZone:'Asia/Hong_Kong'});
}
function chartIsTradingMinute(ts,code=''){
 if(String(code).startsWith('US.')){const cache=chartIsTradingMinute.cache||(chartIsTradingMinute.cache=new Map()),key=Math.floor(ts/60);if(cache.has(key))return cache.get(key);const formatter=chartIsTradingMinute.formatter||(chartIsTradingMinute.formatter=new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',hour:'2-digit',minute:'2-digit',hour12:false}));const values=Object.fromEntries(formatter.formatToParts(new Date(ts*1000)).map(p=>[p.type,p.value]));const minute=Number(values.hour)*60+Number(values.minute),result=minute>=240&&minute<1200;if(cache.size>4000)cache.clear();cache.set(key,result);return result}
 const date=new Date((ts+8*3600)*1000),minute=date.getUTCHours()*60+date.getUTCMinutes();
 if(typeof stockData!=='undefined'&&isDarkStock(stockData.find(stock=>stock.code===code)))return minute>=975&&minute<1110;
 return (minute>=570&&minute<720)||(minute>=780&&minute<960);
}
function chartSvg(code,large=false){
 const us=String(code).startsWith('US.'),unit=us?'美元':'港元',chartWhen=t=>new Date(t*1000).toLocaleString('sv-SE',{timeZone:us?'America/New_York':'Asia/Hong_Kong'});
 const source=(chartBars[code]||[]).filter(b=>chartIsTradingMinute(b.time,code)).slice().sort((a,b)=>a.time-b.time);
 const filled=[];
 for(let i=0;i<source.length;i++){
  const b=source[i],previous=source[i-1];
  if(previous){for(let t=previous.time+60;t<b.time;t+=60){const hk=new Date((t+8*3600)*1000),m=hk.getUTCHours()*60+hk.getUTCMinutes();if(chartIsTradingMinute(t,code))filled.push({time:t,open:previous.close,close:previous.close,high:previous.close,low:previous.close,volume:0,synthetic:true})}}
  filled.push(b);
 }
 const bars=filled.slice(large?0:-60);
 if(!bars.length)return '<p class="empty">等待采集成交生成走势与成交量</p>';
 const width=large?1100:480,height=large?480:230,left=large?24:8,right=65,top=22,priceBottom=large?300:132,volumeTop=large?340:158,volumeBottom=height-32;
 const prices=bars.map(b=>b.close),high=Math.max(...prices),low=Math.min(...prices),padding=Math.max((high-low)*.15,high*.001,.001),max=high+padding,min=low-padding;
 const first=bars[0].time,last=bars[bars.length-1].time,span=Math.max(chartTradingTime(last,code)-chartTradingTime(first,code),60);
 const x=t=>left+(chartTradingTime(t,code)-chartTradingTime(first,code))/span*(width-left-right),y=p=>top+(max-p)/(max-min)*(priceBottom-top);
 const vmax=Math.max(1,...bars.map(b=>Number(b.volume||0))),barWidth=Math.min(large?13:6,(width-left-right)*60/span*.7);
 let path='';bars.forEach((b,i)=>{path+=(i===0||b.time-bars[i-1].time>90?'M':'L')+x(b.time).toFixed(2)+','+y(b.close).toFixed(2)+' '});
 const behaviorMarks=BehaviorView.markers(behaviorRows,code,first,last,x,top,priceBottom);
 const grid=[high,(high+low)/2,low].map(p=>`<line x1="${left}" x2="${width-right}" y1="${y(p)}" y2="${y(p)}" stroke="#e3e9df" stroke-dasharray="3 5"/><text x="${width-right+8}" y="${y(p)+4}" font-size="11" fill="#82917e">${p.toFixed(3)}</text>`).join('');
 const volumes=bars.map((b,i)=>{const h=Number(b.volume||0)/vmax*(volumeBottom-volumeTop),color=b.close>=(bars[i-1]?.close??b.open)?'#b98b70':'#76a791';return `<rect x="${x(b.time)-barWidth/2}" y="${volumeBottom-h}" width="${barWidth}" height="${h}" fill="${color}" opacity=".85"><title>${esc(chartWhen(b.time))} · 成交价 ${b.close.toFixed(3)} · ${b.synthetic?'补齐显示：沿用上次价格，成交量未知（图上按0显示）':'成交量 '+Number(b.volume||0).toLocaleString('zh-CN')+' 股'}</title></rect>`}).join('');
 const count=Math.min(large?6:3,bars.length);
 const times=Array.from({length:count},(_,i)=>{const t=bars[Math.round((bars.length-1)*i/Math.max(1,count-1))].time;return `<text x="${x(t)}" y="${height-8}" text-anchor="${i===0?'start':i===count-1?'end':'middle'}" font-size="11" fill="#82917e">${esc(chartWhen(t).slice(11,16))}</text>`}).join('');
 const points=bars.filter(b=>!b.synthetic).map(b=>`<circle cx="${x(b.time)}" cy="${y(b.close)}" r="${large?3:2}" fill="#35785c"><title>${esc(chartWhen(b.time))} · ${b.close.toFixed(3)} ${unit} · ${Number(b.volume||0).toLocaleString('zh-CN')} 股</title></circle>`).join('');
 return `<svg ${ChartHover.attributes(bars,x,y,code,large)} viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(names[code]||code)} 分钟价格曲线与成交量，共用${us?'纽约':'香港'}时间轴">${behaviorMarks}${grid}<text x="${left}" y="13" font-size="11" fill="#82917e">价格 · ${unit}</text><path d="${path}" fill="none" stroke="#35785c" stroke-width="${large?2.5:2}" stroke-linecap="round" stroke-linejoin="round"/>${points}<line x1="${left}" x2="${width-right}" y1="${volumeBottom}" y2="${volumeBottom}" stroke="#dce5d9"/><text x="${left}" y="${volumeTop-7}" font-size="11" fill="#82917e">成交量 · 股</text><text x="${width-right+8}" y="${volumeTop+10}" font-size="11" fill="#82917e">${vmax.toLocaleString('zh-CN')}</text>${volumes}${times}${ChartHover.frame(width,height,left,right,top,volumeBottom)}</svg>`;
}
function drawChart(code){
 const node=document.querySelector('[data-chart="'+code+'"]');if(!node&&expandedChart!==code)return;if(node)node.innerHTML=chartSvg(code);
 if(expandedChart===code){$('expanded-chart').innerHTML=chartSvg(code,true);$('chart-live-price').textContent=livePrices[code]?'最新价 '+Number(livePrices[code].price).toFixed(3)+(code.startsWith('US.')?' 美元':' 港元'):''}
 ChartHover.restore();
}
function openChart(code){if(!code)return;expandedChart=code;$('chart-title').textContent=(names[code]||code)+' '+code+' · 分钟走势';drawChart(code);$('chart-dialog').hidden=false;$('chart-dialog').setAttribute('aria-hidden','false');document.body.classList.add('chart-modal-open');$('chart-close').focus()}
document.addEventListener('click',event=>{const target=event.target.closest('[data-chart-open]');if(target)openChart(target.dataset.chartOpen)});
function closeChart(){ChartHover.clear();expandedChart=null;$('chart-dialog').hidden=true;$('chart-dialog').setAttribute('aria-hidden','true');document.body.classList.remove('chart-modal-open')}
$('chart-close').addEventListener('click',closeChart);
document.addEventListener('keydown',event=>{if(event.key==='Escape')closeChart();const target=event.target.closest?.('[data-chart-open]');if(target&&(event.key==='Enter'||event.key===' ')){event.preventDefault();openChart(target.dataset.chartOpen)}});
$('chart-dialog').addEventListener('click',event=>{if(event.target===$('chart-dialog'))closeChart()});
function sameBookDay(s){
 const day=ts=>Number.isFinite(ts)?new Date(ts*1000).toLocaleDateString('sv-SE',{timeZone:'Asia/Hong_Kong'}):null;
 const bookDay=day(s.book?.received_at||s.book?.ts);
 return !!bookDay&&bookDay===day(s.broker?.received_at||s.broker?.ts);
}
function depthBrokerNames(s,side,position){
 if(isDarkStock(s))return '<span class="muted">暗盘暂未提供经纪队列</span>';
 if(!sameBookDay(s))return '<span class="muted">等待当日经纪队列</span>';
 const rows=(s.broker?.[side]||[]).filter(r=>Number(r.position)===position);
 return rows.length?rows.map(r=>`<span class="broker-tag">${esc(r.name)} <small>[${esc(r.id)}]</small></span>`).join(' '):'<span class="muted">该档暂无经纪数据</span>';
}
function queuePanels(s){
 if(String(s.code||'').startsWith('US.')){const side=(key,label)=>`<section><h3>${label}</h3><table><thead><tr><th>档位</th><th>美元</th><th>挂单股数</th><th>订单数</th></tr></thead><tbody>${(s.book?.[key]||[]).map((r,i)=>`<tr><td>${i+1}</td><td>${Number(r[0]).toFixed(3)}</td><td>${Number(r[1]).toLocaleString('zh-CN')}</td><td>${r[2]>0?r[2]:'未提供'}</td></tr>`).join('')}</tbody></table></section>`;return `<p class="broker-note">${s.book?'盘口接收 '+esc(when(s.book.received_at||s.book.ts,s.code))+' ET':'等待盘口数据；权限不足时价格与成交监控仍可运行'}。仅显示数据源可见盘口，不提供成交券商身份。</p><div class="live-book-grid">${side('bid','买盘 BID')}${side('ask','卖盘 ASK')}</div>`}

 const number=v=>Number(v||0).toLocaleString('zh-CN');
 const side=(key,label)=>{const levels=s.book?.[key]||[];return `<section><h3>${label}</h3><table><thead><tr><th>档位</th><th>价格</th><th>挂单总股数</th><th>订单笔数</th><th>该档券商（编号）</th></tr></thead><tbody>${levels.map((r,i)=>`<tr><td>${i+1}</td><td>${Number(r[0]).toFixed(3)}</td><td>${number(r[1])}</td><td>${number(r[2])}</td><td class="depth-brokers">${depthBrokerNames(s,key,i+1)}</td></tr>`).join('')}</tbody></table><p class="muted">可见档位合计：${number(levels.reduce((n,r)=>n+Number(r[1]),0))} 股 · ${number(levels.reduce((n,r)=>n+Number(r[2]),0))} 笔订单</p>${sameBookDay(s)&&(s.broker?.[key]||[]).some(r=>Number(r.position)>levels.length)?`<p class="muted">另有 ${(s.broker?.[key]||[]).filter(r=>Number(r.position)>levels.length).length} 条经纪队列信息超出当前 ${levels.length} 档盘口，已保留原始数据。</p>`:''}</section>`};
 return `<p class="broker-note">盘口接收：${esc(when(s.book?.received_at||s.book?.ts))} · 经纪队列接收：${esc(when(s.broker?.received_at||s.broker?.ts))}<br>${s.broker&&!sameBookDay(s)?'经纪队列与盘口日期不一致，等待当日队列更新。':'盘口与经纪队列分别更新。'}订单笔数为该价位的委托数量；券商队列反映挂盘参与者，无法逐笔对应订单。</p><div class="live-book-grid">${side('bid','买盘 · BID')}${side('ask','卖盘 · ASK')}</div>`;
}
function updateQueue(code){const s=stockData.find(s=>s.code===code),node=document.querySelector('[data-live-queues="'+code+'"]');if(s&&node)node.innerHTML=queuePanels(s)}
function renderConnection(state){
 if(state?.market==='US')usConnectionState=state;else if(state)connectionState=state;
 const selected=$('quote-symbol').value||'',us=selected.startsWith('US.');
 const s=(us?usConnectionState:connectionState)||{state:'checking',message:'等待行情状态'};
 const healthy=s.state==='connected',bad=['disconnected','stopped'].includes(s.state);
 $('sync').textContent=s.message||'等待行情状态';$('sync-dot').style.color=healthy?'#638e61':bad?'#b36955':'#b99144';
 const times=Object.values(livePrices).filter(e=>String(e.code).startsWith('US.')===us).map(e=>e.ts).filter(Number.isFinite),last=times.length?Math.max(...times):null;
 $('updated').textContent='行情检查 '+(s.checked_at?when(s.checked_at,selected).slice(11,19):'尚未完成')+' · 最近报价 '+(last?when(last,selected).slice(11,19):'暂无')+(us?' ET':' HKT');
 $('transport').textContent=liveStream?.readyState===1?'网页推送通道已连接（不代表行情在线）':'网页推送通道正在重连';
 document.querySelectorAll('[data-live-time]').forEach(node=>node.innerHTML=priceTime(node.dataset.liveTime));
}
/* Keep every incoming event in memory; batch only DOM paint work. */
const pendingLivePaint=new Map();let livePaintTimer=null,lastChartPaint=0;
function scheduleLivePaint(code,kind){
 const flags=pendingLivePaint.get(code)||{price:false,chart:false,queue:false};
 if(kind==='tick'||kind==='quote'||kind==='auction_tick')flags.price=true;
 if(kind==='tick')flags.chart=true;
 if(['book_snapshot','broker','depth'].includes(kind))flags.queue=true;
 pendingLivePaint.set(code,flags);
 if(livePaintTimer===null)livePaintTimer=setTimeout(flushLivePaint,100);
}
function flushLivePaint(){
 livePaintTimer=null;
 if(document.hidden){pendingLivePaint.clear();return}
 const chartDue=Date.now()-lastChartPaint>=(expandedChart?500:200),selected=$('quote-symbol').value;
 let chartPainted=false;
 for(const [code,flags] of pendingLivePaint){
  if(code!==selected&&code!==expandedChart){pendingLivePaint.delete(code);continue}
  const stock=stockData.find(s=>s.code===code),quote=livePrices[code];
  if(flags.price&&quote){
   const node=document.querySelector('[data-live-price="'+code+'"]');if(node)node.textContent=Number(quote.price).toFixed(3);
   const change=document.querySelector('[data-price-change="'+code+'"]');if(change&&stock)BrokerView.replaceContent(change,priceChange(stock));
   const capital=document.querySelector('[data-capitalization="'+code+'"]');if(capital&&stock)BrokerView.replaceContent(capital,isDarkStock(stock)?'':capitalization(stock));
   const stamp=document.querySelector('[data-live-time="'+code+'"]');if(stamp)stamp.innerHTML=priceTime(code);
   if(expandedChart===code)$('chart-live-price').textContent='最新价 '+Number(quote.price).toFixed(3)+(code.startsWith('US.')?' 美元':' 港元');
   const source=document.querySelector('[data-quote-source="'+code+'"]');if(source&&stock&&source.closest('details')?.open)BrokerView.replaceContent(source,quoteSourceInfo(stock));
   flags.price=false;
  }
  if(flags.queue){updateQueue(code);flags.queue=false}
  if(flags.chart&&chartDue){drawChart(code);flags.chart=false;chartPainted=true}
  if(!flags.price&&!flags.queue&&!flags.chart)pendingLivePaint.delete(code);
 }
 if(chartPainted)lastChartPaint=Date.now();
 if(pendingLivePaint.size&&livePaintTimer===null)livePaintTimer=setTimeout(flushLivePaint,100);
}

function connectLive(){
 if(liveStream)return;
 liveStream=new EventSource('/api/live');
 liveStream.onopen=()=>renderConnection();
 liveStream.onerror=()=>{$('transport').textContent='网页推送断开，行情状态待确认';$('sync').textContent='网页连接中断，保留历史数据';$('sync-dot').style.color='#b99144'};
 liveStream.onmessage=event=>{const e=JSON.parse(event.data);
  if(e.kind==='connection_status'){renderConnection(e);return}
  if(['book_snapshot','broker','depth'].includes(e.kind)){
   const s=stockData.find(s=>s.code===e.code);
   if(s){const key=e.kind==='book_snapshot'?'book':e.kind;if(!s[key]||(e.received_at||e.ts)>=(s[key].received_at||s[key].ts)){s[key]=e;scheduleLivePaint(e.code,e.kind)}}
   return;
  }
  if(!['quote','tick','auction_tick'].includes(e.kind))return;
  if(e.kind==='quote'){const stock=stockData.find(s=>s.code===e.code);if(stock)stock.quote=e}
  rememberPrice(e);
  scheduleLivePaint(e.code,e.kind);
  if(e.kind==='auction_tick'){
   const stock=stockData.find(s=>s.code===e.code);if(stock){stock.auction_ticks=[e,...(stock.auction_ticks||[]).filter(t=>t.sequence!==e.sequence)].slice(0,50);const panel=document.querySelector('[data-auction-panel="'+e.code+'"]');if(panel)BrokerView.replaceContent(panel,auctionPanel(stock))}
  }
  if(e.kind==='tick'){
   const minute=Math.floor(e.ts/60)*60,bars=chartBars[e.code]||(chartBars[e.code]=[]);
   let b=bars.find(b=>b.time===minute);
   if(!b){b={time:minute,open:e.price,high:e.price,low:e.price,close:e.price,first:e.ts,last:e.ts,volume:0,last_sequence:null};bars.push(b);bars.sort((a,b)=>a.time-b.time)}
   if(b.last_sequence!=null&&/^\d+$/.test(String(e.sequence))&&/^\d+$/.test(String(b.last_sequence))&&BigInt(e.sequence)<=BigInt(b.last_sequence))return;
   b.volume=Number(b.volume||0)+Number(e.volume??e.amount/e.price);b.last_sequence=e.sequence;
   b.high=Math.max(b.high,e.price);b.low=Math.min(b.low,e.price);
   if(e.ts<=(b.first??b.time)){b.open=e.price;b.first=e.ts}
   if(e.ts>=(b.last??b.time)){b.close=e.price;b.last=e.ts}
   // A scheduled paint uses the latest aggregate, without dropping trades.
  }
 };
}
function marketCapitalization(data,quote){
 if(!data)return {total:null,circulating:null,estimated:false};
 const base=Number(data.last_price),price=Number(quote?.price);
 const sourceTime=data.update_timestamp??Date.parse(String(data.update_time||'').replace(' ','T')+'+08:00')/1000;
 const estimated=Number.isFinite(base)&&base>0&&Number.isFinite(price)&&price>0&&Number.isFinite(sourceTime)&&quote?.ts>=sourceTime;
 const value=cap=>typeof cap==='number'&&Number.isFinite(cap)&&cap>=0?cap*(estimated?price/base:1):null;
 return {total:value(data.total_market_val),circulating:value(data.circular_market_val),estimated};
}
function priceChange(s){
 const data=s.fundamentals?.data,quote=livePrices[s.code];
 const current=quote?.price??data?.last_price,previous=data?.prev_close_price??quote?.prev_close_price??s.quote?.prev_close_price;
 if(!Number.isFinite(current)||!Number.isFinite(previous)||previous<=0)return '<span class="quote-change">（—）</span>';
 const delta=current-previous,sign=delta>0?'+':'',color=delta>0?'change-up':delta<0?'change-down':'change-flat';
 return `<span class="quote-change ${color}" title="较昨收 ${sign}${delta.toFixed(3)} ${String(s.code||'').startsWith('US.')?'美元':'港元'}">（${sign}${(delta/previous*100).toFixed(2)}%）</span>`;
}
function capitalization(s){
 const value=marketCapitalization(s.fundamentals?.data,livePrices[s.code]);
 const amount=v=>v==null?'—':Number(v)>=1e8?(Number(v)/1e8).toFixed(2)+' 亿':(Number(v)/1e4).toFixed(2)+' 万';
 return `<div class="quote-facts"><span>总市值 <b>${amount(value.total)}</b></span><span>流通市值 <b>${amount(value.circulating)}</b></span><span class="quote-fact-unit">${String(s.code||'').startsWith('US.')?'美元':'港元'}${value.estimated?' · 实时估算':''}</span></div>`;
}
function connectTarget(s){
 const t=s.connect_target||{},value=t.target_price;
 const warning=t.error||t.stale?' · 缓存／更新待恢复':'';
 const tooltip=`智通原始测算：剩余交易日平均收盘价参考，不是盘中触及即达标。源交易日 ${t.source_date||'未知'}；获取 ${t.fetched_at?when(t.fetched_at):'等待首次获取'} HKT；每60秒更新${warning}`;
 return `<span class="connect-target" title="${esc(tooltip)}">目标入通价 <b>${value!=null?Number(value).toFixed(2):'暂未提供'}</b>${value!=null?' 港元':''}${warning}</span>`;
}
function connectTargetInfo(s){
 const t=s.connect_target||{};
 return `<div class="quote-facts"><span>入通门槛 <b>${esc(t.in_market_value||'—')}</b> 港元</span><span>${esc(t.cycle||'等待获取')}</span></div>`;
}
function quoteSourceInfo(s){
 if(String(s.code||'').startsWith('US.'))return `<p>纽约交易日期，金额美元；行情时间 ${livePrices[s.code]?esc(when(livePrices[s.code].ts,s.code))+' ET':'等待推送'}。盘前、盘中、盘后基线独立；行情范围以OpenD实际权限为准。无法提供真实成交券商身份。</p>`;
 const t=s.connect_target||{},data=s.fundamentals?.data,quote=livePrices[s.code];
 return `<p>行情时间 ${quote?esc(when(quote.ts)):'等待报价'} HKT · 本机接收 ${quote?esc(when(quote.received_at)):'—'}</p><p>目标入通价直接采用智通测算，指剩余交易日平均收盘价参考，不是盘中触及即达标。<br>智通源交易日 ${esc(t.source_date||'未知')} · 获取 ${t.fetched_at?esc(when(t.fetched_at))+' HKT':'等待首次获取'} · 每60秒更新${t.error?' · '+esc(t.error):t.stale?' · 缓存待更新':''}</p><p>市值随最新成交价估算；富途基准快照 ${esc(data?.update_time||'等待获取')}，每60秒更新。估算保持快照股本口径，股本变化以新快照为准。</p>`;
}
function usStockCard(s){
 const incoming=[s.quote,s.tick].filter(Boolean).sort((a,b)=>b.ts-a.ts)[0];if(incoming)rememberPrice(incoming);
 const phase={PRE:'盘前',REGULAR:'常规盘',POST:'盘后',CLOSED:'休市'}[s.market_phase]||'待确认';
 const quote=livePrices[s.code],price=quote?.price??s.fundamentals?.data?.last_price;
 const depth=s.depth?Math.min(s.depth.bids,s.depth.asks):null;
 const state=s.monitoring_enabled===false?'监控已停止':monitoringLabels[s.monitoring_state]||s.monitoring_state;
 const unit='美元';
 return `<article class="card quote-card"><div class="quote-layout"><div class="quote-overview"><div class="card-top"><span class="code">${esc(s.name||s.code)}</span><span class="badge">美股 · ${phase}</span></div><div class="muted">${esc(s.code)} · 纽约时间（自动处理夏令时）</div><div class="price"><strong data-live-price="${esc(s.code)}">${price!=null?Number(price).toFixed(3):'—'}</strong><span data-price-change="${esc(s.code)}">${priceChange(s)}</span><span class="quote-currency">美元${!quote?' · 快照参考价':''}</span></div><div data-capitalization="${esc(s.code)}">${capitalization(s)}</div><div class="quote-update" data-live-time="${esc(s.code)}">${priceTime(s.code)}</div><p class="hint">${esc(state)} · 盘前、常规盘、盘后独立建立成交基线；常规盘无午休。</p><p class="source-note">数据来自 OpenD 可用的 Nasdaq／NYSE Arca 行情，不代表全市场完整成交与盘口。夜盘暂不纳入本版监控；半日市常规盘提前结束，盘后暂停。</p><div class="chart-button"><button type="button" class="chart-expand-button" data-chart-open="${esc(s.code)}">放大走势图 ↗</button><div class="mini-chart" data-chart="${esc(s.code)}" data-chart-open="${esc(s.code)}" role="button" tabindex="0" aria-label="放大美股走势图"></div></div><div class="muted">纽约交易日内分钟价与成交股数；缺失分钟补齐仅作展示。</div><div data-daily-panel="${esc(s.code)}">${DailyChart.panel(s.code)}</div><p class="muted">本时段动态门槛：${s.threshold_status?.value?money(s.threshold_status.value.threshold,s.code)+' · '+s.threshold_status.value.samples+' 个样本':'量价采样中；预热3分钟，60秒窗口至少8个历史样本'}</p><p class="hint">可监控成交放大及疑似买卖压力；不提供港股式成交券商身份、经纪商净买卖和入通目标价。</p><details class="quote-data-notes"><summary>数据说明</summary><div data-quote-source="${esc(s.code)}">${quoteSourceInfo(s)}</div></details></div><section class="quote-depth"><h3>实时买卖盘 ${depth==null?'':depth+'档'} · 美元</h3><div class="live-queues" data-live-queues="${esc(s.code)}">${queuePanels(s)}</div></section></div></article>`;
}

let watchlistMarkup='';
function stocks(items){
 const selected=$('quote-symbol').value||defaultQuoteSymbol;
 $('quote-symbol').innerHTML=items.map(s=>`<option value="${esc(s.code)}">${esc(s.name||s.code)} ${esc(s.code)}</option>`).join('');
 if(items.some(s=>s.code===selected))$('quote-symbol').value=selected;
 else if(items.some(s=>s.code===defaultQuoteSymbol))$('quote-symbol').value=defaultQuoteSymbol;
 updateDefaultStockButton();
 const watchlist=items.map(s=>`<button type="button" class="watch" data-watch-code="${esc(s.code)}"><strong>${esc(s.name||s.code)}</strong><span>${esc(s.code)}</span></button>`).join('');
 if(watchlist!==watchlistMarkup){
  $('watchlist').innerHTML=watchlist;
  watchlistMarkup=watchlist;
 }
 document.querySelectorAll('#watchlist [data-watch-code]').forEach(button=>{
  button.setAttribute('aria-pressed',String(button.dataset.watchCode===$('quote-symbol').value));
 });
 BrokerView.replaceContent($('cards'),items.filter(s=>s.code===$('quote-symbol').value).map(s=>{
  if(String(s.code||'').startsWith('US.'))return usStockCard(s);
  const incoming=[s.quote,s.tick,...(s.auction_ticks||[])].filter(Boolean).sort((a,b)=>b.ts-a.ts)[0]; if(incoming)rememberPrice(incoming);
  const dark=isDarkStock(s);
  const d=s.depth,fresh=d&&Date.now()/1000-d.ts<45,depth=d?Math.min(d.bids,d.asks):null;
  return `<article class="card quote-card"><div class="quote-layout"><div class="quote-overview"><div class="card-top"><span class="code">${esc(s.name||s.code)}</span><span class="badge ${!fresh||depth<10?'warn':''}">${dark?'暗盘交易中 · '+(s.book?.bid?.length||0)+' 档盘口':!fresh?'状态待更新':depth+' 档盘口'}</span></div><div class="muted">${esc(s.code)}</div><div class="price"><strong data-live-price="${esc(s.code)}">${livePrices[s.code]?Number(livePrices[s.code].price).toFixed(3):'—'}</strong><span data-price-change="${esc(s.code)}">${priceChange(s)}</span> <span class="quote-currency">港元</span></div><div class="quote-target-row">${dark?'':connectTarget(s)}</div><div class="quote-facts-block"><div data-capitalization="${esc(s.code)}">${dark?'':capitalization(s)}</div>${dark?'':connectTargetInfo(s)}</div><div class="quote-update" data-live-time="${esc(s.code)}">${priceTime(s.code)}</div><details class="quote-data-notes"><summary>数据说明</summary><div data-quote-source="${esc(s.code)}">${quoteSourceInfo(s)}</div></details><div data-auction-panel="${esc(s.code)}">${auctionPanel(s)}</div><div class="chart-button"><button type="button" class="chart-expand-button" data-chart-open="${esc(s.code)}">放大走势图 ↗</button><div class="mini-chart" data-chart="${esc(s.code)}" data-chart-open="${esc(s.code)}" role="button" tabindex="0" aria-label="放大${esc(s.name||s.code)}走势图"></div></div><div class="muted">上：分钟成交价 · 下：成交量（股） · 空缺沿用前价并标记</div><div data-daily-panel="${esc(s.code)}">${DailyChart.panel(s.code)}</div><p class="muted">动态门槛：${s.threshold_status?.value?money(s.threshold_status.value.threshold)+' · '+s.threshold_status.value.samples+' 个样本':'量价采样中；预热3分钟，60秒窗口至少8个历史样本'}</p><p class="muted">${esc(dark?(s.monitoring_enabled===false?'暗盘监控已停止':s.monitoring_state==='warming'?'暗盘量价监控预热中':'暗盘量价监控运行中'):s.monitoring_enabled===false?'行为监控已停止':s.monitoring_state==='waiting_session'?'行为监控等待交易时段':s.behavior_status?.value?.message||'行为监控：等待启用或采样')}</p><div class="card-bottom"><span>日内成交 ${money(s.day?.turnover)}</span><span>经纪 ${s.broker?(s.broker.bid.length+s.broker.ask.length)+' 条':'未采集'}</span></div><div class="stock-flow" data-stock-flow="${esc(s.code)}">${dark?'<p class="hint">暗盘数据独立观察，券商净买卖统计暂不可用。</p>':stockFlow(s)}</div></div><section class="quote-depth"><h3>实时买卖盘 · 挂盘与券商</h3><div class="live-queues" data-live-queues="${esc(s.code)}">${queuePanels(s)}</div></section></div></article>`;
 }).join(''));
 Object.keys(chartBars).forEach(drawChart);
}
$('quote-symbol').addEventListener('change',()=>{stocks(stockData);if(!syncRecordSelection($('quote-symbol').value)){requestVersion++;refresh()}});
$('watchlist').addEventListener('click',event=>{
 const button=event.target.closest('button[data-watch-code]');
 if(!button)return;
 const select=$('quote-symbol');
 const code=button.dataset.watchCode;
 if(!stockData.some(stock=>stock.code===code))return;
 if(select.value!==code){
  select.value=code;
  select.dispatchEvent(new Event('change'));
 }
 $('quote-section').scrollIntoView({block:'start'});
});
function updateDefaultStockButton(){
 const selected=$('quote-symbol').value,button=$('set-default-stock');
 button.disabled=!selected||selected===defaultQuoteSymbol;
 button.textContent=selected&&selected===defaultQuoteSymbol?'默认股票':'设为默认';
}
$('set-default-stock').addEventListener('click',async()=>{
 const button=$('set-default-stock');button.disabled=true;
 try{await monitorAction('set_default',$('quote-symbol').value)}catch(e){$('monitor-message').textContent=e.message}finally{updateDefaultStockButton()}
});
function auctionPanel(s){
 if(isDarkStock(s))return '<p class="source-note">当前阶段：富途暗盘（香港时间）· 涨跌相对发行参考价</p>';
 const stages={PRE_AUCTION:'盘前竞价',CONTINUOUS:'连续交易',CLOSE_AUCTION:'收盘竞价',AUCTION_SETTLING:'竞价结束收尾',BREAK:'午休',CLOSED:'休市'};
 const ticks=s.auction_ticks||[];
 return `<p class="source-note">当前阶段：${stages[marketStage]||'等待确认'}（香港时间）</p>${['PRE_AUCTION','CLOSE_AUCTION','AUCTION_SETTLING'].includes(marketStage)?'<p class="hint">报价与挂盘持续接收；最新价不是参考平衡价格，竞价成交以富途实际推送为准。竞价不套用连续交易异动规则。</p>':''}${ticks.length?`<details data-broker-disclosure="auction-trades:${esc(s.code)}"><summary>当日竞价成交 · ${ticks.length} 笔（最多展示最近50笔）</summary><div class="table-scroll"><table><thead><tr><th>香港时间</th><th>成交价</th><th>成交股数</th><th>成交额</th></tr></thead><tbody>${ticks.map(t=>`<tr><td>${esc(when(t.ts))}</td><td>${Number(t.price).toFixed(3)}</td><td>${Number(t.volume).toLocaleString('zh-CN')}</td><td>${money(t.amount)}</td></tr>`).join('')}</tbody></table></div></details>`:''}`;
}
const brokerRefreshes=new Set(),brokerRefreshMessages=new Map(),brokerDates=new Map(),brokerHistory=new Map();
function brokerDaySummary(summary,date){
 if(!summary?.available)return `<p class="source-note">${esc(summary?.message||'正在读取所选日期的日K…')}</p>`;
 const number=v=>v==null?'—':Number(v).toFixed(3),rate=summary.change_rate;
 const color=rate>0?'change-up':rate<0?'change-down':'change-flat';
 return `<div class="broker-day-summary"><span>${esc(date)} 涨跌幅 <b class="${color}">${rate==null?'—':(rate>0?'+':'')+Number(rate).toFixed(2)+'%'}</b></span><span>最高 <b>${number(summary.high)}</b></span><span>最低 <b>${number(summary.low)}</b></span><span>${summary.completed?'收盘':'最新（日K）'} <b>${number(summary.close)}</b></span><small>港元 · ${esc(summary.source)}${summary.completed?'':' · 当日尚非最终收盘数据'}</small></div>`;
}
function stockFlow(s){
 const selectedDate=brokerDates.get(s.code)||'',historical=!!selectedDate;
 const stats=historical?brokerHistory.get(s.code+':'+selectedDate):s.broker_stats,rows=stats?.rows||[];
 const dayInfo=historical?brokerDaySummary(stats?.daily_summary,selectedDate):'';
 const header=`<div class="section-title"><h3>十大净买入／卖出经纪商</h3><label>日期 <button type="button" class="broker-date-button secondary" data-broker-calendar="${esc(s.code)}" aria-haspopup="dialog">${esc(selectedDate||'选择历史交易日')} ▦</button></label><button type="button" class="secondary" data-broker-today="${esc(s.code)}">今日实时</button><button type="button" class="secondary" data-refresh-brokers="${esc(s.code)}" ${brokerRefreshes.has(s.code)||historical?'disabled':''}>${brokerRefreshes.has(s.code)?'正在查询富途…':'手动刷新'}</button></div><p class="source-note" role="status">${historical?esc(selectedDate+' · '+(stats?.error?stats.error:stats?(stats.after_close?'收盘后采集（非官方最终确认）':'盘中留档，未取得收盘后快照'):'没有已保存记录／正在读取')):esc(brokerRefreshMessages.get(s.code)||'')}</p>${dayInfo}`;
 const buys=rows.filter(r=>Number(r.buy_sell_type)===1).sort((a,b)=>Math.abs(b.net_vol)-Math.abs(a.net_vol)).slice(0,10);
 const sells=rows.filter(r=>Number(r.buy_sell_type)===2).sort((a,b)=>Math.abs(b.net_vol)-Math.abs(a.net_vol)).slice(0,10);
 const times=[...new Set(rows.map(r=>r.data_time_str).filter(Boolean))].join(' / ');
 const today=new Date().toLocaleDateString('sv-SE',{timeZone:'Asia/Hong_Kong'});
 const old=rows.some(r=>!r.is_real_time||!String(r.data_time_str||'').startsWith(today));
 if(!buys.length&&!sells.length)return header+`<p class="muted">经纪商净买卖统计暂不可用${stats?.error?'：'+esc(stats.error):''}</p>`;
 const max=Math.max(1,...rows.map(r=>Math.abs(Number(r.net_vol)||0))),n=Math.max(buys.length,sells.length);
 const chart=`<svg class="broker-flow-chart" viewBox="0 0 620 ${n*55+35}" role="img" aria-label="十大净买入与净卖出经纪商，单位万股"><text x="250" y="18" text-anchor="end" fill="#a66a61" font-size="13">净买入</text><text x="370" y="18" fill="#528571" font-size="13">净卖出</text>${Array.from({length:n},(_,i)=>{const b=buys[i],a=sells[i],y=35+i*55;return `${b?`<text x="295" y="${y+5}" text-anchor="end" fill="#355446" font-size="12">${esc(b.broker_name)}</text><rect x="${295-Math.abs(b.net_vol)/max*215}" y="${y+13}" width="${Math.abs(b.net_vol)/max*215}" height="12" rx="2" fill="#bd8275"/><text x="${Math.max(5,285-Math.abs(b.net_vol)/max*215)}" y="${y+42}" fill="#a66a61" font-size="11">+${(Math.abs(b.net_vol)/10000).toFixed(2)}</text><title>${esc(b.broker_name)} 净买入 ${Math.abs(b.net_vol)} 股；总成交额 ${esc(money(b.total_turnover))}</title>`:''}${a?`<text x="325" y="${y+5}" fill="#355446" font-size="12">${esc(a.broker_name)}</text><rect x="325" y="${y+13}" width="${Math.abs(a.net_vol)/max*215}" height="12" rx="2" fill="#75a38f"/><text x="${335+Math.abs(a.net_vol)/max*215}" y="${y+42}" text-anchor="end" fill="#528571" font-size="11">−${(Math.abs(a.net_vol)/10000).toFixed(2)}</text><title>${esc(a.broker_name)} 净卖出 ${Math.abs(a.net_vol)} 股；总成交额 ${esc(money(a.total_turnover))}</title>`:''}`}).join('')}</svg>`;
 const comparison=stats?.comparison;
 const changes=historical&&comparison?.changes?.length?`<details data-broker-disclosure="broker-changes:${esc(s.code)}:${esc(selectedDate)}"><summary>券商净量变化对照 · ${comparison.sample_count}份快照</summary><p class="hint">${esc(comparison.first_source_time)} → ${esc(comparison.last_source_time)}。首份留档不一定是开盘，未上榜不代表退出，不能据此确认庄家入离场。</p><div class="table-scroll"><table><thead><tr><th>券商</th><th>首份净量</th><th>末份净量</th><th>净量变化（股）</th><th>观察</th></tr></thead><tbody>${comparison.changes.map(r=>`<tr><td>${esc(r.name)}</td><td>${r.first_net??'未上榜'}</td><td>${r.last_net??'未上榜'}</td><td>${r.delta??'不可算'}</td><td>${esc(r.status)}</td></tr>`).join('')}</tbody></table></div></details>`:'';
 return header+`<p class="source-note">单位：万股 · ${historical?'历史留档 · ':old?'非当日实时数据，仅供历史参考 · ':''}源更新时间 ${esc(times||'未知')} · ${historical?'历史数据不被今日刷新覆盖':'每10秒查询'}</p>${chart}${changes}<p class="source-note">富途提供的净买卖股数统计，并非全部经纪商；不能当作资金净流入金额。该接口无券商编号，编号请查看右侧挂盘队列。</p>`;
}
async function selectBrokerDate(code,date){
 const stock=stockData.find(s=>s.code===code),today=new Date().toLocaleDateString('sv-SE',{timeZone:'Asia/Hong_Kong'});
 if(!TradingDatePicker.allowed(date,stock?.listing_date,today,stock?.closed_dates||[]))return;
 brokerDates.set(code,date);market();
 try{const response=await fetch('/api/broker-history?code='+encodeURIComponent(code)+'&date='+date,{cache:'no-store'});const value=await response.json();if(!response.ok)throw Error(value.error);brokerHistory.set(code+':'+date,{...(value.event||{rows:[]}),comparison:value.comparison,daily_summary:value.daily_summary})}
 catch(e){brokerHistory.set(code+':'+date,{rows:[],error:e.message,daily_summary:{available:false,message:e.message}})}finally{market()}
}
document.addEventListener('click',event=>{
 const button=event.target.closest('[data-broker-calendar]');if(!button)return;
 const code=button.dataset.brokerCalendar,stock=stockData.find(s=>s.code===code);
 TradingDatePicker.open({selected:brokerDates.get(code)||'',min:stock?.listing_date||'',max:new Date().toLocaleDateString('sv-SE',{timeZone:'Asia/Hong_Kong'}),closed:stock?.closed_dates||[],onSelect:date=>selectBrokerDate(code,date)});
});
document.addEventListener('click',event=>{const button=event.target.closest('[data-broker-today]');if(button){brokerDates.delete(button.dataset.brokerToday);market()}});
document.addEventListener('click',async event=>{
 const button=event.target.closest('[data-refresh-brokers]');if(!button)return;
 const code=button.dataset.refreshBrokers;if(brokerRefreshes.has(code))return;
 brokerRefreshes.add(code);brokerRefreshMessages.set(code,'正在重新查询当前股票的富途统计');market();
 try{
  const response=await fetch('/api/broker-refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code})});
  const result=await response.json();if(!response.ok)throw Error(result.error||'刷新失败');
  const stock=stockData.find(s=>s.code===code);if(stock)stock.broker_stats=result.event;
  brokerRefreshMessages.set(code,'刷新完成 · 查询时间 '+when(result.event.ts)+'；源数据尚未更新时数值可能保持不变');
 }catch(e){brokerRefreshMessages.set(code,e.message)}finally{brokerRefreshes.delete(code);market()}
});
function market(){stockData.forEach(s=>{const node=document.querySelector('[data-stock-flow="'+s.code+'"]');if(node)BrokerView.replaceContent(node,stockFlow(s))})}
const monitoringLabels={waiting_session:'已启用，等待交易时段',stopped:'已停止',stopping:'正在停止',pending:'等待启动',warming:'预热中',monitoring:'监控中',error:'订阅失败'};
function renderMonitoring(rows,connection){
 const grouped={};for(const row of rows){const group=row.groups?.[0]||'本地自选';(grouped[group]??=[]).push(row)}
 $('monitor-list').innerHTML=Object.entries(grouped).map(([group,items])=>`<section class="monitor-group"><h3>${esc(group)} <small>(${items.length})</small></h3><div class="table-scroll"><table class="monitor-table"><thead><tr><th>股票 / 代码</th><th>所属分组</th><th>监控开关</th><th>运行状态</th><th>操作</th></tr></thead><tbody>${items.map(r=>{
  let state=monitoringLabels[r.state]||r.state;const rowConnection=r.code.startsWith('US.')?usConnectionState:connection;
  if(r.enabled&&rowConnection?.state==='paused')state='已启用，等待交易时段';
  if(r.enabled&&['disconnected','connecting','stopped'].includes(rowConnection?.state))state='等待行情连接';
  return `<tr><td><strong>${esc(r.name||'名称待验证')}</strong><br><span class="muted">${esc(r.code)}</span></td><td>${esc((r.groups||[]).join('、')||'本地自选')}</td><td><button type="button" class="secondary" data-monitor-code="${esc(r.code)}" data-monitor-action="${r.enabled?'stop':'start'}">${r.enabled?'已开启 · 停止':'已停止 · 开启'}</button></td><td>${esc(state)}${r.error?' · '+esc(r.error):''}</td><td><button type="button" class="secondary remove-stock" data-monitor-code="${esc(r.code)}" data-monitor-action="remove">删除自选</button></td></tr>`}).join('')}</tbody></table></div></section>`).join('');
}
async function monitorAction(action,code){
 const response=await fetch('/api/watchlist',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,code})});const result=await response.json();if(!response.ok)throw Error(result.error||'操作失败');
 if(result.default_symbol!=null){defaultQuoteSymbol=result.default_symbol;updateDefaultStockButton()}
 $('monitor-message').textContent=action==='set_default'?'默认股票已保存，下次打开自动展示；不影响监控启停。':action==='remove'?'已从自选移除，后台停止监控；历史行情与异动保留。':action==='add'?'已添加，默认停止。启动时验证名称与订阅权限。':action==='start'?'已启用：交易时段自动订阅，休市时等待下次开盘。':'停止请求已保存，等待后台确认。';await refresh();
}
let stockSearchTimer=null,stockSearchVersion=0;
const stockCodeInput=$('stock-code');
function searchStockNames(){
 clearTimeout(stockSearchTimer);const version=++stockSearchVersion,query=stockCodeInput.value.trim();
 $('stock-suggestions').innerHTML='';if(!query)return;
 stockSearchTimer=setTimeout(async()=>{
  try{
   const response=await fetch('/api/stock-search?market='+encodeURIComponent($('stock-market').value||'HK')+'&q='+encodeURIComponent(query),{cache:'no-store'}),data=await response.json();
   if(version!==stockSearchVersion)return;if(!response.ok)throw Error(data.error||'股票搜索失败');
   $('stock-suggestions').innerHTML=(data.stocks||[]).map(r=>`<option value="${esc(r.code)}" label="${esc(r.name)} ${esc(r.code)}"></option>`).join('');
   $('monitor-message').textContent=data.stocks.length?'请选择匹配的股票代码后添加。':'未找到匹配股票，可输入完整中文名称或代码。';
  }catch(error){if(version===stockSearchVersion)$('monitor-message').textContent=error.message}
 },250);
}
stockCodeInput.addEventListener('input',event=>{if(!event.isComposing)searchStockNames()});
stockCodeInput.addEventListener('compositionend',searchStockNames);
async function loadFutuGroups(){
 try{const response=await fetch('/api/futu-groups'),data=await response.json();if(!response.ok)throw Error(data.error);const select=$('futu-group'),previous=select.value;select.innerHTML=data.groups.map(g=>`<option value="${esc(g.group_name)}">${esc(g.group_name)}</option>`).join('');select.value=previous;}catch(error){$('monitor-message').textContent=error.message}
}
$('futu-group').addEventListener('focus',loadFutuGroups);
$('futu-import').addEventListener('click',async()=>{
 const button=$('futu-import');button.disabled=true;$('monitor-message').textContent='正在读取所选富途分组中的港股…';
 try{
  const response=await fetch('/api/futu-import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({group:$('futu-group').value})}),data=await response.json();
  if(!response.ok)throw Error(data.error||'导入失败');
  $('monitor-message').textContent=`已读取 ${data.total} 只富途港股自选：新增 ${data.added} 只（监控已停止），已有 ${data.existing} 只保持原状态。`;await refresh();
 }catch(error){$('monitor-message').textContent=error.message}finally{button.disabled=false}
});
$('add-stock').addEventListener('submit',async event=>{event.preventDefault();try{await monitorAction('add',$('stock-code').value);$('stock-code').value='';++stockSearchVersion;clearTimeout(stockSearchTimer);$('stock-suggestions').innerHTML=''}catch(e){$('monitor-message').textContent=e.message}});
$('monitor-list').addEventListener('click',async event=>{const button=event.target.closest('[data-monitor-code]');if(!button)return;button.disabled=true;try{await monitorAction(button.dataset.monitorAction,button.dataset.monitorCode)}catch(e){$('monitor-message').textContent=e.message}finally{button.disabled=false}});
async function refresh(){
 if(busy||loggedOut)return;busy=true;const version=requestVersion;
 try{
  const parameters=new URLSearchParams({page:String(page),page_size:String(pageSize),symbol:$('record-symbol').value,quote_symbol:$('quote-symbol').value,signal:$('direction').value,date:$('date').value,search:$('search').value.trim()});
  if(pageAnchor!=null){parameters.set('anchor',pageAnchor);parameters.set('behavior_anchor',pageBehaviorAnchor??pageInfo.behavior_anchor??0);}
  const response=await fetch('/api/state?'+parameters.toString(),{cache:'no-store'});
  if(response.status===401){if(liveStream){liveStream.close();liveStream=null;}$('login').hidden=false;$('app').hidden=true;return}
  const data=await response.json();if(!response.ok)throw Error(data.error);
  if(version!==requestVersion)return;
  const recordSymbol=$('record-symbol').value;
  $('record-symbol').innerHTML='<option value="">全部股票</option>'+(data.alert_symbols||[]).map(s=>`<option value="${esc(s.code)}">${esc(s.name)} ${esc(s.code)}</option>`).join('');
  $('record-symbol').value=recordSymbol;
  $('logout').hidden=data.password_required===false;
  usConnectionState=data.us_connection||usConnectionState;
  marketStage=data.market_stage||'';
  defaultQuoteSymbol=data.default_symbol||'';
  const preferred=data.stocks.some(s=>s.code===defaultQuoteSymbol)?defaultQuoteSymbol:(data.stocks[0]?.code||'');
  const quoteCode=data.stocks.some(s=>s.code===$('quote-symbol').value)?$('quote-symbol').value:preferred;
  if(syncRecordSelection(quoteCode))return;
  behaviorRows=data.behaviors||[];names=data.names||{};total=data.total;renderMonitoring(data.watchlist||[],data.connection);

  records=data.alerts;pageInfo=data.pagination;page=pageInfo.page;
  $('login').hidden=true;$('app').hidden=false;stockData=data.stocks.map(next=>{const old=stockData.find(s=>s.code===next.code);for(const key of ['book','broker','depth','broker_stats']){if(old?.[key]&&(old[key].received_at||old[key].ts)>(next[key]?.received_at||next[key]?.ts||0))next[key]=old[key]}return next});if(data.candles){for(const [code,bars] of Object.entries(data.candles)){const local=chartBars[code]||[];for(const b of local){const i=bars.findIndex(n=>n.time===b.time);if(i<0)bars.push(b);else if(b.last_sequence!=null&&bars[i].last_sequence!=null&&BigInt(b.last_sequence)>BigInt(bars[i].last_sequence))bars[i]=b}bars.sort((a,b)=>a.time-b.time)}chartBars=data.candles;}stocks(stockData);connectLive();market();draw();
  renderConnection(data.connection);
 }catch(e){$('sync').textContent='连接中断，保留已有记录';$('sync-dot').style.color='#c08b4d';if(!$('login').hidden)$('login-error').textContent='登录后读取行情失败：'+e.message+'，页面将自动重试'}finally{busy=false;if(version!==requestVersion)refresh()}
}
$('logout').addEventListener('click',async()=>{
 const button=$('logout');button.disabled=true;loggedOut=true;requestVersion++;
 if(liveStream){liveStream.close();liveStream=null}
 try{
  const response=await fetch('/api/logout',{method:'POST'});
  if(!response.ok)throw Error('退出失败，请重试');
  location.replace('/');
 }catch(e){loggedOut=false;$('sync').textContent=e.message;refresh()}finally{button.disabled=false}
});
$('login-form').addEventListener('submit',async event=>{event.preventDefault();try{const response=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:$('password').value})});if(!response.ok)throw Error('访问口令不正确');$('password').value='';$('login-error').textContent='';loggedOut=false;requestVersion++;refresh()}catch(e){$('login-error').textContent=e.message}});
function updateRecordFollowMode(){
 $('record-follow-mode').textContent=recordFollowsQuote?'当前跟随上方行情股票':'已手动选择，不随上方行情切换';
 $('record-follow').disabled=recordFollowsQuote;
}
function syncRecordSelection(code){
 updateRecordFollowMode();
 if(!recordFollowsQuote||$('record-symbol').value===code)return false;
 $('record-symbol').value=code;resetPages();return true;
}
$('record-symbol').addEventListener('change',()=>{recordFollowsQuote=false;updateRecordFollowMode();resetPages()});
$('record-follow').addEventListener('click',()=>{
 recordFollowsQuote=true;updateRecordFollowMode();
 if(!syncRecordSelection($('quote-symbol').value))resetPages();
});
function resetPages(){page=1;pageAnchor=null;pageBehaviorAnchor=null;requestVersion++;refresh()}
['direction','date','search'].forEach(id=>$(id).addEventListener('change',resetPages));
let searchTimer;$('search').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(resetPages,250)});
$('page-size').addEventListener('change',()=>{pageSize=Number($('page-size').value);resetPages()});
function changePage(next){if(next<1||next>pageInfo.pages)return;if(next===1){pageAnchor=null;pageBehaviorAnchor=null;}else if(pageAnchor==null){pageAnchor=pageInfo.anchor;pageBehaviorAnchor=pageInfo.behavior_anchor;}page=next;requestVersion++;refresh()}
$('page-first').addEventListener('click',()=>changePage(1));$('page-prev').addEventListener('click',()=>changePage(page-1));$('page-next').addEventListener('click',()=>changePage(page+1));
$('refresh').addEventListener('click',()=>resetPages());
function initializeJournalCollapse(){
 const button=$('journal-toggle'),content=$('journal-content');
 let collapsed=false;
 try{collapsed=localStorage.getItem('hk_quote.journal_collapsed')==='1'}catch(error){}
 function apply(){content.hidden=collapsed;button.setAttribute('aria-expanded',String(!collapsed));button.textContent=collapsed?'展开记录 ▾':'收起记录 ▴'}
 apply();button.addEventListener('click',()=>{collapsed=!collapsed;apply();try{localStorage.setItem('hk_quote.journal_collapsed',collapsed?'1':'0')}catch(error){}});
}
refresh();setInterval(()=>{if(!document.hidden)refresh()},3000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh()});

initializeJournalCollapse();

const journalDates=TradingDatePicker.bind($('date'),$('date-pick'),{
 zone:()=>$('record-symbol').value.startsWith('US.')?'America/New_York':'Asia/Hong_Kong',
 min:()=>stockData.find(row=>row.code===$('record-symbol').value)?.listing_date||'',
 closed:()=>{const code=$('record-symbol').value;return code.startsWith('HK.')?stockData.find(row=>row.code===code)?.closed_dates||[]:[]},
 empty:'全部日期'
});
$('date-clear').addEventListener('click',journalDates.clear);
$('record-symbol').addEventListener('change',journalDates.sync);
$('quote-symbol').addEventListener('change',()=>{const previous=$('date').value;journalDates.sync();if(previous!==$('date').value)resetPages()});
