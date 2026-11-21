globalThis.window={};load('src/hk_quote/web/trading-datepicker.js');
const picker=window.TradingDatePicker,options={min:'2026-11-11',max:'2026-11-19',closed:['2026-11-16'],selected:'2026-11-13'};
const html=picker.html('2026-11',options);
for(const date of ['2026-11-10','2026-11-14','2026-11-15','2026-11-16','2026-11-20']){
 if(picker.allowed(date,options.min,options.max,options.closed))throw Error('Invalid date allowed '+date);
 const tag=html.match(new RegExp('<button[^>]*data-calendar-day="'+date+'"[^>]*>'))?.[0];if(!tag||!tag.includes('disabled'))throw Error('Invalid day still clickable '+date);
}
for(const date of ['2026-11-11','2026-11-13','2026-11-17','2026-11-19']){
 if(!picker.allowed(date,options.min,options.max,options.closed))throw Error('Trading day rejected '+date);
 const tag=html.match(new RegExp('<button[^>]*data-calendar-day="'+date+'"[^>]*>'))?.[0];if(!tag||tag.includes('disabled'))throw Error('Trading day disabled '+date);
}
if(!html.match(/data-calendar-nav="-1"[^>]*disabled/)||!html.match(/data-calendar-nav="1"[^>]*disabled/))throw Error('Month bounds missing');
print('Calendar actual disabled buttons, weekends, known holidays, listing/future bounds passed');
