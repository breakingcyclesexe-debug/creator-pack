"""cpack: the pack's commands. The skill runs these; tinkerers can too.

  cpack start [--no-open] [--port N]  start the page (if it isn't running) and open it, unless it is already open
  cpack stop                       stop the page (videos and jobs stay)
  cpack serve [--port N]           run the page's server in this terminal

  CPACK_HOME (data folder, default ~/Movies/Creator Pack) and CPACK_PORT (default 8765) let a second copy run beside the first.
  cpack setup                      what's installed and what's missing (looks only)
  cpack jobs next [--wait S]       take the next job from the page (waits up to S seconds, max 540)
  cpack jobs done ID [--reply T] [--failed]
  cpack transcript PID             the transcript, one line per sentence with times
  cpack project PID                settings, storyboard, versions and the last QA, as JSON
  cpack storyboard save PID FILE   check a storyboard against the transcript and save it
  cpack turn PID CLIP DEG           turn one clip (0, 90, 180, 270), e.g. cpack turn 20261122-ab12cd IMG_1.MOV 90
  cpack settings PID JSON          change settings, e.g. '{"cut": {"breath": "relaxed"}}'
  cpack backdrop PID PICTURE       use a picture (jpg, png, heic, webp) behind the video for the picture background fit;
                                   it is copied into the project. cpack backdrop PID --frame goes back to a still of the video
  cpack render PID [--note T]      cut a new version (same as the page's Go)
  cpack say PID TEXT               post a reply in the project's chat
"""
import json, os, subprocess, sys, time, urllib.request
from . import project as prj, jobs, pipeline, transcribe, setup_check


def _arg(a, flag, default=None):
    return a[a.index(flag) + 1] if flag in a and a.index(flag) + 1 < len(a) else default


PACK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PORT = 8765


def port_wanted(a=()):
    """--port N, else CPACK_PORT, else 8765. A test copy runs beside the real one with its own port and CPACK_HOME."""
    try: return int(_arg(list(a), '--port', os.environ.get('CPACK_PORT') or DEFAULT_PORT))
    except ValueError: sys.exit('The port must be a number, like 8765.')


def running():
    """The page this data home is using right now: (url, its /api/state), or (None, None)."""
    try:
        with open(os.path.join(prj.home(), 'server.url')) as f: url = f.read().strip()
        req = urllib.request.Request(url + 'api/state', headers={'X-CPack-Probe': '1'})   # a probe, not the page: page_seen stays
        with urllib.request.urlopen(req, timeout=5) as r:
            if r.status == 200: return url, json.load(r)
    except Exception: pass
    return None, None


def running_url():
    return running()[0]


def other_copy(state):
    """A note when the running page comes from a different copy of the pack (an older install, a test copy), or ''."""
    pk = (state or {}).get('pack') or {}
    if pk.get('root') and os.path.realpath(pk['root']) == os.path.realpath(PACK): return ''
    mine = pack_version()
    if not pk: return f'Note: the page that is open comes from an older copy of the Creator Pack Editor, not this one ({mine}). Run `cpack stop`, then /creator-pack again to use this one.'
    if pk.get('version') == mine: return ''
    return (f"Note: the page that is open is version {pk.get('version')}, not this copy ({mine}). "
            'Run `cpack stop`, then /creator-pack again to use this one.')


def pack_version():
    return prj.read_json(os.path.join(PACK, '.claude-plugin', 'plugin.json'), {}).get('version', '')


def log_tail(n=6):
    try:
        with open(os.path.join(prj.home(), 'server.log')) as f: return ''.join(f.readlines()[-n:]).strip()
    except OSError: return ''


PAGE_FRESH = 20   # a page that asked for /api/state this recently is open in a browser: don't open another


def should_open(was_running, state, asked=True):
    """Open the browser only when asked, not told otherwise (CPACK_NO_OPEN: listeners, restarts), and no page is open:
    the server wasn't running, or no page has polled it in the last PAGE_FRESH seconds (a tester, 22 Nov: it "just randomly
    opens in a browser" on every /creator-pack and restart)."""
    if not asked or os.environ.get('CPACK_NO_OPEN'): return False
    if not was_running: return True
    seen = (state or {}).get('page_seen')
    return seen is None or seen > PAGE_FRESH


def start(open_browser=True, port=None):
    url, state = running()
    was_running = bool(url)
    if url:
        note = other_copy(state)
        if note: print(note)
    else:
        os.makedirs(prj.home(), exist_ok=True)
        try: os.remove(os.path.join(prj.home(), 'server.url'))   # a stale address from last time must not count as started
        except OSError: pass
        log = open(os.path.join(prj.home(), 'server.log'), 'a')
        proc = subprocess.Popen([sys.executable, '-m', 'cpack', 'serve', '--port', str(port or port_wanted())], cwd=PACK,
                                stdout=log, stderr=log, start_new_session=True)
        for _ in range(100):
            time.sleep(0.2); url = running_url()
            if url or proc.poll() is not None: break
        if not url:
            why = log_tail()
            sys.exit('The page did not start.' + (f' The last lines of its log:\n{why}' if why else '') +
                     f"\nFull log: {os.path.join(prj.home(), 'server.log')}")
        wanted = port or port_wanted()
        if not url.rstrip('/').endswith(f':{wanted}'):
            print(f'Port {wanted} is taken by another program, so the page uses {url} instead.')
    if should_open(was_running, state, open_browser):
        from .platform import get; get().open_url(url)
    elif was_running and open_browser and not os.environ.get('CPACK_NO_OPEN'): print('The page is already open in your browser.')
    print(url)


def stop():
    """Stops the page this data home is using (any copy of the pack). Jobs and videos stay."""
    url, _ = running()
    if not url: print('The page is not running.'); return
    pid = prj.read_json(os.path.join(prj.home(), 'server.json'), {}).get('pid')
    if not pid:
        try:   # pages from before server.json: find whoever listens on that port
            port = url.rstrip('/').rsplit(':', 1)[1]
            out = subprocess.run(['lsof', '-t', f'-iTCP:{port}', '-sTCP:LISTEN'], capture_output=True, text=True).stdout.split()
            pid = int(out[0]) if out else None
        except Exception: pid = None
    if not pid: sys.exit(f'Could not find the page at {url} to stop it. Quit it from Activity Monitor (Python).')
    import signal
    try: os.kill(int(pid), signal.SIGTERM)
    except ProcessLookupError: pass
    for _ in range(25):
        time.sleep(0.2)
        if not running_url(): break
    print('stopped')


GUIDE = {
    'story': 'Build the storyboard: read skills/creator-pack/story-method.md, run `cpack transcript {p}`, write the JSON, '
             'then `cpack storyboard save {p} FILE` until it says saved. Then `cpack jobs done {j} --reply "<one line for the buyer>"`.',
    'change': 'A change request on the cut. `cpack project {p}` shows the storyboard, settings and last QA. Make the change '
              '(storyboard save / settings), run `cpack render {p} --note "<what changed>"`, then `cpack jobs done {j} --reply "..."`.',
    'fit': 'New clips were added to a video that already has a story (job "clips" lists them). Keep the current story: '
           '`cpack project {p}` and `cpack transcript {p}`, then place the new clips\' best lines into it (a new part where it '
           'tells the story better, or another try of an existing part in its "alts"). Never drop parts the buyer kept. '
           '`cpack storyboard save {p} FILE` until saved, then `cpack jobs done {j} --reply "<what you added, one line>"`.',
    'chat': 'A chat message from the buyer about this video. Answer it; if it asks for a change, treat it as a change request. '
            'Finish with `cpack jobs done {j} --reply "<your answer>"`.',
}


def main(a):
    if not a or a[0] in ('-h', '--help'): print(__doc__); return
    cmd = a[0]
    if cmd == 'start': start('--no-open' not in a, port_wanted(a))
    elif cmd == 'stop': stop()
    elif cmd == 'serve':
        from .server import serve; serve(port_wanted(a), '--open' in a)
    elif cmd == 'setup':
        d = setup_check.detect()
        for it in d['items']: print(f"{'ok     ' if it['found'] else 'MISSING'} {it['name']}{' (optional)' if it.get('optional') else ''}: {it['why']}")
        print('ready' if d['ready'] else 'not ready: open the page, tick what is missing and press Install')
    elif cmd == 'jobs' and a[1:2] == ['next']:
        w = min(540.0, float(_arg(a, '--wait', 0)))
        lid = os.environ.get('CPACK_LISTENER')
        keep = None
        if lid:   # the page's headless listener: stop waiting the moment the page no longer counts it as alive
            from . import listener
            keep = lambda: listener.info().get('id') == lid
        j = jobs.take(prj.jobs_dir(), wait=w, keep=keep)
        if not j and lid and not keep():
            print(json.dumps({'none': True, 'stop': True, 'hint': 'the page stopped this listener: stop now'})); return
        if not j and os.environ.get('CPACK_LISTENER'):   # the page's headless listener: stop after a long quiet spell
            from . import listener
            quiet = time.time() - max(float(os.environ.get('CPACK_LISTENER_START') or 0), jobs.last_activity(prj.jobs_dir()))
            if quiet > listener.IDLE:
                print(json.dumps({'none': True, 'stop': True, 'hint': 'no jobs for a long time: stop now; the page starts you again when it needs you'})); return
        if not j: print(json.dumps({'none': True, 'hint': 'no job yet; run `cpack jobs next` again with the same --wait'})); return
        j['what_to_do'] = GUIDE[j['type']].format(p=j['project'], j=j['id'])
        print(json.dumps(j, indent=1))
    elif cmd == 'jobs' and a[1:2] == ['done']:
        jid = a[2]; reply = _arg(a, '--reply', '')
        j = jobs.done(prj.jobs_dir(), jid, reply, ok='--failed' not in a)
        if reply: prj.add_chat(j['project'], 'claude', reply, job=jid)
        print('done', jid)
    elif cmd == 'transcript':
        tr = prj.read_json(os.path.join(prj.folder(a[1]), 'transcript.json'), {})
        print('\n\n'.join(transcribe.compact(v, k) for k, v in tr.items()))
    elif cmd == 'project':
        pj = prj.load(a[1]); pj['storyboard'] = pipeline.load_story(a[1]); pj['chat'] = prj.chat(a[1])[-10:]
        for t in pj['takes']: t.pop('path', None)
        print(json.dumps(pj, indent=1))
    elif cmd == 'storyboard' and a[1:2] == ['save']:
        with open(a[3]) as f: sb = json.load(f)
        errs = pipeline.save_story(a[2], sb)
        if errs: print('NOT SAVED, fix these:\n- ' + '\n- '.join(errs)); sys.exit(1)
        sbc = pipeline.load_story(a[2])
        print(f"saved: {len(sbc['beats'])} beats, shape {sbc['shape']}")
        for b in sbc['beats']: print(f"  {b['id']} [{b['start']:.2f}-{b['end']:.2f}] {b['label']}: {b['heard'][:90]}")
    elif cmd == 'turn':   # cpack turn PID CLIP DEGREES (0 / 90 / 180 / 270, clockwise, for that clip only)
        print(json.dumps({'turn': pipeline.turn_take(a[1], a[2], to=a[3])}))
    elif cmd == 'settings':
        pj = prj.update(a[1], lambda pj: pj.update(settings=prj.merge_settings(pj['settings'], json.loads(a[2]))))
        print(json.dumps(pj['settings'], indent=1))
    elif cmd == 'backdrop':   # cpack backdrop PID PICTURE | --frame
        if len(a) < 3: print(__doc__); sys.exit(2)
        if a[2] == '--frame':
            pj = prj.update(a[1], lambda pj: pj.update(settings=prj.merge_settings(pj['settings'], {'backdrop': {'image': ''}})))
            s = pj['settings']
        else:
            try: s = prj.set_backdrop_image(a[1], os.path.expanduser(a[2].strip().strip('\'"')))
            except ValueError as e: sys.exit(str(e))
        print(json.dumps({'fit': s['fit'], 'backdrop': s['backdrop']}))
    elif cmd == 'render':
        rec = pipeline.cut(a[1], _arg(a, '--note', ''))
        q = rec['qa']
        print(f"v{rec['v']}: {rec['duration']} s, {q['size_mb']} MB, {rec['width']}x{rec['height']}, match {q['match']}, "
              f"fillers {len(q['fillers_heard'])}, repeats {len(q['repeats_heard'])}, clipped at joins {len(q['missing_near_joins'])}")
        ls = q.get('lip_sync') or {}
        print(f"lip sync: worst {ls.get('worst_ms')} ms over {ls.get('measured')} of {ls.get('clips')} clips, "
              f"{'ok' if ls.get('ok') else 'FAILED (over 40 ms)'}; worth a look: {sum(1 for i in q['items'] if i.get('show'))}")
    elif cmd == 'say':
        prj.add_chat(a[1], 'claude', ' '.join(a[2:])); print('posted')
    else:
        print(__doc__); sys.exit(2)


if __name__ == '__main__':
    main(sys.argv[1:])
