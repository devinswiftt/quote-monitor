window.DailyChart=(()=>{
 const data=new Map(),pending=new Set(),messages=new Map(),esc=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 function svg(code,bars){
  if(!bars.length)return '<p class="empty">没有可用日K数据</p>';
  const width=760,height=390,left=12,right=68,top=24,bottom=260,volumeTop=285,volumeBottom=355;
  const high=Math.max(...bars.map(b=>b.high)),low=Math.min(...bars.map(b=>b.low)),pad=Math.max((high-low)*.08,high*.001,.001);
  const y=p=>top+(high+pad-p)/(high-low+2*pad)*(bottom-top),xs=bars.map((b,i)=>left+i/Math.max(1,bars.length-1)*(width-left-right));
  const x=t=>xs[bars.findIndex(b=>b.time===t)],bw=Math.min(9,(width-left-right)/Math.max(1,bars.length)*.65),vmax=Math.max(1,...bars.map(b=>b.volume));
  const candles=bars.map((b,i)=>{const color=b.close>=b.open?'#bd8275':'#75a38f';return `<line x1="${xs[i]}" x2="${xs[i]}" y1="${y(b.high)}" y2="${y(b.low)}" stroke="${color}"/><rect x="${xs[i]-bw/2}" y="${Math.min(y(b.open),y(b.close))}" width="${bw}" height="${Math.max(1,Math.abs(y(b.open)-y(b.close)))}" fill="${color}"/><rect x="${xs[i]-bw/2}" y="${volumeBottom-b.volume/vmax*(volumeBottom-volumeTop)}" width="${bw}" height="${b.volume/vmax*(volumeBottom-volumeTop)}" fill="${color}"/>`}).join('');
  const axes=[high,(high+low)/2,low].map(p=>`<line x1="${left}" x2="${width-right}" y1="${y(p)}" y2="${y(p)}" stroke="#e3e9df" stroke-dasharray="3 5"/><text x="${width-right+7}" y="${y(p)+4}" fill="#82917e" font-size="11">${p.toFixed(3)}</text>`).join('');
  const labels=Array.from({length:Math.min(4,bars.length)},(_,i)=>{const index=Math.round(i*(bars.length-1)/Math.max(1,Math.min(4,bars.length)-1));return `<text x="${xs[index]}" y="380" text-anchor="${i===0?'start':'end'}" font-size="11" fill="#82917e">${new Date(bars[index].time*1000).toLocaleDateString('sv-SE',{timeZone:code.startsWith('US.')?'America/New_York':'Asia/Hong_Kong'})}</text>`}).join('');
  return `<svg ${ChartHover.attributes(bars,x,y,code,true).replace('data-chart-size="large"','data-chart-size="daily"')} viewBox="0 0 ${width} ${height}" width="100%" role="img" aria-label="日K蜡烛图与成交量">${axes}${candles}${labels}<text x="12" y="14" font-size="11" fill="#82917e">日K · 不复权 · ${code.startsWith('US.')?'美元':'港元'}</text><text x="12" y="280" font-size="11" fill="#82917e">成交量 · 股</text>${ChartHover.frame(width,height,left,right,top,volumeBottom)}</svg>`;
 }
 function turnoverTable(code,bars){
  const money=value=>value==null?'未知':(Number(value)/10000).toFixed(2)+(code.startsWith('US.')?' 万美元':' 万港元');
  return `<details data-broker-disclosure="daily-turnover:${esc(code)}"><summary>历史每日成交额与成交量</summary><div class="table-scroll"><table><thead><tr><th>${code.startsWith('US.')?'纽约':'香港'}日期</th><th>收盘价</th><th>涨跌幅</th><th>成交股数</th><th>成交额</th></tr></thead><tbody>${bars.slice().reverse().map(b=>`<tr><td>${new Date(b.time*1000).toLocaleDateString('sv-SE',{timeZone:code.startsWith('US.')?'America/New_York':'Asia/Hong_Kong'})}</td><td>${Number(b.close).toFixed(3)}</td><td>${b.change_rate==null?'未知':(b.change_rate>=0?'+':'')+Number(b.change_rate).toFixed(2)+'%'}</td><td>${Number(b.volume).toLocaleString('zh-CN')}</td><td>${money(b.turnover)}</td></tr>`).join('')}</tbody></table></div></details>`;
 }
 function panel(code){const value=data.get(code);return `<section class="daily-chart-section"><div class="section-title"><h3>日K蜡烛图 · 最近一年（不复权）</h3><button class="secondary" type="button" data-load-daily="${esc(code)}" ${pending.has(code)?'disabled':''}>${pending.has(code)?'正在查询…':value?'刷新日K':'加载日K'}</button></div><p class="source-note">${esc(messages.get(code)||'按需获取，最多250个交易日；历史K线受富途权限和额度限制。')}${value?' · 查询时间 '+new Date(value.ts*1000).toLocaleString('zh-CN',{timeZone:code.startsWith('US.')?'America/New_York':'Asia/Hong_Kong'}):''}</p>${value?svg(code,value.bars)+turnoverTable(code,value.bars):''}<p class="hint">当天日K尚未收盘，按查询时点显示，点击刷新更新；不复权，与当前报价口径一致。</p></section>`}
 function update(code){const root=document.querySelector('[data-daily-panel="'+code+'"]');if(root)BrokerView.replaceContent(root,panel(code));ChartHover.restore()}
 document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-load-daily]');if(!button)return;const code=button.dataset.loadDaily;if(pending.has(code))return;
  const force=data.has(code);pending.add(code);messages.set(code,'正在获取富途历史日K');update(code);
  try{const response=await fetch('/api/daily?code='+encodeURIComponent(code)+(force?'&refresh=1':''),{cache:'no-store'});const value=await response.json();if(!response.ok)throw Error(value.error||'日K加载失败');data.set(code,value);messages.set(code,'已获取 '+value.bars.length+' 个交易日；来源：富途历史K线')}
  catch(e){messages.set(code,e.message)}finally{pending.delete(code);update(code)}
 });
 return {panel,svg};
})();
