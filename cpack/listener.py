"""The page starts Claude Code itself (a tester, 22 Nov: "You need to have an option built into the interface to reconnect").

Before this, the story, change and chat jobs needed a Claude Code session the buyer opened with /creator-pack. Now the
local server can start a headless one: `claude -p` with the pack's instructions, the buyer's own Claude login and plan,
allowed to run only the pack's own command (`cpack ...`), read the pack and the data home, and write its storyboard
drafts into one work folder. Nothing else: no other shell commands, no web, no MCP servers, no user settings or hooks.

  <data home>/jobs/listener.json   the listener the server started: pid, id, when, log
  <data home>/listener.log         what it printed (stream-json), for when something goes wrong

Rules: never two (a lock, and no start while any session's heartbeat is fresh); it stops by itself after IDLE seconds
with no job (`cpack jobs next` tells it to); when the server sees the process it started has died, the jobs that
listener took go straight back in the queue instead of waiting 30 minutes (jobs.requeue_stale).
"""
import contextlib, fcntl, json, os, shutil, signal, subprocess, threading, time, uuid
from . import project as prj, jobs

PACK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IDLE = 1200          # 20 minutes with no job: the listener stops; the next job starts it again
WAIT = 100           # each `cpack jobs next` wait, under the Bash tool's 2 minute default
AUTO_GAP = 90        # an automatic start at most this often, so a broken setup never loops
TOOLS = 'Bash,Read,Write,Agent'   # Agent: the story method's separate judge
CANDIDATES = ('~/.local/bin/claude', '~/.claude/local/claude', '/opt/homebrew/bin/claude', '/usr/local/bin/claude')

_lock = threading.Lock()
_proc = None          # the Popen of the listener this server started (so it can be reaped)
_last = {'auto': 0.0, 'problem': None}


def root(): return prj.jobs_dir()
def work_dir(): return os.path.join(root(), 'work')
def log_path(): return os.path.join(prj.home(), 'listener.log')
def info_path(): return os.path.join(root(), 'listener.json')


def find_claude():
    """The claude command: on PATH, else where its installers put it (a server started from a GUI has a short PATH)."""
    p = os.environ.get('CPACK_CLAUDE') or shutil.which('claude')
    if p and os.path.isfile(p) and os.access(p, os.X_OK): return p
    for c in CANDIDATES:
        c = os.path.expanduser(c)
        if os.path.isfile(c) and os.access(c, os.X_OK): return c
    return None


def logged_in(claude):
    """True / False from `claude auth status --json`; None when it can't tell (old version): then just try."""
    try:
        r = subprocess.run([claude, 'auth', 'status', '--json'], capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL)
        return bool(json.loads(r.stdout or '{}').get('loggedIn'))
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def allowed():
    """The only things the listener may do without asking (and it can't ask: dontAsk mode denies everything else)."""
    # Edit(...) is the rule that governs the Write tool too; //path is an absolute path in Claude Code's rule syntax
    return ['Bash(cpack *)', f'Read(/{PACK}/**)', f'Read(/{prj.home()}/**)', f'Edit(/{work_dir()}/**)', 'Agent']


def prompt():
    skill = os.path.join(PACK, 'skills', 'creator-pack', 'SKILL.md')
    return (f'You are the Creator Pack Editor\'s helper, started by its page on this Mac. Read {skill} and follow sections 2 to 5 '
            f'and its Rules. The page is already open: skip section 1 and never run `cpack start`. Run the pack as plain `cpack ...` '
            f'(it is on your PATH), never with a full path, and only one command per Bash call (no &&, pipes or redirects). '
            f'Wait for jobs with `cpack jobs next --wait {WAIT}`. Write storyboard drafts only inside {work_dir()} and save them '
            f'with `cpack storyboard save PID FILE`. After every job, done or failed, go straight back to `cpack jobs next`: '
            f'keep looping until it prints "stop": true, then stop and end with one short line. Never stop for any other reason. '
            f'Never open a browser, never touch other files, never use the web. Do only the jobs.')


def command(claude):
    return [claude, '-p', prompt(), '--restricted', '--tools', TOOLS, '--allowedTools', *allowed(),
            '--permission-mode', 'dontAsk', '--strict-mcp-config', '--no-session-persistence',
            '--add-dir', PACK, '--add-dir', prj.home(),
            '--output-format', 'stream-json', '--verbose']


def info():
    return prj.read_json(info_path(), {}) or {}


def alive(pid):
    global _proc
    if not pid: return False
    if _proc is not None and _proc.pid == pid:
        if _proc.poll() is None: return True
        return False
    try: os.kill(int(pid), 0); return True
    except (OSError, ValueError): return False


def requeue_by(lid):
    """Jobs the dead listener `lid` took go back in the queue now."""
    d = jobs._dirs(root()); back = []
    for name in os.listdir(d['taken']):
        if not name.endswith('.json'): continue
        p = os.path.join(d['taken'], name)
        try:
            j = jobs._read(p)
            if j.get('by') != lid: continue
            j.update(status='pending', taken=None); jobs._write(p, j)
            os.rename(p, os.path.join(d['pending'], name)); back.append(name[:-5])
        except (OSError, ValueError): continue
    return back


def _tail(n=40):
    try:
        with open(log_path(), errors='replace') as f: lines = f.readlines()[-n:]
    except OSError: return ''
    for ln in reversed(lines):   # the last result or error message in the stream
        try: o = json.loads(ln)
        except ValueError:
            if ln.strip() and not ln.startswith('---'): return ln.strip()[:300]
            continue
        if o.get('type') == 'result': return str(o.get('result') or o.get('subtype') or '')[:300]
    return ''


@contextlib.contextmanager
def _filelock():
    os.makedirs(root(), exist_ok=True)
    with open(os.path.join(root(), 'listener.lock'), 'w') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try: yield
        finally: fcntl.flock(f, fcntl.LOCK_UN)


def check():
    """Notice a listener that died (requeue its jobs, note why) or has been idle far too long (stop it)."""
    with _lock, _filelock():
        i = info(); pid = i.get('pid')
        if not pid: return
        if not alive(pid):
            try: os.remove(info_path())   # first: a `cpack jobs next` it left running sees this and stops taking jobs
            except OSError: pass
            _stop(pid)   # anything left in its process group
            ever = False   # did it ever wait for jobs? if not, it failed to start: say why
            try:   # its last heartbeat would say "connected" for up to 30 s more
                ever = float(jobs._text(os.path.join(root(), 'heartbeat'))) >= float(i.get('started') or 0)
                if ever: os.remove(os.path.join(root(), 'heartbeat'))
            except (OSError, ValueError): pass
            back = requeue_by(i.get('id'))
            if not ever and not back:
                why = _tail()
                _last['problem'] = {'code': 'stopped', 'msg': "Claude Code stopped before it could start." + (f' It said: {why}' if why else '')}
            _last['exit'] = {'at': time.time(), 'requeued': back}
            return
        quiet = time.time() - max(float(i.get('started') or 0), jobs.last_activity(root()))
        if quiet > IDLE + 300 and not os.listdir(jobs._dirs(root())['taken']):
            _stop(pid)


def _stop(pid):
    try: os.killpg(int(pid), signal.SIGTERM)
    except (OSError, ValueError):
        try: os.kill(int(pid), signal.SIGTERM)
        except (OSError, ValueError): pass


def start(auto=False):
    """Start the headless listener unless one is already listening. Returns state()."""
    global _proc
    check()
    with _lock, _filelock():
        i = info()
        if alive(i.get('pid')) or jobs.listening(root()): return state()
        if auto and time.time() - _last['auto'] < AUTO_GAP: return state()
        if auto: _last['auto'] = time.time()
        claude = find_claude()
        if not claude:
            _last['problem'] = {'code': 'no_claude', 'msg': "Claude Code isn't installed on this Mac. Install it from claude.com/code, sign in once, then press Connect Claude."}
            return state()
        if logged_in(claude) is False:
            _last['problem'] = {'code': 'not_logged_in', 'msg': "Claude Code isn't signed in. Open Claude Code once and sign in, then press Connect Claude."}
            return state()
        _last['problem'] = None
        os.makedirs(work_dir(), exist_ok=True)
        lid = uuid.uuid4().hex[:8]
        env = dict(os.environ, CPACK_LISTENER=lid, CPACK_LISTENER_START=str(time.time()), CPACK_NO_OPEN='1',
                   PATH=os.path.join(PACK, 'bin') + os.pathsep + os.environ.get('PATH', '/usr/bin:/bin'))
        env.pop('CLAUDECODE', None)   # a server started from inside a Claude Code session must not look nested
        log = open(log_path(), 'a'); log.write(f'\n--- started {time.ctime()} ({lid})\n'); log.flush()
        _proc = subprocess.Popen(command(claude), cwd=work_dir(), env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                 start_new_session=True)
        log.close()
        prj.write_json(info_path(), {'pid': _proc.pid, 'id': lid, 'started': time.time(), 'log': log_path(), 'auto': auto})
        return state()


def stop():
    with _lock:
        i = info()
        if alive(i.get('pid')): _stop(i['pid'])
        pid = i.get('pid')
    for _ in range(20):   # up to 2 s for it to go, so the answer already says off
        if not alive(pid): break
        time.sleep(0.1)
    check()
    return state()


def auto_start():
    """A job is waiting and nobody is listening: start one (at most every AUTO_GAP seconds)."""
    d = jobs._dirs(root())
    if any(f.endswith('.json') for f in os.listdir(d['pending'])) and not jobs.connected(root()) and not alive(info().get('pid')):
        start(auto=True)


def state():
    """What the chat dot says: connected (a session is waiting or working), connecting (ours is starting), off."""
    on = jobs.connected(root())
    mine = alive(info().get('pid'))
    s = 'connected' if on else 'connecting' if mine else 'off'
    return {'state': s, 'ours': mine, 'problem': None if on or mine else _last.get('problem'), 'can_start': find_claude() is not None}
