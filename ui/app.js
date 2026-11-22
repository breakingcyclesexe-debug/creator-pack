/* Creator Pack page. Talks only to the local server (127.0.0.1). Judgement work (story, changes, chat) is
   written as jobs that the buyer's own Claude Code session picks up; this page never talks to Claude.
   Layout (22 Nov 2026, video first): a thin step rail, the buyer's video big in the middle on every step, the
   tools on the right, the chat as one line under the tools that opens over them, never over the video. */
(function(){
  const $ = s => document.querySelector(s);
  const $$ = s => Array.from(document.querySelectorAll(s));
  const icon = id => `<svg class="ico" aria-hidden="true"><use href="#${id}"/></svg>`;
  const esc = s => String(s==null?'':s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  const val = n => (document.querySelector(`input[name="${n}"]:checked`)||{}).value;
  const setRadio = (n,v) => { const r=document.querySelector(`input[name="${n}"][value="${v}"]`); if(r) r.checked=true; };
  const mmss = t => { t=Math.max(0,Math.round(t||0)); return `${Math.floor(t/60)}:${String(t%60).padStart(2,'0')}`; };
  const plural = (n, w) => `${n} ${w}${n===1?'':'s'}`;
  /* only touch the page when something changed, so spinners and scroll positions don't jump on every poll */
  const setHTML = (el, html) => { if(el._h===html) return false; el.innerHTML=html; el._h=html; return true; };
  let toastT;
  function toast(msg){ const t=$('#toast'); t.textContent=msg; t.classList.add('is-show'); clearTimeout(toastT); toastT=setTimeout(()=>t.classList.remove('is-show'),4200); }
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

  /* one progress card for every wait: the steps as tiles, what is happening, time so far, rough time left */
  function prog(o){
    const n = o.steps.length, frac = Math.min(1, (o.at + (o.frac||0)) / n);
    const clock = o.from ? `<div class="pg-t"><b data-from="${o.from}">0:00</b><span data-from="${o.from}" data-est="${o.est||0}" data-none="${esc(o.noEst||'')}"></span></div>` : '';
    return `<div class="pg" role="status"><div class="pg-h"><span class="ui-spin${o.waiting?' is-wait':''}"></span><div><h2>${esc(o.title)}</h2><p>${esc(o.detail||'')}</p></div>${clock}</div>
      <div class="pg-bar"><i style="width:${Math.max(4, Math.round(frac*100))}%"></i></div>
      <ol class="pg-steps">${o.steps.map((s,i)=>`<li class="pg-step${i<o.at?' is-done':i===o.at?' is-now':''}"><span class="pg-d"><span>${i+1}</span>${icon('i-check')}</span><b>${esc(s[0])}</b>${i<o.at?'Done':i===o.at?(o.waiting?'Waiting for you':'Happening now'):esc(s[1]||'Next')}</li>`).join('')}</ol>
      ${o.ccOff ? ccOff(o.ccOff) : ''}</div>`;
  }
  const ccOff = why => `<div class="ui-ccoff"><b>Claude isn't listening right now</b>${esc(why)} In the Claude app, open Claude Code and send this message. It picks up from here by itself.<div class="ui-cmd"><code>/creator-pack</code><button type="button" class="ui-btn is-sm" data-copy="/creator-pack">Copy</button></div></div>`;

  /* ---------- screens ---------- */
  let screenNow = 'setup';
  function go(name){
    screenNow = name;
    $('#screen-setup').hidden = name!=='setup'; $('#screen-editor').hidden = name!=='editor';
    if(name==='setup') $('#tab-setup').setAttribute('aria-current','page'); else $('#tab-setup').removeAttribute('aria-current');
    document.body.classList.toggle('is-setup', name==='setup');
    if(name==='setup') pauseAll();
    renderProjects(); renderSetupPics();
    if(name==='editor'){ ensureProject(); requestAnimationFrame(()=>{ fitStage(); placeTrack(); }); }
    const h = name==='setup' ? $('#setup-h') : $(PANEL[S.step]+' h1'); if(h) h.focus({preventScroll:true});
  }
  document.addEventListener('click', e => { const b=e.target.closest('[data-go]'); if(b) go(b.dataset.go); });
  document.addEventListener('click', e=>{ const c=e.target.closest('[data-copy]'); if(!c) return; navigator.clipboard.writeText(c.dataset.copy).then(()=>toast('Copied.'), ()=>toast('Select it and copy.')); });

  /* ---------- setup: four ticked tiles, names you say a lot, one button ---------- */
  const sel = {};
  const TOOL = {brew:['Installer','Homebrew','i-box'], python:['Helpers','inside the pack','i-py'], ffmpeg:['Video cutter','ffmpeg','i-cut'],
    whisper:['Listener','whisper','i-ear'], model:['Speech model','1.6 GB, on your Mac','i-brain'], node:['Node.js','not needed yet','i-box']};
  const toolName = t => (TOOL[t.id]||[t.name])[0];
  function setupTile(t){
    if(sel[t.id]===undefined) sel[t.id] = !t.optional;
    const s = ST.setup, d = TOOL[t.id] || [t.name, '', 'i-box'], now = s.installing && s.current===t.id;
    let st = '';
    if(t.found) st = '';
    else if(now) st = `<span class="su-st"><span class="ui-spin is-sm"></span>Installing</span>`;
    else if(s.installing && sel[t.id]) st = `<span class="su-st">Waiting its turn</span>`;
    else if(t.manual || t.error) st = `<span class="su-st">Needs you</span>`;
    else st = `<label class="su-st"><input type="checkbox" data-sel="${t.id}" ${sel[t.id]?'checked':''} ${s.installing?'disabled':''}>${t.optional?'Install (optional)':'Install'}</label>`;
    return `<li class="su-check${t.found?' is-ok':''}">${icon(d[2])}${esc(d[0])}<small>${esc(d[1])}</small>${st}</li>`;
  }
  function renderSetup(){
    if(!ST) return;
    const s = ST.setup;
    /* Node.js is not used yet, and the helpers need nothing from the buyer once they are there: no tile for them */
    const items = s.items.filter(t=>!(t.optional && t.id==='node') && !(t.id==='python' && t.found)), all = s.items.filter(t=>!(t.optional && t.id==='node'));
    const need = items.filter(t=>!t.optional), n = need.filter(t=>t.found).length;
    setHTML($('#tools'), items.map(setupTile).join(''));
    const fix = items.filter(t=>!t.found && (t.manual || (t.error && !(s.installing && s.current===t.id)))).map(t => t.manual
      ? `<div class="su-fix"><b>Homebrew asks for your Mac password, so only you can install it.</b> Open the Terminal app, paste this line, press Return, then press Check again.<div class="ui-cmd"><code>${esc(t.manual)}</code><button type="button" class="ui-btn is-sm" data-copy="${esc(t.manual)}">Copy</button></div></div>`
      : `<div class="su-fix"><b>${esc(toolName(t))} didn't install.</b> ${esc(t.error)}</div>`).join('');
    setHTML($('#setup-fix'), fix);
    const q = all.filter(t=>!t.found && sel[t.id] && !t.manual).length, pb = $('#setup-primary');
    $('#setup-h').textContent = s.ready ? 'Your Mac is ready' : 'Get your Mac ready';
    $('#setup-sub').textContent = s.ready ? 'Your videos never leave your Mac.' : n===need.length && s.licence && !s.licence.ok ? 'Everything is installed. Add your licence key to finish.' : `${n} of ${need.length} ready. About 10 minutes to install.`;
    pb.disabled = !s.ready && (s.installing || !q);
    const madeOne = ((ST.projects)||[]).some(p=>p.versions);
    setHTML(pb, s.ready ? `${madeOne ? 'Back to my video' : 'Make my first video'}${icon('i-next')}` : s.installing ? 'Installing' : q ? `Install ${q} thing${q>1?'s':''}` : 'Nothing to install');
    pb.dataset.act = s.ready ? 'open' : 'install';
    setHTML($('#setup-msg'), s.ready ? '' : s.installing ? 'You can leave this open.' : `<button type="button" class="ui-link" data-go="editor">Look around first</button>`);
    const sp = $('#setup-prog'); sp.hidden = !s.installing;
    if(s.installing){
      const order = all.filter(t=>!t.found && sel[t.id] || t.id===s.current), cur = all.find(t=>t.id===s.current);
      setHTML(sp, prog({title:`Installing the ${cur ? toolName(cur).toLowerCase() : 'tools'}`, detail: s.current==='model' ? 'A big download, so it is the slow one.' : 'Your Mac is downloading it and setting it up.',
        steps: order.map(t=>[toolName(t), '']), at: Math.max(0, order.findIndex(t=>t.id===s.current)), frac:.5, from: since('install'), noEst:'a few minutes'})); tick();
    } else { localStorage.removeItem(`cpack-since-${pid}-install`); sp._h = null; }
    $('#setup-banner').hidden = s.ready;
    renderLicence(s.licence);
    renderWords();
  }
  /* the before and after picture: the buyer's own frame once there is one */
  function renderSetupPics(){
    let url = '';
    const hook = PJ && PJ.storyboard && (PJ.storyboard.beats||[]).find(b=>b.keep!==false);
    if(hook && takeOf(beatUse(hook).take)) url = partStill(hook);   /* a frame from the hook, where the face is */
    else if(PJ && PJ.takes && PJ.takes[0]) url = frameSrc(PJ.takes[0]);
    else { const p = ((ST && ST.projects)||[]).find(x=>!x.empty && x.thumb); if(p) url = `/media/${p.id}/frame/${encodeURIComponent(p.thumb)}`; }
    ['#su-raw','#su-got'].forEach(s=>{ const el=$(s); el.classList.toggle('has-pic', !!url); el.style.backgroundImage = url ? `url("${url}")` : ''; });
    $('#su-got .su-cap').hidden = !url;
  }
  /* licence (paid version only): the server leaves it out of the state when there is no licence check, so nothing shows */
  function renderLicence(l){
    const c = $('#licence-card'); c.hidden = !(l && l.required); if(c.hidden) return;
    $('#licence-st').textContent = l.ok ? (l.offline ? `checked offline, ${l.days_left} day${l.days_left===1?'':'s'} left` : 'active') : 'needs you';
    $('#licence-why').textContent = l.ok ? (l.offline ? 'Go online within that time so the pack can check it again.' : 'Thanks for buying the pack.') : (l.reason || '');
    $('#licence-form').hidden = l.ok && !l.offline;
  }
  $('#licence-form').addEventListener('submit', async e=>{ e.preventDefault(); const k=$('#licence-in').value.trim(); if(!k) return;
    try { ST.setup.licence = await api('/api/licence', {key:k}); $('#licence-in').value=''; await refreshState(); toast(ST.setup.licence && ST.setup.licence.ok ? 'Licence checked.' : (ST.setup.licence||{}).reason || 'Checked.'); } catch(err){ toast(err.message); } });
  document.addEventListener('change', e=>{ const c=e.target.closest('[data-sel]'); if(!c) return; sel[c.dataset.sel]=c.checked; renderSetup(); });

  /* ---------- names you say a lot (read by the listener before it hears a video) and Chinese ---------- */
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
  async function savePrefs(p){ try { ST.prefs = await api('/api/prefs', p); renderWords(); renderGuess(); } catch(e){ toast(e.message); } }
  $('#words-form').addEventListener('submit', e=>{ e.preventDefault(); const i=$('#words-in'), t=i.value.trim(); if(!t) return; i.value=''; savePrefs({words:(prefs().words||[]).concat(t)}); });
  $('#words-list').addEventListener('click', e=>{ const b=e.target.closest('[data-word-drop]'); if(!b) return; const w=(prefs().words||[]).slice(); w.splice(+b.dataset.wordDrop,1); savePrefs({words:w}); });
  $('#words-edit').addEventListener('click', ()=>{ go('setup'); $('#words-in').focus(); });
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
  $('#studio-want').addEventListener('click', async () => {
    try { await api('/api/interest', {what:'story_studio', project: pid || ''}); toast('Thanks. The Story Studio page is open: join there to hear first.'); } catch(e){ toast(e.message); }
    showStudio(false);
  });

  /* ---------- versions: "Version 2 · 3 clips · today 14:02" ---------- */
  function when(at){
    if(!at) return ''; const d = new Date(at*1000), now = new Date(), hm = d.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
    const y = new Date(now); y.setDate(now.getDate()-1);
    return d.toDateString()===now.toDateString() ? `today ${hm}` : d.toDateString()===y.toDateString() ? `yesterday ${hm}` : `${d.toLocaleDateString([], {day:'numeric', month:'short'})} ${hm}`;
  }
  const verLabel = (n, clips, at) => [`Version ${n}`, clips!=null ? `${clips} clip${clips===1?'':'s'}` : '', when(at)].filter(Boolean).join(' · ');

  /* ---------- editor state: four steps on the rail ---------- */
  const S = {step:1};
  const STAGES = ['footage','hearing','story_wait','story','cutting','review','cut_failed'];
  const stageAt = () => STAGES.indexOf(PJ ? PJ.stage : 'footage');
  const heard = () => PJ && stageAt() >= 2;
  const hasStory = () => PJ && PJ.storyboard;
  const hasCut = () => PJ && PJ.versions && PJ.versions.length > 0;
  const STEPS = [['Footage','i-film'],['Story','i-cards'],['Look','i-aa'],['Finish','i-flag']], PANEL = {1:'#p1', 2:'#p2', 3:'#p3', 4:'#p5'};
  const making = () => PJ && PJ.stage==='cutting';
  const canStep = n => n===1 || (n===2 && PJ && stageAt()>=1) || (n===3 && hasStory()) || (n===4 && (hasCut() || making()));
  const stepDone = n => !!([heard(), hasStory() && PJ.storyboard.approved, hasCut(), PJ && (PJ.exports||[]).length>0][n-1]);
  function renderStepper(){
    setHTML($('#stepper'), STEPS.map((l,i)=>{ const n=i+1, done = stepDone(n) && n!==S.step;
      return `<li class="${stepDone(n)?'is-done':''}"><button type="button" data-step="${n}" ${n===S.step?'aria-current="step"':''} ${canStep(n)?'':'disabled'} aria-label="Step ${n} of 4, ${l[0]}"><span class="rl-n">${icon(done?'i-check':l[1])}</span>${l[0]}</button></li>`; }).join(''));
  }
  function step(n, quiet){
    if(!canStep(n)) return;
    if(S.step===2 && n>2 && hasStory() && !PJ.storyboard.approved) approveStory();
    if(n!==S.step){ pauseAll(); chat(false); }
    S.step=n;
    for(let i=1;i<=4;i++) $(PANEL[i]).hidden = i!==n;
    renderAll();
    if(n===2 || n===3) loadPart(selPart);
    if(!quiet) $(PANEL[n]+' h1').focus({preventScroll:true});
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
    pauseAll();
    PJ = p; pid = id; localStorage.setItem('cpack-project', pid); board = null; pendingAsk = null; sending = []; viewV = null; dirty = false; wasCutting = false;
    selTake = ''; selPart = 0; undoStack = []; HW = null; hwKey = ''; plan = null; raw.removeAttribute('src'); raw.load();
    fillForm(); step(autoStep(), true); refreshState();
  }
  async function newVideo(){
    if(PJ && !PJ.takes.length){ step(1); toast('This one is empty. Add your clips here.'); return; }
    const p = await api('/api/project/new', {}); await openProject(p.id); toast('Ready for a new video. Add your clips.');
  }
  /* "Your videos": the frame, the name, the length, New video on top, rename in place */
  const vmenu = $('#vmenu'), vlist = $('#vlist'), vbtn = $('#vbtn'); let renaming = '';
  function showVideos(on){ vlist.hidden = !on; vbtn.setAttribute('aria-expanded', on); if(!on) renaming = ''; renderProjects(); if(on){ const c = vlist.querySelector('.is-cur .vm-open'); (c || vlist.querySelector('button')).focus(); } }
  vbtn.addEventListener('click', e=>{ e.stopPropagation(); showVideos(vlist.hidden); });
  document.addEventListener('click', e=>{ if(!vlist.hidden && !e.composedPath().includes(vmenu)) showVideos(false); });
  document.addEventListener('keydown', e=>{ if(e.key==='Escape' && !vlist.hidden){ showVideos(false); vbtn.focus(); } });
  vlist.addEventListener('keydown', e=>{
    if(e.key!=='ArrowDown' && e.key!=='ArrowUp' || e.target.tagName==='INPUT') return;
    const f = Array.from(vlist.querySelectorAll('.vm-new, .vm-open')), i = f.indexOf(document.activeElement.closest('.vm-new, .vm-open') || document.activeElement);
    e.preventDefault(); f[(i + (e.key==='ArrowDown'?1:-1) + f.length) % f.length].focus();
  });
  vlist.addEventListener('click', async e=>{
    const o = e.target.closest('[data-open]'), r = e.target.closest('[data-rename]');
    if(e.target.closest('.vm-new')){ showVideos(false); newVideo(); return; }
    if(r){ renaming = r.dataset.rename; renderProjects(); const i = vlist.querySelector('form input'); i.focus(); i.select(); return; }
    if(o){ showVideos(false); if(o.dataset.open!==pid) openProject(o.dataset.open); }
  });
  vlist.addEventListener('submit', async e=>{
    e.preventDefault(); const id = renaming, t = e.target.querySelector('input').value.trim();
    try { const r = await api(`/api/project/${id}/rename`, {title:t}); ST.projects = r.projects; if(id===pid && PJ) PJ.title = (r.projects.find(p=>p.id===id)||{}).title; } catch(err){ toast(err.message); }
    renaming = ''; renderProjects(); const b = vlist.querySelector(`[data-open="${id}"]`); if(b) b.focus();
  });
  const thumbOf = p => p.thumb ? `/media/${p.id}/frame/${encodeURIComponent(p.thumb)}` : '';
  function renderProjects(){
    const all = (ST && ST.projects) || [];
    const list = all.filter(p=>p.id===pid || !p.empty).slice(0,30);
    vmenu.hidden = !(screenNow==='editor' && !!PJ);
    const day = t => t ? new Date(t*1000).toLocaleDateString([], {day:'numeric', month:'short'}) : '';
    const nm = p => p.id===pid && PJ ? PJ.title || p.title : p.title || p.name;
    const cur = list.find(p=>p.id===pid);
    $('#vbtn-t').textContent = cur ? nm(cur) : PJ ? PJ.title || 'New video' : '';
    const th = PJ && PJ.takes && PJ.takes[0] ? frameSrc(PJ.takes[0]) : '';
    $('#vbtn-th').style.backgroundImage = th ? `url("${th}")` : '';
    if(vlist.hidden) return;
    setHTML(vlist, `<button type="button" class="vm-new"><span class="vm-pic">${icon('i-plus')}</span><span><b>New video</b><small>Drop in a recording</small></span></button>` + list.map(p=>{
      const full = p.id===pid && PJ && PJ.storyboard ? PJ.storyboard.one_line : p.story;
      if(renaming===p.id) return `<div class="vm-row${p.id===pid?' is-cur':''}"><form><label class="sr" for="vname">Name of this video</label><input type="text" class="ui-in" id="vname" maxlength="60" value="${esc(nm(p))}" autocomplete="off"><button type="submit" class="ui-btn is-navy is-sm">Save</button></form></div>`;
      const facts = [day(p.created), p.duration ? mmss(p.duration) : '', p.versions ? `version ${p.versions}` : ''].filter(Boolean).join(' · ');
      const pic = thumbOf(p);
      return `<div class="vm-row${p.id===pid?' is-cur':''}"><button type="button" class="vm-open" data-open="${p.id}" title="${esc(full||nm(p))}" ${p.id===pid?'aria-current="true"':''}><span class="vm-pic"${pic?` style="background-image:url('${pic}')"`:''}></span><span><b>${esc(nm(p))}</b><small>${esc(facts)}</small></span>${p.exported?'<span class="vm-st">Exported</span>':''}</button><button type="button" class="ui-ib" data-rename="${p.id}" title="Rename" aria-label="Rename ${esc(nm(p))}">${icon('i-pen')}</button></div>`;
    }).join(''));
  }

  /* ---------- footage ---------- */
  const tturn = t => (t && t.turn) || 0;
  const shownWH = t => tturn(t)%180 ? [t.probe.shown_h, t.probe.shown_w] : [t.probe.shown_w, t.probe.shown_h];
  const shapeOf = t => { const [w,h] = shownWH(t); return w>h ? 'wide' : w<h ? 'tall' : 'square'; };
  const SHAPE_SHORT = {wide:'wide', tall:'upright', square:'square'};
  const frameSrc = t => `/media/${pid}/frame/${encodeURIComponent(t.name)}?t=${tturn(t)}-${t.added||0}-${t.turned_at||0}`;
  const takeOf = name => ((PJ && PJ.takes)||[]).find(x=>x.name===name);
  let selTake = '';
  const curTake = () => takeOf(selTake) || ((PJ && PJ.takes)||[])[0];
  function renderFiles(){
    const takes = (PJ && PJ.takes) || [], cur = curTake();
    setHTML($('#takes'), takes.map(t=>`<div class="ft-clip${cur && cur.name===t.name?' is-sel':''}" data-take="${esc(t.name)}" role="button" tabindex="0" aria-label="Show ${esc(t.name)}"><img class="ft-clip-ph" src="${frameSrc(t)}" alt="">
      <button type="button" class="ui-ib is-dark ft-x" data-rm="${esc(t.name)}" aria-label="Take out ${esc(t.name)}" title="Take out">${icon('i-x')}</button>
      <span class="ft-rot"><button type="button" class="ui-ib is-dark" data-turn="-90" data-name="${esc(t.name)}" aria-label="Turn ${esc(t.name)} left" title="Turn left">${icon('i-rl')}</button><button type="button" class="ui-ib is-dark" data-turn="90" data-name="${esc(t.name)}" aria-label="Turn ${esc(t.name)} right" title="Turn right">${icon('i-rr')}</button></span>
      <p><b title="${esc(t.name)}">${esc(t.name.replace(/\.[^.]+$/,''))}</b>${mmss(t.probe.duration)} · ${SHAPE_SHORT[shapeOf(t)]}</p></div>`).join('')
      + `<button type="button" class="ft-add" id="drop">${icon('i-upload')}<b>${takes.length ? 'Drop more clips' : 'Drop clips'}</b>or click to choose</button>`);
    $('#folder-row').hidden = !PJ.folder_name;
    $('#folder-name').textContent = PJ.folder_where || '';
    const shapes = new Set(takes.map(shapeOf).filter(x=>x!=='square'));
    $('#mix-tip').hidden = shapes.size < 2;
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
  const RELISTEN = {fresh:'Your footage changed. Listening again to the new clips.', new:'Clip added. Listening to it now. Your story stays.', hearing:'Clip added. It is heard with the rest.'};
  function afterAdd(r){
    if(r.errors && r.errors.length) toast(r.errors.join('. '));
    else if(r.relisten && RELISTEN[r.relisten]) toast(RELISTEN[r.relisten]);
    else if(r.added && r.added.length) toast(`${r.added.length} clip${r.added.length>1?'s':''} added.`);
    refreshProject().then(refreshState);
  }
  $('#path-add').addEventListener('click', async ()=>{
    const v = $('#path-in').value.trim().replace(/^['"]|['"]$/g,''); if(!v) return;
    try { const r = await api(`/api/project/${pid}/add`, {paths:[v]}); $('#path-in').value=''; afterAdd(r); } catch(e){ toast(e.message); }
  });
  $('#path-in').addEventListener('keydown', e=>{ if(e.key==='Enter') $('#path-add').click(); });
  /* two drop targets: the add tile beside the clips, and the empty video in the middle */
  [['#takes', '.ft-add'], ['#st-drop', null]].forEach(([box, inner])=>{
    const el = $(box), target = e => inner ? e.target.closest(inner) : el;
    el.addEventListener('dragover', e=>{ e.preventDefault(); const t = target(e) || (inner && el.querySelector(inner)); if(t) t.classList.add('is-over'); });
    el.addEventListener('dragleave', ()=>$$('.is-over').forEach(x=>x.classList.remove('is-over')));
    el.addEventListener('drop', e=>{ e.preventDefault(); e.stopPropagation(); $$('.is-over').forEach(x=>x.classList.remove('is-over')); addDropped(Array.from(e.dataTransfer.files||[])); });
  });
  $('#st-drop').addEventListener('click', addPicked);
  document.addEventListener('dragover', e=>e.preventDefault());
  document.addEventListener('drop', e=>e.preventDefault());
  $('#takes').addEventListener('click', async e=>{
    if(e.target.closest('#drop')){ addPicked(); return; }
    const rm=e.target.closest('[data-rm]'), tb=e.target.closest('[data-turn]'), clip=e.target.closest('[data-take]');
    if(rm){ const r = await api(`/api/project/${pid}/remove_take`, {name:rm.dataset.rm}); if(r.relisten==='fresh') toast(RELISTEN.fresh); else if(r.dropped) toast(`${r.dropped} part${r.dropped>1?'s':''} from that clip left your story. The rest is kept.`); board = null; if(selTake===rm.dataset.rm) selTake=''; refreshProject(); return; }
    if(tb){
      tb.disabled = true;
      try { const r = await api(`/api/project/${pid}/turn`, {name:tb.dataset.name, by:+tb.dataset.turn}); const t = PJ.takes.find(x=>x.name===r.name); if(t){ t.turn = r.turn; t.turned_at = Date.now(); t.has_proxy = false; } selTake = r.name; renderFiles(); updateFitQuestion(); markDirty(); renderStage(); } catch(err){ toast(err.message); }
      tb.disabled = false; refreshProject(); return;
    }
    if(clip){ selTake = clip.dataset.take; pauseAll(); renderFiles(); renderStage(); }
  });
  $('#takes').addEventListener('keydown', e=>{ const c=e.target.closest('[data-take]'); if(c && (e.key==='Enter') && e.target===c){ selTake=c.dataset.take; renderFiles(); renderStage(); } });

  /* ---------- settings form <-> project ---------- */
  const LENS = {ig:[['short','Under 1 min'],['mid','Under 3 min']], yt:[['short','Under 3 min'],['mid','3 to 8 min'],['long','Any length']], other:[['auto','Any length']]};
  const FMT = {ig:'9:16', yt:'16:9', other:'source'};
  const READY = {ig:'Ready for Instagram', yt:'Ready for YouTube', other:'Ready to post'};
  const SHAPE_WORD = {'9:16':'Full screen', '4:5':'Feed post', '1:1':'Square', '16:9':'Wide', source:'Same as filmed'};
  const TITLE_FOR = {soft:'soft', clean:'clean', glow:'soft'};
  const LANG = {en:'English', es:'Spanish', fr:'French', de:'German', yue:'Cantonese', zh:'Mandarin'};
  function renderLens(){
    const p = val('purpose')||'ig', cur = PJ ? PJ.settings.length : 'auto';
    const opts = LENS[p];
    setHTML($('#len-seg'), opts.map((l,i)=>`<label class="ui-pick"><input type="radio" name="len" value="${l[0]}" ${(l[0]===cur || (!opts.some(o=>o[0]===cur) && i===opts.length-1))?'checked':''}><span>${l[1]}</span></label>`).join(''));
  }
  /* what we worked out, as chips. A click opens the choice behind it */
  function renderGuess(){
    if(!PJ) return;
    const lang = $('#lang').value, w = prefs().words||[];
    const chips = [['shape', `Shape: ${SHAPE_WORD[val('format')]||'Full screen'}`], ['lang', lang==='auto' ? 'Language: we work it out' : `You speak ${LANG[lang]||lang}`],
      ['names', w.length ? `Names: ${w.slice(0,2).join(', ')}${w.length>2?` +${w.length-2}`:''}` : 'Names: none yet'], ['small', $('#small-file').checked ? 'Small file, under 25 MB' : 'Full quality']];
    setHTML($('#ft-guess'), chips.map(c=>`<button type="button" class="ui-chip-btn" data-guess="${c[0]}" aria-expanded="${!$('#more').hidden}"><i></i>${esc(c[1])}</button>`).join(''));
  }
  $('#ft-guess').addEventListener('click', e=>{
    const b = e.target.closest('[data-guess]'); if(!b) return;
    if(b.dataset.guess==='names'){ go('setup'); $('#words-in').focus(); return; }
    const m = $('#more'), g = b.dataset.guess, again = !m.hidden && m.dataset.g===g;
    m.hidden = again; m.dataset.g = again ? '' : g; renderGuess();
    if(again) return;
    const el = $({shape:'input[name="format"]:checked', lang:'#lang', small:'#small-file'}[g]);
    if(el){ (el.closest('label') || el).scrollIntoView({block:'center', behavior:'smooth'}); el.focus({preventScroll:true}); }
  });
  function fillForm(){
    if(!PJ) return; const s = PJ.settings;
    setRadio('purpose', s.purpose); setRadio('format', s.format); setRadio('fit', s.fit);
    setRadio('filmed', s.mode==='script'?'script':'talk'); setRadio('order', s.mode==='keep'?'keep':'find');
    $('#script-text').value = s.script||''; $('#lang').value = s.language||'auto'; renderWords();
    $('#small-file').checked = !!(s.export && s.export.max_mb);
    setRadio('cap', s.captions.style); setRadio('c-csize', s.captions.size); setRadio('c-cpos', s.captions.position);
    setRadio('c-look', s.captions.look || 'soft'); $('#c-motion').checked = s.captions.motion !== false;
    setRadio('c-zoom', s.captions.zoom || 'punch'); setRadio('title', s.title || 'off');
    $('#c-hi').value = s.captions.pop; $('#c-popon').checked = !!s.captions.pop_on; $('#c-hi-f').hidden = !s.captions.pop_on; $('#c-wpl').value = s.captions.per_line;
    setRadio('breath', s.cut.breath);
    $('#q-filler').checked = s.cut.fillers; $('#q-pause').checked = s.cut.pauses; $('#q-best').checked = s.cut.repeats;
    $('#fn-srt').checked = localStorage.getItem('cpack-srt')==='1';
    renderLens(); syncMode(); updateFitQuestion(); renderGuess();
  }
  function formSettings(){
    const filmed = val('filmed');
    return {purpose: val('purpose'), format: val('format'), fit: val('fit'), language: $('#lang').value,
      mode: filmed==='script' ? 'script' : (val('order')==='keep' ? 'keep' : 'find'), script: $('#script-text').value,
      length: val('len') || 'auto', export: {max_mb: $('#small-file').checked ? 24 : 0},
      captions: {style: val('cap'), look: val('c-look') || 'soft', size: val('c-csize'), position: val('c-cpos'), motion: $('#c-motion').checked, pop: $('#c-hi').value, pop_on: $('#c-popon').checked, per_line: +$('#c-wpl').value, zoom: val('c-zoom') || 'punch'},
      title: val('title') || 'off',
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
  const NOT_SETTINGS = ['shape', 'zh', 'ver'];
  $('#panel').addEventListener('change', e=>{
    const i=e.target; if(NOT_SETTINGS.includes(i.name) || ['fn-srt','sv-pick','chat-in'].includes(i.id) || i.closest('#chat, #ch-dock')) return;
    if(i.id==='lang') renderWords();
    if(i.name==='purpose'){ setRadio('format', FMT[i.value]); renderLens(); updateFitQuestion(); }
    if(i.name==='filmed') syncMode();
    if(i.id==='c-popon') $('#c-hi-f').hidden = !i.checked;
    /* the hook on screen follows the caption look while it still matches the look it had (soft, clean, glow to soft) */
    if(i.name==='c-look' && PJ){ const was = TITLE_FOR[PJ.settings.captions.look||'soft']; if(val('title')===was) setRadio('title', TITLE_FOR[i.value]); }
    if(i.name==='fit') renderFitBg();
    renderGuess();
    /* a Look choice shows on the video straight away, before the server has it */
    if(PJ && i.closest('#p3')){ PJ.settings = Object.assign({}, PJ.settings, formSettings()); renderPreview(); if(raw.paused && (['c-look','c-cpos','cap','c-csize','c-zoom','title'].includes(i.name) || ['c-motion','c-popon'].includes(i.id))) playPart(i.name==='title' || i.name==='c-zoom' ? 0 : selPart); }
    clearTimeout(saveT); saveT = setTimeout(()=>saveSettings(), 150);
    markDirty();
  });
  $('#panel').addEventListener('input', e=>{ if(['script-text','c-wpl','c-hi'].includes(e.target.id)){ if(PJ && e.target.closest('#p3')){ PJ.settings = Object.assign({}, PJ.settings, formSettings()); paintCap(true); } clearTimeout(saveT); saveT=setTimeout(()=>saveSettings(), 500); } });
  $('#panel').addEventListener('change', e=>{ if(e.target.name==='zh') savePrefs({chinese:e.target.value}); });
  $('#fn-srt').addEventListener('change', e=>localStorage.setItem('cpack-srt', e.target.checked?'1':'0'));

  /* the picture background fit: which still is behind the video (the middle of the first clip unless picked) */
  function renderFitBg(){
    if(!PJ) return;
    const on = val('fit')==='image' && !!fitAsked(); $('#fit-bg-row').hidden = !on; if(!on) return;
    const b = PJ.settings.backdrop || {}, t = takeOf(b.take) || PJ.takes[0], at = b.take && b.t >= 0 ? b.t : (t ? t.probe.duration/2 : 0);
    if(t) $('#fit-bg-pic').style.backgroundImage = `url("${stillOf(t.name, at)}")`;
    $('#fit-bg-say').textContent = b.take ? `${t ? t.name.replace(/\.[^.]+$/,'') : b.take} at ${mmss(at)}` : 'the middle of your first clip';
  }
  $('#fit-bg').addEventListener('click', async ()=>{
    const t = curTake(); if(!t) return;
    const at = raw.src && stageMode()==='footage' ? raw.currentTime : t.probe.duration/2;
    await saveSettings({backdrop: {take: t.name, t: Math.round(at*10)/10}}); renderFitBg(); toast(`Background set: ${mmss(at)} into ${t.name.replace(/\.[^.]+$/,'')}.`);
  });

  /* ---------- plan-use heads-up (no money figures; plan limits aren't published as numbers) ---------- */
  function level(k){
    if(k==='story'){ const mins = ((PJ&&PJ.takes)||[]).reduce((a,t)=>a+(t.probe?t.probe.duration:0),0)/60; return mins<5?1:mins<15?2:3; }
    return 2;
  }
  const hu = k => { const lv=level(k); return `<span class="ed-use" title="A rough guide. Anthropic doesn't publish exact plan limits.">${[1,2,3].map(n=>`<i class="${n<=lv?'is-on':''}"></i>`).join('')}${['Light','Medium','Heavy'][lv-1]} use of your Claude plan</span>`; };

  /* ---------- step 1 footer ---------- */
  /* the server starts the work a moment after it answers, so wait until the project says it has begun */
  async function started(ok){ for(let n=0; n<25; n++){ await refreshProject(); if(ok()) return; await new Promise(r=>setTimeout(r,200)); } }
  async function hear(){
    if($('#lang').value==='zh' && !prefs().chinese){   /* Mandarin: Traditional or Simplified, asked once */
      $('#more').hidden = false; $('#zh-ask').scrollIntoView({block:'center'}); toast('Pick Traditional or Simplified characters first.'); return;
    }
    await saveSettings(); clearSince('hearing'); try { await api(`/api/project/${pid}/go`, {}); await started(()=>stageAt()>=1); step(2); } catch(e){ toast(e.message); } }
  const needsEar = () => heard() && (PJ.unheard||[]).length && !PJ.listening_new && PJ.stage!=='hearing' && !hasStory();
  $('#go1').addEventListener('click', ()=>{ if(heard() && !needsEar()) step(2); else hear(); });
  $('#rehear').addEventListener('click', hear);
  function renderClipAsk(){
    const box = $('#clip-ask'), nc = PJ.new_clips||[], back = PJ.offer_back, sv = (PJ.story_versions||[]).find(v=>v.n===back);
    let html = '';
    if(PJ.listening_new) html = `<div class="ui-ask"><p><b>Listening to your new clip.</b> ${esc(PJ.listening_new.label||'')} Your story stays open.</p><span class="ui-spin is-sm"></span></div>`;
    else if(nc.length && hasStory()) html = `<div class="ui-ask"><p><b>You added ${esc(nc.join(', '))}.</b> Your story is still there. Put the new clip in it?</p>
      <div class="ui-row"><button type="button" class="ui-btn is-sm is-navy" id="fit-new">Fit it into my story</button><button type="button" class="ui-btn is-sm" id="fresh">Start fresh</button></div></div>`;
    else if(back && sv) html = `<div class="ui-ask"><p><b>That clip's parts left your story.</b> The rest is kept. Or go back to ${esc(verLabel(sv.n, sv.clips, sv.at))}.</p>
      <div class="ui-row"><button type="button" class="ui-btn is-sm is-navy" id="go-back">Go back</button><button type="button" class="ui-btn is-sm" id="keep-now">Keep it like this</button></div></div>`;
    box.hidden = !html; setHTML(box, html);
  }
  async function clipAct(e){
    const id = e.target.id || (e.target.closest('[data-clip-act]')||{}).dataset?.clipAct;
    try {
      if(id==='fit-new'){ await api(`/api/project/${pid}/fit_new`, {}); toast('Claude Code will fit the new clip in. Your story stays open meanwhile.'); }
      else if(id==='fresh'){ await api(`/api/project/${pid}/fresh`, {}); toast('Listening again. Your old story is kept as a version.'); }
      else if(id==='go-back'){ await api(`/api/project/${pid}/story_version`, {n: PJ.offer_back}); board = null; toast('Your previous story is back.'); }
      else if(id==='keep-now'){ await api(`/api/project/${pid}/dismiss_back`, {}); }
      else return;
    } catch(err){ toast(err.message); }
    refreshProject();
  }
  $('#clip-ask').addEventListener('click', clipAct);
  $('#fit-note').addEventListener('click', e=>{ if(e.target.closest('[data-clip-act]')) clipAct(e); });
  function renderP1(){
    renderClipAsk();
    const has = PJ.takes.length > 0, st = PJ.stage, failed = st==='hearing' && (PJ.errors||[]).length>0, busy = st==='hearing' && !failed;
    const b = $('#go1');
    b.disabled = !has || busy;
    const ear = needsEar(), mins = Math.max(1, Math.round((listenSecs() + 150)/60)), ln = PJ.listening_new;
    setHTML(b, heard() && !ear ? `Next${icon('i-next')}` : busy ? 'Listening' : `Find my story${icon('i-next')}`);
    $('#rehear-row').hidden = !heard();
    setHTML($('#p1-msg'), !has ? 'Add at least one clip to start.'
      : busy && PJ.relisten ? `<b>Your footage changed.</b> Listening again to the new clips, about ${mins} min.`
      : busy ? 'Listening to your clips.'
      : ln ? `<b>Listening to your new clip${(PJ.unheard||[]).length>1?'s':''}.</b> ${esc(ln.label||'')} Your story stays.`
      : ear ? `<b>New clips aren't heard yet.</b> About ${mins} minute${mins>1?'s':''}.`
      : heard() ? 'Your clips are heard.'
      : `<b>About ${mins} minute${mins>1?'s':''}.</b> Nothing leaves your Mac. ${hu('story')}`);
  }

  /* listening time: only the clips not heard yet take time (a 25 minute clip is about a minute and a half) */
  const listenSecs = () => { const un = new Set(PJ.unheard||[]), ts = PJ.takes.filter(t=>!un.size || un.has(t.name)); return 12 + ts.reduce((a,t)=>a+t.probe.duration,0)*0.05; };

  /* ---------- step 2: story, one card per part ---------- */
  const SHAPES = {turn:'a story with a turn', tips:'a tips list', qa:'question and answer', beforeafter:'before and after', rant:'a rant with a point', setback:'a setback', belief:'belief then break', opinion:'against the common view'};
  const SHAPE_SEG = {turn:'Story with a turn', tips:'Tips list', qa:'Question and answer', beforeafter:'Before and after', rant:'Rant with a point', setback:'Setback', belief:'Belief then break', opinion:'Against the common view'};
  let board = null, dirtyBoard = false, boardVer = null, undoStack = [], advI = 0, advShut = false;
  function syncBoard(){
    if(!hasStory()){ board=null; return; }
    if(!board || !dirtyBoard || board._saved !== PJ.storyboard.saved_at){
      board = JSON.parse(JSON.stringify(PJ.storyboard)); board._saved = PJ.storyboard.saved_at; dirtyBoard=false;
      if(board.version !== boardVer){ boardVer = board.version; undoStack = []; advI = 0; advShut = false; selPart = 0; }
    }
  }
  const storyJob = () => (PJ.jobs||[]).find(j=>j.id===PJ.story_job) || (PJ.jobs||[]).filter(j=>j.type==='story').pop();
  let work = null;   /* what the video in the middle says while something is being made */
  function renderStory(){
    const st = PJ.stage, errs = PJ.errors||[], failed = st==='hearing' && errs.length>0;
    const steps = [['Listening','On your Mac'],['Finding the story','Claude Code'],['Ready to check','']];
    let html = ''; work = null;
    if(st==='hearing' && !failed){
      const m = PJ.progress && /(\d+) of (\d+)/.exec(PJ.progress.label||''), re = !!PJ.relisten;
      const detail = (re ? 'Your footage changed. Listening again to the new clips.' : 'Writing down every word you said.') + (m ? ` Clip ${m[1]} of ${m[2]}.` : '');
      html = prog({title: re ? 'Listening again' : 'Listening', detail, steps, at:0, frac: m ? (m[1]-0.5)/m[2] : .3, from: since('hearing', PJ.relisten && PJ.relisten.at), est: Math.round(listenSecs())});
      work = re ? {t:'Your footage changed', s:'Listening again to the new clips.'} : {t:'Listening', s:'Your Mac is writing down every word.'};
    } else if(st==='story_wait'){
      const j = storyJob(), taken = !!(j && j.status==='taken');
      if(!connected() && !taken){ html = prog({title:'Waiting for Claude Code', detail:'Your words are written down. Claude Code finds the story, and it is not open yet.', steps, at:1, waiting:true, ccOff:'Your story is waiting for it.'}); work = {t:'Waiting for Claude Code', s:'Your words are written down.'}; }
      else { html = prog({title:'Finding the story', detail: taken ? 'Claude Code is picking the strongest parts of what you said.' : 'Claude Code is picking it up.', steps, at:1, frac: taken?.4:.1, from: since('story', taken && j.taken), est: taken?150:0, noEst:'starting now'}); work = {t:'Finding your story', s: taken ? 'Picking the best parts.' : 'Claude Code is picking it up.'}; }
    }
    if(st!=='hearing') clearSince('hearing');
    if(st!=='story_wait') clearSince('story');
    setHTML($('#p2-prog'), html); tick();
    $('#p2-err').hidden = !failed;
    if(failed){ setHTML($('#p2-err'), `<b>Listening didn't work.</b>${esc(errs.join(' '))}<div style="margin-top:10px"><button type="button" class="ui-btn is-sm" id="retry-hear">Try again</button></div>`); work = null; }
    const svs = PJ.story_versions||[], cur = hasStory() && PJ.storyboard.version;
    $('#sv-box').hidden = svs.length < 2;
    if(setHTML($('#sv-pick'), svs.slice().reverse().map(v=>`<option value="${v.n}">${esc(verLabel(v.n, v.clips, v.at))}${v.n===cur?', open now':''}</option>`).join('')) || $('#sv-pick').value!=String(cur)) $('#sv-pick').value = cur;
    const fj = (PJ.jobs||[]).find(j=>j.id===PJ.fit_job && j.status!=='done' && j.status!=='failed');
    $('#fit-note').hidden = !fj && !PJ.listening_new && !((PJ.new_clips||[]).length && hasStory());
    if(!fj && PJ.listening_new) setHTML($('#fit-note'), `<div class="ui-ask"><p><b>Your footage changed.</b> Listening to the new clip now. Keep working on this story meanwhile.</p><span class="ui-spin is-sm"></span></div>`);
    else if(!fj && (PJ.new_clips||[]).length && hasStory()) setHTML($('#fit-note'), `<div class="ui-ask"><p><b>You added ${esc(PJ.new_clips.join(', '))}.</b> Put it in your story?</p><div class="ui-row"><button type="button" class="ui-btn is-sm is-navy" data-clip-act="fit-new">Fit it in</button><button type="button" class="ui-btn is-sm" data-clip-act="fresh">Start fresh</button></div></div>`);
    if(fj) setHTML($('#fit-note'), `<div class="ui-ask"><p><b>Fitting your new clip into the story.</b> ${fj.status==='taken' ? 'Claude Code is on it.' : connected() ? 'Claude Code is picking it up.' : 'It waits for Claude Code.'} Keep working meanwhile.</p></div>`);
    syncBoard();
    $('#sb').hidden = !board;
    $('#to-look').disabled = !board;
    $('#p2-h').textContent = board ? 'Is this your story?' : 'Finding your story';
    $('#p2-sub').textContent = board ? 'Drag to reorder. Click a card to watch it.' : failed ? '' : 'It shows up here by itself.';
    if(!board){ setHTML($('#p2-msg'), failed ? '' : 'You can leave this open. It keeps going.'); $('#story-undo').hidden = true; return; }
    $('#story-line').textContent = board.one_line;
    $('#shape-chip').textContent = board.mode==='script' ? 'your script' : (SHAPES[board.shape]||board.shape);
    const alts = board.mode==='script' ? [] : (board.shape_alts||[]);
    $('#shape-try').hidden = !alts.length;
    setHTML($('#shape-alts'), [board.shape].concat(alts).map(k=>`<label class="ui-pick"><input type="radio" name="shape" value="${k}" ${k===board.shape?'checked':''}><span>${SHAPE_SEG[k]||k}</span></label>`).join(''));
    renderAdvice();
    renderBeats();
  }
  /* one suggestion at a time */
  function renderAdvice(){
    const adv = (board.advice||[]).slice();
    if(board.mode==='keep') adv.unshift('You asked to keep your order, so nothing was moved.');
    const box = $('#advice'); box.hidden = !adv.length || advShut;
    if(box.hidden) return;
    advI = advI % adv.length;
    setHTML(box, `${icon('i-bulb')}<span title="Click to read it all">${esc(adv[advI])}</span>${adv.length>1?`<button type="button" class="ui-btn is-sm" data-adv-next>${advI+1} of ${adv.length}</button>`:''}<button type="button" class="ui-ib" data-adv-x aria-label="Hide" title="Hide">${icon('i-x')}</button>`);
  }
  $('#advice').addEventListener('click', e=>{
    if(e.target.closest('[data-adv-next]')){ advI++; $('#advice').classList.remove('is-open'); renderAdvice(); return; }
    if(e.target.closest('[data-adv-x]')){ advShut = true; renderAdvice(); return; }
    $('#advice').classList.toggle('is-open');
  });
  function beatUse(b){ return b.use_alt!=null && b.alts && b.alts[b.use_alt] ? b.alts[b.use_alt] : b; }
  const ready = take => { const t = takeOf(take); return !!(t && t.has_proxy); };
  const keptBeats = () => board ? board.beats.filter(b=>b.keep!==false) : [];
  const stillOf = (take, t) => `/media/${pid}/still/${encodeURIComponent(take)}?t=${Math.max(0,+t||0).toFixed(1)}`;
  const partStill = b => { const u = beatUse(b); return stillOf(u.take, Math.min(u.start + 0.6, (u.start + u.end)/2)); };
  /* a part is named by what is said when the story only gave it a role ("Hook", "Setup") */
  const ROLE = /^(hook|the hook|setup|set up|set-up|context|intro|introduction|turn|the turn|twist|payoff|pay off|point|the point|close|closer|ending|outro|cta|call to act(ion)?|proof|example|story|problem|solution|lesson|tip( \d+)?|part \d+|beat \d+|question|answer|before|after)$/i;
  function partTitle(b, i){
    const l = (b.label||'').trim(); if(l && !ROLE.test(l)) return l;
    const u = beatUse(b), words = String(u.heard||u.line||'').replace(/^(so|and|but|like|um|uh|okay|ok)[, ]+/i,'').split(/\s+/).filter(Boolean);
    return words.slice(0,5).join(' ').replace(/[,.;:!?]+$/,'') || l || `Part ${i+1}`;
  }
  function renderBeats(){
    const kept = keptBeats();
    if(selPart >= kept.length) selPart = Math.max(0, kept.length-1);
    const html = kept.map((b,i)=>{
      const u = beatUse(b), n = (b.alts||[]).length+1, cur = (b.use_alt==null?0:b.use_alt+1)+1, title = partTitle(b,i);
      return `<li class="sb-card${i===0?' is-hook':''}${i===selPart?' is-sel':''}" draggable="true" data-id="${esc(b.id)}" tabindex="0" aria-label="Part ${i+1}${i===0?', your hook':''}: ${esc(title)}. Click to watch.">
        <div class="sb-th" style="background-image:url('${partStill(b)}')"><span class="sb-num">${i+1}</span>
          ${n>1?`<button type="button" class="sb-take" data-swap="${esc(b.id)}" title="You said this ${n===2?'twice':n+' times'}. Click to use the other take.">${icon('i-stack')}${cur} of ${n}</button>`:''}
          <span class="sb-dur">${mmss(u.end-u.start)}</span>${i===0?'<span class="sb-hook">Your hook</span>':''}</div>
        <div class="sb-tx"><b title="${esc(b.label||'')}">${esc(title)}</b><span>${esc(u.heard||u.line||'')}</span></div>
        <button type="button" class="sb-x" data-keep="${esc(b.id)}" title="Leave out" aria-label="Leave out part ${i+1}">${icon('i-x')}</button></li>`;
    }).join('');
    setHTML($('#board'), html);
    const secs = kept.reduce((a,b)=>{const u=beatUse(b);return a+(u.end-u.start);},0);
    const allReady = kept.every(b=>ready(beatUse(b).take));
    setHTML($('#p2-msg'), kept.length ? `<b>${plural(kept.length,'part')} · ${mmss(secs)}</b> · opens with "${esc(partTitle(kept[0],0))}"${allReady?'':'. Play wakes up in a moment.'}` : '<b>Every part is left out.</b> Put one back below.');
    $('#to-look').disabled = !kept.length;
    $('#story-undo').hidden = !undoStack.length;
    /* left out: the parts the buyer took out (click to put back), then what the story left out, and why */
    const mine = board.beats.filter(b=>b.keep===false), theirs = board.left_out||[], show = 8;
    const thumbs = mine.map(b=>`<button type="button" class="sb-out is-back" data-back="${esc(b.id)}" style="background-image:url('${partStill(b)}')" title="Put back: ${esc(partTitle(b,0))}" aria-label="Put back ${esc(partTitle(b,0))}"></button>`)
      .concat(theirs.filter(x=>x.take).map(x=>`<span class="sb-out" style="background-image:url('${stillOf(x.take, (x.start||0)+0.5)}')" title="${esc((x.why||'') + (x.line ? ': "'+x.line.slice(0,90)+'"' : ''))}"></span>`));
    const more = thumbs.length - show + theirs.filter(x=>!x.take).length;
    $('#leftout').hidden = !thumbs.length && !theirs.length;
    setHTML($('#leftout'), `<span><b>Left out</b>${mine.length ? ' · click one to put it back' : ''}</span>${thumbs.slice(0,show).join('')}${more>0?`<span>+${more} more</span>`:''}`);
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
  /* undo: every change to the story can be taken back */
  const snap = () => JSON.stringify(board.beats.map(b=>({id:b.id, keep:b.keep, use_alt:b.use_alt})));
  function remember(){ undoStack.push(snap()); if(undoStack.length>40) undoStack.shift(); }
  $('#story-undo').addEventListener('click', ()=>{
    const s = undoStack.pop(); if(!s || !board) return;
    const was = JSON.parse(s), by = Object.fromEntries(board.beats.map(b=>[b.id,b]));
    board.beats = was.map(x=>Object.assign(by[x.id], {keep:x.keep, use_alt:x.use_alt})).filter(Boolean);
    selPart = 0; renderBeats(); pushBoard(); loadPart(0); renderStage(); toast('Undone.');
  });
  function moveBeat(id, beforeId){
    if(id===beforeId) return;
    remember();
    const b = BB(id); board.beats = board.beats.filter(x=>x.id!==id);
    const at = board.beats.findIndex(x=>x.id===beforeId); board.beats.splice(at<0 ? board.beats.length : at, 0, b);
    const k = keptBeats(); selPart = Math.max(0, k.indexOf(b));
    renderBeats(); pushBoard(); loadPart(selPart); renderStage();
    toast(selPart===0 ? `"${partTitle(b,0)}" is now your hook.` : 'Moved.');
  }
  $('#board').addEventListener('click', e=>{
    const sw=e.target.closest('[data-swap]'), kp=e.target.closest('[data-keep]'), card=e.target.closest('.sb-card');
    if(sw){ e.stopPropagation(); remember(); const b=BB(sw.dataset.swap), n=(b.alts||[]).length; b.use_alt = b.use_alt==null ? 0 : (b.use_alt+1<n ? b.use_alt+1 : null);
      selPart = keptBeats().indexOf(b); renderBeats(); pushBoard(); playPart(selPart); toast(`Using take ${(b.use_alt==null?0:b.use_alt+1)+1} of ${n+1}.`); return; }
    if(kp){ e.stopPropagation(); remember(); const b=BB(kp.dataset.keep); b.keep = false; renderBeats(); pushBoard(); loadPart(selPart); renderStage(); toast('Left out. Click it below to put it back.'); return; }
    if(card){ const i = keptBeats().findIndex(b=>b.id===card.dataset.id); playPart(i); }
  });
  $('#leftout').addEventListener('click', e=>{ const b=e.target.closest('[data-back]'); if(!b) return; remember(); BB(b.dataset.back).keep = true; renderBeats(); pushBoard(); renderStage(); });
  $('#board').addEventListener('keydown', e=>{
    const card = e.target.closest('.sb-card'); if(!card || e.target!==card) return;
    const k = keptBeats(), i = k.findIndex(b=>b.id===card.dataset.id);
    if(e.key==='Enter' || e.key===' '){ e.preventDefault(); playPart(i); return; }
    if(e.altKey && (e.key==='ArrowLeft' || e.key==='ArrowRight')){   /* move a part without a mouse */
      e.preventDefault(); const j = i + (e.key==='ArrowLeft' ? -1 : 2);
      if(j < 0 || j > k.length) return;
      moveBeat(k[i].id, j < k.length ? k[j].id : null);
      const c = $(`#board .sb-card[data-id="${card.dataset.id}"]`); if(c) c.focus();
    }
  });
  let dragId=null;
  $('#board').addEventListener('dragstart', e=>{ const li=e.target.closest('.sb-card'); if(!li) return; pauseAll(); dragId=li.dataset.id; li.classList.add('is-drag'); e.dataTransfer.effectAllowed='move'; });
  $('#board').addEventListener('dragend', ()=>{ dragId=null; $$('.sb-card').forEach(l=>l.classList.remove('is-drag','is-over')); });
  $('#board').addEventListener('dragover', e=>{ const li=e.target.closest('.sb-card'); if(!li||!dragId) return; e.preventDefault(); $$('.sb-card').forEach(l=>l.classList.toggle('is-over', l===li && l.dataset.id!==dragId)); });
  $('#board').addEventListener('drop', e=>{ const li=e.target.closest('.sb-card'); if(!li||!dragId) return; e.preventDefault(); e.stopPropagation(); const id = dragId; dragId = null; moveBeat(id, li.dataset.id); });
  $('#shape-try').addEventListener('click', ()=>{ const a=$('#shape-alts'); a.hidden=!a.hidden; $('#shape-try').setAttribute('aria-expanded', !a.hidden); });
  $('#shape-alts').addEventListener('change', e=>{ if(e.target.name!=='shape') return; board.shape=e.target.value; pushBoard(); renderStory(); toast(`Told as ${SHAPES[board.shape]}. To move the parts for it, ask in the chat.`); });
  $('#to-look').addEventListener('click', async ()=>{ await approveStory(); step(3); });
  $('#p2-err').addEventListener('click', e=>{ if(e.target.closest('#retry-hear')) hear(); });

  /* ---------- the words of every part, with their times, for the line under the video and the live caption ---------- */
  let HW = null, hwKey = '';
  async function syncHeard(){
    const key = hasStory() ? `${pid}:${PJ.storyboard.version}:${PJ.storyboard.saved_at}` : '';
    if(!key || key===hwKey) return; hwKey = key;
    try { const d = await api(`/api/project/${pid}/heard`); if(hwKey===key){ HW = d; renderStage(); } } catch(e){ HW = null; }
  }
  function partWords(b){
    if(!b) return [];
    const list = HW && HW[b.id], i = b.use_alt==null ? 0 : b.use_alt+1;
    if(list && list[i] && list[i].length) return list[i];
    const u = beatUse(b), ws = String(u.heard||u.line||'').split(/\s+/).filter(Boolean), d = Math.max(.2, (u.end-u.start)/Math.max(1,ws.length));
    return ws.map((w,k)=>({w, s:u.start+k*d, e:u.start+(k+1)*d}));   /* no times yet: spread evenly */
  }

  /* ---------- the video in the middle: one place, one size, every step ---------- */
  const raw = $('#st-raw'), cutPlayer = $('#cut-player'), box = $('#st-box');
  let selPart = 0, plan = null;
  function stageMode(){
    if(!PJ) return 'footage';
    if(S.step===1) return 'footage';
    if(S.step===2) return board ? 'story' : 'working';
    if(S.step===3) return 'look';
    return hasCut() ? 'finish' : 'making';
  }
  const player = () => stageMode()==='finish' ? cutPlayer : raw;
  function pauseAll(){ plan && (plan.cont = false); if(!raw.paused) raw.pause(); if(!cutPlayer.paused) cutPlayer.pause(); }
  /* the box keeps the video's own shape and fills what the column has */
  function boxShape(){
    const m = stageMode();
    if(m==='finish'){ const v = shownV(); return v ? [v.width, v.height] : [9,16]; }
    const t = m==='footage' || m==='working' ? curTake() : null;
    if(t) return shownWH(t);
    const fmt = PJ && PJ.settings.format, f = {'9:16':[9,16],'16:9':[16,9],'4:5':[4,5],'1:1':[1,1]}[fmt];
    if(f) return f;
    const k = keptBeats(), tk = k[0] && takeOf(beatUse(k[0]).take) || ((PJ&&PJ.takes)||[])[0];
    return tk ? shownWH(tk) : [9,16];
  }
  function fitStage(){
    const st = $('#stage'); if(!st.offsetWidth) return;
    const [a,b] = boxShape(), W = st.clientWidth - 40, H = Math.max(300, window.innerHeight - 52 - 208);
    let w = Math.min(W, H*a/b), h = w*b/a;
    w = Math.round(w); h = Math.round(h);
    if(box.style.width !== w+'px'){ box.style.width = w+'px'; box.style.height = h+'px'; }
  }
  window.addEventListener('resize', ()=>{ fitStage(); placeTrack(); paintCap(true); });
  function loadPart(i, play){
    const k = keptBeats(); if(!k.length){ plan = null; return; }
    selPart = Math.max(0, Math.min(i, k.length-1));
    const b = k[selPart], u = beatUse(b), src = `/media/${pid}/proxy/${encodeURIComponent(u.take)}`;
    plan = {i:selPart, cont:!!play};
    if(!ready(u.take)){ raw.removeAttribute('src'); raw.poster = partStill(b); raw.load(); if(play) toast('The preview of this clip is still being made. Try again in a minute.'); return; }
    const seek = () => { raw.currentTime = Math.max(0, u.start - 0.05); if(play) raw.play().catch(()=>{}); placeRaw(); };
    if(!raw.src.endsWith(src)){ raw.poster = partStill(b); raw.src = src; raw.addEventListener('loadedmetadata', seek, {once:true}); }
    else seek();
  }
  function playPart(i){ if(i<0) return; loadPart(i, true); renderBeats(); renderStage(); }
  function loadTake(){
    const t = curTake(); if(!t){ raw.removeAttribute('src'); raw.removeAttribute('poster'); return; }
    const src = `/media/${pid}/proxy/${encodeURIComponent(t.name)}`;
    raw.poster = frameSrc(t);
    if(t.has_proxy){ if(!raw.src.endsWith(src)){ raw.src = src; } }
    else if(raw.src){ raw.removeAttribute('src'); raw.load(); }
  }
  raw.addEventListener('timeupdate', ()=>{
    const m = stageMode();
    if((m==='story' || m==='look') && plan){
      const k = keptBeats(), b = k[plan.i]; if(!b) return;
      const u = beatUse(b);
      if(!raw.paused && raw.currentTime >= u.end + 0.1){
        if(plan.cont && plan.i+1 < k.length){ loadPart(plan.i+1, true); if(m==='story') renderBeats(); renderStage(); }
        else { raw.pause(); plan.cont = false; }
      }
    }
    placeRaw();
  });
  let rawRaf = 0;
  function loopRaw(){ cancelAnimationFrame(rawRaf); placeRaw(); if(!raw.paused && !raw.ended) rawRaf = requestAnimationFrame(loopRaw); }
  function syncPP(){ const p = player(), on = !p.paused && !p.ended; setHTML($('#pp'), icon(on?'i-pause':'i-play')); $('#pp').setAttribute('aria-label', on?'Pause':'Play'); $('#st-big').classList.toggle('is-show', !on); }
  ['play','pause','ended'].forEach(ev=>raw.addEventListener(ev, ()=>{ syncPP(); loopRaw(); }));
  ['seeked','loadedmetadata'].forEach(ev=>raw.addEventListener(ev, placeRaw));
  function togglePlay(){
    const m = stageMode();
    if(m==='finish'){ if(cutPlayer.paused || cutPlayer.ended){ cutStop = null; cutPlayer.play().catch(()=>{}); } else cutPlayer.pause(); return; }
    if(!raw.paused){ raw.pause(); if(plan) plan.cont = false; return; }
    if(m==='story' || m==='look'){
      const k = keptBeats(), b = k[selPart]; if(!b) return;
      const u = beatUse(b);
      if(plan && plan.i===selPart && raw.src && raw.currentTime >= u.start - 0.2 && raw.currentTime < u.end){ plan.cont = true; raw.play().catch(()=>{}); }
      else playPart(selPart);
      return;
    }
    if(raw.src) raw.play().catch(()=>{});
    else if(curTake()) toast('The preview of this clip is still being made. Try again in a minute.');
  }
  $('#pp').addEventListener('click', togglePlay);
  raw.addEventListener('click', togglePlay);
  cutPlayer.addEventListener('click', togglePlay);
  document.addEventListener('keydown', e=>{
    if(e.key!==' ' || screenNow!=='editor' || e.target.closest('input, textarea, select, button, summary, a, [contenteditable], .sb-card, .ft-clip')) return;
    e.preventDefault(); togglePlay();
  });
  $('#st-wave').innerHTML = Array.from({length:22},(_, i)=>`<i style="animation-delay:${(i*37%100)/100}s"></i>`).join('');

  /* the head line, the timeline and the line under the video, for the steps that play the clips (not Finish) */
  function renderStage(){
    if(!PJ) return;
    const m = stageMode(), fin = m==='finish';
    raw.hidden = fin; cutPlayer.hidden = !fin;
    if(fin){ if(!raw.paused) raw.pause(); }
    else if(!cutPlayer.paused) cutPlayer.pause();
    const takes = PJ.takes||[], empty = m==='footage' && !takes.length;
    box.classList.toggle('is-empty', empty); $('#st-drop').hidden = !empty; raw.hidden = fin || empty;
    const w = m==='making' ? cutWork() : (m==='working' ? work : null);
    $('#st-work').hidden = !w;
    if(w){ $('#st-work-t').textContent = w.t; $('#st-work-s').textContent = w.s; }
    /* how a sideways take sits in an upright video, as the video will have it (shape.py) */
    const fit = (m==='story' || m==='look') && fitAsked() ? PJ.settings.fit : 'crop';
    raw.classList.toggle('is-fit', fit!=='crop'); raw.classList.toggle('is-inset', fit==='image');
    const bd = PJ.settings.backdrop || {}, bt = takeOf(bd.take) || takes[0];
    box.style.backgroundImage = fit==='image' && bt ? `url("${stillOf(bt.name, bd.take && bd.t >= 0 ? bd.t : bt.probe.duration/2)}")` : '';
    const k = keptBeats(), total = k.reduce((a,b)=>{const u=beatUse(b);return a+(u.end-u.start);},0);
    let l = '', r = '';
    if(m==='footage' || m==='working'){ const t = curTake(); l = t ? `<b>${esc(t.name.replace(/\.[^.]+$/,''))}</b> · as you filmed it` : '<b>Your video</b> · shows up here'; r = t ? (m==='working' ? (PJ.stage==='hearing' ? 'listening' : 'finding the story') : `${mmss(t.probe.duration)} raw`) : ''; }
    else if(m==='story'){ const b = k[selPart]; l = b ? `<b>${selPart+1} · ${esc(partTitle(b, selPart))}</b>${selPart===0?' · your hook':''}` : '<b>Your story</b>'; r = `${mmss(total)} before tidy-up`; }
    else if(m==='look'){ l = '<b>Live preview</b> · your words, your look'; r = `${mmss(total)} before tidy-up`; }
    else if(m==='making'){ l = '<b>Making your video</b>'; r = ''; }
    else { const v = shownV(), last = PJ.versions[PJ.versions.length-1]; l = PJ.versions.length>1 ? `<b>Version ${v.v}</b>${v.v===last.v?' · the newest':''}` : '<b>Your first cut</b>'; r = mmss(v.duration); }
    setHTML($('#st-l'), l); $('#st-r').textContent = r;
    if(m==='footage' || m==='working') loadTake();
    if(m==='making'){ const b = k[0]; raw.removeAttribute('src'); raw.poster = b ? partStill(b) : (takes[0] ? frameSrc(takes[0]) : ''); }
    $('#pp').disabled = empty || m==='making';
    fitStage();
    /* the picture background fit: the whole picture at 92 % of the frame with a thin white line, on the still (shape.py) */
    if(fit==='image'){
      const b = k[selPart], tk = (b && takeOf(beatUse(b).take)) || takes[0], [sw, sh] = tk ? shownWH(tk) : [9,16];
      const W = box.clientWidth, H = box.clientHeight, sc = Math.min(W/sw, H/sh) * 0.92, w = Math.round(sw*sc), h = Math.round(sh*sc);
      Object.assign(raw.style, {left: Math.round((W-w)/2)+'px', top: Math.round((H-h)/2)+'px', width: w+'px', height: h+'px'});
    } else Object.assign(raw.style, {left:'', top:'', width:'', height:''});
    if(fin){ renderTrack(shownV()); return; }
    /* the timeline: the clips on Footage, the parts on Story and Look */
    let segs = '';
    if(m==='footage' || m==='working') segs = takes.length > 1 ? takes.map(t=>`<button type="button" class="tl-seg${curTake()===t?' is-sel':''}" data-take-seg="${esc(t.name)}" style="flex-grow:${Math.max(.5,t.probe.duration).toFixed(1)}" data-tip="${esc(t.name)} · ${mmss(t.probe.duration)}" aria-label="Show ${esc(t.name)}"><i class="tl-fill"></i></button>`).join('')
      : takes.length ? `<button type="button" class="tl-seg" data-take-seg="${esc(takes[0].name)}" aria-label="Jump in the clip"><i class="tl-fill"></i></button>` : '';
    else if(m==='story' || m==='look') segs = k.map((b,i)=>{ const u=beatUse(b); return `<button type="button" class="tl-seg${i===selPart?' is-sel':''}" data-part="${i}" style="flex-grow:${Math.max(.3,u.end-u.start).toFixed(2)}" data-tip="${esc(`${i+1} · ${partTitle(b,i)} · ${mmss(u.end-u.start)}`)}" aria-label="Play part ${i+1}"><i class="tl-fill"></i><span class="tl-num">${i+1}</span></button>`; }).join('');
    else segs = '<span class="tl-seg"><i class="tl-fill"></i></span>';
    setHTML($('#track'), segs);
    $$('#track .tl-seg').forEach((el,i,a)=>{ el.classList.toggle('is-tip-l', i===0); el.classList.toggle('is-tip-r', i===a.length-1 && a.length>1); });
    placeRaw();
    paintCap(true);
  }
  function placeRaw(){
    const m = stageMode(); if(m==='finish' || !PJ) return;
    const t = raw.currentTime || 0, said = $('#said'); if(m==='footage' || m==='working' || m==='making') said._k = '';
    if(m!=='look') raw.style.transform = '';
    if(m==='footage' || m==='working'){
      const tk = curTake(), d = tk ? tk.probe.duration : 0;
      $$('#track .tl-seg').forEach(el=>{ el.querySelector('.tl-fill').style.width = el.dataset.takeSeg===(tk&&tk.name) && raw.src ? (100*Math.min(1,t/Math.max(.1,d))).toFixed(1)+'%' : '0%'; });
      $('#tm').textContent = `${mmss(raw.src?t:0)} / ${mmss(d)}`;
      setHTML($('#tl-now'), '');
      said.classList.remove('is-can');
      setHTML(said, tk ? (m==='working' ? 'Listening to every word. Play it meanwhile.' : 'Play it to check the picture and the sound.') : '');
      return;
    }
    if(m==='making'){ $('#tm').textContent = ''; setHTML($('#tl-now'), ''); setHTML(said, ''); return; }
    const k = keptBeats(), b = k[selPart];
    if(!b){ $('#tm').textContent = '0:00 / 0:00'; setHTML(said, ''); return; }
    const u = beatUse(b), on = plan && plan.i===selPart && raw.src && t >= u.start - 0.3 && t <= u.end + 0.3;
    const inPart = on ? Math.min(u.end-u.start, Math.max(0, t-u.start)) : 0;
    /* punch-in zooms (zoom.py), on Look: the framing changes at each join; push adds a slow push on the hook */
    const z = m==='look' ? (PJ.settings.captions.zoom || 'punch') : 'off';
    const sc = z==='off' ? 1 : selPart===0 ? (z==='push' ? 1 + 0.06*inPart/Math.max(.1,u.end-u.start) : 1) : selPart%2 ? 1.15 : 1;
    raw.style.transform = sc===1 ? '' : `scale(${sc.toFixed(3)})`; raw.style.transformOrigin = '50% 40%';
    $$('#track .tl-seg').forEach((el,i)=>{ el.querySelector('.tl-fill').style.width = i<selPart ? '100%' : i===selPart ? (100*inPart/Math.max(.1,u.end-u.start)).toFixed(1)+'%' : '0%'; el.classList.toggle('is-sel', i===selPart); });
    const before = k.slice(0,selPart).reduce((a,x)=>{const y=beatUse(x);return a+(y.end-y.start);},0), total = before + k.slice(selPart).reduce((a,x)=>{const y=beatUse(x);return a+(y.end-y.start);},0);
    $('#tm').textContent = `${mmss(before+inPart)} / ${mmss(total)}`;
    setHTML($('#tl-now'), `<b>${selPart+1}</b> · ${esc(partTitle(b, selPart))}`);
    const ws = partWords(b); let wi = -1; if(on) ws.forEach((w,i)=>{ if(t >= w.s - 0.02) wi = i; });
    /* the line being said: up to 14 words, broken at a sentence end, like the line under the finished video */
    const lines = []; let cur = [];
    ws.forEach((w,i)=>{ const p = cur[cur.length-1]; if(p && (cur.length>=14 || /[.?!]["')]*$/.test(p.w.w))){ lines.push(cur); cur = []; } cur.push({w, i}); });
    if(cur.length) lines.push(cur);
    const li = Math.max(0, lines.findIndex(l=>l[l.length-1].i >= wi)), line = lines[li] || [];
    said.classList.remove('is-can');
    const key = `${b.id}:${b.use_alt}:${ws.length}:${li}`;
    if(said._k !== key){ said._k = key; said._h = null; setHTML(said, line.map(x=>`<span class="st-w" data-i="${x.i}">${esc(x.w.w)}</span>`).join(' ')); }
    said.querySelectorAll('.st-w').forEach(x=>x.classList.toggle('is-on', +x.dataset.i===wi));
    if(m==='look') paintCap(false);
  }
  $('#track').addEventListener('click', e=>{
    const m = stageMode(); if(m==='finish') return;
    const p = e.target.closest('[data-part]'), tk = e.target.closest('[data-take-seg]');
    if(p){ playPart(+p.dataset.part); return; }
    if(tk){
      if(curTake() && curTake().name!==tk.dataset.takeSeg){ selTake = tk.dataset.takeSeg; renderFiles(); renderStage(); return; }
      const t = curTake(); if(!t || !raw.src) return;
      const r = tk.getBoundingClientRect(); raw.currentTime = t.probe.duration * Math.min(1, Math.max(0, (e.clientX - r.left)/r.width)); placeRaw();
    }
  });

  /* ---------- step 3: look. The caption is drawn live on the video with the buyer's own words ---------- */
  function renderPreview(){
    const c = PJ.settings.captions, none = c.style==='none';
    const k = keptBeats(), hook = k[0], pic = hook ? partStill(hook) : (PJ.takes[0] ? frameSrc(PJ.takes[0]) : '');
    const sample = hook ? capChunks(partWords(hook), 'lines', 2)[0] : null;
    const said = sample ? sample.map(w=>w.w).join(' ') : 'what am I doing with my life?';
    $$('#p3 .lk-ph').forEach(p=>{ p.style.backgroundImage = pic ? `url("${pic}")` : ''; });
    $$('#p3 .lk-txt').forEach(p=>{ if(p.textContent!==said) p.textContent = said; });
    $$('#p3 .lk-mini').forEach(p=>{ p.style.backgroundImage = pic ? `url("${pic}")` : ''; });
    /* the hook on screen, drawn on the hook frame in each style, with the words the title would show */
    const ti = HW && HW._title, tw = ti ? ti.text.split(' ') : said.split(' ').slice(0,5), acc = ti ? ti.accent : tw.length-1;
    const clean = w => esc(w.replace(/[,;:]+$/,''));
    const tHTML = tw.map(clean).join(' '), cHTML = tw.map((w,k)=>k===acc ? `<em>${clean(w)}</em>` : clean(w)).join(' ');
    $$('#p3 .ti-txt').forEach(p=>{ const h = p.classList.contains('ti-clean') ? cHTML : tHTML; if(p.innerHTML!==h) p.innerHTML = h; });
    $('#title-q').classList.toggle('lk-off', !hook);
    ['#look-card','#cap-more','#size-q','#motion-q'].forEach(s=>$(s).classList.toggle('lk-off', none));
    $('#wpl-field').hidden = c.style!=='lines';
    paintCap(true);
  }
  /* captions grouped the way cpack/captions.py chunks() groups them: by count, at a pause, at a sentence end */
  function capChunks(words, style, perLine){
    const cap = {word:1, three:3}[style] || perLine*3, out = []; let cur = [];
    words.forEach(w=>{ const p = cur[cur.length-1]; if(p && (cur.length>=cap || w.s - p.e > 0.45 || /[.?!]["')]*$/.test(p.w))){ out.push(cur); cur = []; } cur.push(w); });
    if(cur.length) out.push(cur);
    return out;
  }
  let titleOn = '';
  function paintTitle(o){
    const el = $('#st-title');
    if(!o){ if(titleOn){ setHTML(el, ''); titleOn = ''; } return; }
    const bw = box.clientWidth || 360, size = {soft:.092, clean:.082, poster:.138}[o.style] * bw;
    const shown = o.style==='poster' ? o.words.filter(w=>w.s <= o.t + 0.02) : o.words;   /* poster: each word as it is said */
    const words = (shown.length ? shown : o.words.slice(0,1)).map((w,k)=>{ const x = esc(w.w.replace(/[,;:]+$/,'')); return o.style==='clean' && k===o.accent ? `<em>${x}</em>` : x; }).join(' ');
    const key = o.style + '|' + words;
    if(key===titleOn) return;
    const fresh = !titleOn.startsWith(o.style + '|'); titleOn = key;
    el._h = null; setHTML(el, `<span class="ti-band"><span class="ti-txt ti-${o.style}${fresh?' is-rise':''}" style="font-size:${Math.round(size)}px">${words}</span></span>`);
  }
  const PV_SPOTS = [['center',.74],['left',.62],['right',.30],['left',.24],['right',.56],['center',.20]];
  const PV_POS = {top:['center',.16], middle:['center',.5], bottom:['center',.74], left:['left',.70], right:['right',.70]};
  let capG = -1;
  function paintCap(force){
    const cap = $('#pv-cap');
    if(!PJ || stageMode()!=='look'){ setHTML(cap, ''); capG = -1; paintTitle(null); return; }
    const c = PJ.settings.captions;
    if(c.style==='none'){ setHTML(cap, ''); capG = -1; return; }
    const k = keptBeats(), b = k[selPart]; if(!b){ setHTML(cap, ''); return; }
    const all = partWords(b), u = beatUse(b); if(!all.length){ setHTML(cap, ''); paintTitle(null); return; }
    let t = raw.currentTime || 0; if(!(plan && plan.i===selPart && raw.src) || t < u.start - 0.3 || t > u.end + 0.3) t = all[0].s;
    /* the hook on screen over the first seconds (titles.py: up 1.5 to 3 s, its words not captioned while it is up) */
    const ti = HW && HW._title, ts = PJ.settings.title;
    const tUp = ts && ts!=='off' && ti && ti.part===b.id && selPart===0 && all[ti.n1-1] ? Math.min(3, Math.max(1.5, all[ti.n1-1].e - all[0].s + 0.45)) : 0;
    paintTitle(tUp && t - all[0].s < tUp ? {style: ts, words: all.slice(ti.n0, ti.n1), accent: ti.accent, t} : null);
    const ws = tUp ? all.filter((w,k)=>k<ti.n0 || k>=ti.n1) : all;
    if(!ws.length){ setHTML(cap, ''); return; }
    const groups = capChunks(ws, c.style, +c.per_line || 4);
    let wi = 0; ws.forEach((w,i)=>{ if(t >= w.s - 0.02) wi = i; });
    let g = 0, n = 0; for(; g<groups.length; g++){ if(wi < n + groups[g].length) break; n += groups[g].length; }
    g = Math.min(g, groups.length-1); const chunk = groups[g], hi = wi - n;
    const per = c.style==='lines' ? (+c.per_line || 4) : 99, lines = [];
    for(let i=0;i<chunk.length;i+=per) lines.push(chunk.slice(i,i+per));
    let q = 0;
    const html = lines.map(l=>l.map(w=>(q++===hi) ? `<b>${esc(w.w)}</b>` : esc(w.w)).join(' ')).join('<br>');
    let spot = PV_POS[c.position] || PV_POS.bottom;
    if(c.position==='moves'){ const ends = groups.slice(0, g).filter(gr=>/[.?!]["')]*$/.test(gr[gr.length-1].w)).length; spot = PV_SPOTS[(ends*2 + 1) % PV_SPOTS.length]; }
    cap.style.top = (spot[1]*100)+'%';
    cap.style.left = spot[0]==='center' ? '11%' : '7%'; cap.style.right = '11%'; cap.style.textAlign = spot[0];
    const bw = box.clientWidth || 360;
    cap.style.fontSize = Math.round(bw * ((c.style==='lines' ? {s:.040,m:.048,l:.058} : {s:.050,m:.064,l:.080})[c.size] || .064)) + 'px';
    const look = c.look || 'soft', motion = c.motion===false ? '' : (look==='clean' ? 'is-pop' : 'is-settle');
    const fresh = g !== capG || force; capG = g;
    const inner = cap.querySelector('.st-cap-in');
    if(inner && !fresh && inner.classList.contains('lk-'+look)) { if(inner.innerHTML!==html) inner.innerHTML = html; }
    else { cap._h = null; setHTML(cap, `<span class="st-cap-in lk-${look}${motion ? ' '+motion : ''}">${html}</span>`); }
    const pop = look==='glow' && /^#(e3991d|e8a13d)$/i.test(c.pop) ? '#faf6ec' : c.pop;
    cap.querySelectorAll('b').forEach(x=>x.style.color = c.pop_on ? pop : '');
  }

  /* ---------- make the video (end of Look) ---------- */
  let dirty = false, wasCutting = false;
  function markDirty(){ if(hasCut() && PJ.stage!=='cutting') dirty = true; }
  const CUT_STEPS = [['plan','Lining up'],['segments','Cutting each part'],['captions','Adding captions'],['final','Joining it up'],['qa','Watching it back']];
  const CUT_SAY = {plan:'Cleaning out what you asked to take out.', segments:'Cutting on the quiet gaps so no word gets clipped.', captions:'Drawing the words on screen.', final:'Putting the parts together and evening out the sound.', qa:'Watching the finished video to check nothing went wrong.'};
  function keptSecs(){ return board ? keptBeats().reduce((a,b)=>{const u=beatUse(b);return a+(u.end-u.start);},0) : 60; }
  const cutEst = () => Math.round(25 + keptSecs()*0.45);
  function cutProg(title){
    const p = PJ.progress || {}, at = Math.max(0, CUT_STEPS.findIndex(o=>o[0]===p.step));
    const m = p.step==='segments' && /(\d+) of (\d+)/.exec(p.label||'');
    return prog({title, detail: CUT_SAY[CUT_STEPS[at][0]] + (m ? ` Part ${m[1]} of ${m[2]}.` : ''), steps: CUT_STEPS.map(o=>[o[1],'']), at, frac: m ? m[1]/m[2] : .3, from: since('cutting'), est: cutEst()});
  }
  function cutWork(){
    const p = PJ.progress || {}, at = Math.max(0, CUT_STEPS.findIndex(o=>o[0]===p.step)), m = p.step==='segments' && /(\d+) of (\d+)/.exec(p.label||'');
    return {t:'Making your video', s: m ? `Cutting part ${m[1]} of ${m[2]}` : CUT_STEPS[at][1]};
  }
  function renderCut(){
    const s = PJ.settings, cutting = PJ.stage==='cutting', failed = PJ.stage==='cut_failed';
    const kept = keptBeats().length;
    const last = hasCut() ? PJ.versions[PJ.versions.length-1] : null, reps = last && last.kept_repeats || 0;
    $('#kept-reps').hidden = !reps;
    if(reps) $('#kept-reps').textContent = `${reps} repeat${reps===1?' was':'s were'} kept last time, because you said ${reps===1?'it':'them'} on purpose.`;
    const fresh = hasCut() && !dirty && !cutting && !failed;
    if(!cutting) clearSince('cutting');
    const b = $('#cut-it'), mins = Math.max(1, Math.ceil(cutEst()/60));
    b.disabled = cutting || !kept;
    setHTML(b, cutting ? 'Making it now' : fresh ? `Back to my video${icon('i-next')}` : failed ? 'Try again' : hasCut() ? `Make version ${PJ.versions.length+1}${icon('i-next')}` : `Make my video${icon('i-next')}`);
    setHTML($('#p3-msg'), cutting ? 'Your Mac is making the video.' : fresh ? 'Your video is made. Change anything to make a new version.' : `<b>About ${mins} minute${mins>1?'s':''}.</b> Free. Your Mac does the cutting.`);
    $('#p3-err').hidden = !failed;
    if(failed) setHTML($('#p3-err'), `<b>The video didn't get made.</b>${esc((PJ.errors||[]).join(' '))} Press Try again.`);
    void s;
  }
  $('#cut-it').addEventListener('click', async ()=>{
    if(hasCut() && !dirty && PJ.stage!=='cut_failed'){ step(4); return; }
    if(board && !PJ.storyboard.approved) await approveStory();
    await saveSettings(); clearSince('cutting');
    const had = PJ.versions.length;
    try {
      await api(`/api/project/${pid}/cut`, {}); dirty=false; wasCutting = true;
      await started(()=>{ wasCutting = true; return PJ.stage==='cutting' || PJ.stage==='cut_failed' || PJ.versions.length>had; });
      if(PJ.stage!=='cut_failed') step(4);   /* the progress, then the video, both on Finish */
    } catch(e){ toast(e.message); }
  });

  /* ---------- step 4: finish. The big player, one timeline under it (the parts, at most 3 spots worth a look as
     dots on the same bar), export, versions. Fixes go through the chat (D24); a caption word is put right on the
     spot, on the Mac, without Claude. ---------- */
  let viewV = null, spots = [], picked = null, capData = null, capKey = '', capLines = [], capLineAt = -1;
  const sentFix = new Set(), askedRecap = new Set();
  const activeJobs = () => (PJ.jobs||[]).filter(j=>(j.type==='change'||j.type==='chat') && j.status!=='done' && j.status!=='failed');
  const shownV = () => PJ.versions.find(x=>x.v===viewV) || PJ.versions[PJ.versions.length-1];
  let cutStop = null, lastFill = '';
  const sectionsOf = v => (v.sections && v.sections.length) ? v.sections : [{label:'', start:0, end:v.duration||cutPlayer.duration||1}];
  /* one numbering from Story to Finish: a piece of the video is "part 3" when it is the story's third part */
  function partNos(v){
    const secs = sectionsOf(v), ids = hasStory() ? PJ.storyboard.beats.filter(b=>b.keep!==false).map(b=>b.id) : [];
    const n = secs.map(s=>ids.indexOf(s.beat)+1);
    return n.every((x,i)=>x>0 && (i===0 || x>n[i-1])) ? n : secs.map((s,i)=>i+1);
  }
  const secTitle = (s, no) => `Part ${no}${s.label ? ' · '+s.label : ''}`;
  /* what changed in this version, as one plain sentence, or nothing (never a bare internal note) */
  function changedLine(note){
    const t = String(note||'').trim().replace(/\s+/g,' ');
    if(t.length < 12 || !/\s/.test(t) || /^(test|engine|check|debug|wip|tmp)\b/i.test(t)) return '';
    return t.charAt(0).toUpperCase() + t.slice(1).replace(/\.$/, '');
  }
  let exporting = false;
  function renderFinish(){
    /* the first video is being made: the progress lives here, and the video appears in its place */
    const first = !hasCut();
    $('#finish').hidden = first; $('#p5-first').hidden = !first;
    $('#p5-h').textContent = first ? 'Making your video' : 'Your video';
    $('#p5-sub').textContent = first ? 'Nothing to press. It shows up here.' : 'Watch it. Export it, or say what to change.';
    if(first){ setHTML($('#p5-first'), making() ? cutProg('Making your video') : ''); tick(); return; }
    const last = PJ.versions[PJ.versions.length-1], v = shownV(), q = v.qa || {};
    const src = `/media/${pid}/video/${v.v}?c=${Math.round(v.captions_at||0)}`;
    if(!cutPlayer.src.endsWith(src)){
      /* same version with new captions: carry on from where they were */
      const same = cutPlayer.dataset.v===`${pid}:${v.v}`, at = same ? cutPlayer.currentTime : 0;
      cutPlayer.src = src; cutPlayer.dataset.v = `${pid}:${v.v}`; cutPlayer.poster = `/media/${pid}/vframe/${v.v}`;
      if(at) cutPlayer.addEventListener('loadedmetadata', ()=>{ cutPlayer.currentTime = at; }, {once:true});
      if(!same){ picked = null; cutStop = null; }
    }
    const r = v.width/v.height, shape = r>1.2 ? 'wide' : r>0.95 ? 'square' : r>0.7 ? 'feed post' : 'full screen', small = PJ.settings.export && PJ.settings.export.max_mb;
    $('#vtag').textContent = v.v===last.v ? READY[PJ.settings.purpose]||'Ready to post' : `Version ${v.v}`;
    $('#stats').textContent = `${mmss(v.duration)} · ${shape} · ${small ? 'small file' : 'full quality'} (${Math.round(v.size_mb)} MB)`;
    $('#fn-ph').style.backgroundImage = `url("/media/${pid}/vframe/${v.v}")`;
    /* versions as small cards: the frame, the number, what changed */
    $('#vers-q').hidden = PJ.versions.length < 2;
    setHTML($('#vchips'), PJ.versions.length>1 ? PJ.versions.map(x=>`<label class="ui-pick" title="${esc(verLabel(x.v, x.takes, x.at))}"><input type="radio" name="ver" value="${x.v}" ${x.v===v.v?'checked':''}><span class="ui-tile"><span class="fn-vph" style="background-image:url('/media/${pid}/vframe/${x.v}')"></span><span><b>${x.v}${x.v===last.v?' · newest':''}</b><br>${esc(changedLine(x.note) || (x.v===1 ? 'First cut' : when(x.at)))}</span></span></label>`).join('') : '');
    /* the checks: small things are fixed by the engine and never listed; what is left (3 at most, only what can
       be heard) is a dot on the bar */
    const items = (q.items||[]).filter(i=>i.show).slice(0,3);
    if(q.shape_ok===false && !items.some(i=>i.kind==='shape')) items.unshift({at:0, kind:'shape', say:'The shape came out different from what you picked', ask:'The video came out the wrong shape. Make it the shape I picked.'});
    spots = items.slice(0,3);
    $('#spot-key').textContent = spots.length ? `${plural(spots.length,'spot')}, marked on the bar` : '';
    /* export stays Export. It used to turn into "Start a new video" in the same spot the moment the file was saved,
       so a second click there opened an empty new video (22 Nov). */
    const ex = (PJ.exports||[]).filter(x=>x.v===v.v).pop(), stale = ex && (v.captions_at||0) > ex.at;
    const fin = $('#final'); fin.hidden = !ex; fin.classList.toggle('is-stale', !!stale);
    if(ex) setHTML(fin, stale ? `${icon('i-warn')}<span><b>Saved before you fixed the captions.</b> Export again to save the new one.</span>`
      : `${icon('i-check')}<span><b>Saved.</b> ${esc(String(ex.path).split('/').pop())}${ex.srt ? ' and its captions file' : ''}</span><button type="button" class="ui-link" data-open-exports>Show in Finder</button><button type="button" class="ui-link" data-new-video>Start a new video</button>`);
    const fp = $('#fin-primary'); fp.disabled = exporting; fp.classList.toggle('is-primary', !ex || stale);
    setHTML(fp, exporting ? 'Saving' : ex ? 'Export again' : 'Export');
    /* a new version on its way: say so here, with the video still playable */
    const job = activeJobs().find(j=>j.type==='change'), cutting = PJ.stage==='cutting', nv = PJ.versions.length+1;
    let html = '';
    if(cutting) html = cutProg(`Making version ${nv}`);
    else if(job){
      const steps = [['Reads your message',''],['Makes the change',''],['Your Mac cuts it',''],['Ready to watch','']];
      const taken = job.status==='taken';
      if(!taken && !connected()) html = prog({title:`Version ${nv} is waiting for Claude Code`, detail:'Your message is saved.', steps, at:0, waiting:true, ccOff:'Your change is waiting for it.'});
      else html = prog({title:`Making version ${nv}`, detail: taken ? 'Claude Code is working out the change you asked for.' : 'Claude Code is picking up your message.', steps, at: taken?1:0, frac:.4, from: since('job', taken ? job.taken : job.created), est: taken?120:0, noEst:'starting now'});
    }
    setHTML($('#p5-prog'), html); tick();
    setHTML($('#p5-msg'), html ? 'Keep watching this version while the new one is made.' : '');
    renderTrack(v); renderPick(); syncCaptions(v);
  }
  $('#vchips').addEventListener('change', e=>{ if(e.target.name==='ver'){ viewV = +e.target.value; renderFinish(); renderStage(); } });

  /* --- the one timeline --- */
  const spotTip = i => `${String(i.say||'').replace(/ at \d+:\d\d$/, '')} · ${mmss(i.at)}`;
  function renderTrack(v){
    if(stageMode()!=='finish') return;
    const secs = sectionsOf(v), n = secs.length, nos = partNos(v);
    const html = secs.map((s,i)=>`<button type="button" class="tl-seg" data-sec="${i}" style="flex-grow:${Math.max(.01,s.end-s.start).toFixed(2)}" data-tip="${esc(`${secTitle(s,nos[i])} · ${mmss(s.start)} to ${mmss(s.end)}`)}" aria-label="${esc(`Play ${secTitle(s,nos[i])}, ${mmss(s.start)} to ${mmss(s.end)}`)}"><i class="tl-fill"></i>${n>1?`<span class="tl-num">${nos[i]}</span>`:''}</button>`).join('')
      + spots.map((i,k)=>`<button type="button" class="tl-spot" data-spot="${k}" data-at="${i.at}" data-tip="${esc(spotTip(i))}" aria-label="${esc('Worth a look: '+i.say)}"></button>`).join('')
      + '<i class="tl-knob" id="knob"></i>';
    setHTML($('#track'), html);
    placeTrack();
  }
  /* a time in the video <-> x on the bar, through the section it falls in (sections have small gaps between them) */
  function xAt(t){
    const secs = sectionsOf(shownV()); let i = secs.findIndex(s=>t < s.end); if(i<0) i = secs.length-1;
    const el = $(`.tl-seg[data-sec="${i}"]`), s = secs[i]; if(!el || !s) return null;
    return el.offsetLeft + el.offsetWidth * Math.min(1, Math.max(0, (t - s.start)/Math.max(.01, s.end - s.start)));
  }
  function tAt(x){
    const secs = sectionsOf(shownV()), els = $$('#track .tl-seg'); if(!els.length) return 0;
    let i = els.findIndex(el=>x <= el.offsetLeft + el.offsetWidth); if(i<0) i = els.length-1;
    const el = els[i], s = secs[i];
    return s.start + (s.end - s.start) * Math.min(1, Math.max(0, (x - el.offsetLeft)/Math.max(1, el.offsetWidth)));
  }
  function placeTrack(){
    if(!hasCut() || stageMode()!=='finish') return;
    const v = shownV(), secs = sectionsOf(v), t = cutPlayer.currentTime || 0, n = secs.length, nos = partNos(v);
    let cur = secs.findIndex(s=>t < s.end); if(cur<0) cur = n-1;
    $$('#track .tl-seg').forEach((el,i)=>{
      const s = secs[i]; if(!s) return;
      el.querySelector('.tl-fill').style.width = (100*Math.min(1, Math.max(0, (t - s.start)/Math.max(.01, s.end - s.start)))).toFixed(1) + '%';
      el.classList.toggle('is-on', i===cur); el.classList.toggle('is-sel', !!picked && picked.kind==='sec' && picked.i===i);
      el.classList.toggle('is-tip-l', i===0); el.classList.toggle('is-tip-r', i===n-1);
    });
    const tw = $('#track').offsetWidth;
    $$('#track .tl-spot').forEach((m,k)=>{ const x = xAt(+m.dataset.at); if(x!=null){ m.style.left = x + 'px'; m.classList.toggle('is-tip-l', x < 110); m.classList.toggle('is-tip-r', x > tw - 110); } m.classList.toggle('is-sel', !!picked && picked.kind==='spot' && picked.k===k); });
    const knob = $('#knob'), x = xAt(t); if(knob && x!=null) knob.style.left = x + 'px';
    const dur = v.duration || cutPlayer.duration || 0;
    $('#tm').textContent = `${mmss(t)} / ${mmss(dur)}`;
    setHTML($('#tl-now'), capBusy() ? `<span class="ui-spin is-sm"></span>Updating your captions, about 20 seconds` : n>1 ? `<b>${nos[cur]}</b> · ${esc(secs[cur].label||'Part '+nos[cur])}` : '');
    placeSaid(t);
  }
  let raf = 0;
  function loopTrack(){ cancelAnimationFrame(raf); placeTrack(); if(!cutPlayer.paused && !cutPlayer.ended) raf = requestAnimationFrame(loopTrack); }
  cutPlayer.addEventListener('timeupdate', ()=>{ if(cutStop!=null && cutPlayer.currentTime >= cutStop){ cutPlayer.pause(); cutStop=null; } placeTrack(); });
  ['play','pause','ended'].forEach(ev=>cutPlayer.addEventListener(ev, ()=>{ syncPP(); loopTrack(); }));
  ['seeked','loadedmetadata'].forEach(ev=>cutPlayer.addEventListener(ev, placeTrack));
  function playSpan(a, b){ cutStop = b; cutPlayer.currentTime = Math.max(0, a); cutPlayer.play().catch(()=>{}); }
  function fillChat(text){ const i=$('#chat-in'); if(!i.value.trim() || i.value===lastFill){ i.value = text; lastFill = text; } i.focus(); i.setSelectionRange(i.value.length, i.value.length); }
  const track = $('#track'); let drag = null, scrubbed = false;
  /* drag along the bar to scrub; a plain click picks the part or the spot */
  track.addEventListener('pointerdown', e=>{ if(stageMode()!=='finish' || e.button || e.target.closest('.tl-spot')) return; drag = {x:e.clientX, id:e.pointerId}; scrubbed = false; });
  track.addEventListener('pointermove', e=>{
    if(!drag || (!scrubbed && Math.abs(e.clientX - drag.x) < 5)) return;
    if(!scrubbed){ scrubbed = true; cutStop = null; try { track.setPointerCapture(drag.id); } catch(_){} }
    cutPlayer.currentTime = tAt(e.clientX - track.getBoundingClientRect().left); placeTrack();
  });
  ['pointerup','pointercancel'].forEach(ev=>track.addEventListener(ev, ()=>{ drag = null; }));
  track.addEventListener('click', e=>{
    if(stageMode()!=='finish') return;
    if(scrubbed){ scrubbed = false; return; }
    const sp = e.target.closest('[data-spot]'), sec = e.target.closest('[data-sec]');
    if(sp){ const k = +sp.dataset.spot, i = spots[k]; if(!i) return; picked = {kind:'spot', k}; playSpan(i.at-2, i.at+1.5); }
    else if(sec){ const i = +sec.dataset.sec, s = sectionsOf(shownV())[i]; picked = {kind:'sec', i}; playSpan(s.start, s.end); }
    else return;
    renderPick(); placeTrack();
  });
  /* "Worth a look": what is selected, Hear it and Fix it; when nothing is, a calm line */
  function renderPick(){
    const v = shownV(), secs = sectionsOf(v), nos = partNos(v), box2 = $('#pick'), q = v.qa || {}; let html = '';
    if(picked && picked.kind==='spot' && spots[picked.k]){
      const i = spots[picked.k], sent = sentFix.has(`${v.v}:${i.at}:${i.kind}`);
      html = `<span><b>${esc(String(i.say||'').replace(/ at \d+:\d\d$/, ''))}</b> · ${mmss(i.at)}<small>${sent ? 'Sent to the chat. Claude Code fixes it in a new version.' : i.kind==='missing' ? 'Fix it moves the cut so the whole word is heard.' : 'Worth a look.'}</small></span>
        <button type="button" class="ui-btn is-sm" data-hear-spot="${picked.k}">${icon('i-play')}Hear it</button><button type="button" class="ui-btn is-sm is-navy" data-fix-spot="${picked.k}" ${sent?'disabled':''}>${sent?'Sent':'Fix it'}</button>`;
    } else if(picked && picked.kind==='sec' && secs[picked.i]){
      const s = secs[picked.i];
      html = `<span><b>${esc(secTitle(s, nos[picked.i]))}</b><small>${mmss(s.start)} to ${mmss(s.end)}. Say what to change.</small></span><button type="button" class="ui-btn is-sm is-navy" data-fix-sec="${picked.i}">Fix it</button>`;
    } else {
      picked = null;
      const fixed = q.self_repairs||0, fx = Object.keys(PJ.fixes||{}).length;
      const good = [fixed ? `${fixed} fix${fixed===1?'':'es'} made for you` : '', fx ? `${plural(fx,'caption word')} put right` : ''].filter(Boolean).join(' · ');
      html = spots.length ? `<span><span class="fn-dot"></span>Click a dot under the video to hear it.${good?`<small>${esc(good)}</small>`:''}</span>`
        : `<span class="fn-good">${esc(good ? 'Checked. ' + good + '.' : 'Checked. Nothing needs a look.')}</span>`;
    }
    if(picked) html += `<button type="button" class="ui-ib" data-pick-x aria-label="Close" title="Close">${icon('i-x')}</button>`;
    box2.classList.toggle('is-calm', !picked);
    setHTML(box2, html);
  }
  $('#pick').addEventListener('click', e=>{
    const sp = e.target.closest('[data-fix-spot]'), sc = e.target.closest('[data-fix-sec]'), hs = e.target.closest('[data-hear-spot]'), v = shownV();
    if(e.target.closest('[data-pick-x]')){ picked = null; renderPick(); placeTrack(); return; }
    if(hs){ const i = spots[+hs.dataset.hearSpot]; if(i) playSpan(i.at-2, i.at+1.5); return; }
    if(sp){ const i = spots[+sp.dataset.fixSpot]; if(!i) return; sentFix.add(`${v.v}:${i.at}:${i.kind}`); renderPick(); sendChat({text:i.ask, kind:'change'}); chat(true, true); toast('Sent to the chat. Claude Code will fix it in a new version.'); }
    if(sc){ const i = +sc.dataset.fixSec, s = sectionsOf(v)[i]; lastFill = $('#chat-in').value; fillChat(`In part ${partNos(v)[i]} (${mmss(s.start)} to ${mmss(s.end)}), `); }
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
    if(stageMode()!=='finish') return;
    const el = $('#said'); if(!capLines.length){ setHTML(el, ''); return; }
    let li = 0; capLines.forEach((l,i)=>{ if(t >= l[0].s - 0.02) li = i; });   /* the line being said, or the last one said */
    const fixed = new Set(Object.values(PJ.fixes||{}).map(x=>x.toLowerCase()));
    if(li !== capLineAt || el._k !== capKey){
      capLineAt = li; el._k = capKey; el.classList.toggle('is-can', !!capData.on);
      el._h = null;
      setHTML(el, capLines[li].map(w=>`<button type="button" class="st-w${fixed.has(w.w.replace(/^[^\w]+|[^\w']+$/g,'').toLowerCase())?' is-fx':''}" data-k="${w.k}" ${capData.on?`title="Wrong word? Click to fix it."`:'tabindex="-1"'}>${esc(w.w)}</button>`).join(' '));
    }
    const line = capLines[li]; let on = -1;
    line.forEach((w,i)=>{ if(t >= w.s - 0.02) on = i; });
    el.querySelectorAll('.st-w').forEach((b,i)=>b.classList.toggle('is-on', i===on && t <= line[line.length-1].e + 0.4));
  }
  const wf = $('#wordfix'); let wfWord = null;
  function closeFix(){ wf.hidden = true; wfWord = null; }
  $('#said').addEventListener('click', e=>{
    if(stageMode()!=='finish') return;
    const b = e.target.closest('.st-w'); if(!b || !capData || !capData.on) return;
    const w = capData.words[+b.dataset.k]; if(!w) return;
    const core = w.w.replace(/^[^\w㐀-鿿]+|[^\w'㐀-鿿]+$/g, ''); if(!core) return;
    if(PJ.stage==='cutting' || PJ.recaption){ toast('One moment, your Mac is still drawing the video.'); return; }
    cutPlayer.pause(); wfWord = core;
    const n = capData.words.filter(x=>x.w.replace(/^[^\w㐀-鿿]+|[^\w'㐀-鿿]+$/g, '').toLowerCase()===core.toLowerCase()).length;
    $('#wf-lab').textContent = `Fix "${core}" everywhere`;
    $('#wf-hint').textContent = `${n>1 ? `All ${n} times` : 'Everywhere'} in this video. Free, about 20 seconds. A name also goes on your names list.`;
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
  document.addEventListener('mousedown', e=>{ if(!wf.hidden && !e.target.closest('#wordfix, #said .st-w')) closeFix(); });
  window.addEventListener('scroll', ()=>{ if(!wf.hidden) closeFix(); }, true);

  /* export saves a copy (and the captions file when ticked) and nothing else: same step, same video, same place */
  async function doExport(){
    if(exporting) return; exporting = true; renderFinish();
    const srt = $('#fn-srt').checked;
    try { await api(`/api/project/${pid}/export`, {v: shownV().v, reveal: false, srt}); toast(srt ? 'Saved to Exports, with the captions file.' : 'Saved to Exports.'); await refreshProject(); }
    catch(e){ toast(e.message); }
    exporting = false; renderFinish();
  }
  $('#fin-primary').addEventListener('click', doExport);
  $('#final').addEventListener('click', e=>{ if(e.target.closest('[data-open-exports]')) openFolder('Exports'); if(e.target.closest('[data-new-video]')) newVideo(); });

  /* ---------- chat: one line under the tools, opens over the tools, answered by the buyer's own Claude Code ---------- */
  let pendingAsk = null, sending = [];
  function chat(open, flash){
    const th = $('#chat'); th.hidden = !open; $('#ch-open').setAttribute('aria-expanded', !!open);
    if(open){ th.style.bottom = $('#ch-dock').offsetHeight + 'px'; $('#msgs').scrollTop = 1e6; if(flash){ th.classList.remove('is-flash'); void th.offsetWidth; th.classList.add('is-flash'); } }
  }
  $('#ch-open').addEventListener('click', ()=>chat($('#chat').hidden));
  $('#ch-close').addEventListener('click', ()=>chat(false));
  document.addEventListener('keydown', e=>{ if(e.key==='Escape' && !$('#chat').hidden && wf.hidden && studio.hidden && vlist.hidden) chat(false); });
  function jobLine(j){
    const taken = j.status==='taken';
    if(taken && PJ.stage==='cutting') return ['Your Mac is cutting the new version', (PJ.progress && PJ.progress.label) || '', 1];
    if(taken) return ['Working on it', j.type==='change' ? 'Claude Code is making the change.' : 'Claude Code is writing an answer.', 1];
    if(connected()) return ['Working on it', 'Claude Code is picking up your message.', 1];
    return ['Waiting for Claude Code', CC_HELP + '. Your message is saved.', 0];
  }
  function examples(){
    if(S.step===2 && board){ const n = keptBeats().length; return [n>=3 ? 'Open with part 3' : 'Open with part 2', 'Make it shorter', 'Tell it another way']; }
    if(S.step===3) return ['Make the words bigger', 'Only caption the hook'];
    if(S.step===4 && hasCut()){ const v = shownV(), secs = v.sections || [], n = secs.length, nos = partNos(v);
      return [n>1 ? `The cut at ${mmss(secs[1].start)} is choppy` : 'The start is choppy', n>3 ? `Drop part ${nos[3]}` : 'Make it shorter', 'More pause after each sentence']; }
    return [];
  }
  function renderChat(){
    if(!PJ) return;
    const on = connected(), act = activeJobs(), ob = $('#ch-open');
    ob.classList.toggle('is-off', !on); ob.title = on ? 'Claude is listening' : "Claude isn't listening";
    $('#chat-off').hidden = on || act.some(j=>j.status==='taken');
    setHTML($('#chips'), examples().map(c=>`<button type="button">${esc(c)}</button>`).join(''));
    $('#chat-in').placeholder = hasCut() || board ? 'Say what to change' : 'Ask anything about this video';
    const events = (PJ.chat||[]).map(m=>({at:m.at, html:`<li class="ch-m ${m.who==='you'?'is-me':'is-cl'}"><span class="ch-who">${m.who==='you'?'You':'Claude'}</span>${esc(m.text)}</li>`}))
      .concat((PJ.versions||[]).map(v=>({at:v.at, html:`<li class="ch-m is-ev">${v.v===1?'Your video is ready':`Version ${v.v} is ready`}<button type="button" class="ui-btn is-sm" data-watch="${v.v}">Watch it</button></li>`})))
      .sort((a,b)=>a.at-b.at).map(x=>x.html);
    if(!events.length && !pendingAsk && !sending.length) events.push(`<li class="ch-m is-cl"><span class="ch-who">Claude</span>Ask me anything about this video, or say what to change in plain words. Your video stays in view.</li>`);
    const texts = new Set((PJ.chat||[]).map(m=>m.text));
    sending = sending.filter(t=>!texts.has(t));
    sending.forEach(t=>events.push(`<li class="ch-m is-me"><span class="ch-who">You</span>${esc(t)}</li>`));
    act.forEach(j=>{ const l = jobLine(j); events.push(`<li class="ch-m is-cl is-work"><span class="ui-spin is-sm${l[2]?'':' is-wait'}"></span><span><b>${l[0]}${l[2]?'…':''}</b><small>${esc(l[1])}</small><small><span data-from="${Math.round(j.created*1000)}">0:00</span> so far${!l[2]?'':j.type==='change'?', usually 2 to 4 minutes':', usually under a minute'}</small></span></li>`); });
    const lastJob = (PJ.jobs||[]).filter(j=>j.type!=='story').pop();
    if(lastJob && lastJob.status==='failed' && !lastJob.reply) events.push(`<li class="ch-m is-cl"><span class="ch-who">Claude</span>That one didn't work. Try saying it another way.</li>`);
    /* two tries through the chat and still asking: point at finishing by hand, shown greyed until that ships */
    if((PJ.jobs||[]).filter(j=>j.type==='change' && (j.status==='done'||j.status==='failed')).length >= 2 && !act.length)
      events.push(`<li class="ch-m is-offer">Still not right after two tries? Small fixes like a trim are quicker by hand.<button type="button" class="ui-btn is-sm" disabled>Finish it in Edits <span class="ui-soon">Coming next</span></button></li>`);
    if(pendingAsk) events.push(`<li class="ch-m is-me is-draft"><span class="ch-who">You, not sent yet</span>${esc(pendingAsk.text)}</li>
      <li class="ch-confirm"><b>Happy with the instructions?</b>${hu('change')}<span class="ui-row"><button type="button" class="ui-btn is-primary" data-chat-go>Go</button><button type="button" class="ui-btn" data-chat-no>Edit it</button></span></li>`);
    if(setHTML($('#msgs'), events.join(''))){ $('#msgs').scrollTop = $('#msgs').scrollHeight; tick(); }
  }
  async function sendChat(a){
    sending.push(a.text); renderChat();
    try { await api(`/api/project/${pid}/${a.kind}`, {text:a.text, part:null}); clearSince('job'); await refreshProject(); }
    catch(err){ sending = sending.filter(t=>t!==a.text); $('#chat-in').value = a.text; renderChat(); toast(err.message); }
  }
  $('#chat-form').addEventListener('submit', e=>{
    e.preventDefault(); const i=$('#chat-in'), t=i.value.trim(); if(!t) return;
    i.value=''; chat(true);
    if(pendingAsk){ pendingAsk.text += '\n' + t; renderChat(); $('[data-chat-go]').focus(); return; }
    /* a question is light, so it goes straight away; a change to a finished cut makes a new version, so it asks once */
    if(!hasCut()){ sendChat({text:t, kind:'chat'}); return; }
    pendingAsk = {text:t, kind:'change'}; renderChat(); $('[data-chat-go]').focus();
  });
  $('#chips').addEventListener('click', e=>{ const b=e.target.closest('button'); if(!b) return; lastFill = $('#chat-in').value; fillChat(b.textContent); });
  $('#msgs').addEventListener('click', e=>{
    const w = e.target.closest('[data-watch]');
    if(w){ viewV = +w.dataset.watch; chat(false); step(4); cutPlayer.play().catch(()=>{}); return; }
    if(e.target.closest('[data-chat-no]')){ $('#chat-in').value = pendingAsk.text; pendingAsk=null; renderChat(); $('#chat-in').focus(); return; }
    if(!e.target.closest('[data-chat-go]') || !pendingAsk) return;
    const a = pendingAsk; pendingAsk = null; sendChat(a); if(S.step!==4) step(4, true);
  });

  /* ---------- render + poll ---------- */
  function renderAll(){
    if(!PJ) return;
    renderFiles(); renderFitBg(); renderStepper(); renderP1(); renderStory(); renderPreview(); renderCut(); renderFinish(); renderChat(); renderProjects(); updateFitQuestion(); renderGuess(); renderStage(); syncPP();
    syncHeard();
  }
  async function refreshState(){ try { ST = await api('/api/state'); renderSetup(); if(screenNow==='setup') renderSetupPics(); if(PJ) renderAll(); } catch(e){} }
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
      if(!hadStory && hasStory() && S.step===2){ toast('Your story is ready to check.'); loadPart(0); renderStage(); }
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
  const where = pur==='ig' ? 'Instagram is upright' : pur==='yt' ? 'YouTube is wide' : (k==='sideways' ? 'Your video is full screen' : 'Your video is wide');
  const legend = k==='sideways' ? `You filmed ${it} sideways. ${where}. How should it fit?` : `You filmed ${it} upright. ${where}. How should it fit?`;
  const set = (id, t) => { const el = document.getElementById(id); if(el && el.textContent!==t) el.textContent = t; };
  set('fit-legend', legend); set('fit-legend-sr', legend);
  set('fit-pad-say', k==='sideways' ? 'Nothing cut off. A soft blur above and below.' : 'Nothing cut off. A soft blur at the sides.');
  set('fit-crop-say', k==='sideways' ? 'Fills the screen, follows your face. The sides get cut.' : 'Fills the screen, follows your face. Top and bottom get cut.');
  const t = PJ.takes.find(f => { const w = (f.turn||0)%180 ? [f.probe.shown_h, f.probe.shown_w] : [f.probe.shown_w, f.probe.shown_h]; return k==='sideways' ? w[0]>w[1] : w[1]>w[0]; });
  document.querySelectorAll('#fit-q .ft-fitpic').forEach(p => p.classList.toggle('is-wide', k==='upright'));
  if(t){ const src = `/media/${PJ.id}/frame/${encodeURIComponent(t.name)}?t=${t.turn||0}-${t.added||0}-${t.turned_at||0}`;
    document.querySelectorAll('#fit-q .ft-fitpic, #fit-q .ft-fitpic i').forEach(p => { p.style.backgroundImage = `url("${src}")`; }); }
}
document.addEventListener('change', e => { if(e.target && (e.target.name === 'format' || e.target.name === 'purpose')) updateFitQuestion(); });
