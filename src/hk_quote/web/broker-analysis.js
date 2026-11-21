/* Shared views for observed changes and explicitly unverified passive-side clues. */
window.BrokerView=(()=>{
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const pct=v=>v==null?'—':Math.round(v*100)+'%';
 const num=v=>v==null?'—':Number(v).toLocaleString('zh-CN',{maximumFractionDigits:2});
 const broker=r=>`${esc(r.name)}<small class="broker-ids">${esc((r.ids||[]).join(' / '))}</small>`;
 function chart(rows,label){
  if(!rows.length)return '<p class="empty">未发现达到规则的明显变化，或常态采样不足。</p>';
  const max=Math.max(1,...rows.map(r=>r.changed_alerts));
  return `<svg class="report-bars" viewBox="0 0 650 ${rows.length*66+12}" role="img" aria-label="${esc(label)}变化异动次数">${rows.map((r,i)=>`<g><title>${esc(r.name)} [${esc(r.ids.join('/'))}]：${r.changed_alerts}次明显变化；在场${r.alerts}/${r.eligible_alerts}次；低置信成交候选${r.clue_alerts}次</title><text x="0" y="${i*66+19}" fill="#3c5b41" font-size="13">${esc(r.name)}</text><rect x="155" y="${i*66+5}" width="375" height="20" rx="4" fill="#edf2e7"/><rect x="155" y="${i*66+5}" width="${375*r.changed_alerts/max}" height="20" rx="4" fill="${label==='买1'?'#719a75':'#b48775'}"/><text x="550" y="${i*66+20}" fill="#466a47" font-size="13">${r.changed_alerts} 次</text><text x="155" y="${i*66+44}" fill="#87967b" font-size="10">${esc(r.ids.join(' / '))}</text><text x="155" y="${i*66+58}" fill="#87967b" font-size="10">在场 ${r.alerts}/${r.eligible_alerts} 次 · 低置信候选 ${r.clue_alerts} 次</text></g>`).join('')}</svg>`;
 }
 function summary(rows,code){
  const filtered=rows.filter(r=>!code||r.code===code);
  return '<p class="hint">主图按“相比常态发生明显变化”的异动次数排名，仅统计买1／卖1；常驻但没有明显变化的券商不进入主图。成交候选均为低置信线索。</p><div class="data-grid">'+['bid','ask'].map((side,i)=>{const rs=filtered.filter(r=>r.side===side&&r.changed_alerts>0).sort((a,b)=>b.changed_alerts-a.changed_alerts||b.alerts-a.alerts).slice(0,10);return `<section><h3>${i?'卖1':'买1'} · 明显变化券商</h3>${chart(rs,i?'卖1':'买1')}</section>`}).join('')+'</div><details data-broker-disclosure="presence-background"><summary>查看买1／卖1在场背景统计</summary><div class="table-scroll"><table><thead><tr><th>股票／一侧</th><th>券商／编号</th><th>在场异动</th><th>明显变化</th><th>低置信候选</th></tr></thead><tbody>'+filtered.map(r=>`<tr><td>${esc(r.code)}<br>${r.side==='bid'?'买1':'卖1'}</td><td>${broker(r)}</td><td>${r.alerts}/${r.eligible_alerts}</td><td>${r.changed_alerts}</td><td>${r.clue_alerts}</td></tr>`).join('')+'</tbody></table></div><p class="hint">在场分母为有有效采样的异动；不同券商的次数不可相加作为异动总数。</p></details>';
 }
 function notice(a){
  const n=a.notification_summary;
  if(!n)return a.participation?.status==='pending'?'<div class="notice-preview muted">券商摘要采样中，完成后自动显示。</div>':'';
  return `<div class="notice-preview"><strong>券商通知摘要</strong><p>${esc(n.text)}</p>${n.reconstructed?'<small>由已保存分析还原；未保存当时的通知原文。</small>':''}</div>`;
 }
 function detail(p){
  if(!p)return '<p class="broker-note">此记录缺少分析数据。</p>';
  if(p.status==='pending')return '<p class="broker-note">正在收集异动后10秒数据，约11秒后更新在场、常态变化与成交线索。</p>';
  if(p.version!==2)return '<p class="broker-note">旧口径记录尚未重新计算，不纳入买1／卖1排名。</p>';
  const baseline=p.baseline||{},clue=p.trade_clues||{},e=clue.evidence||{};
  const evidence=e.price!=null?`<div class="metrics"><span>对照价格 HK$ ${num(e.price)}</span><span>该价挂盘净减少 ${num(e.queue_reduction)} 股</span><span>同价同方向成交 ${num(e.matched_volume)} 股</span></div>`:'';
  const candidates=(clue.candidates||[]).map(r=>`<li>${broker(r)} · ${esc(clue.passive_side)} · 最优档条目减少 ${r.removed_queue_entries}</li>`).join('');
  const rows=p.changes||[];
  const changes=rows.length?'<div class="table-scroll"><table><thead><tr><th>一侧／券商</th><th>变化</th><th>常态 → 异动出现比例</th><th>平均条目数变化</th></tr></thead><tbody>'+rows.map(r=>`<tr><td>${r.side==='bid'?'买1':'卖1'} · ${broker(r)}</td><td>${esc(r.change)}</td><td>${pct(r.baseline_ratio)} → ${pct(r.presence_ratio)} <small>（${r.presence_delta>=0?'+':''}${Math.round(r.presence_delta*100)} 个百分点）</small></td><td>${num(r.baseline_mean_queue_entries)} → ${num(r.mean_queue_entries)}</td></tr>`).join('')+'</tbody></table></div>':`<p class="empty">${baseline.sufficient?'未观察到达到变化规则的券商；不能据此认定没有成交。':'常态或异动采样不足，不判断谁明显增加或退出。'}</p>`;
  const presence=['bid','ask'].map(side=>`<section><h3>${side==='bid'?'买1':'卖1'}在场</h3><div class="table-scroll"><table><thead><tr><th>券商／编号</th><th>常态比例</th><th>异动比例</th><th>平均条目</th></tr></thead><tbody>${(p[side]||[]).map(r=>`<tr><td>${broker(r)}</td><td>${pct(r.baseline_ratio)}</td><td>${pct(r.presence_ratio)}</td><td>${num(r.mean_queue_entries)}</td></tr>`).join('')}</tbody></table></div></section>`).join('');
  return `<p class="broker-note">仅买1／卖1 · 异动采样 ${p.valid_samples}/21 · 常态采样 ${baseline.valid_samples||0}/60。${p.interrupted?'窗口因暂停或断连截断，按已有数据分析。':''}</p><h3>相比常态，谁明显变化？</h3>${changes}<section class="clue-panel"><h3>成交线索 · ${candidates?'低置信候选':'无法判断'}</h3><p>${esc(clue.reason||'缺少成交证据')}</p>${candidates?'<ul>'+candidates+'</ul>':''}${evidence}<p class="hint">只尝试寻找被动成交方；主动方未知。撤单、补单和推送不同步仍可能造成相同变化，条目数不等于股数，候选不是确认成交。</p></section><details><summary>查看买1／卖1在场名单与规则</summary><div class="data-grid">${presence}</div><p class="hint">常态：触发前70～11秒；异动：触发前后各10秒。每秒取最近5秒内推送；缺失不算未出现。常态至少30、异动至少10个有效采样才比较；出现比例变化至少20个百分点，且相应窗口至少出现3次，或平均条目变化同时达到1个及常态的50%。这是观察规则，不是成交概率。</p></details>`;
 }
 function disclosureKey(node,root){
  const parts=[];
  for(let current=node;current&&current!==root;current=current.parentElement){
   if(current.tagName!=='DETAILS')continue;
   const d=current.dataset;
   const token=d.id!=null?'alert:'+d.id:d.analysisId!=null?'analysis:'+d.analysisId:d.behaviorId!=null?'behavior:'+d.behaviorId:d.brokerDisclosure||current.querySelector('summary')?.textContent.trim();
   parts.unshift(token||'details');
  }
  return JSON.stringify(parts);
 }
 function captureDisclosures(root){
  return [...root.querySelectorAll('details')].map(node=>({key:disclosureKey(node,root),open:node.open,
   scroll:[...node.querySelectorAll('.table-scroll')].map(n=>({left:n.scrollLeft,top:n.scrollTop}))}));
 }
 function restoreDisclosures(root,state){
  const saved=new Map(state.map(s=>[s.key,s]));
  root.querySelectorAll('details').forEach(node=>{
   const old=saved.get(disclosureKey(node,root));if(!old)return;
   node.open=old.open;
   node.querySelectorAll('.table-scroll').forEach((n,i)=>{if(old.scroll[i]){n.scrollLeft=old.scroll[i].left;n.scrollTop=old.scroll[i].top}});
  });
 }
 const renderedContent=new WeakMap();
 function replaceContent(root,html){
  if(renderedContent.get(root)===html)return;
  const state=captureDisclosures(root);root.innerHTML=html;restoreDisclosures(root,state);
  renderedContent.set(root,html);
 }
 function renderSummary(root,rows,code){replaceContent(root,summary(rows,code))}
 function attribution(value){
  if(!value)return '';
  const e=esc,n=x=>Number(x).toLocaleString('zh-CN'),rows=value.candidates||[],scale=Math.max(1,...rows.map(r=>Math.abs(r.delta)));
  return `<section class="delayed-broker-analysis"><h3>延迟经纪商净量对照</h3><p class="broker-note">${e(value.reason)}。${e(value.note)}</p>${value.from_source?`<p class="source-note">源时间 ${e(value.from_source)} → ${e(value.to_source)}${value.interval_seconds!=null?' · '+value.interval_seconds+' 秒区间':''}<br>${value.before_id!=null?'快照 #'+value.before_id+' / #'+value.after_id+' · 获取延迟 '+value.before_delay+' / '+value.after_delay+' 秒':''}${value.after_close_review?' · 后快照为收盘后采集，非官方最终确认':''}${value.same_time_revisions?' · 包含同源时间修订，未当作额外更新':''}</p>`:''}${value.related?.length?`<p class="source-note">本区间相关记录：${value.related.map(e).join('、')}；关联提醒与行为事件可能描述同一段行情，数量不代表独立操作。</p>`:''}${rows.length?`<div class="table-scroll"><table><thead><tr><th>券商（无编号）</th><th>前净量（股）</th><th>后净量（股）</th><th>净量变化（股）</th><th>解释</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${e(r.name)}</td><td>${n(r.before_net)}</td><td>${n(r.after_net)}</td><td><span class="${r.delta>0?'change-up':'change-down'}">${r.delta>0?'+':''}${n(r.delta)}</span><div class="broker-delta-track"><span class="${r.delta>0?'delta-buy':'delta-sell'}" style="width:${Math.abs(r.delta)/scale*100}%"></span></div></td><td>${e(r.meaning)}${r.aligned?' · 与本次成交方向一致':''}${r.queue_context?.length?' · 同期'+r.queue_context.map(side=>side==='bid'?'买1':'卖1').join('/')+'在场（非成交证明）':''}</td></tr>`).join('')}</tbody></table></div>`:value.status==='available'||value.status==='interval'?'<p class="muted">没有能在前后两份榜单中连续比较、且净量发生变化的券商。</p>':''}${value.before_id!=null?(value.closing_review?`<details><summary>收盘后末次快照复核 · ${e(value.closing_review.source)}</summary><p class="source-note">这是事件后到末次收盘后快照的全区间变化，不归属于本次异动；未获官方最终确认。</p><div class="table-scroll"><table><thead><tr><th>券商</th><th>事件后净量（股）</th><th>末次净量（股）</th><th>此后变化（股）</th></tr></thead><tbody>${value.closing_review.changes.map(r=>`<tr><td>${e(r.name)}</td><td>${n(r.event_after_net)}</td><td>${r.closing_net==null?'未上榜':n(r.closing_net)}</td><td>${r.delta_since_event==null?'不可算':n(r.delta_since_event)}</td></tr>`).join('')}</tbody></table></div></details>`:'<p class="source-note">收盘复核：尚未取得该日收盘后采集快照，不把盘中末次数据当作最终值。</p>'):''}${value.unmatched?.length?`<details><summary>上榜变化，不能计算净量差</summary><p>${value.unmatched.map(r=>e(r.name)+'：'+e(r.status)).join('；')}。榜外不是零，不能当作入场或清仓。</p></details>`:''}</section>`;
 }
 return {attribution,summary,detail,notice,renderSummary,replaceContent,captureDisclosures,restoreDisclosures};
})();
