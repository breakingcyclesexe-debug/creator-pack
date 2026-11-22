"""The steps of one video, shared by the page's server and the session's commands.

  add_takes     probe, first frame, then sound frames + a preview copy in the background
  hear          transcribe every take (fast path), then hand the story to the session as a job
  save_story    the session's storyboard, checked against the transcript (only the speaker's words)
  edit_story    the buyer's reorders, drops, take swaps, approval
  cut           render a new version, then QA it
  export        copy the chosen version to the Exports folder and show it in Finder
"""
import json, os, re, shutil, threading, time, traceback
from . import project as prj, media, transcribe, storyboard, render, qa, jobs, cutrules, captions
from .platform import get as platform

P = platform()
_busy = {}


def _progress(pid, step, frac, label):
    prj.update(pid, lambda pj: pj.update(progress={'step': step, 'pct': round(100 * frac), 'label': label, 'at': time.time()}))


def cache(pid, *parts):
    return os.path.join(prj.folder(pid), 'cache', *parts)


def energy_of(pid, pj):
    def get(take):
        return media.energy(prj.take_path(pj, take), cache(pid, f'energy-{take}.npy'))
    return get


def add_takes(pid, paths):
    added, errors = [], []
    for p in paths:
        p = os.path.abspath(os.path.expanduser(p))
        if not os.path.isfile(p): errors.append(f'not found: {os.path.basename(p)}'); continue
        try: pr = media.probe(p)
        except ValueError as e: errors.append(str(e)); continue
        if not pr['has_audio']: errors.append(f'{os.path.basename(p)} has no sound'); continue
        tmp = cache(pid, f'frame-new-{os.getpid()}-{threading.get_ident()}.jpg')   # the picture exists before the page sees the clip
        media.frame(p, min(1.0, pr['duration'] / 2), tmp, 0, probe=pr)
        with prj.locked(pid):
            pj = prj.load(pid)
            name = prj.take_name(pj, p)
            if os.path.exists(tmp): os.replace(tmp, cache(pid, f'frame-{name}.jpg'))
            pj['takes'].append({'name': name, 'path': p, 'probe': pr, 'added': time.time(), 'turn': 0})
            if len(pj['takes']) == 1:
                pj['name'] = os.path.splitext(name)[0]
                if not pj.get('folder_named', True):   # "My video (22 Nov)" becomes "IMG_0265 (22 Nov)"
                    try:
                        prj.rename_folder(pj, f"{pj['name']} ({time.strftime('%-d %b', time.localtime(pj.get('created') or time.time()))})")
                        p = next(t['path'] for t in pj['takes'] if t['name'] == name)
                    except OSError: pass
                    pj['folder_named'] = True
            if has_story(pid): pj.setdefault('new_clips', []).append(name)   # the story stays; the page asks fit or fresh
            else: pj['stage'] = 'footage'
            prj.save(pj)
        pj = prj.load(pid); p = next((t['path'] for t in pj['takes'] if t['name'] == name), p)
        added.append(name)
        threading.Thread(target=_prep, args=(pid, name, p), daemon=True).start()
    return added, errors


def scan(pid):
    """Files the buyer put straight into the project's Footage folder in Finder are picked up (on page focus and
    with "I added files"). Returns {"added", "errors", "references"}."""
    pj = prj.load(pid); had = pj.get('folder')
    foot = prj.sub(pj, 'Footage')
    if not had: prj.update(pid, lambda x: x.update(folder=pj['folder']))
    have = {os.path.realpath(t['path']) for t in pj['takes']}
    gone = set(pj.get('removed_paths', []))
    new = [os.path.join(foot, f) for f in sorted(prj.user_files(foot))
           if os.path.splitext(f)[1].lower() in prj.VIDEO_EXT and os.path.realpath(os.path.join(foot, f)) not in have | gone]
    added, errors = add_takes(pid, new) if new else ([], [])
    refs = prj.sub(prj.load(pid), 'References')   # the folder may have just been named after the first clip
    return {'added': added, 'errors': errors, 'references': sorted(prj.user_files(refs))}


def _prep(pid, name, path):
    try:
        media.energy(path, cache(pid, f'energy-{name}.npy'))
        pj = prj.load(pid)
        t = next((t for t in pj['takes'] if t['name'] == name), {})
        media.proxy(path, cache(pid, f'proxy-{name}.mp4'), prj.take_turn(pj, name), probe=t.get('probe'))
    except Exception:  # a missing preview only means beats can't be played in the browser
        traceback.print_exc()


def refresh_frames(pid, only=None):
    pj = prj.load(pid)
    for t in pj['takes']:
        if only and t['name'] != only: continue
        media.frame(t['path'], min(1.0, t['probe']['duration'] / 2), cache(pid, f'frame-{t["name"]}.jpg'), t.get('turn', 0), probe=t['probe'])


def turn_take(pid, name, by=None, to=None):
    """Turn one clip: its frame now, its preview copy in the background (the old one is wrong until then)."""
    pj = prj.load(pid)
    cur = prj.take_turn(pj, name)
    deg = prj.set_turn(pid, name, (cur + int(by)) % 360 if by is not None else to)
    refresh_frames(pid, name)
    t = next(t for t in prj.load(pid)['takes'] if t['name'] == name)
    try: os.remove(cache(pid, f'proxy-{name}.mp4'))
    except OSError: pass
    threading.Thread(target=_prep, args=(pid, name, t['path']), daemon=True).start()
    return deg


def plan_use(words):
    return 'Light' if words < 700 else 'Medium' if words < 2500 else 'Heavy'


def hear(pid):
    """Transcribe every take, then queue the story job for the session."""
    t0 = time.time()
    prj.update(pid, lambda pj: pj.update(stage='hearing', errors=[]))
    pj = prj.load(pid)
    tr = prj.read_json(os.path.join(prj.folder(pid), 'transcript.json'), {})
    lang = pj['settings'].get('language', 'auto')
    for n, t in enumerate(pj['takes'], 1):
        if t['name'] in tr: continue
        _progress(pid, 'hearing', (n - 1) / len(pj['takes']), f'Hearing take {n} of {len(pj["takes"])}')
        e = media.energy(t['path'], cache(pid, f'energy-{t["name"]}.npy'))
        tr[t['name']] = transcribe.take_transcript(t['path'], lang, e)
    tr = {k: v for k, v in tr.items() if any(t['name'] == k for t in pj['takes'])}
    prj.write_json(os.path.join(prj.folder(pid), 'transcript.json'), tr)
    words = sum(len(v['words']) for v in tr.values())
    heard_s = round(time.time() - t0, 1)
    job = jobs.new(prj.jobs_dir(), 'story', pid, f'Build the storyboard ({pj["settings"]["mode"]} mode)', mode=pj['settings']['mode'])

    def fin(pj):
        pj.update(stage='story_wait', progress={'step': 'story_wait', 'pct': 0, 'label': 'Waiting for Claude Code to build your story', 'at': time.time()},
                  story_job=job['id'], plan_use=plan_use(words), words=words)
        pj['timings']['hear'] = heard_s; pj['timings']['story_queued_at'] = time.time()
    prj.update(pid, fin)
    return job


def transcript_takes(pid):
    tr = prj.read_json(os.path.join(prj.folder(pid), 'transcript.json'), {})
    return tr, {k: cutrules.prepare(v['words']) for k, v in tr.items()}


def save_story(pid, sb):
    tr, takes = transcript_takes(pid)
    clean, errors = storyboard.check(sb, takes)
    if errors: return errors
    pj = prj.load(pid)
    if pj['settings']['mode'] in ('keep',) and clean['mode'] != 'keep': clean['mode'] = pj['settings']['mode']
    clean['approved'] = False; clean['saved_at'] = time.time()
    story_versions(pid)   # an older project's story becomes version 1 first
    archive_story(pid, clean)

    def fin(pj):
        pj.update(stage='story', progress=None)
        q = pj['timings'].get('story_queued_at')
        if q: pj['timings']['story'] = round(time.time() - q, 1)
    prj.update(pid, fin)
    return []


def load_story(pid):
    return prj.read_json(os.path.join(prj.folder(pid), 'storyboard.json'))


def has_story(pid):
    return os.path.exists(os.path.join(prj.folder(pid), 'storyboard.json'))


# ---- story versions: every storyboard is kept (stories/s1.json, s2.json ...); changing footage never deletes one
def story_takes(sb):
    out = set()
    for b in (sb or {}).get('beats', []):
        out.add(b['take']); out.update(a['take'] for a in b.get('alts', []))
    return sorted(out)


def _sdir(pid):
    d = os.path.join(prj.folder(pid), 'stories'); os.makedirs(d, exist_ok=True); return d


def story_versions(pid):
    """[{n, takes, clips, beats, at, why}], oldest first. A project made before versions gets its story as version 1."""
    d = _sdir(pid)
    ns = sorted(int(f[1:-5]) for f in os.listdir(d) if f.startswith('s') and f.endswith('.json') and f[1:-5].isdigit())
    if not ns and has_story(pid):
        sb = load_story(pid); sb['version'] = 1
        prj.write_json(os.path.join(d, 's1.json'), sb); prj.write_json(os.path.join(prj.folder(pid), 'storyboard.json'), sb)
        ns = [1]
    out = []
    for n in ns:
        sb = prj.read_json(os.path.join(d, f's{n}.json'), {}) or {}
        tk = story_takes(sb)
        out.append({'n': n, 'takes': tk, 'clips': len(tk), 'beats': len(sb.get('beats', [])), 'at': sb.get('saved_at'),
                    'why': sb.get('why', ''), 'one_line': sb.get('one_line', '')})
    return out


def archive_story(pid, sb, why=''):
    """Store sb as the next story version and make it the current one. Returns its number."""
    vs = story_versions(pid)
    n = (vs[-1]['n'] + 1) if vs else 1
    sb = dict(sb, version=n, why=why or sb.get('why', ''))
    sb.setdefault('saved_at', time.time())
    prj.write_json(os.path.join(_sdir(pid), f's{n}.json'), sb)
    prj.write_json(os.path.join(prj.folder(pid), 'storyboard.json'), sb)
    return n


def use_story_version(pid, n):
    """Make an earlier story the current one again (it stays its own version)."""
    sb = prj.read_json(os.path.join(_sdir(pid), f's{int(n)}.json'))
    if not sb: raise ValueError('no such story version')
    names = {t['name'] for t in prj.load(pid)['takes']}
    gone = [t for t in story_takes(sb) if t not in names]
    if gone: raise ValueError(f'That version uses a clip you took out ({", ".join(gone)}). Add it again first.')
    prj.write_json(os.path.join(prj.folder(pid), 'storyboard.json'), sb)
    prj.update(pid, lambda pj: pj.update(offer_back=None, stage=pj['stage'] if pj['stage'] not in ('footage', 'hearing', 'story_wait') else 'story'))
    return sb


def without_take(sb, take):
    """The storyboard with every part from `take` taken out; a part whose main try is from it uses its next try."""
    sb = json.loads(json.dumps(sb)); beats = []
    for b in sb.get('beats', []):
        alts = [a for a in b.get('alts', []) if a['take'] != take]
        cur = b['alts'][b['use_alt']] if b.get('use_alt') is not None and 0 <= int(b['use_alt']) < len(b.get('alts', [])) else None
        if b['take'] == take:
            if not alts: continue
            first = alts.pop(0)
            b.update({k: first[k] for k in first if k not in ('id',)})
        b['alts'] = alts
        b['use_alt'] = alts.index(cur) if cur in alts else None
        beats.append(b)
    sb['beats'] = beats; sb['approved'] = False
    return sb


def remove_take(pid, name):
    """Take a clip out. A story that uses it keeps every other part (as a new version), and when an earlier story
    without that clip exists the page offers to go back to it. Returns {"dropped": parts dropped, "offer_back": n}."""
    out = {'dropped': 0, 'offer_back': None}
    with prj.locked(pid):
        pj = prj.load(pid)
        gone = [t['path'] for t in pj['takes'] if t['name'] == name]
        pj['removed_paths'] = sorted(set(pj.get('removed_paths', [])) | {os.path.realpath(x) for x in gone})
        pj['takes'] = [t for t in pj['takes'] if t['name'] != name]
        pj['new_clips'] = [x for x in pj.get('new_clips', []) if x != name]
        prj.save(pj)
    sb = load_story(pid)
    if sb and name in story_takes(sb):
        vs = story_versions(pid)
        back = next((v['n'] for v in reversed(vs) if name not in v['takes'] and v['n'] != sb.get('version')), None)
        new = without_take(sb, name)
        out['dropped'] = len(sb['beats']) - len(new['beats'])
        new['saved_at'] = time.time()
        archive_story(pid, new, why=f'{name} taken out')
        out['offer_back'] = back
        prj.update(pid, lambda pj: pj.update(offer_back=back))
    return out


def fit_new(pid):
    """Keep the story and send a job to place the new clips' best lines into it. The story stays usable meanwhile."""
    pj = prj.load(pid); names = [n for n in pj.get('new_clips', []) if any(t['name'] == n for t in pj['takes'])]
    if not names: raise ValueError('no new clip to fit in')
    tr = prj.read_json(os.path.join(prj.folder(pid), 'transcript.json'), {})
    lang = pj['settings'].get('language', 'auto')
    for t in pj['takes']:
        if t['name'] in names and t['name'] not in tr:
            e = media.energy(t['path'], cache(pid, f'energy-{t["name"]}.npy'))
            tr[t['name']] = transcribe.take_transcript(t['path'], lang, e)
    prj.write_json(os.path.join(prj.folder(pid), 'transcript.json'), tr)
    job = jobs.new(prj.jobs_dir(), 'fit', pid, f'Fit the new clip{"s" if len(names) > 1 else ""} {", ".join(names)} into the story',
                   clips=names)
    prj.update(pid, lambda pj: pj.update(new_clips=[], fit_job=job['id']))
    return job


def start_fresh(pid):
    """Forget the new-clip question and build a new story from every clip (the old ones stay as versions)."""
    prj.update(pid, lambda pj: pj.update(new_clips=[], offer_back=None))
    return hear(pid)


def edit_story(pid, edits):
    with prj.locked(pid):
        sb = load_story(pid)
        if not sb: raise ValueError('no storyboard yet')
        by = {b['id']: b for b in sb['beats']}
        order = [i for i in edits.get('order', []) if i in by]
        if order and sorted(order) == sorted(by):
            sb['beats'] = [by[i] for i in order]
        for i, k in (edits.get('keep') or {}).items():
            if i in by: by[i]['keep'] = bool(k)
        for i, a in (edits.get('use_alt') or {}).items():
            if i in by: by[i]['use_alt'] = None if a is None else int(a) if 0 <= int(a) < len(by[i].get('alts', [])) else None
        if 'shape' in edits and edits['shape'] in storyboard.SHAPES: sb['shape'] = edits['shape']
        if 'approved' in edits: sb['approved'] = bool(edits['approved'])
        prj.write_json(os.path.join(prj.folder(pid), 'storyboard.json'), sb)
        if sb.get('version'): prj.write_json(os.path.join(_sdir(pid), f"s{sb['version']}.json"), sb)
    return sb


def cut(pid, note=''):
    if _busy.get(pid): raise RuntimeError('a cut is already running')
    _busy[pid] = True
    try:
        pj = prj.load(pid); sb = load_story(pid)
        if not sb: raise RuntimeError('no storyboard yet')
        v = len(pj['versions']) + 1
        folder = os.path.join(prj.folder(pid), f'v{v}')
        prj.update(pid, lambda pj: pj.update(stage='cutting', errors=[]))
        tr, _ = transcript_takes(pid)
        t0 = time.time()
        lang = pj['settings'].get('language', 'auto')
        hs = (lambda take, a, b: transcribe.hear_span(prj.take_path(pj, take), a, b, lang)) if transcribe.available() else None
        pcm = lambda take: media.pcm16k(prj.take_path(pj, take), cache(pid, f'pcm-{take}.npy'))
        hc = (lambda spans: transcribe.hear_clips(spans, pcm, lang)) if transcribe.available() else None
        pj['caption_script'] = captions.script_for(lang, prj.prefs()['chinese'])
        rep = render.run(pj, sb, tr, energy_of(pid, pj), folder, lambda s, f, l: _progress(pid, s, f, l), hs, hc)
        _progress(pid, 'qa', 0, 'Checking the cut')
        t1 = time.time()
        q = qa.check(rep['video'], rep, (rep['width'], rep['height']), pj['settings'].get('language', 'auto'))
        rep['timings']['qa'] = round(time.time() - t1, 1)
        rep['qa'] = q; rep['note'] = note; rep['version'] = v; rep['settings'] = pj['settings']
        prj.write_json(os.path.join(folder, 'cut.json'), rep)
        rec = {'v': v, 'video': f'v{v}/video.mp4', 'duration': rep['duration'], 'size_mb': q['size_mb'],
               'width': rep['width'], 'height': rep['height'], 'clips': len(rep['clips']), 'qa': q, 'note': note,
               'timings': rep['timings'], 'seconds': round(time.time() - t0, 1), 'at': time.time(),
               'story_v': sb.get('version'), 'takes': len(story_takes(sb)), 'kept_repeats': len(rep.get('kept_repeats') or []), 'fixes': dict(rep.get('caption_fixes') or {})}

        def fin(pj):
            pj['versions'].append(rec); pj.update(stage='review', progress=None)
            pj['timings'][f'cut_v{v}'] = rec['seconds']
        prj.update(pid, fin)
        return rec
    except Exception as e:
        prj.update(pid, lambda pj: pj.update(stage='cut_failed', progress=None, errors=[str(e)[:500]]))
        raise
    finally:
        _busy.pop(pid, None)


# ---- a caption word heard wrong, put right by the buyer (free, on the Mac, no Claude)
def caption_words(pid, v):
    """(words as heard and timed in version v, the cut's report). Cuts from before the words were kept get them
    back from the transcript."""
    folder = os.path.join(prj.folder(pid), f'v{int(v)}')
    rep = prj.read_json(os.path.join(folder, 'cut.json'))
    if not rep: raise KeyError(pid)
    words = rep.get('caption_words')
    if words is None:
        words = render.words_from_transcript(rep, prj.read_json(os.path.join(prj.folder(pid), 'transcript.json'), {}) or {})
    return words, rep


def captions_view(pid, v):
    """What the page shows under the player: every caption word of this version, as drawn, with its time."""
    pj = prj.load(pid)
    words, rep = caption_words(pid, v)
    script = captions.script_for(pj['settings'].get('language', 'auto'), prj.prefs()['chinese'])
    show = render.shown_words(words, pj.get('caption_fixes') or {}, script)
    return {'v': int(v), 'on': ((rep.get('settings') or {}).get('captions') or {}).get('style', 'three') != 'none',
            'words': [{'w': w['w'].strip(), 's': w['s'], 'e': w['e']} for w in show if w['w'].strip()]}


def stale_captions(pj, rec):
    """This version's video was drawn before the latest correction."""
    return (rec.get('fixes') or {}) != (pj.get('caption_fixes') or {}) and \
        os.path.exists(os.path.join(prj.folder(pj['id']), f"v{rec['v']}", 'segments', 'segments.txt'))


def fix_word(pid, old, new):
    """Remember that `old` (as it shows in the captions now) should read `new`, everywhere in this video.
    The new word also goes on the buyer's Words I use list, so the next video hears it right first time."""
    new = captions.clean_fix(new); key = cutrules.norm(str(old or ''))
    if not key or not new: raise ValueError('Type the right word')

    def fn(pj):
        fx = dict(pj.get('caption_fixes') or {})
        for k, val in list(fx.items()):   # "clock" was already changed to "Cloud", now "Cloud" becomes "Claude"
            if cutrules.norm(val) == key: fx[k] = new
        fx[key] = new
        fx = {k: val for k, val in fx.items() if not (val == k)}
        pj['caption_fixes'] = fx
    pj = prj.update(pid, fn)
    if re.search(r'[A-Z\u3400-\u9fff]', new): prj.add_word(new)
    return pj['caption_fixes']


def recaption(pid, v):
    """Draw version v's captions again with the corrections (captions only: the cut is not touched)."""
    if _busy.get(pid): raise RuntimeError('Your Mac is still making the video. Try again when it is done.')
    _busy[pid] = True
    v = int(v); t0 = time.time()
    try:
        pj = prj.load(pid)
        rec = next(x for x in pj['versions'] if x['v'] == v)
        prj.update(pid, lambda pj: pj.update(recaption={'v': v, 'at': time.time()}, recaption_error=None))
        folder = os.path.join(prj.folder(pid), f'v{v}')
        words, rep = caption_words(pid, v)
        fixes = dict(pj.get('caption_fixes') or {})
        script = captions.script_for(pj['settings'].get('language', 'auto'), prj.prefs()['chinese'])
        if ((rep.get('settings') or {}).get('captions') or {}).get('style', 'three') != 'none':
            render.recaption(rep, folder, words, fixes, script)
        rep['caption_fixes'] = fixes
        if 'caption_words' not in rep: rep['caption_words'] = words
        prj.write_json(os.path.join(folder, 'cut.json'), rep)
        size = round(os.path.getsize(os.path.join(folder, 'video.mp4')) / 1e6, 1)

        def fin(pj):
            for x in pj['versions']:
                if x['v'] == v: x.update(fixes=fixes, captions_at=time.time(), size_mb=size)
            pj.update(recaption=None)
            pj['timings'][f'recaption_v{v}'] = round(time.time() - t0, 1)
        prj.update(pid, fin)
        return fixes
    except Exception as e:
        prj.update(pid, lambda pj: pj.update(recaption=None, recaption_error=str(e)[:300]))
        raise
    finally:
        _busy.pop(pid, None)


def export(pid, v=None, dest=None):
    pj = prj.load(pid)
    if not pj['versions']: raise RuntimeError('no cut to export yet')
    rec = pj['versions'][-1] if v is None else next(x for x in pj['versions'] if x['v'] == int(v))
    if stale_captions(pj, rec):
        recaption(pid, rec['v'])   # never export a video with a caption word the buyer already put right
    if not dest:
        had = pj.get('folder'); dest = prj.sub(pj, 'Exports')
        if not had: prj.update(pid, lambda x: x.update(folder=pj['folder']))
    os.makedirs(dest, exist_ok=True)
    safe = ''.join(ch for ch in pj['name'] if ch.isalnum() or ch in ' -_').strip() or 'video'
    out = os.path.join(dest, f'{safe} v{rec["v"]}.mp4')
    shutil.copy2(os.path.join(prj.folder(pid), rec['video']), out)
    prj.update(pid, lambda pj: pj.setdefault('exports', []).append({'v': rec['v'], 'path': out, 'at': time.time()}))
    return out
