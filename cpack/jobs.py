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
    touch(root)
    return job


def heartbeat(root):
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, 'heartbeat'), 'w') as f: f.write(str(time.time()))


def listening(root):
    """A session is waiting for jobs right now (fresh heartbeat)."""
    try: return time.time() - float(_text(os.path.join(root, 'heartbeat'))) < ALIVE
    except (OSError, ValueError): return False


def touch(root):
    """Something happened with the jobs (one queued, taken, answered): the headless listener's idle clock starts again."""
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, 'activity'), 'w') as f: f.write(str(time.time()))


def last_activity(root):
    try: return float(_text(os.path.join(root, 'activity')))
    except (OSError, ValueError): return 0.0


def connected(root):
    """A session is waiting (fresh heartbeat) or working on a job it took in the last 15 minutes."""
    try:
        if time.time() - float(_text(os.path.join(root, 'heartbeat'))) < ALIVE: return True
    except (OSError, ValueError): pass
    d = os.path.join(root, 'taken')
    return os.path.isdir(d) and any(time.time() - os.path.getmtime(os.path.join(d, f)) < 900 for f in os.listdir(d) if f.endswith('.json'))


STALE = 1800   # a job taken this long ago with no answer: the session that took it stopped (closed, crashed)


def requeue_stale(root, now=None):
    """Put jobs back in the queue when the session that took them went away, so the next session picks them up
    instead of the page waiting forever (22 Nov: a story job sat 'taken' for 1h40 after the session stopped)."""
    d = _dirs(root); now = now or time.time(); back = []
    for name in os.listdir(d['taken']):
        if not name.endswith('.json'): continue
        p = os.path.join(d['taken'], name)
        try:
            if now - os.path.getmtime(p) < STALE: continue
            os.rename(p, os.path.join(d['pending'], name)); back.append(name[:-5])
        except OSError: continue
    return back


def take(root, wait=0.0, poll=1.0, keep=None):
    """Oldest pending job, moved to taken; None if nothing arrives within `wait` seconds, or as soon as keep() says
    this waiter should stop (the page's listener it belongs to was declared dead: it must not take jobs)."""
    d = _dirs(root); end = time.time() + wait
    requeue_stale(root)
    while True:
        if keep and not keep(): return None
        heartbeat(root)
        for name in sorted(f for f in os.listdir(d['pending']) if f.endswith('.json')):
            src, dst = os.path.join(d['pending'], name), os.path.join(d['taken'], name)
            try: os.rename(src, dst)
            except OSError: continue
            job = _read(dst)
            if job.get('type') and job['type'] not in TYPES:   # left over from a version that had a job kind this one doesn't: close it, never hand it out
                job.update(status='failed', reply="This version can't do that job.", finished=time.time())
                _write(os.path.join(d['done'], name), job); os.remove(dst)
                continue
            job.update(status='taken', taken=time.time(), by=os.environ.get('CPACK_LISTENER') or 'session')
            _write(dst, job); touch(root)
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
    _write(os.path.join(d['done'], jid + '.json'), job); os.remove(src); touch(root)
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
