"""Mac (Apple chip): Homebrew installs, folders under ~/Movies, the Mac's own file picker, Finder, Metal transcription."""
import os, shutil, subprocess

NAME = 'mac'
BREW_DIRS = ['/opt/homebrew/bin', '/usr/local/bin']
MODEL_FILE = 'ggml-large-v3-turbo.bin'
MODEL_URL = 'https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin'
MODEL_GB = 1.6
VIDEO_ENCODER = 'h264_videotoolbox'   # the Mac's own video chip
HWACCEL = ['-hwaccel', 'videotoolbox']
FONTS = ['/System/Library/Fonts/Supplemental/Arial Bold.ttf', '/System/Library/Fonts/Supplemental/Arial Black.ttf',
         '/System/Library/Fonts/Helvetica.ttc', '/Library/Fonts/Arial Bold.ttf']


def data_home():
    """Projects, jobs, exports and the speech model. Outside the pack, so updates never touch them."""
    return os.path.abspath(os.path.expanduser(os.environ.get('CPACK_HOME') or '~/Movies/Creator Pack'))


def tool(name):
    p = shutil.which(name)
    if p: return p
    for d in BREW_DIRS:
        c = os.path.join(d, name)
        if os.access(c, os.X_OK): return c
    return None


# Places a speech model often already sits on a Mac (whisper.cpp guides, Homebrew, other apps), so nobody
# downloads 1.6 GB twice (a tester's Mac had it in ~/whisper-models and setup said MISSING, 21 Nov).
MODEL_SEARCH = ['~/whisper-models', '~/models', '~/.cache/whisper', '~/.cache/whisper.cpp', '~/Library/Application Support/whisper',
                '/opt/homebrew/share/whisper-cpp', '/opt/homebrew/share/whisper.cpp', '/usr/local/share/whisper-cpp']


def whisper_model():
    if os.environ.get('CPACK_WHISPER_MODEL'): return os.environ['CPACK_WHISPER_MODEL']
    own = os.path.join(data_home(), 'models', MODEL_FILE)
    if os.path.exists(own): return own
    found = next((os.path.join(os.path.expanduser(d), MODEL_FILE) for d in MODEL_SEARCH
                  if os.path.exists(os.path.join(os.path.expanduser(d), MODEL_FILE))), None)
    return found or own


def whisper_device():
    return 'Apple graphics chip (Metal)'


def font():
    return next((f for f in FONTS if os.path.exists(f)), None)


# Chinese captions: fonts that come with every Mac. (file, name of the Traditional face, name of the Simplified face)
CJK_FONTS = [('/System/Library/Fonts/PingFang.ttc', 'PingFang TC', 'PingFang SC'),
             ('/System/Library/Fonts/STHeiti Medium.ttc', 'Heiti TC', 'Heiti SC'),
             ('/System/Library/Fonts/Hiragino Sans GB.ttc', 'Hiragino Sans GB', 'Hiragino Sans GB')]
_cjk = {}


def font_cjk(script='trad'):
    """(file, face number) of a bold-ish font with Traditional (or Simplified) Chinese characters, or None."""
    if script in _cjk: return _cjk[script]
    from PIL import ImageFont
    import glob
    files = list(CJK_FONTS) + [(f, 'PingFang TC', 'PingFang SC') for f in glob.glob('/System/Library/AssetsV2/com_apple_MobileAsset_Font*/*/AssetData/PingFang.ttc')]
    found = None
    for path, trad, simp in files:
        if not os.path.exists(path): continue
        want, faces = (simp if script == 'simp' else trad), []
        for i in range(40):
            try: faces.append((i, ImageFont.truetype(path, 20, index=i).getname()))
            except Exception: break
        mine = [(i, style) for i, (fam, style) in faces if fam == want]
        if not mine: continue
        pick = next((i for i, st in mine if st in ('Semibold', 'Medium', 'W6', 'Bold')), mine[0][0])
        found = (path, pick); break
    _cjk[script] = found
    return found


def han(texts, script):
    """Chinese text in Traditional ('trad') or Simplified ('simp') characters, with the Mac's own converter
    (nothing to install, nothing leaves the Mac). texts: list of strings; returns the same number of strings."""
    import json
    if not texts: return []
    js = ('ObjC.import("Foundation"); function run(a){ var r = JSON.parse(a[0]).map(function(t){ '
          'return $(t).stringByApplyingTransformReverse("Hans-Hant", ' + ('true' if script == 'simp' else 'false') + ').js; }); return JSON.stringify(r); }')
    r = subprocess.run(['/usr/bin/osascript', '-l', 'JavaScript', '-e', js, json.dumps(list(texts), ensure_ascii=False)],
                       capture_output=True, text=True, timeout=30)
    out = json.loads(r.stdout)
    if len(out) != len(texts): raise RuntimeError('convert failed')
    return out


def install_steps(item, pack_dir, python):
    """Commands that install one setup item, run only after the buyer clicks Install. None = the buyer does it."""
    brew = tool('brew')
    if item == 'brew': return None   # needs the Mac password in Terminal; we show the one line instead
    if item in ('ffmpeg', 'whisper', 'node'):
        if not brew: return None
        return [[brew, 'install', {'ffmpeg': 'ffmpeg', 'whisper': 'whisper-cpp', 'node': 'node'}[item]]]
    if item == 'python':
        venv = os.path.join(pack_dir, '.venv')
        return [[python, '-m', 'venv', venv],
                [os.path.join(venv, 'bin', 'python'), '-m', 'pip', 'install', '-q', '-r', os.path.join(pack_dir, 'requirements.txt')]]
    if item == 'model':
        dst = whisper_model(); os.makedirs(os.path.dirname(dst), exist_ok=True)
        return [['curl', '-L', '--fail', '-o', dst + '.part', MODEL_URL], ['mv', dst + '.part', dst]]
    return None


BREW_LINE = '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'


def pick_files(prompt='Choose your takes'):
    """The Mac's own file picker. Returns real paths (nothing is copied)."""
    script = (f'set fs to choose file with prompt "{prompt}" of type {{"public.movie"}} with multiple selections allowed\n'
              'set out to ""\nrepeat with f in fs\nset out to out & POSIX path of f & linefeed\nend repeat\nreturn out')
    r = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
    if r.returncode != 0: return []   # cancelled
    return [l for l in r.stdout.splitlines() if l.strip()]


def reveal(path):
    if os.environ.get('CPACK_NO_BROWSER'): return   # headless runs: no Finder window
    subprocess.run(['open', '-R', path], capture_output=True)


def open_folder(path):
    """The folder in a Finder window."""
    if os.environ.get('CPACK_NO_BROWSER'): return
    subprocess.run(['open', path], capture_output=True)


def open_url(url):
    if os.environ.get('CPACK_NO_BROWSER'): return   # headless runs and tests: no browser window
    subprocess.run(['open', url], capture_output=True)
