/* SVG coordinates keep the cursor aligned at all display sizes. */
window.ChartHover=(()=>{
 let pointer=null;
 const escape=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 function attributes(bars,x,y,code,large){
  const values=bars.map(b=>[b.time,x(b.time),y(b.close),b.close,b.volume||0,!!b.synthetic,b.source||'local',b.open,b.high,b.low,b.turnover,b.change_rate]);
  return `data-price-chart="${escape(code)}" data-chart-size="${large?'large':'small'}" data-chart-values="${escape(JSON.stringify(values))}"`;
 }
 function frame(width,height,left,right,top,bottom){
  const boxWidth=width>500?320:260;
  return `<g data-chart-cursor="" display="none" pointer-events="none"><line data-hover-vertical="" y1="${top}" y2="${bottom}" stroke="#81957d" stroke-dasharray="4 4"/><line data-hover-horizontal="" x1="${left}" x2="${width-right}" stroke="#81957d" stroke-dasharray="4 4"/><circle data-hover-dot="" r="4" fill="#35785c" stroke="#fbfdf9" stroke-width="2"/><g data-hover-box="" data-box-width="${boxWidth}"><rect width="${boxWidth}" height="128" rx="6" fill="#163d30" opacity=".96"/>${[0,1,2,3,4,5].map(i=>`<text data-hover-label="${i}" x="10" y="${19+i*19}" fill="#fff" font-size="11"/>`).join('')}</g></g>`;
 }
 function nearest(values,x){
  let low=0,high=values.length-1;
  while(low<high){const mid=(low+high)>>1;if(values[mid][1]<x)low=mid+1;else high=mid}
  return low>0&&Math.abs(values[low-1][1]-x)<=Math.abs(values[low][1]-x)?values[low-1]:values[low];
 }
 function hide(){document.querySelectorAll('[data-chart-cursor]').forEach(n=>n.setAttribute('display','none'))}
 function show(svg,clientX,clientY){
  const values=JSON.parse(svg.dataset.chartValues||'[]');if(!values.length)return;
  const matrix=svg.getScreenCTM();if(!matrix)return;
  const point=svg.createSVGPoint();point.x=clientX;point.y=clientY;
  const p=point.matrixTransform(matrix.inverse()),view=svg.viewBox.baseVal;
  const first=values[0][1],last=values[values.length-1][1];
  if(p.x<first-4||p.x>last+4||p.y<16||p.y>view.height-25){hide();return}
  const sample=nearest(values,p.x);if(!sample)return;
  const [ts,x,y,price,volume,synthetic,source]=sample;
  const group=svg.querySelector('[data-chart-cursor]');group.setAttribute('display','inline');
  const vertical=group.querySelector('[data-hover-vertical]');vertical.setAttribute('x1',x);vertical.setAttribute('x2',x);
  const horizontal=group.querySelector('[data-hover-horizontal]');horizontal.setAttribute('y1',y);horizontal.setAttribute('y2',y);
  const dot=group.querySelector('[data-hover-dot]');dot.setAttribute('cx',x);dot.setAttribute('cy',y);
  const box=group.querySelector('[data-hover-box]'),width=Number(box.dataset.boxWidth);
  const bx=Math.max(4,Math.min(x+12,view.width-width-4)),by=Math.max(18,Math.min(y-140,view.height-132));
  box.setAttribute('transform',`translate(${bx},${by})`);
  const us=String(svg.dataset.priceChart||'').startsWith('US.'),unit=us?'美元':'港元';
  const time=new Date(ts*1000).toLocaleString('sv-SE',{timeZone:us?'America/New_York':'Asia/Hong_Kong'});
  const labels=source==='daily'?[time.slice(0,10)+' 日K · 不复权',`开 ${Number(sample[7]).toFixed(3)} · 高 ${Number(sample[8]).toFixed(3)}`,`低 ${Number(sample[9]).toFixed(3)} · 收 ${Number(price).toFixed(3)}`,`成交量 ${Number(volume).toLocaleString('zh-CN')} 股`,sample[10]==null?'成交额：未知':`成交额 ${(Number(sample[10])/10000).toFixed(2)} 万${unit}` ,sample[11]==null?'涨跌幅：未知':`涨跌幅 ${Number(sample[11])>=0?'+':''}${Number(sample[11]).toFixed(2)}%`]:[time+(us?' ET':' HKT'),`${synthetic?'沿用前价':'分钟成交价'}：${Number(price).toFixed(3)} ${unit}`,synthetic?'成交量：未知（图中按0显示）':`成交量：${Number(volume).toLocaleString('zh-CN')} 股`,synthetic?'缺失分钟补齐，非真实成交':source==='futu'?'来源：富途分钟行情':'来源：本机保存逐笔成交'];
  group.querySelectorAll('[data-hover-label]').forEach((n,i)=>n.textContent=labels[i]||'');
 }
 function restore(){
  if(!pointer)return;
  const svg=[...document.querySelectorAll('svg[data-price-chart]')].find(n=>n.dataset.priceChart===pointer.code&&n.dataset.chartSize===pointer.size);
  if(svg)show(svg,pointer.x,pointer.y);
 }
 document.addEventListener('pointermove',event=>{
  const svg=event.target.closest?.('svg[data-price-chart]');
  if(!svg){if(pointer){hide();pointer=null}return}
  hide();pointer={code:svg.dataset.priceChart,size:svg.dataset.chartSize,x:event.clientX,y:event.clientY};show(svg,event.clientX,event.clientY);
 });
 document.addEventListener('pointerout',event=>{if(!event.relatedTarget){hide();pointer=null}});
 function clear(){hide();pointer=null}
 return {attributes,frame,nearest,restore,clear};
})();
