"""Job files: how the interface hands judgement work to the buyer's own Claude Code session (spec "shape X").

The page never talks to Claude. It writes a job file; the session the buyer started with /creator-pack runs
`cpack jobs next --wait 540`, which takes the oldest pending job (an atomic rename, so two sessions never take the
same one), acts on it, and answers with `cpack jobs done ID --reply "..."`. While a session is waiting it touches a
heartbeat file, so the page can say "Claude Code connected".

  <root>/pending/<id>.json -> <root>/taken/<id>.json -> <root>/done/<id>.json
"""
import json, os, time, uuid

TYPES = {'story', 'change', 'chat', 'fit'}
ALIVE = 30  # seconds since the last heartbeat that still count as connected


def _dirs(root):
    d = {k: os.path.join(root, k) for k in ('pending', 'taken', 'done')}
    for p in d.values(): os.makedirs(p, exist_ok=True)
    return d


def _text(path):
    with open(path) as f: return f.read()


def _read(path):
    return json.loads(_text(path))


def _write(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w') as f: json.dump(obj, f, indent=1)
    os.replace(tmp, path)


def new(root, kind, project, text='', **extra):
    if kind not in TYPES: raise ValueError(f'unknown job type {kind}')
    d = _dirs(root)
    jid = time.strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6]
    job = dict(extra, id=jid, type=kind, project=project, text=str(text)[:4000], created=time.time(), status='pending')
    _write(os.path.join(d['pending'], jid + '.json'), job)
    return job


def heartbeat(root):
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, 'heartbeat'), 'w') as f: f.write(str(time.time()))


def connected(root):
    """A session is waiting (fresh heartbeat) or working on a job it took in the last 15 minutes."""
    try:
        if time.time() - float(_text(os.path.join(root, 'heartbeat'))) < ALIVE: return True
    except (OSError, ValueError): pass
    d = os.path.join(root, 'taken')
    return os.path.isdir(d) and any(time.time() - os.path.getmtime(os.path.join(d, f)) < 900 for f in os.listdir(d) if f.endswith('.json'))


def take(root, wait=0.0, poll=1.0):
    """Oldest pending job, moved to taken; None if nothing arrives within `wait` seconds."""
    d = _dirs(root); end = time.time() + wait
    while True:
        heartbeat(root)
        for name in sorted(f for f in os.listdir(d['pending']) if f.endswith('.json')):
            src, dst = os.path.join(d['pending'], name), os.path.join(d['taken'], name)
            try: os.rename(src, dst)
            except OSError: continue
            job = _read(dst); job.update(status='taken', taken=time.time()); _write(dst, job)
            return job
        if time.time() >= end: return None
        time.sleep(poll)


def done(root, jid, reply='', ok=True):
    d = _dirs(root)
    if '/' in jid or '..' in jid: raise ValueError('bad job id')
    src = os.path.join(d['taken'], jid + '.json')
    if not os.path.exists(src): src = os.path.join(d['pending'], jid + '.json')
    job = _read(src)
    job.update(status='done' if ok else 'failed', reply=str(reply)[:4000], finished=time.time())
    _write(os.path.join(d['done'], jid + '.json'), job); os.remove(src)
    heartbeat(root)   # the session just answered: it is still there, so the page never flashes "isn't listening" before its next wait
    return job


def listing(root, project=None):
    d = _dirs(root); out = []
    for k in ('pending', 'taken', 'done'):
        for name in os.listdir(d[k]):
            if not name.endswith('.json'): continue
            try: j = _read(os.path.join(d[k], name))
            except (OSError, ValueError): continue
            if project is None or j.get('project') == project: out.append(j)
    return sorted(out, key=lambda j: j.get('created', 0))
