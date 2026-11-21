const html=readFile('src/hk_quote/web/report.html'),js=readFile('src/hk_quote/web/report.js');
if(html.includes('异常席位 · 重点关注')||js.includes('function renderSeatHighlights'))throw Error('Five anomaly cards remain');
if(!html.includes('券商上午／下午买卖对照'))throw Error('Broker comparison missing');
if(html.includes('id="seat-category"')||js.includes("$('seat-category').addEventListener"))throw Error('Old per-seat selector remains');
if(!js.includes("pager('seat',seatPage,rows.length)"))throw Error('All brokers must remain pageable');
print('Obsolete top-five UI removed; full broker comparison pageable');
