"""What the pack needs on this Mac, what's missing, and installing only what the buyer ticked, after the click.

detect() only looks; nothing is installed until install(ids) is called from the page's Install button."""
import importlib.util, os, subprocess, sys, threading, time
from .platform import get as platform
from . import licence

P = platform()
PACK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ITEMS = [
    {'id': 'brew', 'name': 'Homebrew', 'why': 'Installs the other tools.'},
    {'id': 'python', 'name': 'Python helpers', 'why': 'numpy and Pillow, inside the pack only.'},
    {'id': 'ffmpeg', 'name': 'ffmpeg', 'why': 'Cuts and joins video.'},
    {'id': 'whisper', 'name': 'whisper-cli', 'why': 'Hears your words on the Mac\'s graphics chip.'},
    {'id': 'model', 'name': 'Speech model', 'why': f'Large v3 turbo, {P.MODEL_GB} GB download.'},
    {'id': 'node', 'name': 'Node.js', 'why': 'Not needed yet. Later versions use it for titles.', 'optional': True},
]
_state = {'running': False, 'log': [], 'current': None, 'failed': {}}


def _found(i):
    if i == 'brew': return bool(P.tool('brew'))
    if i == 'python': return all(importlib.util.find_spec(m) for m in ('numpy', 'PIL'))
    if i == 'ffmpeg': return bool(P.tool('ffmpeg') and P.tool('ffprobe'))
    if i == 'whisper': return bool(P.tool('whisper-cli'))
    if i == 'model': return os.path.exists(P.whisper_model()) and os.path.getsize(P.whisper_model()) > 500e6
    if i == 'node': return bool(P.tool('node'))
    return False


def detect():
    items = []
    for it in ITEMS:
        d = dict(it, found=_found(it['id']))
        if d['id'] in _state['failed']: d['error'] = _state['failed'][d['id']]
        if not d['found'] and d['id'] == 'brew': d['manual'] = P.BREW_LINE
        items.append(d)
    need = [x for x in items if not x.get('optional')]
    out = {'platform': P.NAME, 'items': items, 'ready': all(x['found'] for x in need),
            'installing': _state['running'], 'current': _state['current'], 'log': _state['log'][-20:],
            'model_path': P.whisper_model(), 'device': P.whisper_device(), 'python': sys.executable}
    if licence.required():   # paid version only; the beta has no licence check and the page shows nothing
        out['licence'] = licence.status()
        out['ready'] = out['ready'] and out['licence']['ok']
    return out


def install(ids):
    """Runs in a background thread; the page polls detect()."""
    if _state['running']: return False
    order = [it['id'] for it in ITEMS if it['id'] in set(ids) and not _found(it['id'])]

    def go():
        _state.update(running=True, failed={})
        try:
            for i in order:
                _state['current'] = i
                steps = P.install_steps(i, PACK, sys.executable)
                if steps is None:
                    _state['failed'][i] = 'Needs you: run the line shown in Terminal (it asks for your Mac password), then press Check again.'
                    continue
                for cmd in steps:
                    _state['log'].append(f'{time.strftime("%H:%M:%S")} {" ".join(os.path.basename(c) if n == 0 else c for n, c in enumerate(cmd))}')
                    r = subprocess.run(cmd, capture_output=True, text=True)
                    if r.returncode != 0:
                        _state['failed'][i] = (r.stderr or r.stdout or 'failed')[-300:]; break
        finally:
            _state.update(running=False, current=None)
    threading.Thread(target=go, daemon=True).start()
    return True
