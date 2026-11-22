const $=id=>document.getElementById(id),esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let data=null,seatPage=0,netPage=0,intervalPage=0,selectedEvidence='';
const time=t=>new Date(t*1000).toLocaleTimeString('zh-CN',{timeZone:'Asia/Hong_Kong',hour12:false});
const money=v=>v==null?'—':(v/10000).toFixed(2)+' 万港元';
const num=v=>v==null?'—':Number(v).toLocaleString('zh-CN',{maximumFractionDigits:3});
const pct=v=>v==null?'—':Math.round(v*100)+'%';
const signed=v=>v==null?'—':(v>0?'+':'')+(v/10000).toFixed(3);
const empty=message=>`<p class="empty">${esc(message)}</p>`;
const labels={BUY:'主动买入',SELL:'主动卖出',VOLUME:'成交放大'};
const categoryLabels={buy_to_sell:'买侧转卖侧',sell_to_buy:'卖侧转买侧',tail_change:'尾盘明显变化',other:'方向未明显转换'};
function currentCode(){return $('report-symbol').value}
function behaviorRows(){const code=currentCode(),kind=$('report-behavior-type').value,phase=$('report-behavior-phase').value;return (data.behaviors||[]).filter(r=>{
 const confirmed=(r.history||[]).some(h=>h.phase==='confirmed'),ended=['resolved','failed','interrupted'].includes(r.phase);
 return r.code===code&&(!kind||r.type===kind)&&(!phase||(phase==='confirmed'?confirmed:phase==='unconfirmed'?!confirmed:phase==='active'?!ended:ended));
})}
function pager(key,page,count){const pages=Math.max(1,Math.ceil(count/10));return `<div class="pagination"><button class="secondary" data-analysis-page="${key}" data-page="${page-1}" ${page<=0?'disabled':''}>上一页</button><span>第 ${page+1} / ${pages} 页 · ${count} 条</span><button class="secondary" data-analysis-page="${key}" data-page="${page+1}" ${page+1>=pages?'disabled':''}>下一页</button></div>`}
function priceChart(rows,events){
 if(!rows.length)return empty('本机未保存该日成交价格，无法绘制对应走势。');
 const clock=t=>t-Math.max(0,Math.min(3600,t-(Math.floor((t+28800)/86400)*86400-28800+43200)));
 const first=clock(rows[0].ts),last=clock(rows[rows.length-1].ts),low=Math.min(...rows.map(r=>r.price)),high=Math.max(...rows.map(r=>r.price)),span=high-low||Math.max(high*.01,.01);
 const x=t=>50+(clock(t)-first)/Math.max(60,last-first)*870,y=p=>25+(high-p)/span*180;
 return `<svg class="insight-price-chart" viewBox="0 0 1000 265" role="img" aria-label="本机成交价格与行为区间">${[0,.5,1].map(f=>`<line x1="50" x2="920" y1="${25+180*f}" y2="${25+180*f}" stroke="#dfe6d8"/><text x="930" y="${30+180*f}" font-size="12">${num(high-span*f)}</text>`).join('')}<path d="${rows.map((r,i)=>(i?'L':'M')+x(r.ts)+','+y(r.price)).join(' ')}" fill="none" stroke="#36765d" stroke-width="2"/>${events.filter(r=>r.updated_at>=rows[0].ts&&r.started_at<=rows[rows.length-1].ts+60).map(r=>{const confirmed=(r.history||[]).some(h=>h.phase==='confirmed');return `<rect tabindex="0" role="button" aria-label="查看 B${r.id} ${esc(BehaviorView.labels[r.type])}" data-evidence-ref="B${r.id}" x="${Math.max(50,x(r.started_at))}" y="20" width="${Math.max(6,Math.min(920,x(r.updated_at))-Math.max(50,x(r.started_at)))}" height="190" fill="${confirmed?({DUMP:'#57977c',SUPPORT:'#be9f55',LIFT:'#c47f70'}[r.type]):'#a8afa2'}" opacity=".25"><title>B${r.id} ${esc(BehaviorView.labels[r.type])} ${time(r.started_at)} · ${confirmed?'曾确认':'仅观察'}，点击查看证据</title></rect>`}).join('')}${rows.map(r=>`<circle cx="${x(r.ts)}" cy="${y(r.price)}" r="3" fill="transparent"><title>${time(r.ts)} · ${num(r.price)} 港元 · 成交 ${num(r.volume)} 股</title></circle>`).join('')}${[rows[0],rows[Math.floor(rows.length/2)],rows[rows.length-1]].map(r=>`<text x="${x(r.ts)}" y="245" text-anchor="middle" font-size="12">${time(r.ts).slice(0,5)}</text>`).join('')}</svg>`;
}
function brokerChannelBadge(profile){
 const p=profile||{category:'unknown',label:'待核实',basis:'尚无已核实的券商渠道资料'};
 const category=['retail','institutional','mixed','unknown'].includes(p.category)?p.category:'unknown';
 return `<span class="broker-channel broker-channel-${category}" title="${esc(p.basis)}；仅代表渠道特征，不是实际客户身份">${esc(p.label)}</span>`;
}
function renderBrokerPeriods(code){
 const value=data.insights?.broker_periods?.[code];
 if(!value){BrokerView.replaceContent($('seat-analysis'),empty('该日没有可用的券商分时记录。'));return}
 const rows=value.brokers;seatPage=Math.min(seatPage,Math.max(0,Math.ceil(rows.length/10)-1));
 const amount=v=>(Math.abs(v)/10000).toLocaleString('zh-CN',{maximumFractionDigits:3})+' 万股';
 const direction={buy:'净买入',sell:'净卖出',flat:'净量无变化',unknown:'净买卖未知'};
 const netCell=period=>`<strong class="${period.net_direction==='buy'?'broker-net-buy':period.net_direction==='sell'?'broker-net-sell':''}">${direction[period.net_direction]}${period.net!=null&&period.net!==0?' '+amount(period.net):''}</strong><small>${period.to_source?'源时间 '+esc(period.to_source):'缺少该时段源快照'}</small><small>挂盘：${period.share==null?'没有有效在场记录':period.share>.5?'偏买侧，买侧占比 '+pct(period.share):period.share<.5?'偏卖侧，买侧占比 '+pct(period.share):'买卖侧各半'}</small>`;
 const summary=['morning','afternoon'].flatMap(key=>['buy','sell'].map(side=>{
  const list=value.summary[key][side];return `<section class="broker-period-summary"><h3>${key==='morning'?'上午':'下午'} · ${side==='buy'?'净买入':'净卖出'}券商 <small>${list.length} 家</small></h3>${list.length?'<ul>'+list.map(r=>`<li><div><strong>${esc(r.name)}</strong>${brokerChannelBadge(r.channel_profile)}</div><span>${amount(r.net)}</span></li>`).join('')+'</ul>':'<p class="hint">暂无可比净量记录；不表示没有买卖。</p>'}</section>`;
 })).join('');
 const conclusion=r=>r.morning.net_direction!=='unknown'&&r.afternoon.net_direction!=='unknown'?`上午${direction[r.morning.net_direction]} → 下午${direction[r.afternoon.net_direction]}`:'部分时段净量未知，挂盘仅供补充';
 const audit=r=>`<details data-broker-disclosure="broker-period-${esc(code)}-${esc(r.name)}"><summary>席位编号、分类依据与计算</summary><p class="hint">渠道分类：${esc(r.channel_profile?.label||'待核实')} · ${esc(r.channel_profile?.basis||'暂无已核实资料')}。核实日期：${esc(r.channel_profile?.reviewed_on||'未核实')}。</p>${(r.channel_profile?.sources||[]).map(s=>`<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title)}</a>`).join(' · ')}<p class="hint">同一券商下这些编号继承同一渠道标签；没有编号级客户身份信息。</p><p class="hint">合并编号：${r.ids.length?r.ids.map(esc).join(' / '):'净量接口无编号，队列未捕捉对应席位'}</p>${['morning','afternoon'].map(key=>{const period=r[key],coverage=value.periods[key];return `<p class="hint">${key==='morning'?'上午':'下午'}挂盘在场：买侧 ${period.bid} / 卖侧 ${period.ask} 次；${period.present}/${coverage.valid} 个有效采样点出现。${period.net==null?esc(period.reason):key==='morning'?'上午净量取午间源快照的当日累计值，包含开盘后的全部累计交易。':'下午净量 = 下午累计净量 − 午间累计净量。'}${period.from_source?'比较源时间 '+esc(period.from_source)+' → '+esc(period.to_source):''}</p>`}).join('')}<p class="hint">每10秒固定采样；同券商同侧多个编号只计一次，不能按编号数量放大活跃度。双侧可同时出现。只合并来源中一致的券商名称，不凭相似名字猜测集团归属。榜外不当作零，净量未知时不能据挂盘确定真实成交方向。</p></details>`;
 BrokerView.replaceContent($('seat-analysis'),`<p class="seat-read-guide">直接看上午、下午哪些券商净买入或净卖出；同一券商的席位合并为一行。净买卖以源快照为依据，挂盘统计单独标注。标签按公开业务资料区分零售平台、机构业务、综合渠道；不能据此认定具体交易是机构或散户。待核实不强行归类，展开可查来源。</p><div class="broker-period-grid">${summary}</div><p class="hint">上午源时间 ${esc(value.morning_source||'缺失')}；午间基准 ${esc(value.noon_source||'缺失')}；下午源时间 ${esc(value.afternoon_source||'缺失')}。对照表按当日券商总成交量降序排列；相同成交量再按净买卖变化排序。数据源只覆盖上榜券商，成交量缺失排在最后，不当作零；无法拆分到具体席位编号。四栏净买卖榜仍按对应净量大小排列。</p><div class="table-scroll"><table class="broker-period-table"><thead><tr><th>券商</th><th>当日总成交量 ↓</th><th>上午：谁在净买／净卖</th><th>下午：谁在净买／净卖</th><th>方向对照与席位</th></tr></thead><tbody>${rows.slice(seatPage*10,seatPage*10+10).map(r=>`<tr><td><strong>${esc(r.name)}</strong>${brokerChannelBadge(r.channel_profile)}<small>${r.ids.length} 个已捕捉席位</small></td><td><strong>${r.total_volume==null?'未知':num(r.total_volume/10000)+' 万股'}</strong><small>${r.volume_source?esc(r.volume_source):'当前源快照未提供，排在末尾'}</small></td><td>${netCell(r.morning)}</td><td>${netCell(r.afternoon)}</td><td><p>${esc(conclusion(r))}</p>${audit(r)}</td></tr>`).join('')}</tbody></table></div>${rows.length?pager('seat',seatPage,rows.length):empty('没有券商记录。')}`);
}
function renderSeats(code){renderBrokerPeriods(code)}

function renderNet(code){
 const n=data.insights?.nets?.[code];if(!n){BrokerView.replaceContent($('net-analysis'),empty('该日没有可比较的券商净量快照。'));return}
 netPage=Math.min(netPage,Math.max(0,Math.ceil(n.brokers.length/10)-1));
 BrokerView.replaceContent($('net-analysis'),`<p class="hint">源时间 ${esc(n.first_source)} → ${esc(n.last_source)} · ${n.sample_count} 份不同源时间快照。单位：万股。缺少区间端点或券商未上榜显示 —，不按零处理。</p><div class="table-scroll"><table><thead><tr><th>券商</th><th>起点净量</th><th>最新净量</th><th>全区间变化</th><th>上午变化</th><th>下午变化</th><th>15点后变化</th></tr></thead><tbody>${n.brokers.slice(netPage*10,netPage*10+10).map(r=>`<tr><td>${esc(r.name)}${r.status!=='both'?`<small>${r.status==='newly_listed'?'起点未上榜':'终点未上榜'}，无法推断进出</small>`:''}</td><td>${signed(r.first)}</td><td>${signed(r.last)}</td><td>${signed(r.delta)}</td>${['morning','afternoon','tail'].map(key=>`<td title="${esc(r.periods[key].from_source||'起点缺失')} → ${esc(r.periods[key].to_source||'终点缺失')}">${signed(r.periods[key].delta)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>${pager('net',netPage,n.brokers.length)}<p class="hint">正变化表示净买量增加或净卖量减少，不能拆解买卖总量；名单只覆盖数据源公布的券商，无法拆到具体席位。分时起点允许 5 分钟边界偏差，上午可能从首份快照开始；悬停可看实际比较时间。尾盘包含在下午内，不能重复相加。</p>`);
}
function evidenceItems(code){return [...(data.behaviors||[]).filter(r=>r.code===code).map(r=>({ref:'B'+r.id,ts:r.started_at,label:BehaviorView.labels[r.type],behavior:r,attribution:r.broker_attribution})),...(data.rows||[]).filter(r=>r.alert.code===code).map(r=>({ref:'#'+r.id,ts:r.alert.ts,label:r.alert.signal_label||labels[r.alert.signal]||r.alert.signal,row:r,attribution:r.broker_attribution}))].sort((a,b)=>b.ts-a.ts)}
function renderIntervals(items){
 const intervals=new Map();for(const item of items){const a=item.attribution;if(!a?.before_id||!a?.after_id)continue;const key=a.before_id+':'+a.after_id;if(!intervals.has(key))intervals.set(key,{a,items:[]});intervals.get(key).items.push(item)}
 const rows=[...intervals.values()].sort((x,y)=>y.a.to_source.localeCompare(x.a.to_source));intervalPage=Math.min(intervalPage,Math.max(0,Math.ceil(rows.length/10)-1));
 BrokerView.replaceContent($('interval-analysis'),`<p class="hint">${items.length} 条信号与行为 · ${rows.length} 个可对照源快照区间。同一对快照合并展示一次；区间内多条异动不能逐笔分配券商净量。</p>${rows.length?`<div class="table-scroll"><table><thead><tr><th>源快照区间</th><th>净量增加较多</th><th>净量减少较多</th><th>关联证据</th></tr></thead><tbody>${rows.slice(intervalPage*10,intervalPage*10+10).map(({a,items:linked})=>`<tr><td>${esc(a.from_source)}<small>→ ${esc(a.to_source)}</small></td>${[1,-1].map(sign=>`<td>${(a.candidates||[]).filter(c=>c.delta*sign>0).slice(0,3).map(c=>`${esc(c.name)} ${signed(c.delta)} 万股`).join('<br>')||'无可比较变化'}</td>`).join('')}<td>${linked.map(item=>`<button class="secondary" data-evidence-ref="${item.ref}">${item.ref}</button>`).join(' ')}</td></tr>`).join('')}</tbody></table></div>${pager('interval',intervalPage,rows.length)}`:empty('尚无足够前后源快照可关联；可从下方选择记录查看等待或不足的原因。')}`);
 const select=$('evidence-select');select.innerHTML='<option value="">选择一条证据（按需展开）</option>'+items.map(item=>`<option value="${item.ref}">${time(item.ts)} · ${item.ref} ${esc(item.label)}</option>`).join('');
 if(!items.some(item=>item.ref===selectedEvidence))selectedEvidence='';select.value=selectedEvidence;renderEvidence(items);
}
function renderEvidence(items){
 const item=items.find(r=>r.ref===selectedEvidence);if(!item){BrokerView.replaceContent($('selected-evidence'),empty('点击行为标记、区间关联编号，或选择一条记录，查看对应证据。'));return}
 const row=item.row;
 const html=item.behavior?BehaviorView.journal(item.behavior,data.names):`<details class="record" data-analysis-id="${row.id}" open><summary>${esc(item.label)} · ${item.ref} · ${time(item.ts)} · ${money(row.alert.amount)}</summary><div class="detail">${BrokerView.notice(row.alert)}${BrokerView.attribution(row.broker_attribution)}${BrokerView.detail(row.profile)}</div></details>`;
 BrokerView.replaceContent($('selected-evidence'),html);
}
function render(){
 if(!data)return;const code=currentCode(),all=(data.rows||[]).filter(r=>r.alert.code===code),events=behaviorRows(),allBehaviors=(data.behaviors||[]).filter(r=>r.code===code),confirmed=allBehaviors.filter(r=>(r.history||[]).some(h=>h.phase==='confirmed')).length;
 $('report-kpis').innerHTML=[['成交信号',all.length,'原始成交提醒'],['行为观察',allBehaviors.length,`曾确认 ${confirmed} · 仅观察 ${allBehaviors.length-confirmed}`],['已合并券商',data.insights?.broker_periods?.[code]?.brokers?.length||0,'同券商不同席位合并，上午与下午分别对照']].map(([label,n,note])=>`<article class="card"><p class="eyebrow">${label}</p><div class="report-number">${n}<small>${label==='已合并券商'?'家':'条'}</small></div><p class="muted">${note}</p></article>`).join('');
 BrokerView.replaceContent($('report-price'),priceChart(data.insights?.prices?.[code]||[],events));
 BrokerView.replaceContent($('report-behaviors'),BehaviorView.render(data.behaviors||[],data.names,code,$('report-behavior-type').value,$('report-behavior-phase').value,true));
 renderSeats(code);renderNet(code);renderIntervals(evidenceItems(code));
 const ready=all.filter(r=>r.profile?.status==='ready').length;
 BrokerView.replaceContent($('analysis-quality'),`<p>券商异动采样较完整 ${ready} / ${all.length} 条成交信号。缺失时段不推算、不填零。</p><p>席位按保存的完整队列统计；队列位置不自动等同于价格档位。买卖两侧可同时出现，同一侧重复席位每次只记一次。</p><p>挂盘时间为本机接收时间；净买卖按数据源时间对齐。前后快照间隔超过 5 分钟不用于单次异动关联；同一区间多条事件只共同参考。</p><p>行为标签描述价格、成交与盘口表现；在场比例、净量变化均不能认定实际成交归属或庄家身份。收盘后可继续查看保存的数据。</p>`);
}
function chooseEvidence(ref){selectedEvidence=ref;renderIntervals(evidenceItems(currentCode()));const panel=$('module-evidence');panel.open=true;saveModule(panel);const record=document.querySelector('#selected-evidence details');if(record)record.open=true;panel.scrollIntoView?.({block:'start',behavior:'smooth'})}
function saveModule(panel){try{localStorage.setItem('hk_quote.analysis.'+panel.dataset.analysisModule,panel.open?'1':'0')}catch(error){}}
function initializeModules(){document.querySelectorAll('[data-analysis-module]').forEach(panel=>{try{const saved=localStorage.getItem('hk_quote.analysis.'+panel.dataset.analysisModule);if(saved!==null)panel.open=saved==='1'}catch(error){}panel.addEventListener('toggle',()=>saveModule(panel))})}
$('report-symbol').addEventListener('change',()=>{seatPage=netPage=intervalPage=0;selectedEvidence='';render()});
['report-behavior-type','report-behavior-phase'].forEach(id=>$(id).addEventListener('change',render));
$('evidence-select').addEventListener('change',()=>{if($('evidence-select').value)chooseEvidence($('evidence-select').value);else{selectedEvidence='';renderEvidence([])}});
$('report-content').addEventListener('click',event=>{const ref=event.target.closest('[data-evidence-ref]');if(ref){chooseEvidence(ref.dataset.evidenceRef);return}const count=event.target.closest('[data-behavior-filter]');if(count){const select=$('report-behavior-type');select.value=select.value===count.dataset.behaviorFilter?'':count.dataset.behaviorFilter;render();return}const page=event.target.closest('[data-analysis-page]');if(page){const value=Math.max(0,Number(page.dataset.page));if(page.dataset.analysisPage==='seat')seatPage=value;if(page.dataset.analysisPage==='net')netPage=value;if(page.dataset.analysisPage==='interval')intervalPage=value;render()}});
$('report-content').addEventListener('keydown',event=>{if(['Enter',' '].includes(event.key)&&event.target.matches('rect[data-evidence-ref]')){event.preventDefault();chooseEvidence(event.target.dataset.evidenceRef)}});
let loading=false;
async function refreshAnalysis(){
 if(loading)return;loading=true;
 try{
  const selected=$('analysis-date').value,response=await fetch('/api/report-data'+(selected?'?date='+encodeURIComponent(selected):''),{cache:'no-store'});
  if(response.status===401){$('report-error').innerHTML='请先在<a href="/">实时看板登录</a>，再返回此页面。';return}
  const result=await response.json();if(!response.ok)throw Error(result.error||'读取分析失败');if(selected!==$('analysis-date').value)return;
  data=result;$('report-error').textContent='';$('report-date').textContent=data.date+' · 香港时间 '+time(data.updated_at)+' 更新';
  const select=$('report-symbol'),requested=select.dataset.initialized?select.value:(new URLSearchParams(location.search).get('code')||'');select.dataset.initialized='1';
  select.innerHTML=Object.entries(data.names).map(([c,n])=>`<option value="${esc(c)}">${esc(n)} ${esc(c)}</option>`).join('');
  if([...select.options].some(o=>o.value===requested))select.value=requested;
  $('report-content').hidden=false;render();
  if(!select.dataset.ccassReady){
   select.dataset.ccassReady='1';
   select.dispatchEvent(new Event('ccass-ready'));
  }
 }catch(error){$('report-error').textContent='更新失败，保留现有数据：'+error.message}finally{loading=false}
}
$('analysis-date').addEventListener('change',()=>{seatPage=netPage=intervalPage=0;selectedEvidence='';refreshAnalysis()});
$('analysis-date').value=new URLSearchParams(location.search).get('date')||'';
function initializeReportDate(){
 const field=$('analysis-date');
 const dates=TradingDatePicker.bind(field,$('analysis-date-pick'),{zone:()=>'Asia/Hong_Kong',empty:'最新'});
 $('analysis-date-clear').addEventListener('click',dates.clear);
}
initializeReportDate();initializeModules();refreshAnalysis();setInterval(()=>{if(!document.hidden)refreshAnalysis()},3000);

// Display aliases keyed by CCASS participant ID. Keep Futu's original name as a fallback.
const ccassChineseNames = {
 A00005:'中国证券登记结算（香港）',
 B02159:'盈立证券',
 C00010:'花旗银行',
 B01664:'路华证券',
 B01584:'致富证券',
 B01959:'中泰国际证券',
 B01955:'富途证券',
 B01148:'招商证券（香港）',
 B01900:'东方证券（香港）',
 C00019:'香港上海汇丰银行',
};
function ccassPercent(value){
 return Number.isFinite(value)?value.toLocaleString('zh-CN',{minimumFractionDigits:1,maximumFractionDigits:1})+'%':'—';
}
function initializeIpoTrend(){
 const panel=$('module-ipo-trend'), button=$('ipo-update'), status=$('ipo-status');
 const stock=$('report-symbol'), date=$('analysis-date');
 let version=0;
 function sourceLink(text, source){
  return typeof source==='string'&&source.startsWith('https://')
   ? `<a href="${esc(source)}" target="_blank" rel="noopener">${text}</a>`
   : esc(source||'来源待补充');
 }

 const signed=value=>value==null?'—':(value>0?'+':'')+num(value);
 function render(trend){
  $('ipo-reference').textContent='';
  $('ipo-ranking').textContent='';
  $('ipo-newcomers').textContent='';
  if(!trend?.days.length){
   $('ipo-summary').textContent=trend?.message||'所选日期暂无持仓趋势。';
   $('ipo-breakdown').textContent='';
   return;
  }
  const allocation=trend.public_shares==null?'缺少配发公告数据':`公发 ${num(trend.public_shares)} 股 · 国配 ${num(trend.international_shares)} 股 · ${sourceLink('配发公告',trend.announcement)}`;
  $('ipo-reference').innerHTML=`基准 ${esc(trend.baseline)} 日末 · ${sourceLink('首日持仓来源',trend.baseline_source)} · ${allocation}`;
  $('ipo-newcomers').innerHTML=`<p class="hint">${esc(trend.rank_day)} 前十 · ${sourceLink('排名来源',trend.rank_source)}<br>${trend.newcomers.length?'较首日新进前十：'+trend.newcomers.map(row=>esc(ccassChineseNames[row.id]||row.name)+' ['+esc(row.id)+'] '+(row.shares!=null?num(row.shares)+' 股':row.ratio!=null?num(row.ratio)+'%':'')).join(' · '):'较首日无新进前十'}</p>`;
  const ranking=trend.selected_ranking||[];
  const rankTitle=esc(trend.selected_day)+' · 当日前十大托管（股）';
  const rankedRows=ranking.map(row=>`<tr><td>${row.rank}</td><td><button type="button" class="secondary" data-ipo-broker="${esc(row.id)}">${esc(ccassChineseNames[row.id]||row.name)}</button><small> ${esc(row.id)}${row.newcomer?' · 较首日新进':''}</small></td><td>${num(row.shares)}</td><td>${ccassPercent(row.ratio)}</td><td>${esc(row.label)}</td></tr>`).join('');
  $('ipo-ranking').innerHTML=ranking.length
   ? `<h3>${rankTitle}</h3><p class="hint">${sourceLink('当日排名来源',trend.selected_source)} · 比例以 IPO 全球发售股数为分母 · 点击参与者看比例走势</p><div class="table-scroll"><table><thead><tr><th>排名</th><th>参与者</th><th>持仓股数</th><th>占全球发售</th><th>国配线索</th></tr></thead><tbody>${rankedRows}</tbody></table></div>`
   : `<p class="hint">${rankTitle} · 缺少该日排名快照。</p>`;
  const groups=Object.entries(trend.groups);
  const ordered=trend.rows.filter(row=>row.previous_change!=null).sort((a,b)=>b.previous_change-a.previous_change);
  const increase=ordered.find(row=>row.previous_change>0);
  const decrease=[...ordered].reverse().find(row=>row.previous_change<0);
  const movers=[increase&&'增加最多 '+increase.name+' '+signed(increase.previous_change)+' 股',decrease&&'减少最多 '+decrease.name+' '+signed(decrease.previous_change)+' 股'].filter(Boolean);
  $('ipo-summary').innerHTML=`<p class="hint">截至 ${esc(trend.latest)} · 较上市首日</p><div class="ipo-summary-grid">${groups.map(([label,group])=>{
   const point=group.values[group.values.length-1];
   return `<div><span>${esc(label)}</span><strong>${signed(point.change)} 股</strong><small>覆盖 ${point.covered}/${group.size}</small></div>`;
  }).join('')}</div>${movers.length?`<p>较前一数据日 · ${movers.map(esc).join(' · ')}</p>`:''}`;
  const channels=trend.rows.map(row=>`<tr><td>${esc(row.name)}<small>${esc(row.id)} · ${esc(row.label)}</small></td><td>${num(row.initial)}</td><td>${num(row.current)}</td><td>${signed(row.change)}</td><td>${row.remaining==null?'—':(row.remaining*100).toFixed(2)+'%'}</td><td>${signed(row.previous_change)}</td></tr>`).join('');
  const days=trend.days.map((day,index)=>`<tr><td>${esc(day)}</td>${groups.map(([,group])=>`<td>${signed(group.values[index].change)}</td>`).join('')}<td>${num(trend.prices[index]?.close)}</td><td>${money(trend.prices[index]?.turnover)}</td></tr>`).join('');
  BrokerView.replaceContent($('ipo-breakdown'),`<div class="table-scroll"><table><thead><tr><th>观察渠道</th><th>首日股数</th><th>当日股数</th><th>较首日增减</th><th>为首日比例</th><th>较前一数据日</th></tr></thead><tbody>${channels}</tbody></table></div><div class="table-scroll"><table><thead><tr><th>香港日期</th>${groups.map(([name])=>`<th>${esc(name)}变化（股）</th>`).join('')}<th>收盘（港元）</th><th>成交额</th></tr></thead><tbody>${days}</tbody></table></div>`);
 }
 async function load(){
  const sequence=++version;
  panel.hidden=!stock.value.startsWith('HK.');
  if(panel.hidden||!panel.open)return;
  try{
   const params=new URLSearchParams({code:stock.value,date:date.value});
   const response=await fetch('/api/ipo-trend?'+params,{cache:'no-store'});
   const payload=await response.json();
   if(sequence!==version)return;
   if(!response.ok)throw Error(payload.error);
   render(payload.trend);
  }catch(error){if(sequence===version)status.textContent=error.message}
 }
 const brokerPanel=$('ipo-broker-panel'), brokerHistory=$('ipo-broker-history');
 const brokerChart=$('ipo-broker-line'), brokerTitle=$('ipo-broker-title'), brokerPoint=$('ipo-broker-point');
 let historyVersion=0, historyPoints=[], positions=[];
 function drawBrokerHistory(){
  if(!brokerPanel.open||!historyPoints.length)return;
  const width=Math.floor(brokerChart.clientWidth), height=300;
  if(width<120)return;
  const scale=window.devicePixelRatio||1;
  brokerChart.width=width*scale;brokerChart.height=height*scale;
  const ctx=brokerChart.getContext('2d');
  ctx.setTransform(scale,0,0,scale,0,0);
  ctx.font='12px sans-serif';ctx.fillStyle='#284638';
  ctx.fillText('占全球发售（%）',8,16);
  const left=Math.max(74,...historyPoints.map(row=>ctx.measureText(ccassPercent(row.hold_ratio)).width+20));
  const right=width-24, values=historyPoints.map(row=>row.hold_ratio);
  const dates=historyPoints.map(row=>Date.parse(row.date+'T00:00:00Z'));
  const low=Math.min(...values), high=Math.max(...values);
  const y=value=>245-(high===low?.5:(value-low)/(high-low))*195;
  const x=i=>dates.length===1?(left+right)/2:left+(right-left)*(dates[i]-dates[0])/(dates[dates.length-1]-dates[0]);
  for(const value of new Set([low,(low+high)/2,high])){
   ctx.strokeStyle='#dfe6d8';ctx.beginPath();ctx.moveTo(left,y(value));ctx.lineTo(right,y(value));ctx.stroke();
   ctx.textAlign='right';ctx.fillText(ccassPercent(value),left-10,y(value)+4);
  }
  ctx.strokeStyle='#29654c';ctx.fillStyle='#29654c';ctx.lineWidth=2;ctx.beginPath();
  historyPoints.forEach((row,i)=>{if(i)ctx.lineTo(x(i),y(row.hold_ratio));else ctx.moveTo(x(i),y(row.hold_ratio))});
  ctx.stroke();
  positions=historyPoints.map((row,i)=>{
   ctx.beginPath();ctx.arc(x(i),y(row.hold_ratio),3,0,2*Math.PI);ctx.fill();return x(i);
  });
  ctx.textAlign='center';
  let previous=-Infinity;
  historyPoints.forEach((row,i)=>{
   if(i===0||i===historyPoints.length-1||(x(i)-previous>=55&&right-x(i)>=45)){
    ctx.fillText(row.date.slice(5),x(i),273);previous=x(i);
   }
  });
 }
 new ResizeObserver(drawBrokerHistory).observe(brokerChart);
 brokerChart.addEventListener('pointermove',event=>{
  if(!positions.length||!historyPoints.length)return;
  const x=event.clientX-brokerChart.getBoundingClientRect().left;
  const i=positions.reduce((best,value,index)=>Math.abs(value-x)<Math.abs(positions[best]-x)?index:best,0);
  const row=historyPoints[i];
  brokerPoint.textContent=row.date+' · '+ccassPercent(row.hold_ratio);
 });
 brokerPanel.addEventListener('close',()=>{historyVersion++;historyPoints=[];positions=[]});
 brokerPanel.addEventListener('click',event=>{if(event.target===brokerPanel&&event.clientX<brokerPanel.getBoundingClientRect().left)brokerPanel.close()});

 $('ipo-ranking').addEventListener('click',async event=>{
  const target=event.target.closest('[data-ipo-broker]');
  if(!target)return;
  const code=stock.value, broker=target.dataset.ipoBroker, name=target.textContent, sequence=++historyVersion;
  brokerTitle.textContent=name+' · '+broker+' 持仓趋势';
  historyPoints=[];positions=[];brokerChart.hidden=true;brokerPoint.textContent='';
  if(!brokerPanel.open)brokerPanel.showModal();
  brokerHistory.textContent='正在读取 '+name+' 的持仓历史…';
  const stale=()=>code!==stock.value||sequence!==historyVersion;
  const params=new URLSearchParams({code,broker});
  const read=async()=>{
   const response=await fetch('/api/ipo-trend?'+params,{cache:'no-store'});
   const result=await response.json();
   if(!response.ok)throw Error(result.error);
   return result;
  };
  function show(result,note=''){
   if(stale())return;
   historyPoints=result.items.filter(row=>Number.isFinite(row.hold_ratio));
   const base=historyPoints.find(row=>row.date===result.baseline);
   const latest=historyPoints[historyPoints.length-1];
   brokerHistory.textContent=latest
    ? '截至 '+latest.date+' · '+ccassPercent(latest.hold_ratio)+(base?' · 较首日 '+signed(latest.hold_ratio-base.hold_ratio)+' 个百分点':'')+(note?' · '+note:'')
    : ('暂无可计算的全球发售占比。'+note);
   brokerChart.hidden=!latest;
   brokerPoint.textContent=latest&&historyPoints.length>1?'移动鼠标查看各日全球发售占比。':'';
   if(latest)drawBrokerHistory();
  }
  let saved;
  try{
   saved=await read();
   show(saved,'正在向富途查询最新历史…');
   if(stale())return;
   const response=await fetch('/api/ccass-refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code,broker})});
   const result=await response.json();
   if(!response.ok)throw Error(result.error);
   if(!stale()){show(await read());load()}
  }catch(error){if(!stale()){if(saved)show(saved,'显示已保存记录。'+error.message);else brokerHistory.textContent=error.message}}
 });
 stock.addEventListener('change',()=>{historyVersion++;if(brokerPanel.open)brokerPanel.close();brokerHistory.textContent=''});
 button.addEventListener('click',async()=>{
  const code=stock.value;
  button.disabled=true;status.textContent='正在查询首日前十渠道的历史持仓…';
  try{
   const response=await fetch('/api/ccass-refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code,trend:true})});
   const payload=await response.json();
   if(!response.ok)throw Error(payload.error);
   status.textContent=payload.failed.length?'这些渠道本次查询失败，仍显示已保存数据：'+payload.failed.join('、'):'首日前十持仓已更新。';
   await load();
  }catch(error){status.textContent=error.message}
  finally{button.disabled=false}
 });
 stock.addEventListener('change',load);
 stock.addEventListener('ccass-ready',load);
 date.addEventListener('change',load);
 panel.addEventListener('toggle',load);
}
initializeIpoTrend();
