"""cpack: the pack's commands. The skill runs these; tinkerers can too.

  cpack start [--no-open]          start the page (if it isn't running) and open it in the browser
  cpack serve [--port N]           run the page's server in this terminal
  cpack setup                      what's installed and what's missing (looks only)
  cpack jobs next [--wait S]       take the next job from the page (waits up to S seconds, max 540)
  cpack jobs done ID [--reply T] [--failed]
  cpack transcript PID             the transcript, one line per sentence with times
  cpack project PID                settings, storyboard, versions and the last QA, as JSON
  cpack storyboard save PID FILE   check a storyboard against the transcript and save it
  cpack turn PID CLIP DEG           turn one clip (0, 90, 180, 270), e.g. cpack turn 20261122-ab12cd IMG_1.MOV 90
  cpack settings PID JSON          change settings, e.g. '{"cut": {"breath": "relaxed"}}'
  cpack render PID [--note T]      cut a new version (same as the page's Go)
  cpack say PID TEXT               post a reply in the project's chat
"""
import json, os, subprocess, sys, time, urllib.request
from . import project as prj, jobs, pipeline, transcribe, setup_check


def _arg(a, flag, default=None):
    return a[a.index(flag) + 1] if flag in a and a.index(flag) + 1 < len(a) else default


def running_url():
    try:
        with open(os.path.join(prj.home(), 'server.url')) as f: url = f.read().strip()
        with urllib.request.urlopen(url + 'api/state', timeout=2) as r:
            if r.status == 200: return url
    except Exception: return None


def start(open_browser=True):
    url = running_url()
    if not url:
        os.makedirs(prj.home(), exist_ok=True)
        log = open(os.path.join(prj.home(), 'server.log'), 'a')
        subprocess.Popen([sys.executable, '-m', 'cpack', 'serve'], cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         stdout=log, stderr=log, start_new_session=True)
        for _ in range(50):
            time.sleep(0.2); url = running_url()
            if url: break
    if not url: sys.exit('The page did not start; see ' + os.path.join(prj.home(), 'server.log'))
    if open_browser:
        from .platform import get; get().open_url(url)
    print(url)


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
    if cmd == 'start': start('--no-open' not in a)
    elif cmd == 'serve':
        from .server import serve; serve(int(_arg(a, '--port', 8765)), '--open' in a)
    elif cmd == 'setup':
        d = setup_check.detect()
        for it in d['items']: print(f"{'ok     ' if it['found'] else 'MISSING'} {it['name']}{' (optional)' if it.get('optional') else ''}: {it['why']}")
        print('ready' if d['ready'] else 'not ready: open the page, tick what is missing and press Install')
    elif cmd == 'jobs' and a[1:2] == ['next']:
        w = min(540.0, float(_arg(a, '--wait', 0)))
        j = jobs.take(prj.jobs_dir(), wait=w)
        if not j: print(json.dumps({'none': True, 'hint': 'no job yet; run `cpack jobs next --wait 540` again'})); return
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
