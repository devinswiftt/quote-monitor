window.BehaviorView=(()=>{
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const labels={DUMP:'疑似砸盘',SUPPORT:'疑似承接护盘',LIFT:'疑似主动拉升'};
 const phases={observing:'观察中',confirmed:'证据增强',ongoing:'持续发生',cooling:'信号缓解',resolved:'观察结束',failed:'承接失效',interrupted:'监控中断'};
 const colors={DUMP:'#789887',SUPPORT:'#a78d55',LIFT:'#b67c67'};
 const time=t=>new Date(t*1000).toLocaleTimeString('zh-CN',{timeZone:'Asia/Hong_Kong',hour12:false});
 const number=n=>n==null?'—':Number(n).toLocaleString('zh-CN',{maximumFractionDigits:3});
 const money=n=>n==null?'—':(Number(n)/10000).toFixed(2)+' 万港元';
 const pct=n=>n==null?'—':Math.round(n*100)+'%';
 function segments(r){
  const parts=[];let begin=r.started_at,kind=r.history[0]?.type||r.type,confirmed=false,phase='observing';
  for(const h of r.history){
   if(h.type!==kind){parts.push({r,start:begin,end:h.ts,type:kind,confirmed,phase});begin=h.ts;kind=h.type;confirmed=false}
   if(h.phase==='confirmed')confirmed=true;phase=h.phase;
  }
  parts.push({r,start:begin,end:r.updated_at,type:kind,confirmed,phase});return parts;
 }
 function timeline(rows,names){
  if(!rows.length)return '';
  const day=new Date((rows[0].started_at+8*3600)*1000);day.setUTCHours(0,0,0,0);
  const midnight=day.getTime()/1000-8*3600,start=midnight+9.5*3600,end=midnight+16*3600;
  const x=t=>105+(Math.min(end,Math.max(start,t))-start)/(end-start)*870;
  return `<svg class="behavior-timeline" viewBox="0 0 1000 150" role="img" aria-label="当日行为观察区间，灰色代表仅观察"><rect x="${x(midnight+12*3600)}" y="0" width="${x(midnight+13*3600)-x(midnight+12*3600)}" height="110" fill="#f0f0e9"/>${['DUMP','SUPPORT','LIFT'].map((kind,i)=>`<text x="0" y="${25+i*35}" font-size="12" fill="#73836e">${labels[kind]}</text><line x1="105" x2="975" y1="${22+i*35}" y2="${22+i*35}" stroke="#e3e9df"/>${rows.flatMap(segments).filter(v=>v.type===kind).map(v=>`<rect x="${x(v.start)}" y="${14+i*35}" width="${Math.max(3,x(v.end)-x(v.start))}" height="16" rx="3" fill="${v.confirmed?colors[kind]:'#c6cdbf'}"><title>${esc(names[v.r.code]||v.r.code)} B${v.r.id} ${labels[kind]} ${phases[v.phase]} ${time(v.start)}—${time(v.end)}</title></rect>`).join('')}`).join('')}${[9.5,12,13,16].map(h=>`<text x="${x(midnight+h*3600)}" y="135" font-size="11" text-anchor="middle" fill="#82917e">${h===9.5?'09:30':h+':00'}</text>`).join('')}</svg>`;
 }
 function detail(r){
  const e=r.evidence||{};
  const trades=(r.signals||[]).map(a=>`<tr><td>#${a.id}</td><td>${time(a.ts)}</td><td>${esc(a.signal_label||{BUY:'主动买入异动',SELL:'主动卖出异动',VOLUME:'成交放大'}[a.signal]||a.signal)}</td><td>${money(a.amount)}</td><td>${number(a.price)}</td></tr>`).join('');
  return `${window.BrokerView.attribution?window.BrokerView.attribution(r.broker_attribution):''}<p class="broker-note">${esc(r.status_reason||e.reason)}。${r.source==='replay'?'历史原始数据回放补充；不是当时发送的通知。':''}这些标签描述行情表现，不确认操作意图。</p><div class="metrics"><span>${e.window_seconds} 秒窗口成交 ${money(e.amount)}</span><span>主动买入 ${money(e.buy_amount)}</span><span>主动卖出 ${money(e.sell_amount)}</span><span>方向集中度 ${pct(e.direction_ratio)} · 已知方向覆盖 ${pct(e.coverage)}</span><span>成交 ${number(e.price_from)} → ${number(e.price_to)}</span><span>动态门槛 ${money(e.threshold)} · ${e.baseline_samples} 个历史非空窗口</span></div>${r.type==='SUPPORT'?`<p>承接参考价 ${number(e.anchor)}；同价卖出 ${number(e.matched_sell_shares)} 股；挂盘消耗后恢复 ${number(e.replenishment_cycles)} 轮，恢复股数合计 ${number(e.restored_shares)}。恢复是快照估计，不能精确拆分新增、撤单与补单。</p>`:`<p>成交价格推进 ${number(e.price_change)}；观察价格步长 ${number(e.observed_price_step)}、价差 ${number(e.spread)}。同价 ${number(e.consumed_price)} 挂盘净减少 ${number(e.queue_reduction)} 股，对应方向成交 ${number(e.matched_shares)} 股；${e.book_supported?'有盘口佐证':'尚缺充分盘口佐证'}。观察步长来自可见价差，未认定为交易所最小价位。</p>`}${r.failure_price!=null?`<p>承接区域随后被连续主动卖出成交跌破，失效成交价 ${number(r.failure_price)}。</p>`:''}<h3>事件过程</h3><div class="table-scroll"><table><thead><tr><th>香港时间</th><th>行为</th><th>状态／原因</th></tr></thead><tbody>${r.history.map(h=>`<tr><td>${time(h.ts)}</td><td>${esc(labels[h.type])}</td><td>${esc(phases[h.phase])} · ${esc(h.reason)}</td></tr>`).join('')}</tbody></table></div><h3>关联的原始成交提醒</h3>${trades?`<div class="table-scroll"><table><thead><tr><th>编号</th><th>时间</th><th>原始信号</th><th>成交额</th><th>触发价</th></tr></thead><tbody>${trades}</tbody></table></div>`:'<p class="muted">本事件未触发原有大额成交门槛，或当时没有保存相关成交提醒；行为监控可独立触发。</p>'}<details><summary>首次观察窗口的券商证据附件</summary>${window.BrokerView.detail(r.participation)}</details>`;
 }
 function confirmedTypes(r){return [...new Set((r.history||[]).filter(h=>h.phase==='confirmed').map(h=>h.type))]}
 function confirmation(r){const types=confirmedTypes(r);return types.length?'曾确认：'+types.map(t=>labels[t]||t).join('、'):'仅观察，未达到确认条件'}
 function ended(r){return ['resolved','failed','interrupted'].includes(r.phase)}
 function render(rows,names,code='',type='',phase='',summaryOnly=false){
  const confirmed=r=>confirmedTypes(r).length>0;
  const filtered=rows.filter(r=>(!code||r.code===code)&&(!type||r.type===type)&&(!phase||(phase==='confirmed'?confirmed(r):phase==='unconfirmed'?!confirmed(r):phase==='ended'?ended(r):phase==='active'?!ended(r):r.phase===phase)));
  const confirmedCount=filtered.filter(confirmed).length;
  const counts=['DUMP','SUPPORT','LIFT'].map(kind=>{const matches=filtered.filter(r=>r.type===kind),n=matches.filter(confirmed).length;return `<button type="button" class="behavior-stat secondary" data-behavior-filter="${kind}" aria-pressed="${type===kind}"><strong>${matches.length}<small> 条</small></strong><span>${labels[kind]}</span><p class="muted">曾确认 ${n} 条 · 仅观察 ${matches.length-n} 条</p></button>`}).join('');
  if(summaryOnly)return `<p class="hint">当前筛选：共 ${filtered.length} 条 · 曾确认 ${confirmedCount} 条 · 仅观察 ${filtered.length-confirmedCount} 条</p><div class="behavior-stats">${counts}</div><p class="hint">每个行为按当前类型计一次，数量对应上方图中同一筛选；具体证据按需打开，完整记录见首页。</p>`;
  return `<p class="hint">当前筛选：共 ${filtered.length} 条 · 曾确认 ${confirmedCount} 条 · 仅观察 ${filtered.length-confirmedCount} 条</p><div class="behavior-stats">${counts}</div>${timeline(filtered,names)}<p class="hint">数量与下方记录使用同一筛选，按事件当前行为归类，每个事件只计一次。曾确认表示历史中至少一种行为达到确认条件；具体确认行为见记录标签。时间轴保留行为转换过程，灰色仅为观察。</p>`+filtered.map(r=>`<details class="record" data-behavior-id="${r.id}"><summary><div><div class="title"><span class="pill">${labels[r.type]}</span>${esc(names[r.code]||r.code)} ${esc(r.code)}</div><div class="time">${time(r.started_at)}—${time(r.updated_at)} HKT · B${r.id} ${r.source==='replay'?'· 历史回放':''} · 关联 ${(r.alert_ids||[]).length} 条原始提醒</div><div class="time">${esc(confirmation(r))}</div></div><span class="badge">${ended(r)?'已结束':'进行中'} · ${esc(phases[r.phase]||r.phase)}</span></summary><div class="detail">${detail(r)}</div></details>`).join('')+(filtered.length?'':'<p class="empty">当前筛选没有行为记录；可切换确认情况或进行状态查看。</p>');
 }
 function journal(r,names){
  const e=r.evidence||{},confirmed=(r.history||[]).some(h=>h.phase==='confirmed');
  const date=t=>new Date(t*1000).toLocaleString('sv-SE',{timeZone:'Asia/Hong_Kong'});
  return `<details class="record" data-id="B${r.id}" data-behavior-id="${r.id}"><summary><div><div class="title"><span class="pill ${r.type==='DUMP'?'sell':''}">${esc(labels[r.type])}</span>${esc(names[r.code]||r.code)} ${esc(r.code)}</div><div class="time">${esc(date(r.started_at))}—${time(r.updated_at)} HKT · B${r.id} · ${esc(phases[r.phase])} · ${confirmed?'曾达到确认条件':'仅观察，未达到确认条件'}${r.source==='replay'?' · 历史回放':''}</div><div class="time">成交价 ${number(e.price_from)} → ${number(e.price_to)} 港元 · 关联 ${(r.alert_ids||[]).length} 条原始提醒${r.alert_ids?.length?'：'+r.alert_ids.map(id=>'#'+id).join('、'):''}</div></div><div class="money">${money(e.amount)}<small>${e.window_seconds} 秒观察窗口 · 行为事件 ⌄</small></div></summary><div class="detail">${detail(r)}</div></details>`;
 }
 function markers(rows,code,first,last,x,top,bottom){
  return rows.filter(r=>r.code===code).flatMap(segments).filter(v=>v.start<=last+60&&v.end>=first).map(v=>{const a=x(Math.max(first,v.start)),b=x(Math.min(last,v.end));return `<rect x="${a}" y="${top}" width="${Math.max(2,b-a)}" height="${bottom-top}" fill="${v.confirmed?colors[v.type]:'#aab4a2'}" opacity=".10"><title>B${v.r.id} ${labels[v.type]} ${phases[v.phase]} ${time(v.start)}—${time(v.end)}</title></rect>`}).join('');
 }
 return {render,markers,labels,journal};
})();
