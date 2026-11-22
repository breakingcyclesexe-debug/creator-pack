"""A video project: one folder under <data home>/projects/<id>/ holding everything about one video.

  project.json      takes, settings, where it's at, versions
  transcript.json   words per take
  storyboard.json   the checked storyboard (with the buyer's reorders, drops and take swaps)
  chat.json         the project's chat thread
  footage/          files dropped onto the page (picked files stay where they are)
  cache/            sound frames, preview copies, frames
  v1/, v2/ ...      each cut: video.mp4, cut.json, qa.json
"""
import contextlib, copy, fcntl, json, os, re, shutil, time, uuid
from .platform import get as platform

P = platform()

DEFAULT_SETTINGS = {
    'purpose': 'ig', 'format': '9:16', 'fit': 'pad', 'mode': 'find', 'script': '', 'language': 'auto',
    'length': 'auto',
    'cut': {'breath': 'normal', 'fillers': True, 'pauses': True, 'repeats': True, 'best_take': True, 'max_pause': 0.7},
    'captions': {'style': 'three', 'look': 'soft', 'size': 'm', 'position': 'bottom', 'motion': True, 'color': '#ffffff',
                 'pop': '#e3991d', 'pop_on': False, 'per_line': 4, 'upper': True},   # color, upper: kept for old projects, the look decides
    'export': {'max_mb': 0},
}
CHOICES = {'purpose': {'ig', 'yt', 'other'}, 'format': {'9:16', '16:9', '4:5', '1:1', 'source'}, 'fit': {'crop', 'pad'},
           'mode': {'find', 'keep', 'script'}, 'length': {'auto', 'short', 'mid', 'long'},
           'cut.breath': {'tight', 'normal', 'relaxed'}, 'captions.style': {'word', 'three', 'lines', 'none'},
           'captions.size': {'s', 'm', 'l'}, 'captions.position': {'top', 'middle', 'bottom', 'left', 'right', 'moves'},
           'captions.look': {'soft', 'clean', 'glow'}}
HEX = re.compile(r'^#[0-9a-fA-F]{6}$')


def home(): return P.data_home()
def projects_dir(): return os.path.join(home(), 'projects')
def jobs_dir(): return os.path.join(home(), 'jobs')
def exports_dir(): return os.path.join(home(), 'Exports')


# ---- the buyer's own things, kept across videos: <data home>/prefs.json
#   words    names, brands and places they say ("Claude", "Tamraght"): given to the listener so it hears them right
#   chinese  Mandarin captions in 'trad' (Taiwan, Hong Kong) or 'simp' (mainland China); '' = not picked yet
def prefs():
    p = read_json(os.path.join(home(), 'prefs.json'), {}) or {}
    return {'words': clean_words(p.get('words')), 'chinese': p.get('chinese') if p.get('chinese') in ('trad', 'simp') else ''}


def clean_words(words):
    out, seen = [], set()
    for w in (words if isinstance(words, list) else []):
        w = ' '.join(re.sub(r'[\x00-\x1f\x7f,;]', ' ', str(w)).split())[:40]
        if w and w.lower() not in seen: out.append(w); seen.add(w.lower())
    return out[:200]


def save_prefs(new):
    cur = prefs()
    if isinstance((new or {}).get('words'), list): cur['words'] = clean_words(new['words'])
    if (new or {}).get('chinese') in ('trad', 'simp', ''): cur['chinese'] = new['chinese']
    os.makedirs(home(), exist_ok=True)
    write_json(os.path.join(home(), 'prefs.json'), cur)
    return cur


def add_word(word):
    cur = prefs()
    return save_prefs({'words': cur['words'] + [word]}) if word else cur


def valid_id(pid):
    return bool(re.fullmatch(r'[a-z0-9-]{6,40}', pid or ''))


def folder(pid):
    if not valid_id(pid): raise ValueError('bad project id')
    return os.path.join(projects_dir(), pid)


def read_json(path, default=None):
    try:
        with open(path) as f: return json.load(f)
    except (OSError, ValueError): return copy.deepcopy(default)


def write_json(path, obj):
    tmp = f'{path}.{uuid.uuid4().hex[:6]}.tmp'
    with open(tmp, 'w') as f: json.dump(obj, f, indent=1)
    os.replace(tmp, path)


@contextlib.contextmanager
def locked(pid):
    """One writer at a time per project, across the page's server and the session's commands."""
    os.makedirs(folder(pid), exist_ok=True)
    with open(os.path.join(folder(pid), '.lock'), 'w') as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try: yield
        finally: fcntl.flock(lk, fcntl.LOCK_UN)


# ---- the buyer's own folder per video (D29): <data home>/<name>/Footage, References, Exports, easy to find in Finder.
# The pack's working files stay in projects/<id>/ (cache, versions), out of the way.
SUBS = ('Footage', 'References', 'Exports')
RESERVED = {'projects', 'jobs', 'models', 'exports', 'cache'}
VIDEO_EXT = {'.mov', '.mp4', '.m4v', '.mkv', '.avi', '.mts', '.webm'}


def safe_name(name):
    s = ''.join(ch for ch in str(name) if ch.isalnum() or ch in ' -_.,()&\'').strip(' .')[:60]
    return s or 'My video'


def free_folder(name, mine=None):
    """<data home>/<name>, or '<name> 2', '<name> 3' ... if that one is taken (mine = this project's own, allowed)."""
    base = safe_name(name); cand, n = base, 2
    while True:
        p = os.path.join(home(), cand)
        if cand.lower() not in RESERVED and (not os.path.exists(p) or (mine and os.path.realpath(p) == os.path.realpath(mine))): return p
        cand = f'{base} {n}'; n += 1


def make_folder(pj, name=None):
    pj['folder'] = free_folder(name or f"{pj.get('name') or 'My video'} ({time.strftime('%-d %b', time.localtime(pj.get('created') or time.time()))})")
    for sub in SUBS: os.makedirs(os.path.join(pj['folder'], sub), exist_ok=True)
    return pj['folder']


def sub(pj, which):
    """One of the project's folders (Footage, References, Exports), made if missing. Projects from before D29 get
    their folder the first time it is asked for."""
    if which not in SUBS: raise ValueError('no such folder')
    if not pj.get('folder'): make_folder(pj)
    d = os.path.join(pj['folder'], which); os.makedirs(d, exist_ok=True)
    return d


def user_files(d):
    try: return [f for f in os.listdir(d) if not f.startswith('.') and not f.endswith('.part')]
    except OSError: return []


def rename_folder(pj, name):
    """Give the folder the video's name (the first clip's), moving it and the paths of clips inside it."""
    old = pj.get('folder')
    if not old or not os.path.isdir(old): return make_folder(pj, name)
    new = free_folder(name, mine=old)
    if os.path.realpath(new) == os.path.realpath(old): return old
    os.rename(old, new); pj['folder'] = new
    for t in pj['takes']:
        if t.get('path', '').startswith(old + os.sep): t['path'] = new + t['path'][len(old):]
    return new


def create(name='My video'):
    pid = time.strftime('%Y%m%d-') + uuid.uuid4().hex[:6]
    d = folder(pid)
    os.makedirs(os.path.join(d, 'cache'), exist_ok=True)
    pj = {'id': pid, 'name': name, 'created': time.time(), 'takes': [], 'settings': copy.deepcopy(DEFAULT_SETTINGS),
          'stage': 'footage', 'progress': None, 'versions': [], 'timings': {}, 'errors': [], 'folder_named': False}
    make_folder(pj)
    write_json(os.path.join(d, 'project.json'), pj)
    return pj


def is_empty(pid, pj=None):
    """A video nobody has put anything into yet: no clips, no versions, no story."""
    pj = pj or read_json(os.path.join(folder(pid), 'project.json'))
    return bool(pj) and not pj.get('takes') and not pj.get('versions') and pj.get('stage', 'footage') == 'footage' \
        and not os.path.exists(os.path.join(folder(pid), 'storyboard.json'))


def new_or_empty():
    """The page asks for a new video on every fresh browser open. Hand back the newest empty one if there is one, so
    opening the page twice never leaves "My video (22 Nov) 2" behind; else make one."""
    os.makedirs(projects_dir(), exist_ok=True)
    for pid in sorted(os.listdir(projects_dir()), reverse=True):
        if valid_id(pid) and is_empty(pid): return load(pid)
    return create()


TURNS = {0, 90, 180, 270}


def migrate(pj):
    """Projects made before turn per clip (CT-133) had one turn for the whole project: every clip gets it."""
    old = pj.get('settings', {}).pop('turn', None)
    for t in pj.get('takes', []):
        if 'turn' not in t: t['turn'] = int(old or 0) % 360
    return pj


def load(pid):
    pj = read_json(os.path.join(folder(pid), 'project.json'))
    if pj is None: raise KeyError(pid)
    return migrate(pj)


def take_turn(pj, name):
    t = next((t for t in pj['takes'] if t['name'] == name), None)
    return int((t or {}).get('turn', 0)) % 360


def set_turn(pid, name, deg):
    """Turn one clip (0 / 90 / 180 / 270, clockwise). Returns the new turn."""
    try: deg = int(deg) % 360
    except (TypeError, ValueError): raise ValueError('turn must be 0, 90, 180 or 270')
    if deg not in TURNS: raise ValueError('turn must be 0, 90, 180 or 270')
    def fn(pj):
        t = next((t for t in pj['takes'] if t['name'] == name), None)
        if not t: raise KeyError(name)
        t['turn'] = deg
    update(pid, fn)
    return deg


def save(pj):
    write_json(os.path.join(folder(pj['id']), 'project.json'), pj)


def update(pid, fn):
    with locked(pid):
        pj = load(pid); fn(pj); save(pj); return pj


TITLE_STOP = {'a', 'an', 'the', 'and', 'or', 'but', 'so', 'to', 'of', 'in', 'on', 'at', 'with', 'for', 'from', 'my', 'your', 'is',
              'are', 'was', 'i', "i'm", 'you', "you're", 'that', 'then', 'by', 'as', 'no', 'two', 'still'}


def short_title(text, words=6, chars=40):
    """A video's name for the "Your videos" list: the first few words of its one-line story, cut at a word (never
    mid-word), without a dangling "and" or "with" at the end."""
    out = []
    for w in ' '.join(str(text or '').split()).split(' '):
        if not w or len(out) >= words or len(' '.join(out + [w])) > chars: break
        out.append(w)
        if w[-1:] in ',.;:!?': break
    while len(out) > 1 and out[-1].strip(',.;:!?').lower() in TITLE_STOP: out.pop()
    t = ' '.join(out).strip(' ,.;:!?')
    return t[:1].upper() + t[1:]


def title_of(pj, sb=None):
    """What a video is called in the list: the buyer's own name for it, else the story's short title, else the
    first words of the one-line story, else the first clip's name."""
    sb = sb or {}
    return (pj.get('title') or short_title(sb.get('short_title') or '', 7, 48) or short_title(sb.get('one_line') or '')
            or (pj.get('name') if pj.get('takes') else '') or 'New video')


def rename(pid, title):
    """The buyer's own name for a video (empty = back to the story's short title)."""
    t = ' '.join(re.sub(r'[\x00-\x1f\x7f]', ' ', str(title or '')).split())[:60]
    return update(pid, lambda pj: pj.update(title=t))


def numbered(items):
    """Videos with the same name in the list get "(2)", "(3)" by age, oldest first without a number, so the buyer
    can tell them apart. items: dicts with id, title, created; titles are changed in place."""
    seen = {}
    for it in sorted(items, key=lambda x: (x.get('created') or 0, x['id'])):
        k = (it.get('title') or '').strip().lower(); seen[k] = seen.get(k, 0) + 1
        if seen[k] > 1: it['title'] = f"{it['title']} ({seen[k]})"
    return items


def listing():
    os.makedirs(projects_dir(), exist_ok=True)
    out = []
    for pid in sorted(os.listdir(projects_dir()), reverse=True):
        if valid_id(pid):
            pj = read_json(os.path.join(projects_dir(), pid, 'project.json'))
            if pj:
                sb = read_json(os.path.join(projects_dir(), pid, 'storyboard.json'), {}) or {}
                out.append({'id': pid, 'name': pj.get('name'), 'stage': pj.get('stage'), 'created': pj.get('created'),
                            'title': title_of(pj, sb), 'story': str(sb.get('one_line', ''))[:240], 'empty': not pj.get('takes')})
    named = [x for x in out if not x['empty']]   # empty videos never show in the list, so they never take a number
    numbered(named)
    return out


def merge_settings(cur, new):
    """Only known keys with allowed values; everything else is ignored."""
    out = copy.deepcopy(cur)
    for k, v in (new or {}).items():
        if k not in DEFAULT_SETTINGS: continue
        if isinstance(DEFAULT_SETTINGS[k], dict):
            if not isinstance(v, dict): continue
            for k2, v2 in v.items():
                if k2 not in DEFAULT_SETTINGS[k]: continue
                d2 = DEFAULT_SETTINGS[k][k2]; key = f'{k}.{k2}'
                if key in CHOICES and v2 not in CHOICES[key]: continue
                if isinstance(d2, bool): v2 = bool(v2)
                elif isinstance(d2, (int, float)) and not isinstance(d2, bool):
                    try: v2 = type(d2)(v2)
                    except (TypeError, ValueError): continue
                elif k2 in ('color', 'pop') and not HEX.match(str(v2)): continue
                out[k][k2] = v2
        else:
            if k in CHOICES:
                if v not in CHOICES[k]: continue
            if k == 'script': v = str(v)[:20000]
            out[k] = v
    return out


def take_name(pj, path):
    base = os.path.basename(path); name, n = base, 2
    while any(t['name'] == name for t in pj['takes']):
        stem, ext = os.path.splitext(base); name = f'{stem}-{n}{ext}'; n += 1
    return name


def take_path(pj, name):
    t = next((t for t in pj['takes'] if t['name'] == name), None)
    return t['path'] if t else None


def chat(pid):
    return read_json(os.path.join(folder(pid), 'chat.json'), [])


def add_chat(pid, who, text, **extra):
    with locked(pid):
        c = chat(pid); c.append(dict(extra, who=who, text=str(text)[:4000], at=time.time()))
        write_json(os.path.join(folder(pid), 'chat.json'), c)


def remove(pid):
    shutil.rmtree(folder(pid), ignore_errors=True)
