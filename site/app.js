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
  $('#meta').textContent=['f1','f2','f3'].filter(s=>d[s].status==='ok').map(s=>`${LABEL[s]} ${d[s].season} after round ${d[s].round}`).join(' · ');
  $('#standings').innerHTML=['f1','f2','f3'].map(s=>{const x=d[s];
    if(x.status!=='ok') return `<div class="card"><h2>${LABEL[s]}</h2><h3>Drivers</h3>${soon(s,'driver standings')}<h3>Teams</h3>${soon(s,'team standings')}</div>`;
    return `<div class="card"><h2>${LABEL[s]} ${x.season}</h2><h3>Drivers</h3>${tbl(x.drivers,[['#','pos'],['Driver','name'],['Team','team'],['Pts','points','n'],['W','wins','n']])}
      <h3>${s==="f1"?"Constructors":"Teams"}</h3>${tbl(x.teams,[['#','pos'],['Team','name'],['Pts','points','n'],['W','wins','n']])}</div>`}).join('');
}
function schedule(d){
  const local=Intl.DateTimeFormat().resolvedOptions().timeZone, saved=localStorage.getItem('tz')||local;
  const zones=Intl.supportedValuesOf?Intl.supportedValuesOf('timeZone'):[local,'UTC'];
  if(!zones.includes(saved)) zones.unshift(saved);
  $('#tz').innerHTML=zones.map(z=>`<option ${z===saved?'selected':''}>${z}</option>`).join('');
  $('#tzhint').textContent=`(detected: ${local})`;
  $('#cals').innerHTML='Add to your calendar: '+['f1','f2','f3'].map(s=>d[s].status==='ok'?`<a href="cal/${s}.ics" download>📅 ${LABEL[s]} .ics</a>`:`<a aria-disabled="true" style="opacity:.5">${LABEL[s]} .ics (coming soon)</a>`).join('');
  let view=location.hash==='#past'?'past':'upcoming';
  const draw=tz=>{const now=Date.now(),f=new Intl.DateTimeFormat(undefined,{timeZone:tz,weekday:'short',month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'});
    document.querySelectorAll('#view button').forEach(b=>b.setAttribute('aria-pressed',b.dataset.v===view));
    $('#h1').textContent=view==='past'?'Past events & results':'Upcoming sessions';
    $('#schedule').innerHTML=['f1','f2','f3'].map(s=>{const x=d[s];
      if(x.status!=='ok') return `<div class="card"><h2>${LABEL[s]}</h2>${soon(s,view==='past'?'race results':'session times')}</div>`;
      if(view==='past'){const rs=x.results||[];
        if(!rs.length) return `<div class="card"><h2>${LABEL[s]}</h2><p class="sub">No results yet this season.</p></div>`;
        return `<div class="card"><h2>${LABEL[s]} ${esc(x.season)} results</h2>${rs.map(r=>{const c=r.classification,pod=c.slice(0,3);
          return `<details class="race"><summary><b>${esc(r.event)}</b> <small>Rd ${esc(r.round)} · ${esc(r.place)} · ${esc(r.date)}</small>
            <ol class="podium">${pod.map(p=>`<li>${esc(p.name)} <small>${esc(p.team)}</small></li>`).join('')}</ol><span class="more">Full classification ▾</span></summary>
            ${tbl(c,[['Pos','pos'],['Driver','name'],['Team','team'],['Time/Status','time'],['Pts','points','n']])}</details>`}).join('')}</div>`}
      const up=x.sessions.filter(e=>Date.parse(e.start)>now-3*3600e3).slice(0,24);
      if(!up.length) return `<div class="card"><h2>${LABEL[s]}</h2><p class="sub">No upcoming sessions. The ${esc(x.season)} season is complete; see Past events &amp; results.</p></div>`;
      return `<div class="card"><h2>${LABEL[s]}</h2>${tbl(up.map(e=>({...e,when:f.format(new Date(e.start))})),[['Event','event'],['Session','session'],['When','when']])}</div>`}).join('');};
  document.querySelectorAll('#view button').forEach(b=>b.onclick=()=>{view=b.dataset.v;history.replaceState(null,'',view==='past'?'#past':location.pathname);draw($('#tz').value)});
  draw(saved); $('#tz').onchange=e=>{localStorage.setItem('tz',e.target.value);draw(e.target.value)};
}
async function news(){
  const n=await (await fetch('data/news.json')).json();
  $('#updated').textContent='News last updated: '+n.updated;
  let cat=(location.hash.slice(1)||'all').toLowerCase(), kind='all';
  const items=n.items.sort((a,b)=>b.date.localeCompare(a.date));
  const draw=()=>{
    document.querySelectorAll('#cats button').forEach(b=>b.setAttribute('aria-pressed',b.dataset.c===cat));
    document.querySelectorAll('#kinds button').forEach(b=>b.setAttribute('aria-pressed',b.dataset.k===kind));
    const list=items.filter(i=>(cat==='all'||(i.category||'f1').toLowerCase()===cat)&&(kind==='all'||i.type===kind));
    $('#news').innerHTML=list.length?list.map(i=>{const r=i.type==='Rumor';return `<div class="item ${r?'is-rumor':''}"><span class="badge cat">${esc((i.category||'F1').toUpperCase())}</span> <span class="badge ${r?'rumor':''}">${r?'⚠ Rumor · unconfirmed':'News · confirmed'}</span> <small>${esc(i.date)}</small>
    <h2>${esc(i.title)}</h2><p>${esc(i.summary)}</p><small>${r?'Reported by':'Source'}: <a href="${esc(i.url)}" target="_blank" rel="noopener">${esc(i.source)} ↗</a></small></div>`}).join(''):'<p class="sub">No items in this category from the last two weeks.</p>'};
  document.querySelectorAll('#cats button').forEach(b=>b.onclick=()=>{cat=b.dataset.c;history.replaceState(null,'',cat==='all'?location.pathname:'#'+cat);draw()});
  document.querySelectorAll('#kinds button').forEach(b=>b.onclick=()=>{kind=b.dataset.k;draw()});
  draw();
}
load();
