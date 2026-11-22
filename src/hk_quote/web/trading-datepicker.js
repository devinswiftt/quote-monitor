window.TradingDatePicker=(()=>{
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 function allowed(date,min,max,closed=[]){const day=new Date(date+'T12:00:00Z').getUTCDay();return !!date&&Number.isFinite(day)&&(!min||date>=min)&&(!max||date<=max)&&day!==0&&day!==6&&!closed.includes(date)}
 function html(month,options){
  const {min,max,closed=[],selected=''}=options,first=new Date(month+'-01T12:00:00Z'),offset=(first.getUTCDay()+6)%7;
  const cells=Array.from({length:42},(_,index)=>{const date=new Date(first);date.setUTCDate(1-offset+index);const iso=date.toISOString().slice(0,10),valid=allowed(iso,min,max,closed),other=iso.slice(0,7)!==month;
   return `<button type="button" data-calendar-day="${iso}" ${valid?'':'disabled'} class="${other?'other-month ':''}${iso===selected?'selected':''}" aria-label="${iso}${valid?'':' 不可选'}" ${iso===selected?'aria-current="date"':''}>${date.getUTCDate()}</button>`});
  return `<div class="trading-calendar-head"><button type="button" data-calendar-nav="-1" aria-label="上个月" ${min&&month<=min.slice(0,7)?'disabled':''}>‹</button><strong>${esc(month.replace('-','年'))}月</strong><button type="button" data-calendar-nav="1" aria-label="下个月" ${max&&month>=max.slice(0,7)?'disabled':''}>›</button><button type="button" data-calendar-close aria-label="关闭日历">×</button></div><div class="trading-calendar-grid">${['一','二','三','四','五','六','日'].map(d=>`<span>${d}</span>`).join('')}${cells.join('')}</div><p>周末、已知休市日、上市前与未来日期不可选</p>`;
 }
 function open(options){
  document.getElementById('trading-calendar-overlay')?.remove();
  const opener=document.activeElement,overlay=document.createElement('div');overlay.id='trading-calendar-overlay';overlay.className='trading-calendar-overlay';
  const panel=document.createElement('div');panel.className='trading-calendar';panel.setAttribute('role','dialog');panel.setAttribute('aria-modal','true');panel.setAttribute('aria-label','选择交易日期');overlay.append(panel);
  let month=(options.selected||options.max).slice(0,7);
  const close=()=>{overlay.remove();document.removeEventListener('keydown',keydown);if(opener?.isConnected)opener.focus()};
  const keydown=event=>{if(event.key==='Escape')close();if(event.key==='Tab'){const buttons=[...panel.querySelectorAll('button:not(:disabled)')],first=buttons[0],last=buttons[buttons.length-1];if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus()}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus()}}};
  const render=()=>{panel.innerHTML=html(month,options)};
  overlay.addEventListener('click',event=>{
   if(event.target===overlay||event.target.closest('[data-calendar-close]')){close();return}
   const nav=event.target.closest('[data-calendar-nav]');if(nav&&!nav.disabled){const date=new Date(month+'-01T12:00:00Z');date.setUTCMonth(date.getUTCMonth()+Number(nav.dataset.calendarNav));month=date.toISOString().slice(0,7);render();panel.querySelector('[data-calendar-close]').focus();return}
   const day=event.target.closest('[data-calendar-day]');if(day&&!day.disabled&&allowed(day.dataset.calendarDay,options.min,options.max,options.closed)){close();options.onSelect(day.dataset.calendarDay)}
  });
  render();document.body.append(overlay);document.addEventListener('keydown',keydown);panel.querySelector('button:not(:disabled)').focus();
 }
 function today(zone){return new Date().toLocaleDateString('sv-SE',{timeZone:zone})}
 function bind(input,button,{zone,closed=()=>[],min=()=>'',empty='选择日期'}){
  const options=()=>({min:min(),max:today(zone()),closed:closed()});
  function sync(){
   const {min,max,closed}=options();
   if(input.value&&!allowed(input.value,min,max,closed))input.value='';
   button.textContent=input.value||empty;
  }
  function select(value){input.value=value;sync();input.dispatchEvent(new Event('change'))}
  button.addEventListener('click',()=>open({...options(),selected:input.value,onSelect:select}));
  input.addEventListener('change',sync);
  sync();
  return {sync,clear:()=>select('')};
 }
 return {open,allowed,html,bind,today};
})();
