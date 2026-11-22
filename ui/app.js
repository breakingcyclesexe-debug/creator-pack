/* Creator Pack page. Talks only to the local server (127.0.0.1). Judgement work (story, changes, chat) is
   written as jobs that the buyer's own Claude Code session picks up; this page never talks to Claude. */
(function(){
  const $ = s => document.querySelector(s);
  const $$ = s => Array.from(document.querySelectorAll(s));
  const icon = id => `<svg class="ico" aria-hidden="true"><use href="#${id}"/></svg>`;
  const esc = s => String(s==null?'':s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  const val = n => (document.querySelector(`input[name="${n}"]:checked`)||{}).value;
  const setRadio = (n,v) => { const r=document.querySelector(`input[name="${n}"][value="${v}"]`); if(r) r.checked=true; };
  const mmss = t => { t=Math.max(0,Math.round(t||0)); return `${Math.floor(t/60)}:${String(t%60).padStart(2,'0')}`; };
  /* only touch the page when something changed, so spinners and scroll positions don't jump on every poll */
  const setHTML = (el, html) => { if(el._h===html) return false; el.innerHTML=html; el._h=html; return true; };
  let toastT;
  function toast(msg){ const t=$('#toast'); t.textContent=msg; t.classList.add('show'); clearTimeout(toastT); toastT=setTimeout(()=>t.classList.remove('show'),3600); }
  const CC_HELP = 'In the Claude app, open Claude Code and send /creator-pack';

  /* ---------- server ---------- */
  async function api(path, body, raw){
    const opt = body===undefined ? {} : {method:'POST', headers:{'X-CPack':'1', 'Content-Type': raw?'application/octet-stream':'application/json'}, body: raw?body:JSON.stringify(body)};
    const r = await fetch(path, opt);
    const j = await r.json().catch(()=>({}));
    if(!r.ok) throw new Error(j.error || `Something went wrong (${r.status})`);
    return j;
  }
  let ST = null, PJ = null, pid = localStorage.getItem('cpack-project') || '';
  Object.defineProperty(window, 'PJ', { get: () => PJ, configurable: true });
  const connected = () => !!(ST && ST.connected);

  /* ---------- clocks: when a piece of work started, so every wait shows time so far and a rough time left ---------- */
  function since(key, serverSecs){
    if(serverSecs) return Math.round(serverSecs*1000);
    const k = `cpack-since-${pid}-${key}`; let v = +localStorage.getItem(k);
    if(!v){ v = Date.now(); localStorage.setItem(k, v); }
    return v;
  }
  const clearSince = key => localStorage.removeItem(`cpack-since-${pid}-${key}`);
  function leftText(el){
    const est = +el.dataset.est, gone = (Date.now() - +el.dataset.from)/1000, left = est - gone;
    if(!est) return el.dataset.none || '';
    if(left > 90) return `about ${Math.round(left/60)} min left`;
    if(left > 45) return 'about a minute left';
    if(left > 8) return 'under a minute left';
    if(left > -20) return 'almost done';
    return 'taking a bit longer than usual, still working';
  }
  function tick(){
    $$('[data-from]').forEach(el=>{ const t = el.dataset.est===undefined ? mmss((Date.now() - +el.dataset.from)/1000) : leftText(el); if(el.textContent!==t) el.textContent = t; });
  }
  setInterval(tick, 1000);

  /* one progress card for every wait: step list, current step, what is happening, time so far, rough time left */
  function prog(o){
    const n = o.steps.length, frac = Math.min(1, (o.at + (o.frac||0)) / n);
    const clock = o.from ? `<div class="prog-t"><b data-from="${o.from}">0:00</b><span data-from="${o.from}" data-est="${o.est||0}" data-none="${esc(o.noEst||'')}"></span></div>` : '';
    return `<div class="prog" role="status"><div class="prog-h"><span class="spin${o.waiting?' wait':''}"></span><div><h2>${esc(o.title)}</h2><p>${esc(o.detail||'')}</p></div>${clock}</div>
      <div class="pbar"><i style="width:${Math.max(4, Math.round(frac*100))}%"></i></div>
      <ol class="psteps">${o.steps.map((s,i)=>`<li class="${i<o.at?'done':i===o.at?'now':''}"><span class="d"><span>${i+1}</span>${icon('i-check')}</span>${esc(s[0])}<small>${i<o.at?'Done':i===o.at?(o.waiting?'Waiting for you':'Happening now'):esc(s[1]||'')}</small></li>`).join('')}</ol>
      ${o.ccOff ? ccOff(o.ccOff) : ''}</div>`;
  }
  const ccOff = why => `<div class="ccoff"><b>Claude isn't listening right now</b>${esc(why)} In the Claude app, open Claude Code and send this message. It picks up from here by itself.<div class="cmd"><code>/creator-pack</code><button type="button" class="btn sm" data-copy="/creator-pack">Copy</button></div></div>`;

  /* ---------- screens ---------- */
  let screenNow = 'setup';
  function go(name){
    screenNow = name;
    $('#screen-setup').hidden = name!=='setup'; $('#screen-editor').hidden = name!=='editor';
    ['setup','editor'].forEach(n=>{ if(name===n) $('#tab-'+n).setAttribute('aria-current','page'); else $('#tab-'+n).removeAttribute('aria-current'); });
    document.body.classList.toggle('no-chat', name!=='editor');
    renderProjects();
    if(name==='editor') ensureProject();
    window.scrollTo(0,0);
    const h = name==='setup' ? $('#setup-h') : $(PANEL[S.step]+' h1'); if(h) h.focus({preventScroll:true});
  }
  document.addEventListener('click', e => { const b=e.target.closest('[data-go]'); if(b) go(b.dataset.go); });
  document.addEventListener('click', e=>{ const c=e.target.closest('[data-copy]'); if(!c) return; navigator.clipboard.writeText(c.dataset.copy).then(()=>toast('Copied.'), ()=>toast('Select it and copy.')); });

  /* ---------- setup ---------- */
  const sel = {};
  const TOOL = {brew:['Homebrew','A free installer for the Mac. It fetches the tools below.'], python:['Helper files','Small helpers that stay inside the pack.'], ffmpeg:['Video cutter','Cuts and joins your video (ffmpeg).'],
    whisper:['Speech listener','Hears your words, on your Mac (whisper).'], model:['Speech model','The part that understands your words. One 1.6 GB download, kept on your Mac.'], node:['Node.js','Not needed yet. A later version uses it for titles.']};
  const toolName = t => (TOOL[t.id]||[t.name])[0];
  function setupRow(t){
    if(sel[t.id]===undefined) sel[t.id] = !t.optional;
    const s = ST.setup, why = (TOOL[t.id]||[])[1] || t.why;
    const now = s.installing && s.current===t.id;
    let st;
    if(t.found) st = `<span class="st">Ready</span>`;
    else if(now) st = `<span class="st miss"><span class="spin sm"></span>Installing now</span>`;
    else if(s.installing && sel[t.id]) st = `<span class="st miss">Waiting its turn</span>`;
    else if(t.manual || t.error) st = `<span class="st miss">Needs you</span>`;
    else st = `<label class="st miss"><input type="checkbox" data-sel="${t.id}" ${sel[t.id]?'checked':''} ${s.installing?'disabled':''}>${t.optional?'Install (optional)':'Install'}</label>`;
    let fix = '';
    if(!t.found && t.manual) fix = `<div class="fix"><b>Homebrew asks for your Mac password, so only you can install it.</b> Open the Terminal app, paste this line, press Return, then come back and press Check again.<div class="cmd"><code style="overflow:auto;white-space:nowrap;flex:1">${esc(t.manual)}</code><button type="button" class="btn sm" data-copy="${esc(t.manual)}">Copy</button></div></div>`;
    else if(!t.found && t.error && !now) fix = `<div class="fix"><b>This one didn't install.</b> ${esc(t.error)}</div>`;
    return `<li class="tool${t.found?' ok':''}"><span class="mark">${icon('i-check')}</span><div><b>${esc(toolName(t))}</b><small>${esc(why)}</small></div>${st}${fix}</li>`;
  }
  function renderSetup(){
    if(!ST) return;
    const s = ST.setup, items = s.items.filter(t=>!(t.optional && t.id==='node')), need = items.filter(t=>!t.optional), n = need.filter(t=>t.found).length;   /* Node.js is not used yet: no row for it */
    setHTML($('#tools'), items.map(setupRow).join(''));
    const q = items.filter(t=>!t.found && sel[t.id] && !t.manual).length, pb = $('#setup-primary');
    $('#setup-h').textContent = s.ready ? 'Your Mac is ready' : 'Get your Mac ready';
    $('#setup-sub').textContent = s.ready ? 'Everything the pack needs is here. Your videos never leave your Mac.' : n===need.length && s.licence && !s.licence.ok ? 'Everything is installed. Add your licence key below to finish.' : `${n} of ${need.length} things are ready. Tick what you want, then press Install. It takes about 10 minutes.`;
    pb.disabled = !s.ready && (s.installing || !q);
    setHTML(pb, s.ready ? `Open the editor${icon('i-next')}` : s.installing ? 'Installing' : q ? `Install ${q} thing${q>1?'s':''}` : 'Nothing to install');
    pb.dataset.act = s.ready ? 'open' : 'install';
    setHTML($('#setup-msg'), s.ready ? '' : s.installing ? 'You can leave this open and do something else.' : `<button type="button" class="linkbtn" data-go="editor">Look around the editor first</button>`);
    const sp = $('#setup-prog'); sp.hidden = !s.installing;
    if(s.installing){
      const order = items.filter(t=>!t.found && sel[t.id] || t.id===s.current), cur = items.find(t=>t.id===s.current);
      setHTML(sp, prog({title:`Installing the ${cur ? toolName(cur).toLowerCase() : 'tools'}`, detail: s.current==='model' ? 'This is a big download, so it is the slow one.' : 'Your Mac is downloading it and setting it up.',
        steps: order.map(t=>[toolName(t), '']), at: Math.max(0, order.findIndex(t=>t.id===s.current)), frac:.5, from: since('install'), noEst:'a few minutes'})); tick();
    } else { localStorage.removeItem(`cpack-since-${pid}-install`); sp._h = null; }
    $('#setup-banner').hidden = s.ready;
    renderLicence(s.licence);
    renderWords();
  }
  /* licence (paid version only): the server leaves it out of the state when there is no licence check, so nothing shows */
  function renderLicence(l){
    const c = $('#licence-card'); c.hidden = !(l && l.required); if(c.hidden) return;
    $('#licence-st').textContent = l.ok ? (l.offline ? `Checked offline, ${l.days_left} day${l.days_left===1?'':'s'} left` : 'Active') : 'Needs you';
    $('#licence-why').textContent = l.ok ? (l.offline ? 'Connect to the internet within that time so the pack can check it again.' : 'Thanks for buying the pack.') : (l.reason || '');
    $('#licence-form').hidden = l.ok && !l.offline;
  }
  $('#licence-form').addEventListener('submit', async e=>{ e.preventDefault(); const k=$('#licence-in').value.trim(); if(!k) return;
    try { ST.setup.licence = await api('/api/licence', {key:k}); $('#licence-in').value=''; await refreshState(); toast(ST.setup.licence && ST.setup.licence.ok ? 'Licence checked.' : (ST.setup.licence||{}).reason || 'Checked.'); } catch(err){ toast(err.message); } });
  document.addEventListener('change', e=>{ const c=e.target.closest('[data-sel]'); if(!c) return; sel[c.dataset.sel]=c.checked; renderSetup(); });

  /* ---------- words I use (names, brands, places: read by the listener before it hears a video) and Chinese ---------- */
  const prefs = () => (ST && ST.prefs) || {words:[], chinese:''};
  function renderWords(){
    if(!ST) return; const w = prefs().words||[];
    setHTML($('#words-list'), w.map((x,i)=>`<li>${esc(x)}<button type="button" data-word-drop="${i}" aria-label="Take ${esc(x)} off the list">${icon('i-x')}</button></li>`).join(''));
    $('#words-sum').textContent = w.length ? w.slice(0,3).join(', ') + (w.length>3 ? ` and ${w.length-3} more` : '') : 'None yet';
    /* Cantonese is always Traditional characters; Mandarin asks once and remembers */
    const lang = $('#lang').value;
    $('#zh-ask').hidden = lang!=='zh'; $('#yue-note').hidden = lang!=='yue';
    if(prefs().chinese) setRadio('zh', prefs().chinese);
  }
  async function savePrefs(p){ try { ST.prefs = await api('/api/prefs', p); renderWords(); } catch(e){ toast(e.message); } }
  $('#words-form').addEventListener('submit', e=>{ e.preventDefault(); const i=$('#words-in'), t=i.value.trim(); if(!t) return; i.value=''; savePrefs({words:(prefs().words||[]).concat(t)}); });
  $('#words-list').addEventListener('click', e=>{ const b=e.target.closest('[data-word-drop]'); if(!b) return; const w=(prefs().words||[]).slice(); w.splice(+b.dataset.wordDrop,1); savePrefs({words:w}); });
  $('#words-edit').addEventListener('click', ()=>{ go('setup'); $('#words-card').scrollIntoView({block:'center'}); $('#words-in').focus({preventScroll:true}); });
  $('#setup-primary').addEventListener('click', async ()=>{
    if($('#setup-primary').dataset.act==='open'){ go('editor'); return; }
    const ids = ST.setup.items.filter(t=>!t.found && sel[t.id]).map(t=>t.id);
    try { await api('/api/setup/install', {ids}); await refreshState(); } catch(e){ toast(e.message); }
  });
  $('#recheck').addEventListener('click', ()=>refreshState().then(()=>toast(ST.setup.ready ? 'Checked. Everything is ready.' : 'Checked.')));

  /* ---------- Story Studio: shown, not built yet ---------- */
  const studio = $('#studio-card'), studioTab = $('#tab-studio');
  const showStudio = on => { studio.hidden = !on; studioTab.setAttribute('aria-expanded', on); if(on) $('#studio-want').focus(); };
  studioTab.addEventListener('click', e => { e.stopPropagation(); showStudio(studio.hidden); });
  $('#studio-close').addEventListener('click', () => { showStudio(false); studioTab.focus(); });
  document.addEventListener('keydown', e => { if(e.key==='Escape' && !studio.hidden){ showStudio(false); studioTab.focus(); } });
  document.addEventListener('click', e => { if(!studio.hidden && !e.target.closest('#studio-card, #tab-studio')) showStudio(false); });
  const wantStudio = async () => {
    try { await api('/api/interest', {what:'story_studio', project: (typeof pid!=='undefined' && pid) || ''}); toast('Thanks. The waitlist page is open in your browser.'); } catch(e){ toast(e.message); }
    showStudio(false);
  };
  $('#studio-want').addEventListener('click', wantStudio);
  document.querySelectorAll('.ss-want').forEach(b => b.addEventListener('click', wantStudio));

  /* ---------- versions: "Version 2 · 3 clips · today 14:02" ---------- */
  function when(at){
    if(!at) return ''; const d = new Date(at*1000), now = new Date(), hm = d.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
    const y = new Date(now); y.setDate(now.getDate()-1);
    return d.toDateString()===now.toDateString() ? `today ${hm}` : d.toDateString()===y.toDateString() ? `yesterday ${hm}` : `${d.toLocaleDateString([], {day:'numeric', month:'short'})} ${hm}`;
  }
  const verLabel = (n, clips, at) => [`Version ${n}`, clips!=null ? `${clips} clip${clips===1?'':'s'}` : '', when(at)].filter(Boolean).join(' · ');

  /* ---------- editor state ---------- */
  const S = {step:1};
  const STAGES = ['footage','hearing','story_wait','story','cutting','review','cut_failed'];
  const stageAt = () => STAGES.indexOf(PJ ? PJ.stage : 'footage');
  const heard = () => PJ && stageAt() >= 2;
  const hasStory = () => PJ && PJ.storyboard;
  const hasCut = () => PJ && PJ.versions && PJ.versions.length > 0;
  /* four steps. Tidy up and Make my video sit at the end of Look (a page of switches was not a step) */
  const STEPS=['Footage','Story','Look','Finish'], PANEL = {1:'#p1', 2:'#p2', 3:'#p3', 4:'#p5'};
  const making = () => PJ && PJ.stage==='cutting';
  const canStep = n => n===1 || (n===2 && PJ && stageAt()>=1) || (n===3 && hasStory()) || (n===4 && (hasCut() || making()));
  const stepDone = n => !!([heard(), hasStory() && PJ.storyboard.approved, hasCut(), PJ && (PJ.exports||[]).length>0][n-1]);
  function renderStepper(){
    setHTML($('#stepper'), STEPS.map((l,i)=>{ const n=i+1; return `<li class="${stepDone(n)?'done':''}"><button type="button" data-step="${n}" ${n===S.step?'aria-current="step"':''} ${canStep(n)?'':'disabled'} aria-label="Step ${n} of 4, ${l}"><span class="n"><span>${n}</span>${icon('i-check')}</span>${l}</button></li>`; }).join(''));
  }
  function step(n, quiet){
    if(!canStep(n)) return;
    if(S.step===2 && n>2 && hasStory() && !PJ.storyboard.approved) approveStory();
    S.step=n;
    for(let i=1;i<=4;i++) $(PANEL[i]).hidden = i!==n;
    renderAll();
    if(!quiet){ window.scrollTo(0,0); $(PANEL[n]+' h1').focus({preventScroll:true}); }
  }
  document.addEventListener('click', e=>{ const b=e.target.closest('[data-step]'); if(b && !b.disabled) step(+b.dataset.step); });
  const autoStep = () => hasCut() || PJ.stage==='cutting' ? 4 : PJ.stage==='cut_failed' ? 3 : stageAt()>=1 ? 2 : 1;

  let ensuring = null;
  function ensureProject(){ return ensuring || (ensuring = _ensure().finally(()=>{ ensuring = null; })); }
  async function _ensure(){
    if(PJ && PJ.id===pid) return;
    if(pid){ try { PJ = await api('/api/project/'+pid); return; } catch(e){ pid=''; } }
    PJ = await api('/api/project/new', {}); pid = PJ.id; localStorage.setItem('cpack-project', pid);
    PJ = await api('/api/project/'+pid); fillForm(); renderAll();
  }
  async function openProject(id){
    let p; try { p = await api('/api/project/'+id); } catch(e){ toast(e.message); return; }
    PJ = p; pid = id; localStorage.setItem('cpack-project', pid); board = null; pendingAsk = null; sending = []; viewV = null; dirty = false; wasCutting = false; playingId = null;
    fillForm(); step(autoStep(), true); refreshState();
  }
  async function newVideo(){
    if(PJ && !PJ.takes.length){ step(1); toast('This one is empty. Add your clips here.'); return; }
    const p = await api('/api/project/new', {}); await openProject(p.id); toast('Ready for a new video. Add your clips.');
  }
  /* "Your videos": short names with the date, New video on top, rename in place. Never the Mac's grey list. */
  const vmenu = $('#vmenu'), vlist = $('#vlist'), vbtn = $('#vbtn'); let renaming = '';
  function showVideos(on){ vlist.hidden = !on; vbtn.setAttribute('aria-expanded', on); if(!on) renaming = ''; renderProjects(); if(on){ const c = vlist.querySelector('.cur .vopen'); (c || vlist.querySelector('button')).focus(); } }
  vbtn.addEventListener('click', e=>{ e.stopPropagation(); showVideos(vlist.hidden); });
  document.addEventListener('click', e=>{ if(!vlist.hidden && !e.composedPath().includes(vmenu)) showVideos(false); });
  document.addEventListener('keydown', e=>{ if(e.key==='Escape' && !vlist.hidden){ showVideos(false); vbtn.focus(); } });
  vlist.addEventListener('keydown', e=>{
    if(e.key!=='ArrowDown' && e.key!=='ArrowUp' || e.target.tagName==='INPUT') return;
    const f = Array.from(vlist.querySelectorAll('.vnew, .vopen')), i = f.indexOf(document.activeElement.closest('.vnew, .vopen') || document.activeElement);
    e.preventDefault(); f[(i + (e.key==='ArrowDown'?1:-1) + f.length) % f.length].focus();
  });
  vlist.addEventListener('click', async e=>{
    const o = e.target.closest('[data-open]'), r = e.target.closest('[data-rename]');
    if(e.target.closest('.vnew')){ showVideos(false); newVideo(); return; }
    if(r){ renaming = r.dataset.rename; renderProjects(); const i = vlist.querySelector('form input'); i.focus(); i.select(); return; }
    if(o){ showVideos(false); if(o.dataset.open!==pid) openProject(o.dataset.open); }
  });
  vlist.addEventListener('submit', async e=>{
    e.preventDefault(); const id = renaming, t = e.target.querySelector('input').value.trim();
    try { const r = await api(`/api/project/${id}/rename`, {title:t}); ST.projects = r.projects; if(id===pid && PJ) PJ.title = (r.projects.find(p=>p.id===id)||{}).title; } catch(err){ toast(err.message); }
    renaming = ''; renderProjects(); const b = vlist.querySelector(`[data-open="${id}"]`); if(b) b.focus();
  });
  function renderProjects(){
    const all = (ST && ST.projects) || [];
    const list = all.filter(p=>p.id===pid || !p.empty).slice(0,30);
    vmenu.hidden = !(screenNow==='editor' && !!PJ);
    const day = t => t ? new Date(t*1000).toLocaleDateString([], {day:'numeric', month:'short'}) : '';
    const nm = p => p.id===pid && PJ ? PJ.title || p.title : p.title || p.name;
    const cur = list.find(p=>p.id===pid);
    $('#vbtn-t').textContent = cur ? nm(cur) : PJ ? PJ.title || 'New video' : '';
    if(vlist.hidden) return;
    setHTML(vlist, `<button type="button" class="vnew">${icon('i-plus')}New video</button>` + (list.length ? '<p class="lab">Your videos</p>' : '') + list.map(p=>{
      const full = p.id===pid && PJ && PJ.storyboard ? PJ.storyboard.one_line : p.story;
      if(renaming===p.id) return `<div class="vrow${p.id===pid?' cur':''}"><form><label class="sr" for="vname">Name of this video</label><input type="text" id="vname" maxlength="60" value="${esc(nm(p))}" autocomplete="off"><button type="submit" class="btn navy sm">Save</button></form></div>`;
      return `<div class="vrow${p.id===pid?' cur':''}"><button type="button" class="vopen" data-open="${p.id}" title="${esc(full||nm(p))}" ${p.id===pid?'aria-current="true"':''}><b>${esc(nm(p))}</b><span>${esc(day(p.created))}</span></button><button type="button" class="ib" data-rename="${p.id}" title="Rename" aria-label="Rename ${esc(nm(p))}">${icon('i-pen')}</button></div>`;
    }).join(''));
  }

  /* ---------- footage ---------- */
  const tturn = t => (t && t.turn) || 0;
  const shownWH = t => tturn(t)%180 ? [t.probe.shown_h, t.probe.shown_w] : [t.probe.shown_w, t.probe.shown_h];
  const shapeOf = t => { const [w,h] = shownWH(t); return w>h ? 'wide' : w<h ? 'tall' : 'square'; };
  const lay = t => ({wide:'filmed sideways (wide)', tall:'filmed upright', square:'square'})[shapeOf(t)];
  const frameSrc = t => `/media/${pid}/frame/${encodeURIComponent(t.name)}?t=${tturn(t)}-${t.added||0}-${t.turned_at||0}`;
  const turnWord = d => d===180 ? 'upside down' : d===90 ? 'to the right' : d===270 ? 'to the left' : '';
  function renderFiles(){
    const takes = (PJ && PJ.takes) || [];
    setHTML($('#takes'), takes.map(t=>`<li class="file"><span class="thumb"><img src="${frameSrc(t)}" alt="A picture from ${esc(t.name)}"></span><div><p class="fn" title="${esc(t.name)}">${esc(t.name)}</p><p class="fd">${mmss(t.probe.duration)} long, ${lay(t)}${tturn(t)?`, turned ${turnWord(tturn(t))}`:''}</p></div>
      <span class="turns"><button type="button" class="btn sm" data-turn="-90" data-name="${esc(t.name)}" aria-label="Turn ${esc(t.name)} left">Turn left</button><button type="button" class="btn sm" data-turn="90" data-name="${esc(t.name)}" aria-label="Turn ${esc(t.name)} right">Turn right</button></span>
      <button type="button" class="ib" data-rm="${esc(t.name)}" aria-label="Take out ${esc(t.name)}" title="Take this clip out">${icon('i-x')}</button></li>`).join(''));
    $('#turn-hint').hidden = !takes.length;
    $('#folder-row').hidden = !PJ.folder_name;
    $('#folder-name').textContent = PJ.folder_where || '';
    const shapes = new Set(takes.map(shapeOf).filter(x=>x!=='square'));
    $('#mix-tip').hidden = shapes.size < 2;
    $('#drop').querySelector('b').textContent = takes.length ? 'Drop more clips here' : 'Drop your clips here';
  }
  async function openFolder(sub){ try { await api(`/api/project/${pid}/open_folder`, {sub}); } catch(e){ toast(e.message); } }
  async function scanFolder(loud){
    if(!PJ || !pid) return;
    try { const r = await api(`/api/project/${pid}/scan`, {});
      if(r.added.length || r.errors.length || loud) afterAdd(r.added.length || r.errors.length ? r : {added:[], errors:[]});
      if(loud && !r.added.length && !r.errors.length) toast(r.references.length ? `No new clips in Footage. ${r.references.length} file${r.references.length>1?'s':''} in References.` : 'No new clips in the Footage folder yet.');
    } catch(e){ if(loud) toast(e.message); }
  }
  $('#open-foot').addEventListener('click', ()=>openFolder('Footage'));
  $('#scan-now').addEventListener('click', ()=>scanFolder(true));
  window.addEventListener('focus', ()=>scanFolder(false));
  document.addEventListener('visibilitychange', ()=>{ if(!document.hidden) scanFolder(false); });
  async function addPicked(){
    try { const r = await api(`/api/project/${pid}/pick`, {}); afterAdd(r); } catch(e){ toast(e.message); }
  }
  async function addDropped(files){
    for(const f of files){
      toast(`Adding ${f.name}. Big files take a moment.`);
      try { const r = await api(`/api/project/${pid}/upload?name=${encodeURIComponent(f.name)}`, f, true); afterAdd(r); } catch(e){ toast(e.message); }
    }
  }
  function afterAdd(r){
    if(r.errors && r.errors.length) toast(r.errors.join('. '));
    else if(r.added && r.added.length) toast(`${r.added.length} clip${r.added.length>1?'s':''} added.`);
    refreshProject().then(refreshState);
  }
  $('#path-add').addEventListener('click', async ()=>{
    const v = $('#path-in').value.trim().replace(/^['"]|['"]$/g,''); if(!v) return;
    try { const r = await api(`/api/project/${pid}/add`, {paths:[v]}); $('#path-in').value=''; afterAdd(r); } catch(e){ toast(e.message); }
  });
  $('#path-in').addEventListener('keydown', e=>{ if(e.key==='Enter') $('#path-add').click(); });
  const drop = $('#drop');
  drop.addEventListener('click', addPicked);
  drop.addEventListener('dragover', e=>{ e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', ()=>drop.classList.remove('over'));
  drop.addEventListener('drop', e=>{ e.preventDefault(); e.stopPropagation(); drop.classList.remove('over'); addDropped(Array.from(e.dataTransfer.files||[])); });
  document.addEventListener('dragover', e=>e.preventDefault());
  document.addEventListener('drop', e=>e.preventDefault());
  $('#takes').addEventListener('click', async e=>{ const b=e.target.closest('[data-rm]'); if(!b) return; const r = await api(`/api/project/${pid}/remove_take`, {name:b.dataset.rm}); if(r.dropped) toast(`${r.dropped} part${r.dropped>1?'s':''} from that clip left your story. The rest is kept.`); board = null; refreshProject(); });
  $('#takes').addEventListener('click', async e=>{
    const b=e.target.closest('[data-turn]'); if(!b) return;
    b.disabled = true;
    try { const r = await api(`/api/project/${pid}/turn`, {name:b.dataset.name, by:+b.dataset.turn}); const t = PJ.takes.find(x=>x.name===r.name); if(t){ t.turn = r.turn; t.turned_at = Date.now(); } renderFiles(); updateFitQuestion(); markDirty(); } catch(err){ toast(err.message); }
    b.disabled = false; refreshProject();
  });

  /* ---------- settings form <-> project ---------- */
  const LENS = {ig:[['short','Up to 1 minute'],['mid','Up to 3 minutes']], yt:[['short','Under 3 minutes'],['mid','3 to 8 minutes'],['long','As long as it needs']], other:[['auto','As long as it needs']]};
  const FMT = {ig:'9:16', yt:'16:9', other:'source'};
  const PURPOSE = {ig:'Instagram', yt:'YouTube', other:'somewhere else'};
  const SHAPE_WORD = {'9:16':'upright', '4:5':'tall', '1:1':'square', '16:9':'wide', source:'the same shape you filmed'};
  const CAP_NAME = {word:'Captions, one word at a time', three:'Captions, a few words at a time', lines:'Captions in full lines', none:'No captions'};
  const LOOK_NAME = {soft:'Soft', clean:'Clean', glow:'Glow'};
  const POS_NAME = {top:'at the top', middle:'in the middle', bottom:'at the bottom', left:'on the left', right:'on the right', moves:'moving around'};
  function renderLens(){
    const p = val('purpose')||'ig', cur = PJ ? PJ.settings.length : 'auto';
    const opts = LENS[p];
    $('#len-seg').innerHTML = opts.map((l,i)=>`<label class="choice"><input type="radio" name="len" value="${l[0]}" ${(l[0]===cur || (!opts.some(o=>o[0]===cur) && i===opts.length-1))?'checked':''}><span>${l[1]}</span></label>`).join('');
    $('#reach-tip').hidden = p!=='ig';
  }
  function fillForm(){
    if(!PJ) return; const s = PJ.settings;
    setRadio('purpose', s.purpose); setRadio('format', s.format); setRadio('fit', s.fit);
    setRadio('filmed', s.mode==='script'?'script':'talk'); $('#keep-order').checked = s.mode==='keep';
    $('#script-text').value = s.script||''; $('#lang').value = s.language||'auto'; renderWords();
    $('#small-file').checked = !!(s.export && s.export.max_mb);
    setRadio('cap', s.captions.style); setRadio('c-csize', s.captions.size); setRadio('c-cpos', s.captions.position);
    setRadio('c-look', s.captions.look || 'soft'); $('#c-motion').checked = s.captions.motion !== false;
    $('#c-hi').value = s.captions.pop; $('#c-popon').checked = !!s.captions.pop_on; $('#c-hi-f').hidden = !s.captions.pop_on; $('#c-wpl').value = s.captions.per_line;
    setRadio('breath', s.cut.breath);
    $('#q-filler').checked = s.cut.fillers; $('#q-pause').checked = s.cut.pauses; $('#q-best').checked = s.cut.repeats;
    renderLens(); syncMode(); updateFitQuestion();
  }
  function formSettings(){
    const filmed = val('filmed');
    return {purpose: val('purpose'), format: val('format'), fit: val('fit'), language: $('#lang').value,
      mode: filmed==='script' ? 'script' : ($('#keep-order').checked ? 'keep' : 'find'), script: $('#script-text').value,
      length: val('len') || 'auto', export: {max_mb: $('#small-file').checked ? 24 : 0},
      captions: {style: val('cap'), look: val('c-look') || 'soft', size: val('c-csize'), position: val('c-cpos'), motion: $('#c-motion').checked, pop: $('#c-hi').value, pop_on: $('#c-popon').checked, per_line: +$('#c-wpl').value},
      cut: {breath: val('breath') || 'normal', fillers: $('#q-filler').checked, pauses: $('#q-pause').checked, repeats: $('#q-best').checked, best_take: $('#q-best').checked}};
  }
  let saveT;
  async function saveSettings(extra){
    if(!PJ) return;
    const s = Object.assign(formSettings(), extra||{});
    try { PJ.settings = await api(`/api/project/${pid}/settings`, s); } catch(e){ toast(e.message); }
    renderAll();
  }
  function syncMode(){
    const sc = val('filmed')==='script';
    $('#script-box').hidden = !sc; $('#talk-box').hidden = sc;
  }
  $('.main').addEventListener('change', e=>{
    const i=e.target; if(i.name==='shape') return;
    if(i.name==='zh'){ savePrefs({chinese:i.value}); return; }
    if(i.id==='lang') renderWords();
    if(i.name==='purpose'){ setRadio('format', FMT[i.value]); renderLens(); updateFitQuestion(); }
    if(i.name==='filmed') syncMode();
    if(i.id==='c-popon') $('#c-hi-f').hidden = !i.checked;
    clearTimeout(saveT); saveT = setTimeout(()=>saveSettings(), 150);
    markDirty();
  });
  $('.main').addEventListener('input', e=>{ if(['script-text','c-wpl','c-hi'].includes(e.target.id)){ clearTimeout(saveT); saveT=setTimeout(()=>saveSettings(), 500); } });

  /* ---------- plan-use heads-up (no money figures; plan limits aren't published as numbers) ---------- */
  const HU_WHAT = {story:'Your Mac listens for free, then Claude Code finds your story.', change:'Claude Code makes the change, then your Mac cuts a new version.'};
  function level(k){
    if(k==='story'){ const mins = ((PJ&&PJ.takes)||[]).reduce((a,t)=>a+(t.probe?t.probe.duration:0),0)/60; return mins<5?1:mins<15?2:3; }
    return 2;
  }
  const hu = k => { const lv=level(k); return `<span class="hu" title="A rough guide. Anthropic doesn't publish exact plan limits."><span class="gauge" aria-hidden="true">${[1,2,3].map(n=>`<i class="${n<=lv?'on':''}"></i>`).join('')}</span><b>${['Light','Medium','Heavy'][lv-1]} use of your Claude plan.</b><span>${HU_WHAT[k]}</span></span>`; };

  /* ---------- step 1 footer ---------- */
  /* the server starts the work a moment after it answers, so wait until the project says it has begun */
  async function started(ok){ for(let n=0; n<25; n++){ await refreshProject(); if(ok()) return; await new Promise(r=>setTimeout(r,200)); } }
  async function hear(){
    if($('#lang').value==='zh' && !prefs().chinese){   /* Mandarin: Traditional or Simplified, asked once */
      $('#more').open = true; $('#zh-ask').scrollIntoView({block:'center'}); toast('Pick Traditional or Simplified characters for your captions first.'); return;
    }
    await saveSettings(); clearSince('hearing'); try { await api(`/api/project/${pid}/go`, {}); await started(()=>stageAt()>=1); step(2); } catch(e){ toast(e.message); } }
  $('#go1').addEventListener('click', ()=>{ if(heard()) step(2); else hear(); });
  $('#rehear').addEventListener('click', hear);
  function renderClipAsk(){
    const box = $('#clip-ask'), nc = PJ.new_clips||[], back = PJ.offer_back, sv = (PJ.story_versions||[]).find(v=>v.n===back);
    let html = '';
    if(nc.length && hasStory()) html = `<p><b>You added ${esc(nc.join(', '))}.</b> Your story is still there. Should the new clip go into it?</p>
      <div class="row"><button type="button" class="btn sm primary" id="fit-new">Fit the new clip into your story</button><button type="button" class="btn sm" id="fresh">Start fresh</button></div>`;
    else if(back && sv) html = `<p><b>We took that clip's parts out of your story.</b> The rest is kept. Or go back to the story you had before it: ${esc(verLabel(sv.n, sv.clips, sv.at))}.</p>
      <div class="row"><button type="button" class="btn sm primary" id="go-back">Go back to your previous story</button><button type="button" class="btn sm" id="keep-now">Keep it like this</button></div>`;
    box.hidden = !html; setHTML(box, html);
  }
  $('#clip-ask').addEventListener('click', async e=>{
    const id = e.target.id;
    try {
      if(id==='fit-new'){ await api(`/api/project/${pid}/fit_new`, {}); toast('Claude Code will fit the new clip into your story. Your story stays open meanwhile.'); }
      else if(id==='fresh'){ await api(`/api/project/${pid}/fresh`, {}); toast('Listening again. Your old story is kept as a version.'); }
      else if(id==='go-back'){ await api(`/api/project/${pid}/story_version`, {n: PJ.offer_back}); board = null; toast('Your previous story is back.'); }
      else if(id==='keep-now'){ await api(`/api/project/${pid}/dismiss_back`, {}); }
      else return;
    } catch(err){ toast(err.message); }
    refreshProject();
  });
  function renderP1(){
    renderClipAsk();
    const has = PJ.takes.length > 0, st = PJ.stage, failed = st==='hearing' && (PJ.errors||[]).length>0, busy = st==='hearing' && !failed;
    const b = $('#go1');
    b.disabled = !has || busy;
    setHTML(b, heard() ? `Next${icon('i-next')}` : busy ? 'Listening' : 'Go');
    $('#rehear').hidden = !heard();
    setHTML($('#p1-msg'), !has ? 'Add at least one clip to start.' : heard() ? (hasStory() ? 'Your clips have been listened to. Your story is kept when you add or take out a clip.' : 'Your clips have been listened to. Added or changed a clip? Press Listen again.') : busy ? 'Listening to your clips.' : `<b>Happy with these choices? Press Go.</b>${hu('story')}`);
  }

  /* ---------- step 2: story ---------- */
  const SHAPES = {turn:'Story with a turn', tips:'Tips list', qa:'Question and answer', beforeafter:'Before and after', rant:'Rant with a point', setback:'Setback', belief:'Belief then break', opinion:'Against the common view'};
  let board = null, dirtyBoard = false; const openLines = new Set();
  function syncBoard(){
    if(!hasStory()){ board=null; return; }
    if(!board || !dirtyBoard || board._saved !== PJ.storyboard.saved_at){ board = JSON.parse(JSON.stringify(PJ.storyboard)); board._saved = PJ.storyboard.saved_at; dirtyBoard=false; }
  }
  const storyJob = () => (PJ.jobs||[]).find(j=>j.id===PJ.story_job) || (PJ.jobs||[]).filter(j=>j.type==='story').pop();
  function renderStory(){
    const st = PJ.stage, errs = PJ.errors||[], failed = st==='hearing' && errs.length>0;
    const steps = [['Listening to your clips','On your Mac, free'],['Finding your story','Claude Code'],['Ready for you to check','']];
    let html = '';
    if(st==='hearing' && !failed){
      const secs = PJ.takes.reduce((a,t)=>a+t.probe.duration,0), m = PJ.progress && /(\d+) of (\d+)/.exec(PJ.progress.label||'');
      html = prog({title:'Listening to your clips', detail: m ? `Your Mac is writing down every word you said. Clip ${m[1]} of ${m[2]}.` : 'Your Mac is writing down every word you said.', steps, at:0, frac: m ? (m[1]-0.5)/m[2] : .3, from: since('hearing'), est: Math.round(12 + secs*0.05)});
    } else if(st==='story_wait'){
      const j = storyJob(), taken = !!(j && j.status==='taken');
      if(!connected() && !taken) html = prog({title:'Waiting for Claude Code', detail:'Your words are written down. Claude Code finds the story in them, and it is not open yet.', steps, at:1, waiting:true, ccOff:'Your story is waiting for it.'});
      else html = prog({title:'Finding your story', detail: taken ? 'Claude Code is reading what you said and picking the strongest parts.' : 'Claude Code is picking it up.', steps, at:1, frac: taken?.4:.1, from: since('story', taken && j.taken), est: taken?150:0, noEst:'starting now'});
    }
    if(st!=='hearing') clearSince('hearing');
    if(st!=='story_wait') clearSince('story');
    setHTML($('#p2-prog'), html); tick();
    $('#p2-err').hidden = !failed;
    if(failed) setHTML($('#p2-err'), `<b>Listening didn't work.</b>${esc(errs.join(' '))}<div style="margin-top:12px"><button type="button" class="btn sm" id="retry-hear">Try again</button></div>`);
    $('#p2-sub').textContent = hasStory() ? 'This is the story we found in what you said. Move parts around or leave some out, then carry on.' : 'Your story shows up here by itself. Nothing to press.';
    const svs = PJ.story_versions||[], cur = hasStory() && PJ.storyboard.version;
    $('#sv-box').hidden = svs.length < 2;
    if(setHTML($('#sv-pick'), svs.slice().reverse().map(v=>`<option value="${v.n}">${esc(verLabel(v.n, v.clips, v.at))}${v.n===cur?', open now':''}</option>`).join('')) || $('#sv-pick').value!=String(cur)) $('#sv-pick').value = cur;
    const fj = (PJ.jobs||[]).find(j=>j.id===PJ.fit_job && j.status!=='done' && j.status!=='failed');
    $('#fit-note').hidden = !fj;
    if(fj) setHTML($('#fit-note'), `<p><b>Fitting your new clip into the story.</b> ${fj.status==='taken' ? 'Claude Code is on it.' : connected() ? 'Claude Code is picking it up.' : 'It waits for Claude Code.'} You can keep working on this story meanwhile.</p>`);
    syncBoard();
    $('#sb').hidden = !board;
    $('#to-look').disabled = !board;
    if(!board){ setHTML($('#p2-msg'), 'The next button wakes up when your story is ready.'); return; }
    $('#story-line').textContent = board.one_line;
    $('#shape-chip').textContent = board.mode==='script' ? 'Follows your script' : (SHAPES[board.shape]||board.shape);
    const alts = board.mode==='script' ? [] : (board.shape_alts||[]);
    $('#shape-try').hidden = !alts.length;
    setHTML($('#shape-alts'), [board.shape].concat(alts).map(k=>`<label class="choice"><input type="radio" name="shape" value="${k}" ${k===board.shape?'checked':''}><span>${SHAPES[k]||k}</span></label>`).join(''));
    const adv = (board.advice||[]).slice();
    if(board.mode==='keep') adv.unshift('You asked to keep your order, so nothing was moved.');
    setHTML($('#advice'), adv.map(a=>`<li title="Click to read it all">${icon('i-bulb')}<span>${esc(a)}</span></li>`).join(''));
    renderBeats();
  }
  function beatUse(b){ return b.use_alt!=null && b.alts && b.alts[b.use_alt] ? b.alts[b.use_alt] : b; }
  const player = $('#beat-player'), playBox = $('#beat-play'); let stopAt = null, playingId = null;
  const ready = take => { const t = PJ.takes.find(x=>x.name===take); return !!(t && t.has_proxy); };
  function renderBeats(){
    const kept = board.beats.filter(b=>b.keep!==false), many = PJ.takes.length > 1;
    const html = board.beats.map((b,i)=>{
      const u = beatUse(b), on = b.keep!==false, n = (b.alts||[]).length+1, line = u.heard||u.line||'', long = line.length > 130, open = openLines.has(b.id);
      return `<li class="beat${on?'':' off'}" draggable="true" data-id="${esc(b.id)}">
        <span class="grip" title="Drag to move" aria-hidden="true">&#8942;&#8942;</span><span class="num" title="Drag to move">${i+1}</span>
        <div class="beat-b"><div class="beat-h"><b>${esc(b.label||'Part '+(i+1))}</b><span>${on ? `${mmss(u.start)} to ${mmss(u.end)}${many?` in ${esc(u.take)}`:''}${n>1?`, take ${(b.use_alt==null?0:b.use_alt+1)+1} of ${n} (you said this ${n===2?'twice':n+' times'})`:''}` : 'Left out'}</span></div>
          <p class="beat-line${long&&!open?' clamp':''}">${esc(line)}</p>${long?`<button type="button" class="linkbtn" data-more="${esc(b.id)}">${open?'less':'more'}</button>`:''}</div>
        <span class="beat-acts">
          ${ready(u.take) ? `<button type="button" class="ib" data-play="${esc(b.id)}" title="Play this part" aria-label="Play ${esc(b.label)}">${icon('i-play')}</button>` : `<span class="ib" title="Your Mac is still making the preview of this clip. Play wakes up in a moment."><span class="spin sm"></span></span>`}
          ${n>1?`<button type="button" class="tb" data-swap="${esc(b.id)}" title="You said this more than once. Use your other take.">Use my other take</button>`:''}
          <button type="button" class="ib" data-mv="-1" data-id="${esc(b.id)}" title="Move up" aria-label="Move ${esc(b.label)} up" ${i===0?'disabled':''}>${icon('i-up')}</button>
          <button type="button" class="ib" data-mv="1" data-id="${esc(b.id)}" title="Move down" aria-label="Move ${esc(b.label)} down" ${i===board.beats.length-1?'disabled':''}>${icon('i-down')}</button>
          <button type="button" class="tb" data-keep="${esc(b.id)}" aria-pressed="${!on}">${on?'Leave out':'Put back'}</button>
        </span></li>`;
    }).join('');
    if($('#board')._h !== html){ $('#player-home').appendChild(playBox); setHTML($('#board'), html); if(playingId) mountPlayer(playingId); }
    const secs = kept.reduce((a,b)=>{const u=beatUse(b);return a+(u.end-u.start);},0);
    $('#sb-count').textContent = board.beats.every(b=>ready(beatUse(b).take)) ? `${kept.length} of ${board.beats.length} parts kept, about ${mmss(secs)} before tidying` : 'Play buttons wake up in a moment. Your Mac is making a quick preview.';
    setHTML($('#p2-msg'), `<b>${kept.length} part${kept.length===1?'':'s'}, about ${mmss(secs)}.</b>Want it told another way? Ask in the chat.`);
    const out = (board.left_out||[]).map(x=>`${x.start!=null?mmss(x.start)+' ':''}${x.line?`"${x.line.slice(0,80)}${x.line.length>80?'...':''}" `:''}${x.why}`)
      .concat(board.beats.filter(b=>b.keep===false).map(b=>`${b.label}, you left it out`));
    setHTML($('#leftout'), out.map(x=>`<li>${esc(x)}</li>`).join(''));
    $('#leftout-d').hidden = !out.length;
    setHTML($('#sum-left'), `What we left out <span>${out.length} bit${out.length===1?'':'s'}, and why</span>`);
  }
  $('#sv-pick').addEventListener('change', async e=>{ try { await api(`/api/project/${pid}/story_version`, {n:+e.target.value}); board = null; toast(`Story version ${e.target.value} is open.`); } catch(err){ toast(err.message); } refreshProject(); });
  const BB = id => board.beats.find(b=>b.id===id);
  async function pushBoard(extra){
    dirtyBoard = true;
    const body = Object.assign({order: board.beats.map(b=>b.id), keep: Object.fromEntries(board.beats.map(b=>[b.id, b.keep!==false])),
      use_alt: Object.fromEntries(board.beats.map(b=>[b.id, b.use_alt==null?null:b.use_alt])), shape: board.shape}, extra||{});
    try { const sb = await api(`/api/project/${pid}/story`, body); PJ.storyboard = sb; board._saved = sb.saved_at; dirtyBoard=false; } catch(e){ toast(e.message); }
    markDirty(); renderStepper();
  }
  async function approveStory(){ if(board) await pushBoard({approved:true}); }
  $('#board').addEventListener('click', e=>{
    const sw=e.target.closest('[data-swap]'), kp=e.target.closest('[data-keep]'), mv=e.target.closest('[data-mv]'), pl=e.target.closest('[data-play]'), mo=e.target.closest('[data-more]');
    if(mo){ const id=mo.dataset.more; if(openLines.has(id)) openLines.delete(id); else openLines.add(id); renderBeats(); return; }
    if(pl){ playBeat(pl.dataset.play); return; }
    if(sw){ const b=BB(sw.dataset.swap), n=(b.alts||[]).length; b.use_alt = b.use_alt==null ? 0 : (b.use_alt+1<n ? b.use_alt+1 : null); renderBeats(); pushBoard(); toast(`${b.label} now uses your other take. Press play to hear it.`); }
    if(kp){ const b=BB(kp.dataset.keep); b.keep = b.keep===false; renderBeats(); pushBoard(); }
    if(mv){ const id=mv.dataset.id, i=board.beats.findIndex(b=>b.id===id), j=i+(+mv.dataset.mv); if(j<0||j>=board.beats.length) return; [board.beats[i],board.beats[j]]=[board.beats[j],board.beats[i]]; renderBeats(); pushBoard(); }
  });
  let dragId=null;
  $('#board').addEventListener('dragstart', e=>{ const li=e.target.closest('.beat'); if(!li) return; dragId=li.dataset.id; li.classList.add('dragging'); });
  $('#board').addEventListener('dragend', ()=>{ dragId=null; $$('.beat').forEach(l=>l.classList.remove('dragging','over')); });
  $('#board').addEventListener('dragover', e=>{ const li=e.target.closest('.beat'); if(!li||!dragId) return; e.preventDefault(); $$('.beat').forEach(l=>l.classList.toggle('over', l===li && l.dataset.id!==dragId)); });
  $('#board').addEventListener('drop', e=>{ const li=e.target.closest('.beat'); if(!li||!dragId) return; e.preventDefault(); const from=board.beats.findIndex(b=>b.id===dragId), to=board.beats.findIndex(b=>b.id===li.dataset.id); if(from<0||to<0||from===to) return; const [m]=board.beats.splice(from,1); board.beats.splice(to,0,m); renderBeats(); pushBoard(); });
  $('#shape-try').addEventListener('click', ()=>{ const a=$('#shape-alts'); a.hidden=!a.hidden; $('#shape-try').setAttribute('aria-expanded', !a.hidden); });
  $('#shape-alts').addEventListener('change', e=>{ if(e.target.name!=='shape') return; board.shape=e.target.value; pushBoard(); renderStory(); toast(`Marked as a ${SHAPES[board.shape].toLowerCase()}. To rearrange the parts for it, ask in the chat.`); });
  function mountPlayer(id){ const li = $$('#board .beat').find(l=>l.dataset.id===id); if(li) li.appendChild(playBox); }
  function playBeat(id){
    const b = BB(id), u = beatUse(b), t = PJ.takes.find(x=>x.name===u.take);
    if(!t || !t.has_proxy){ toast('The preview of this clip is still being made. Try again in a minute.'); return; }
    playingId = id; mountPlayer(id);
    const src = `/media/${pid}/proxy/${encodeURIComponent(u.take)}`;
    if(!player.src.endsWith(src)) player.src = src;
    stopAt = u.end + 0.2;
    const start = () => { player.currentTime = Math.max(0, u.start - 0.1); player.play().catch(()=>{}); };
    if(player.readyState >= 1) start(); else player.addEventListener('loadedmetadata', start, {once:true});
  }
  player.addEventListener('timeupdate', ()=>{ if(stopAt && player.currentTime >= stopAt){ player.pause(); stopAt=null; } });
  $('#advice').addEventListener('click', e=>{ const li=e.target.closest('li'); if(li) li.classList.toggle('open'); });
  $('#to-look').addEventListener('click', async ()=>{ await approveStory(); step(3); });
  $('#p2-err').addEventListener('click', e=>{ if(e.target.closest('#retry-hear')) hear(); });

  /* ---------- step 3: look (captions now, the rest comes next) ---------- */
  function renderPreview(){
    const f = PJ.takes[0], c = PJ.settings.captions, pv = $('#pv');
    const fmt = PJ.settings.format;
    const ar = {'9:16':'9/16','16:9':'16/9','4:5':'4/5','1:1':'1/1'}[fmt] || (f ? shownWH(f).join('/') : '9/16');
    const [a,b] = ar.split('/').map(Number);
    pv.style.aspectRatio = ar; pv.style.width = a>=b ? '100%' : Math.round(460*a/b)+'px';
    if(f){ pv.style.backgroundImage = `url("${frameSrc(f)}")`; pv.style.backgroundSize = PJ.settings.fit==='pad' && fitAsked() ? 'contain' : 'cover'; }
    const cap = $('#pv-cap'), none = c.style==='none';
    cap.hidden = none; $('#cap-more').style.opacity = none ? .4 : 1; $('#cap-more').style.pointerEvents = none ? 'none' : '';
    $('#look-card').style.opacity = none ? .4 : 1; $('#look-card').style.pointerEvents = none ? 'none' : '';
    $('#wpl-field').hidden = c.style!=='lines';
    if(f) document.querySelectorAll('.look-pic').forEach(p=>p.style.backgroundImage = `linear-gradient(rgba(0,0,0,.38),rgba(0,0,0,.38)),url("${frameSrc(f)}")`);
    paintCap(true);
    if(!pvTimer) pvTimer = setInterval(()=>paintCap(false), 420);
  }
  /* the preview plays a few captions the way the video will: a new caption pops in, the word being said switches,
     "moves around" changes spot on a new sentence (same spots as cpack/captions.py) */
  const PV_LINES = [['I','quit','my','job.'], ['Then','I','drove','out'], ['of','Hong','Kong.'], ['Two','years','on,'], ['still','figuring','it','out.']];
  const PV_SPOTS = [['center',.74],['left',.62],['right',.30],['left',.24],['right',.56],['center',.20]];
  const PV_POS = {top:['center',.16], middle:['center',.5], bottom:['center',.74], left:['left',.70], right:['right',.70]};
  let pvTimer = 0, pvStep = 0, pvKey = '';
  function paintCap(settingsChanged){
    if(!PJ || $('#p3').hidden) return;
    const c = PJ.settings.captions, cap = $('#pv-cap'), pv = $('#pv');
    if(c.style==='none') return;
    const look = c.look || 'soft', key = [look, c.style, c.size, c.position, c.motion, c.pop, pv.clientWidth].join();
    if(settingsChanged && key===pvKey) return;
    if(settingsChanged){ pvKey = key; pvStep = 0; } else pvStep++;
    /* which caption and which word: full lines shows two phrases at once */
    const per = c.style==='lines' ? 2 : 1, groups = [];
    for(let i=0;i<PV_LINES.length;i+=per) groups.push(PV_LINES.slice(i,i+per));
    const count = gr => gr.reduce((a,l)=>a+l.length,0);
    const total = groups.reduce((a,gr)=>a+count(gr),0);
    let n = pvStep % total, g = 0;
    while(n >= count(groups[g])){ n -= count(groups[g]); g++; }
    let lines = groups[g], hi = n, fresh = n===0;
    if(c.style==='word'){ lines = [[lines.flat()[n]]]; hi = 0; fresh = true; }
    else if(c.style==='three'){ const flat = lines.flat(), k0 = Math.floor(n/3)*3; lines = [flat.slice(k0,k0+3)]; hi = n-k0; fresh = n%3===0; }
    let k = 0;
    const html = lines.map(l=>l.map(w=>(k++===hi) ? `<b>${esc(w)}</b>` : esc(w)).join(' ')).join('<br>');
    let spot = PV_POS[c.position] || PV_POS.bottom;
    if(c.position==='moves'){ const said = PV_LINES.slice(0, g*per).filter(l=>/[.?!]$/.test(l[l.length-1])).length; spot = PV_SPOTS[(said*2 + 1) % PV_SPOTS.length]; }
    cap.style.top = (spot[1]*100)+'%';
    cap.style.left = spot[0]==='center' ? '11%' : '7%'; cap.style.right = '11%'; cap.style.textAlign = spot[0];
    cap.style.fontSize = Math.round(pv.clientWidth * ((c.style==='lines' ? {s:.040,m:.048,l:.058} : {s:.050,m:.064,l:.080})[c.size] || .064)) + 'px';
    const motion = c.motion===false ? '' : (look==='clean' ? 'pop' : 'settle');
    const inner = cap.querySelector('.pv-in');
    if(inner && !fresh && !settingsChanged) inner.innerHTML = html;
    else setHTML(cap, `<span class="pv-in lk-${look}${motion ? ' '+motion : ''}">${html}</span>`);
    const pop = look==='glow' && /^#(e3991d|e8a13d)$/i.test(c.pop) ? '#faf6ec' : c.pop;
    cap.querySelectorAll('b').forEach(x=>x.style.color = c.pop_on ? pop : '');
  }

  /* ---------- step 4: cut ---------- */
  let dirty = false, wasCutting = false;
  function markDirty(){ if(hasCut() && PJ.stage!=='cutting') dirty = true; }
  const CUT_STEPS = [['plan','Lining up your story'],['segments','Cutting each part'],['captions','Adding your captions'],['final','Joining it together and evening out the sound'],['qa','Watching it back to check']];
  const CUT_SAY = {plan:'Going through each part and cleaning out what you asked to take out.', segments:'Cutting on the quiet gaps so no word gets clipped.', captions:'Drawing the words on screen.', final:'Putting the parts together into one video file.', qa:'Listening to the finished video to make sure nothing went wrong.'};
  function keptSecs(){ return board ? board.beats.filter(b=>b.keep!==false).reduce((a,b)=>{const u=beatUse(b);return a+(u.end-u.start);},0) : 60; }
  function cutProg(title){
    const p = PJ.progress || {}, at = Math.max(0, CUT_STEPS.findIndex(o=>o[0]===p.step));
    const m = p.step==='segments' && /(\d+) of (\d+)/.exec(p.label||'');
    return prog({title, detail: CUT_SAY[CUT_STEPS[at][0]] + (m ? ` Part ${m[1]} of ${m[2]}.` : ''), steps: CUT_STEPS.map(o=>[o[1],'']), at, frac: m ? m[1]/m[2] : .3, from: since('cutting'), est: Math.round(25 + keptSecs()*0.45)});
  }
  function renderCut(){
    const s = PJ.settings, cutting = PJ.stage==='cutting', failed = PJ.stage==='cut_failed';
    const kept = board ? board.beats.filter(b=>b.keep!==false).length : 0;
    const out = [s.cut.fillers&&'ums', s.cut.pauses&&'long pauses', s.cut.repeats&&'retakes'].filter(Boolean);
    const list = out.length>1 ? out.slice(0,-1).join(', ') + ' and ' + out[out.length-1] : out[0] || '';
    const cap = t => t.charAt(0).toUpperCase() + t.slice(1);
    /* the tidy up choices in one line, so the section can stay closed */
    $('#tidy-sum').textContent = `${out.length ? cap(list) + ' cut' : 'Nothing cut'} · ${s.cut.breath} pauses`;
    const last = hasCut() ? PJ.versions[PJ.versions.length-1] : null, reps = last && last.kept_repeats || 0;
    $('#kept-reps').hidden = !reps;
    if(reps) $('#kept-reps').textContent = `${reps} repeat${reps===1?' was':'s were'} kept in your last version, because you said ${reps===1?'it':'them'} on purpose.`;
    const bits = [`Your story in ${kept} part${kept===1?'':'s'}, about ${mmss(keptSecs())} before tidying`,
      `Made for ${PURPOSE[s.purpose]}, ${SHAPE_WORD[s.format]}${fitAsked() ? (s.fit==='pad' ? `, whole picture with a soft blur ${fitAsked()==='upright'?'at the sides':'above and below'}` : ', zoomed in to fill the screen') : ''}`,
      s.captions.style==='none' ? CAP_NAME.none : `${CAP_NAME[s.captions.style]}, ${LOOK_NAME[s.captions.look||'soft']} look, ${POS_NAME[s.captions.position]||'at the bottom'}${s.captions.motion===false ? '' : ', popping in'}`,
      out.length ? `${cap(list)} cut out` : 'Nothing cut out, your words as you said them',
      `${cap(s.cut.breath)} pauses between sentences`,
      s.export.max_mb ? 'A small file, under 25 MB' : 'Full picture quality'];
    setHTML($('#recap'), bits.map(b=>`<li>${icon('i-check')}<span>${esc(b)}</span></li>`).join(''));
    const fresh = hasCut() && !dirty && !cutting && !failed;
    if(!cutting) clearSince('cutting');
    const b = $('#cut-it');
    b.disabled = cutting || !kept;
    setHTML(b, cutting ? 'Making it now' : fresh ? `See my video${icon('i-next')}` : failed ? 'Try again' : hasCut() ? 'Make a new version' : 'Make my video');
    setHTML($('#p3-msg'), cutting ? 'Your Mac is making the video.' : fresh ? 'Your video is made. Change anything above to make a new version.' : `<b>${dirty ? 'You changed something. Make a new version?' : 'Happy with these choices?'}</b>Free. Your Mac does the cutting, so this uses nothing from your Claude plan. About ${Math.max(1, Math.ceil((25 + keptSecs()*0.45)/60))} minute${Math.ceil((25 + keptSecs()*0.45)/60)>1?'s':''}.`);
    $('#p3-err').hidden = !failed;
    if(failed) setHTML($('#p3-err'), `<b>The video didn't get made.</b>${esc((PJ.errors||[]).join(' '))} Press Try again.`);
  }
  $('#cut-it').addEventListener('click', async ()=>{
    if(hasCut() && !dirty && PJ.stage!=='cut_failed'){ step(4); return; }
    if(board && !PJ.storyboard.approved) await approveStory();
    await saveSettings(); clearSince('cutting');
    const had = PJ.versions.length;
    try {
      await api(`/api/project/${pid}/cut`, {}); dirty=false; wasCutting = true;
      await started(()=>{ wasCutting = true; return PJ.stage==='cutting' || PJ.stage==='cut_failed' || PJ.versions.length>had; });
      if(PJ.stage!=='cut_failed') step(4);   /* the progress card, then the video, both on Finish */
    } catch(e){ toast(e.message); }
  });

  /* ---------- step 5: finish. One player, one timeline under it (sections as chapter marks, at most 3 spots
     worth a look as dots on the same bar), one small panel for whatever is selected. Fixes go through the chat
     (D24); a caption word is put right on the spot, on the Mac, without Claude. ---------- */
  let viewV = null, spots = [], picked = null, capData = null, capKey = '', capLines = [], capLineAt = -1;
  const sentFix = new Set(), askedRecap = new Set();
  const activeJobs = () => (PJ.jobs||[]).filter(j=>(j.type==='change'||j.type==='chat') && j.status!=='done' && j.status!=='failed');
  const shownV = () => PJ.versions.find(x=>x.v===viewV) || PJ.versions[PJ.versions.length-1];
  const cutPlayer = $('#cut-player'); let cutStop = null, lastFill = '';
  const sectionsOf = v => (v.sections && v.sections.length) ? v.sections : [{label:'', start:0, end:v.duration||cutPlayer.duration||1}];
  const secTitle = (s,i,n) => `Section ${i+1} of ${n}${s.label ? ' · '+s.label : ''}`;
  const plural = (n, w) => `${n} ${w}${n===1?'':'s'}`;
  /* what changed in this version, as one plain sentence, or nothing (never a bare internal note) */
  function changedLine(note){
    const t = String(note||'').trim().replace(/\s+/g,' ');
    if(t.length < 12 || !/\s/.test(t) || /^(test|engine|check|debug|wip|tmp)\b/i.test(t)) return '';
    return 'Changed: ' + t.charAt(0).toLowerCase() + t.slice(1).replace(/\.$/, '') + '.';
  }
  function renderFinish(){
    /* the first video is being made: the progress card lives here, and the video appears in its place */
    const first = !hasCut();
    $('#finish').hidden = first; $('#p5-first').hidden = !first;
    $('#p5-h').textContent = first ? 'Making your video' : 'Your video';
    $('#p5-sub').textContent = first ? 'Your Mac is doing the work. Nothing to press. Your video shows up here when it is ready.' : 'Watch it through. Export it when it feels right, or say what to change in the chat.';
    if(first){ setHTML($('#p5-first'), making() ? cutProg('Making your video') : ''); tick(); return; }
    const last = PJ.versions[PJ.versions.length-1], v = shownV(), q = v.qa || {};
    const src = `/media/${pid}/video/${v.v}?c=${Math.round(v.captions_at||0)}`;
    if(!cutPlayer.src.endsWith(src)){
      /* same version with new captions: carry on from where they were */
      const same = cutPlayer.dataset.v===`${pid}:${v.v}`, at = same ? cutPlayer.currentTime : 0;
      cutPlayer.src = src; cutPlayer.dataset.v = `${pid}:${v.v}`; cutPlayer.style.aspectRatio = `${v.width}/${v.height}`;
      if(at) cutPlayer.addEventListener('loadedmetadata', ()=>{ cutPlayer.currentTime = at; }, {once:true});
      if(!same){ picked = null; cutStop = null; }
    }
    setHTML($('#vchips'), PJ.versions.length>1 ? '<span class="lab">Versions</span>' + PJ.versions.map(x=>`<button type="button" data-v="${x.v}" aria-pressed="${x.v===v.v}" title="${esc(verLabel(x.v, x.takes, x.at))}" aria-label="Version ${x.v}">${x.v}</button>`).join('') : '');
    $('#vtag').textContent = PJ.versions.length>1 ? `Version ${v.v}${v.v===last.v?', the newest':''}` : 'Your first cut';
    $('#stats').textContent = `${mmss(v.duration)} long · ${v.size_mb} MB · ${v.width>v.height?'wide':v.width<v.height?'upright':'square'}`;
    $('#vnote').textContent = changedLine(v.note);
    /* the checks, as one quiet line. Small things are fixed by the engine and never listed; what is left (3 at
       most, only what can be heard) is a dot on the bar. */
    const items = (q.items||[]).filter(i=>i.show).slice(0,3);
    if(q.shape_ok===false && !items.some(i=>i.kind==='shape')) items.unshift({at:0, kind:'shape', say:'The shape came out different from what you picked', ask:'The video came out the wrong shape. Make it the shape I picked.'});
    spots = items.slice(0,3);
    const ls = q.lip_sync, fixed = q.self_repairs||0, fx = Object.keys(PJ.fixes||{}).length;
    const good = [q.shape_ok===false ? '' : 'Shape right', ls && ls.measured && ls.ok ? 'lips in sync' : '', fixed ? `${fixed} fix${fixed===1?'':'es'} made for you` : '', fx ? `${plural(fx,'caption word')} put right` : ''].filter(Boolean);
    setHTML($('#qa-line'), `<p class="quiet">${icon('i-check')}<span>${esc(good.join(' · ') || 'Checked')}</span></p>` +
      (spots.length ? `<p class="quiet"><i></i><span>${plural(spots.length,'spot')} worth a look, marked on the bar</span></p>` : ''));
    /* Export stays Export. It used to turn into "Start a new video" in the same spot the moment the file was saved,
       so a second click there opened an empty new video: "the whole clip is gone, the page is refreshed" (22 Nov). */
    const ex = (PJ.exports||[]).filter(x=>x.v===v.v).pop(), stale = ex && (v.captions_at||0) > ex.at;
    $('#final').hidden = !ex;
    if(ex) setHTML($('#final'), `${icon('i-check')}<span><b>${stale ? 'Saved before you fixed the captions' : 'Saved to Exports'}</b><small>${stale ? 'Export again to save the new one.' : esc(String(ex.path).split('/').pop())}</small><button type="button" class="linkbtn" data-open-exports>Open the folder</button></span>`);
    const fp = $('#fin-primary'); fp.disabled = exporting; fp.classList.toggle('primary', !ex || stale);
    setHTML(fp, exporting ? 'Saving' : ex ? 'Export again' : 'Export');
    $('#fin-new').hidden = !ex;
    /* a new version on its way: say so here, with the video still playable */
    const job = activeJobs().find(j=>j.type==='change'), cutting = PJ.stage==='cutting', nv = PJ.versions.length+1;
    let html = '';
    if(cutting) html = cutProg(`Making version ${nv}`);
    else if(job){
      const steps = [['Claude Code reads your message',''],['Claude Code makes the change',''],['Your Mac cuts the new version',''],['Ready to watch','']];
      const taken = job.status==='taken';
      if(!taken && !connected()) html = prog({title:`Version ${nv} is waiting for Claude Code`, detail:'Your message is saved.', steps, at:0, waiting:true, ccOff:'Your change is waiting for it.'});
      else html = prog({title:`Making version ${nv}`, detail: taken ? 'Claude Code is working out the change you asked for.' : 'Claude Code is picking up your message.', steps, at: taken?1:0, frac:.4, from: since('job', taken ? job.taken : job.created), est: taken?120:0, noEst:'starting now'});
    }
    setHTML($('#p5-prog'), html ? html + '<div style="height:16px"></div>' : ''); tick();
    setHTML($('#p5-msg'), html ? 'You can keep watching this version while the new one is made.' : ex ? '' : `Export saves a copy in this video's Exports folder. Your video stays here.`);
    renderTrack(v); renderPick(); syncCaptions(v);
  }

  /* --- the one timeline --- */
  const spotTip = i => `${String(i.say||'').replace(/ at \d+:\d\d$/, '')} · ${mmss(i.at)}`;
  function renderTrack(v){
    const secs = sectionsOf(v), n = secs.length;
    const html = secs.map((s,i)=>`<button type="button" class="tseg" data-sec="${i}" style="flex-grow:${Math.max(.01,s.end-s.start).toFixed(2)}" data-tip="${esc(`${secTitle(s,i,n)} · ${mmss(s.start)} to ${mmss(s.end)}`)}" aria-label="${esc(`Play ${secTitle(s,i,n)}, ${mmss(s.start)} to ${mmss(s.end)}`)}"><i class="fill"></i>${n>1?`<span class="num">${i+1}</span>`:''}</button>`).join('')
      + spots.map((i,k)=>`<button type="button" class="spot" data-spot="${k}" data-at="${i.at}" data-tip="${esc(spotTip(i))}" aria-label="${esc('Worth a look: '+i.say)}"></button>`).join('')
      + '<i class="knob" id="knob"></i>';
    setHTML($('#track'), html); $('#spot-key').hidden = !spots.length;
    placeTrack();
  }
  /* a time in the video <-> x on the bar, through the section it falls in (sections have small gaps between them) */
  function xAt(t){
    const secs = sectionsOf(shownV()); let i = secs.findIndex(s=>t < s.end); if(i<0) i = secs.length-1;
    const el = $(`.tseg[data-sec="${i}"]`), s = secs[i]; if(!el || !s) return null;
    return el.offsetLeft + el.offsetWidth * Math.min(1, Math.max(0, (t - s.start)/Math.max(.01, s.end - s.start)));
  }
  function tAt(x){
    const secs = sectionsOf(shownV()), els = $$('#track .tseg'); if(!els.length) return 0;
    let i = els.findIndex(el=>x <= el.offsetLeft + el.offsetWidth); if(i<0) i = els.length-1;
    const el = els[i], s = secs[i];
    return s.start + (s.end - s.start) * Math.min(1, Math.max(0, (x - el.offsetLeft)/Math.max(1, el.offsetWidth)));
  }
  function placeTrack(){
    if(!hasCut()) return;
    const secs = sectionsOf(shownV()), t = cutPlayer.currentTime || 0, n = secs.length;
    let cur = secs.findIndex(s=>t < s.end); if(cur<0) cur = n-1;
    $$('#track .tseg').forEach((el,i)=>{
      const s = secs[i]; if(!s) return;
      el.querySelector('.fill').style.width = (100*Math.min(1, Math.max(0, (t - s.start)/Math.max(.01, s.end - s.start)))).toFixed(1) + '%';
      el.classList.toggle('on', i===cur); el.classList.toggle('sel', !!picked && picked.kind==='sec' && picked.i===i);
      el.classList.toggle('tip-l', i===0); el.classList.toggle('tip-r', i===n-1);
    });
    const tw = $('#track').offsetWidth;
    $$('#track .spot').forEach((m,k)=>{ const x = xAt(+m.dataset.at); if(x!=null){ m.style.left = x + 'px'; m.classList.toggle('tip-l', x < 110); m.classList.toggle('tip-r', x > tw - 110); } m.classList.toggle('sel', !!picked && picked.kind==='spot' && picked.k===k); });
    const knob = $('#knob'), x = xAt(t); if(knob && x!=null) knob.style.left = x + 'px';
    const dur = shownV().duration || cutPlayer.duration || 0;
    $('#tm').textContent = `${mmss(t)} / ${mmss(dur)}`;
    if(!hoverNow) setHTML($('#tl-now'), capBusy() ? `<span class="spin sm"></span>Updating your captions, about 20 seconds` : n>1 ? `<b>${cur+1}</b> · ${esc(secs[cur].label||'Section '+(cur+1))}` : '');
    placeSaid(t);
  }
  let hoverNow = false, raf = 0;
  function loopTrack(){ cancelAnimationFrame(raf); placeTrack(); if(!cutPlayer.paused && !cutPlayer.ended) raf = requestAnimationFrame(loopTrack); }
  function syncPlay(){ const on = !cutPlayer.paused && !cutPlayer.ended; setHTML($('#pp'), icon(on?'i-pause':'i-play')); $('#pp').setAttribute('aria-label', on?'Pause':'Play'); loopTrack(); }
  cutPlayer.addEventListener('timeupdate', ()=>{ if(cutStop!=null && cutPlayer.currentTime >= cutStop){ cutPlayer.pause(); cutStop=null; } placeTrack(); });
  ['play','pause','ended'].forEach(ev=>cutPlayer.addEventListener(ev, syncPlay));
  ['seeked','loadedmetadata'].forEach(ev=>cutPlayer.addEventListener(ev, placeTrack));
  window.addEventListener('resize', placeTrack);
  function togglePlay(){ if(cutPlayer.paused || cutPlayer.ended){ cutStop = null; cutPlayer.play().catch(()=>{}); } else cutPlayer.pause(); }
  $('#pp').addEventListener('click', togglePlay);
  cutPlayer.addEventListener('click', togglePlay);
  $('#stage').addEventListener('keydown', e=>{ if(e.key===' ' && !e.target.closest('button, input')){ e.preventDefault(); togglePlay(); } });
  function playSpan(a, b){ cutStop = b; cutPlayer.currentTime = Math.max(0, a); cutPlayer.play().catch(()=>{}); }
  function fillChat(text){ const i=$('#chat-in'); if(!i.value.trim() || i.value===lastFill){ i.value = text; lastFill = text; } i.focus(); i.setSelectionRange(i.value.length, i.value.length); }
  function flashChat(){ const c=$('#chat'); c.classList.remove('flash'); void c.offsetWidth; c.classList.add('flash'); }
  const track = $('#track'); let drag = null, scrubbed = false;
    /* drag along the bar to scrub; a plain click picks the section or the spot */
  track.addEventListener('pointerdown', e=>{ if(e.button || e.target.closest('.spot')) return; drag = {x:e.clientX, id:e.pointerId}; scrubbed = false; });
  track.addEventListener('pointermove', e=>{
    if(!drag || (!scrubbed && Math.abs(e.clientX - drag.x) < 5)) return;
    if(!scrubbed){ scrubbed = true; cutStop = null; try { track.setPointerCapture(drag.id); } catch(_){} }
    cutPlayer.currentTime = tAt(e.clientX - track.getBoundingClientRect().left); placeTrack();
  });
  ['pointerup','pointercancel'].forEach(ev=>track.addEventListener(ev, ()=>{ drag = null; }));
  track.addEventListener('click', e=>{
    if(scrubbed){ scrubbed = false; return; }
    const sp = e.target.closest('[data-spot]'), sec = e.target.closest('[data-sec]');
    if(sp){ const k = +sp.dataset.spot, i = spots[k]; if(!i) return; picked = {kind:'spot', k}; playSpan(i.at-2, i.at+1.5); }
    else if(sec){ const i = +sec.dataset.sec, s = sectionsOf(shownV())[i]; picked = {kind:'sec', i}; playSpan(s.start, s.end); }
    else return;
    renderPick(); placeTrack();
  });
  /* the one small panel: what is selected, and a single button */
  function renderPick(){
    const v = shownV(), secs = sectionsOf(v), box = $('#pick'); let html = '';
    if(picked && picked.kind==='spot' && spots[picked.k]){
      const i = spots[picked.k], sent = sentFix.has(`${v.v}:${i.at}:${i.kind}`);
      html = `<div class="what"><b>${esc(i.say)}</b><span>${sent ? 'Sent to the chat. Claude Code fixes it and makes a new version.' : `Worth a look. It plays from ${mmss(Math.max(0,i.at-2))}.`}</span></div><button type="button" class="btn navy sm" data-fix-spot="${picked.k}" ${sent?'disabled':''}>${sent?'Sent':'Fix it'}</button>`;
    } else if(picked && picked.kind==='sec' && secs[picked.i]){
      const s = secs[picked.i];
      html = `<div class="what"><b>${esc(secTitle(s, picked.i, secs.length))}</b><span>${mmss(s.start)} to ${mmss(s.end)}. Say what to change and Claude Code does it.</span></div><button type="button" class="btn navy sm" data-fix-sec="${picked.i}">Fix it</button>`;
    } else picked = null;
    if(html) html += `<button type="button" class="ib" data-pick-x aria-label="Close" title="Close">${icon('i-x')}</button>`;
    box.hidden = !html; box.classList.toggle('spotp', !!picked && picked.kind==='spot'); $('#fin-tip').hidden = !!html;
    setHTML(box, html);
  }
  $('#pick').addEventListener('click', e=>{
    const sp = e.target.closest('[data-fix-spot]'), sc = e.target.closest('[data-fix-sec]'), v = shownV();
    if(e.target.closest('[data-pick-x]')){ picked = null; renderPick(); placeTrack(); return; }
    if(sp){ const i = spots[+sp.dataset.fixSpot]; if(!i) return; sentFix.add(`${v.v}:${i.at}:${i.kind}`); renderPick(); sendChat({text:i.ask, kind:'change'}); flashChat(); toast('Sent to the chat. Claude Code will fix it and make a new version.'); }
    if(sc){ const i = +sc.dataset.fixSec, s = sectionsOf(v)[i]; lastFill = $('#chat-in').value; fillChat(`In section ${i+1} (${mmss(s.start)} to ${mmss(s.end)}), `); flashChat(); }
  });

  /* --- what you say, under the bar: every caption word, clickable to put right --- */
  const capBusy = () => !!(PJ && PJ.recaption) || (wfSent && Date.now() - wfSent < 4000);
  let wfSent = 0;
  async function syncCaptions(v){
    const key = `${pid}:${v.v}:${JSON.stringify(PJ.fixes||{})}`;
    if(key !== capKey){
      capKey = key; const want = key;
      try { const d = await api(`/api/project/${pid}/captions/${v.v}`); if(want!==capKey) return; capData = d; } catch(e){ capData = {words:[], on:false}; }
      /* lines of what is said: a sentence, or 14 words, or up to a real pause */
      capLines = []; let cur = [];
      capData.words.forEach((w,k)=>{ const p = cur[cur.length-1];
        if(p && (cur.length>=14 || w.s - p.e > 0.8 || /[.?!]["')]*$/.test(p.w))){ capLines.push(cur); cur = []; }
        cur.push(Object.assign({k}, w)); });
      if(cur.length) capLines.push(cur);
      capLineAt = -1; placeSaid(cutPlayer.currentTime||0);
    }
    /* a version drawn before the latest correction is drawn again, once, when it is on screen */
    if(v.captions_stale && !PJ.recaption && PJ.stage!=='cutting' && !askedRecap.has(key)){
      askedRecap.add(key); api(`/api/project/${pid}/recaption`, {v:v.v}).then(refreshProject, ()=>{});
    }
    if(PJ.recaption_error && !askedRecap.has('err:'+PJ.recaption_error)){ askedRecap.add('err:'+PJ.recaption_error); toast(PJ.recaption_error); }
  }
  function placeSaid(t){
    const el = $('#said'); if(!capLines.length){ setHTML(el, ''); return; }
    let li = 0; capLines.forEach((l,i)=>{ if(t >= l[0].s - 0.02) li = i; });   /* the line being said, or the last one said */
    const fixed = new Set(Object.values(PJ.fixes||{}).map(x=>x.toLowerCase()));
    if(li !== capLineAt || el._k !== capKey){
      capLineAt = li; el._k = capKey; el.classList.toggle('can', !!capData.on);
      el._h = null;
      setHTML(el, capLines[li].map(w=>`<button type="button" class="w${fixed.has(w.w.replace(/^[^\w]+|[^\w']+$/g,'').toLowerCase())?' fx':''}" data-k="${w.k}" ${capData.on?`title="Click to fix this word"`:'tabindex="-1"'}>${esc(w.w)}</button>`).join(' '));
    }
    const line = capLines[li]; let on = -1;
    line.forEach((w,i)=>{ if(t >= w.s - 0.02) on = i; });
    el.querySelectorAll('.w').forEach((b,i)=>b.classList.toggle('on', i===on && t <= line[line.length-1].e + 0.4));
  }
  const wf = $('#wordfix'); let wfWord = null;
  function closeFix(){ wf.hidden = true; wfWord = null; }
  $('#said').addEventListener('click', e=>{
    const b = e.target.closest('.w'); if(!b || !capData || !capData.on) return;
    const w = capData.words[+b.dataset.k]; if(!w) return;
    const core = w.w.replace(/^[^\w㐀-鿿]+|[^\w'㐀-鿿]+$/g, ''); if(!core) return;
    if(PJ.stage==='cutting' || PJ.recaption){ toast('One moment, your Mac is still drawing the video.'); return; }
    cutPlayer.pause(); wfWord = core;
    const n = capData.words.filter(x=>x.w.replace(/^[^\w㐀-鿿]+|[^\w'㐀-鿿]+$/g, '').toLowerCase()===core.toLowerCase()).length;
    $('#wf-lab').textContent = `Fix "${core}"`;
    $('#wf-hint').textContent = `${n>1 ? `All ${n} times it shows` : 'Everywhere it shows'} in this video's captions. Free, about 20 seconds. A name is also saved to Words I use, so the next video hears it right.`;
    wf.hidden = false;
    const r = b.getBoundingClientRect(), W = wf.offsetWidth, H = wf.offsetHeight;
    wf.style.left = Math.max(12, Math.min(window.innerWidth - W - 12, r.left + r.width/2 - W/2)) + 'px';
    wf.style.top = (r.top - H - 10 > 64 ? r.top - H - 10 : r.bottom + 10) + 'px';
    const i = $('#wf-in'); i.value = core; i.focus(); i.select();
  });
  wf.addEventListener('submit', async e=>{
    e.preventDefault(); const to = $('#wf-in').value.trim(), from = wfWord; if(!from) return;
    if(!to || to===from){ closeFix(); return; }
    closeFix(); wfSent = Date.now();
    try { await api(`/api/project/${pid}/fix_word`, {v: shownV().v, from, to}); toast(`Changing "${from}" to "${to}" in your captions. About 20 seconds.`); await refreshProject(); refreshState(); }
    catch(err){ wfSent = 0; toast(err.message); }
  });
  document.addEventListener('keydown', e=>{ if(e.key==='Escape' && !wf.hidden) closeFix(); });
  document.addEventListener('mousedown', e=>{ if(!wf.hidden && !e.target.closest('#wordfix, #said .w')) closeFix(); });
  window.addEventListener('scroll', ()=>{ if(!wf.hidden) closeFix(); }, true);

  $('#chips').addEventListener('click', e=>{ const b=e.target.closest('button'); if(!b) return; lastFill = $('#chat-in').value; fillChat(b.textContent); });
  $('#vchips').addEventListener('click', e=>{ const b=e.target.closest('[data-v]'); if(b){ viewV=+b.dataset.v; renderFinish(); } });
  /* export saves a copy and nothing else: same step, same video, same place in it. No Finder window on top of the page. */
  let exporting = false;
  async function doExport(){
    if(exporting) return; exporting = true; renderFinish();
    try { await api(`/api/project/${pid}/export`, {v: shownV().v, reveal: false}); toast('Saved to Exports.'); await refreshProject(); }
    catch(e){ toast(e.message); }
    exporting = false; renderFinish();
  }
  $('#fin-primary').addEventListener('click', doExport);
  $('#fin-new').addEventListener('click', newVideo);
  $('#final').addEventListener('click', e=>{ if(e.target.closest('[data-open-exports]')) openFolder('Exports'); });
  $('#tweak').addEventListener('click', ()=>{ flashChat(); $('#chat-in').focus(); });

  /* ---------- chat: one thread per video, beside the work, answered by the buyer's own Claude Code ---------- */
  let pendingAsk = null, sending = [];
  function jobLine(j){
    const taken = j.status==='taken';
    if(taken && PJ.stage==='cutting') return ['Your Mac is cutting the new version', (PJ.progress && PJ.progress.label) || '', 1];
    if(taken) return ['Working on it', j.type==='change' ? 'Claude Code is making the change.' : 'Claude Code is writing an answer.', 1];
    if(connected()) return ['Working on it', 'Claude Code is picking up your message.', 1];
    return ['Waiting for Claude Code', CC_HELP + '. Your message is saved.', 0];
  }
  function renderChat(){
    if(!PJ) return;
    const on = connected(), act = activeJobs();
    $('#conn').classList.toggle('off', !on); $('#conn span').textContent = on ? 'Claude Code is connected' : "Claude isn't listening";
    $('#cc-pill').classList.toggle('off', !on); $('#cc-pill span').textContent = on ? 'Claude Code connected' : "Claude isn't listening";
    $('#chat-off').hidden = on || act.some(j=>j.status==='taken');
    $('#conn').hidden = !$('#chat-off').hidden;   /* the card below already says it */
    const secs = hasCut() ? (shownV().sections || []) : [], n = secs.length;
    $('#chips').hidden = !hasCut();
    if(hasCut()) setHTML($('#chips'), [n>1 ? `The cut at ${mmss(secs[1].start)} is choppy` : 'The start is choppy', `You cut off my last word in section ${Math.min(3, n||1)}`, n>3 ? 'Drop section 4' : 'Make it shorter', 'More pause after each sentence', n>1 ? 'Start with section 2' : 'Make the captions bigger'].map(c=>`<button type="button">${esc(c)}</button>`).join(''));
    $('#chat-in').placeholder = hasCut() ? 'Say what to change, like "start with my second line"' : 'Ask anything about this video';
    const events = (PJ.chat||[]).map(m=>({at:m.at, html:`<li class="msg ${m.who==='you'?'me':'cl'}"><span class="who">${m.who==='you'?'You':'Claude'}</span>${esc(m.text)}</li>`}))
      .concat((PJ.versions||[]).map(v=>({at:v.at, html:`<li class="msg ev">${v.v===1?'Your video is ready':`Version ${v.v} is ready`}<button type="button" class="btn sm" data-watch="${v.v}">Watch it</button></li>`})))
      .sort((a,b)=>a.at-b.at).map(x=>x.html);
    if(!events.length && !pendingAsk && !sending.length) events.push(`<li class="msg cl"><span class="who">Claude</span>Ask me anything about this video, or tell me what to change in plain words. Your video stays in view while we talk.</li>`);
    const texts = new Set((PJ.chat||[]).map(m=>m.text));
    sending = sending.filter(t=>!texts.has(t));
    sending.forEach(t=>events.push(`<li class="msg me"><span class="who">You</span>${esc(t)}</li>`));
    act.forEach(j=>{ const l = jobLine(j); events.push(`<li class="msg cl work"><span class="spin sm${l[2]?'':' wait'}"></span><span><b>${l[0]}${l[2]?'…':''}</b><small>${esc(l[1])}</small><small><span data-from="${Math.round(j.created*1000)}">0:00</span> so far${!l[2]?'':j.type==='change'?', usually 2 to 4 minutes':', usually under a minute'}</small></span></li>`); });
    const lastJob = (PJ.jobs||[]).filter(j=>j.type!=='story').pop();
    if(lastJob && lastJob.status==='failed' && !lastJob.reply) events.push(`<li class="msg cl"><span class="who">Claude</span>That one didn't work. Try saying it another way.</li>`);
    /* two tries through the chat and still asking: point at finishing by hand, shown greyed until that ships */
    if((PJ.jobs||[]).filter(j=>j.type==='change' && (j.status==='done'||j.status==='failed')).length >= 2 && !act.length)
      events.push(`<li class="msg offer">Still not right after two tries? Small fixes like a trim are quicker by hand.<button type="button" class="btn sm" disabled>Finish it in Edits <span class="soon">Coming next</span></button></li>`);
    if(pendingAsk) events.push(`<li class="msg me draft"><span class="who">You, not sent yet</span>${esc(pendingAsk.text)}</li>
      <li class="confirm"><b>Happy with the instructions?</b>${hu('change')}<span class="row"><button type="button" class="btn primary" data-chat-go>Go</button><button type="button" class="btn" data-chat-no>Edit it</button></span></li>`);
    document.body.classList.toggle('asking', !!pendingAsk);
    if(setHTML($('#msgs'), events.join(''))){ $('#msgs').scrollTop = $('#msgs').scrollHeight; tick(); }
  }
  async function sendChat(a){
    sending.push(a.text); renderChat();
    try { await api(`/api/project/${pid}/${a.kind}`, {text:a.text, part:null}); clearSince('job'); await refreshProject(); }
    catch(err){ sending = sending.filter(t=>t!==a.text); $('#chat-in').value = a.text; renderChat(); toast(err.message); }
  }
  $('#chat-form').addEventListener('submit', e=>{
    e.preventDefault(); const i=$('#chat-in'), t=i.value.trim(); if(!t) return;
    i.value='';
    if(pendingAsk){ pendingAsk.text += '\n' + t; renderChat(); $('[data-chat-go]').focus(); return; }
    /* a question is light, so it goes straight away; a change to a finished cut makes a new version, so it asks once */
    if(!hasCut()){ sendChat({text:t, kind:'chat'}); return; }
    pendingAsk = {text:t, kind:'change'}; renderChat(); $('[data-chat-go]').focus();
  });
  $('#chat-in').addEventListener('keydown', e=>{ if(e.key==='Enter' && !e.shiftKey){ e.preventDefault(); $('#chat-form').requestSubmit(); } });
  $('#msgs').addEventListener('click', e=>{
    const w = e.target.closest('[data-watch]');
    if(w){ viewV = +w.dataset.watch; step(4); $('#cut-player').play().catch(()=>{}); return; }
    if(e.target.closest('[data-chat-no]')){ $('#chat-in').value = pendingAsk.text; pendingAsk=null; renderChat(); $('#chat-in').focus(); return; }
    if(!e.target.closest('[data-chat-go]') || !pendingAsk) return;
    const a = pendingAsk; pendingAsk = null; sendChat(a); if(S.step!==4) step(4, true);
  });

  /* ---------- render + poll ---------- */
  function renderAll(){
    if(!PJ) return;
    renderFiles(); renderStepper(); renderP1(); renderStory(); renderPreview(); renderCut(); renderFinish(); renderChat(); renderProjects(); updateFitQuestion();
  }
  async function refreshState(){ try { ST = await api('/api/state'); renderSetup(); if(PJ) renderAll(); } catch(e){} }
  async function refreshProject(){
    if(!pid) return;
    try {
      const want = pid, fresh = await api('/api/project/'+want);
      if(want!==pid) return;
      const before = PJ ? PJ.versions.length : 0, hadStory = !!hasStory(), wasCap = PJ && PJ.id===fresh.id && PJ.recaption;
      PJ = fresh;
      if(wasCap && !PJ.recaption && !PJ.recaption_error) toast('Your captions are updated.');
      if(PJ.versions.length > before) viewV = null;
      renderAll();
      if(PJ.versions.length > before){ wasCutting=false; dirty=false; step(4, true); toast(`${PJ.versions.length===1?'Your video':'Version '+PJ.versions.length} is ready. Press play.`); }
      else if(wasCutting && PJ.stage!=='cutting') wasCutting=false;
      if(!hadStory && hasStory() && S.step===2) toast('Your story is ready to check.');
      if(PJ.stage==='cutting') wasCutting = true;
    } catch(e){}
  }
  const busy = () => PJ && (['hearing','story_wait','cutting'].includes(PJ.stage) || (PJ.jobs||[]).some(j=>j.status!=='done'&&j.status!=='failed'));
  async function loop(){ await refreshProject(); setTimeout(loop, busy() ? 1500 : 4000); }
  async function stateLoop(){ await refreshState(); setTimeout(stateLoop, (ST && ST.setup.installing) || busy() ? 2000 : 5000); }

  (async function init(){
    await refreshState();
    await ensureProject(); fillForm(); renderAll();
    if(ST && ST.setup.ready){ go('editor'); step(autoStep(), true); } else go('setup');
    loop(); stateLoop();
  })();
})();

/* D35: ask how to fit only when a clip's shape differs from the video's, both ways: a sideways clip into an upright /
   tall / square video, or an upright clip into a wide one. Returns 'sideways', 'upright' or '' (no question). */
function fitAsked(){
  if(!window.PJ || !PJ.takes || !PJ.takes[0]) return '';
  const sel = document.querySelector('input[name="format"]:checked'), fmt = sel ? sel.value : (PJ.settings && PJ.settings.format) || '9:16';
  const wh = f => ((f.turn||0)%180 ? [f.probe.shown_h, f.probe.shown_w] : [f.probe.shown_w, f.probe.shown_h]);
  if(['9:16','4:5','1:1'].includes(fmt) && PJ.takes.some(f => { const [w,h]=wh(f); return w>h; })) return 'sideways';
  if(fmt==='16:9' && PJ.takes.some(f => { const [w,h]=wh(f); return h>w; })) return 'upright';
  return '';
}
function updateFitQuestion(){
  const q = document.getElementById('fit-q'); if(!q) return;
  const k = fitAsked(); q.hidden = !k; if(!k) return;
  const sel = document.querySelector('input[name="purpose"]:checked'), pur = sel ? sel.value : 'ig';
  const many = PJ.takes.length > 1, it = many ? 'a clip' : 'this';
  const where = pur==='ig' ? 'Instagram is upright' : pur==='yt' ? 'YouTube is wide' : (k==='sideways' ? 'Your video is upright' : 'Your video is wide');
  const legend = k==='sideways' ? `You filmed ${it} sideways. ${where}. How should it fit?` : `You filmed ${it} upright. ${where}. How should it fit?`;
  const set = (id, t) => { const el = document.getElementById(id); if(el && el.textContent!==t) el.textContent = t; };
  set('fit-legend', legend);
  set('fit-pad-say', k==='sideways' ? 'Nothing is cut off. A soft blur fills the empty space above and below.' : 'Nothing is cut off. A soft blur fills the empty sides.');
  set('fit-crop-say', k==='sideways' ? 'Fills the screen and follows your face. The left and right edges get cut off.' : 'Fills the screen and follows your face. The top and bottom get cut off.');
  const t = PJ.takes.find(f => { const w = (f.turn||0)%180 ? [f.probe.shown_h, f.probe.shown_w] : [f.probe.shown_w, f.probe.shown_h]; return k==='sideways' ? w[0]>w[1] : w[1]>w[0]; });
  document.querySelectorAll('#fit-q .fitpic').forEach(p => p.classList.toggle('wide', k==='upright'));
  if(t){ const src = `/media/${PJ.id}/frame/${encodeURIComponent(t.name)}?t=${t.turn||0}-${t.added||0}-${t.turned_at||0}`;
    document.querySelectorAll('#fit-q .fitpic, #fit-q .fitpic i').forEach(p => { p.style.backgroundImage = `url("${src}")`; }); }
}
document.addEventListener('change', e => { if(e.target && (e.target.name === 'format' || e.target.name === 'purpose')) updateFitQuestion(); });
