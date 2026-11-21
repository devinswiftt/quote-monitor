const source=readFile('src/hk_quote/web/app.js');let click,stored='0';const button={setAttribute(k,v){this[k]=v},addEventListener(type,fn){click=fn}},content={hidden:false};const $=id=>id==='journal-toggle'?button:content;
const localStorage={getItem:()=>stored,setItem:(key,value)=>stored=value};
const init=new Function('$','localStorage',source.slice(source.indexOf('function initializeJournalCollapse('),source.indexOf('\n}\n',source.indexOf('function initializeJournalCollapse('))+3)+';return initializeJournalCollapse;')($,localStorage);
init();if(content.hidden)throw Error('Initial list unexpectedly hidden');click();if(!content.hidden||button['aria-expanded']!=='false'||stored!=='1')throw Error('Collapse failed');
init();if(!content.hidden)throw Error('Reload preference lost');click();if(content.hidden||stored!=='0')throw Error('Expand failed');
const failing=new Function('$','localStorage',source.slice(source.indexOf('function initializeJournalCollapse('),source.indexOf('\n}\n',source.indexOf('function initializeJournalCollapse('))+3)+';return initializeJournalCollapse;')($,{getItem(){throw Error()},setItem(){throw Error()}});failing();click();if(!content.hidden)throw Error('Storage error broke toggle');
print('Journal collapse/expand, reload persistence, storage failure passed');
