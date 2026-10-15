const $=s=>document.querySelector(s), esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const LABEL={f1:'F1',f2:'F2',f3:'F3'};
const soon=(s,what)=>`<div class="soon"><b>Coming soon</b>${LABEL[s]} ${what} aren't connected yet. We only show real data, never placeholders dressed up as results.</div>`;
const tbl=(rows,cols)=>`<table><tr>${cols.map(c=>`<th class="${c[2]||''}">${c[0]}</th>`).join('')}</tr>${rows.map(r=>`<tr>${cols.map(c=>`<td class="${c[2]||''}">${esc(r[c[1]])}</td>`).join('')}</tr>`).join('')}</table>`;
async function load(){
  if($('#news')) return news();
  const d=await (await fetch('data/series.json')).json();
  $('#updated').textContent='Data last refreshed: '+new Date(d.updated).toLocaleString();
  if($('#standings')) standings(d); if($('#schedule')) schedule(d);
}
function standings(d){
  $('#meta').textContent=`F1 ${d.f1.season} after round ${d.f1.round}. F2 and F3 standings update after each round once connected.`;
  $('#standings').innerHTML=['f1','f2','f3'].map(s=>{const x=d[s];
    if(x.status!=='ok') return `<div class="card"><h2>${LABEL[s]}</h2><h3>Drivers</h3>${soon(s,'driver standings')}<h3>Teams</h3>${soon(s,'team standings')}</div>`;
    return `<div class="card"><h2>${LABEL[s]} ${x.season}</h2><h3>Drivers</h3>${tbl(x.drivers,[['#','pos'],['Driver','name'],['Team','team'],['Pts','points','n'],['W','wins','n']])}
      <h3>Constructors</h3>${tbl(x.teams,[['#','pos'],['Team','name'],['Pts','points','n'],['W','wins','n']])}</div>`}).join('');
}
function schedule(d){
  const local=Intl.DateTimeFormat().resolvedOptions().timeZone, saved=localStorage.getItem('tz')||local;
  const zones=Intl.supportedValuesOf?Intl.supportedValuesOf('timeZone'):[local,'UTC'];
  if(!zones.includes(saved)) zones.unshift(saved);
  $('#tz').innerHTML=zones.map(z=>`<option ${z===saved?'selected':''}>${z}</option>`).join('');
  $('#tzhint').textContent=`(detected: ${local})`;
  $('#cals').innerHTML='Add to your calendar: '+['f1','f2','f3'].map(s=>d[s].status==='ok'?`<a href="cal/${s}.ics" download>📅 ${LABEL[s]} .ics</a>`:`<a aria-disabled="true" style="opacity:.5">${LABEL[s]} .ics (coming soon)</a>`).join('');
  const draw=tz=>{const now=Date.now(),f=new Intl.DateTimeFormat(undefined,{timeZone:tz,weekday:'short',month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'});
    $('#schedule').innerHTML=['f1','f2','f3'].map(s=>{const x=d[s];
      if(x.status!=='ok') return `<div class="card"><h2>${LABEL[s]}</h2>${soon(s,'session times')}</div>`;
      const up=x.sessions.filter(e=>Date.parse(e.start)>now-3*3600e3).slice(0,24);
      return `<div class="card"><h2>${LABEL[s]}</h2>${tbl(up.map(e=>({...e,when:f.format(new Date(e.start))})),[['Event','event'],['Session','session'],['When','when']])}</div>`}).join('');};
  draw(saved); $('#tz').onchange=e=>{localStorage.setItem('tz',e.target.value);draw(e.target.value)};
}
async function news(){
  const n=await (await fetch('data/news.json')).json();
  $('#updated').textContent='News last updated: '+n.updated;
  $('#news').innerHTML=n.items.sort((a,b)=>b.date.localeCompare(a.date)).map(i=>`<div class="item"><span class="badge ${i.type==='Rumor'?'rumor':''}">${esc(i.type)}</span> <small>${esc(i.date)}</small>
    <h2>${esc(i.title)}</h2><p>${esc(i.summary)}</p><small>${i.type==='Rumor'?'Reported by':'Source'}: <a href="${esc(i.url)}" target="_blank" rel="noopener">${esc(i.source)} ↗</a></small></div>`).join('');
}
load();
