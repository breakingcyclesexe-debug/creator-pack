"""The local page's server. Listens on 127.0.0.1 only; nothing is uploaded anywhere, and nothing here talks to Claude.

Safety rules (spec acceptance criterion 4):
- binds 127.0.0.1, refuses any Host header that isn't this machine (stops DNS-rebinding pages from reaching it)
- every POST needs the X-CPack header (a page on another site can't send it without a blocked preflight)
- files are served only from the pack's ui folder and from a project's own folder, checked after resolving links
"""
import json, mimetypes, os, re, shutil, threading, time, traceback
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote
from . import project as prj, pipeline, jobs, setup_check, qa, licence
from .platform import get as platform

P = platform()
UI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'ui')
FONTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'fonts')
VIDEO_EXT = {'.mov', '.mp4', '.m4v', '.mkv', '.avi', '.mts', '.webm'}
MAX_JSON = 1 << 20
WAITLIST_URL = os.environ.get('CPACK_WAITLIST_URL', 'https://breakingcycles.life')   # Story Studio "I want this": point at the real page later


def inside(base, path):
    base = os.path.realpath(base); path = os.path.realpath(path)
    return path == base or path.startswith(base + os.sep)


def background(pid, fn, *a):
    def go():
        try: fn(pid, *a)
        except Exception as e:
            traceback.print_exc()
            try: prj.update(pid, lambda pj: pj.update(errors=[str(e)[:500]], progress=None))
            except Exception: pass
    threading.Thread(target=go, daemon=True).start()


def sections(pid, v, labels):
    """The finished video as its story sections, for the read-only timeline: consecutive clips of one beat are one section."""
    rep = prj.read_json(os.path.join(prj.folder(pid), f'v{int(v)}', 'cut.json'), {}) or {}
    out, t = [], 0.0
    for c in rep.get('clips', []):
        d = float(c.get('dur') or 0)
        if out and out[-1]['beat'] == c.get('beat'): out[-1]['end'] = round(t + d, 2)
        else: out.append({'beat': c.get('beat'), 'label': labels.get(c.get('beat'), ''), 'start': round(t, 2), 'end': round(t + d, 2)})
        t += d
    return out


def project_view(pid):
    pj = prj.load(pid)
    pj['story_versions'] = pipeline.story_versions(pid)
    pj['storyboard'] = pipeline.load_story(pid)
    labels = {b['id']: b.get('label', '') for b in (pj['storyboard'] or {}).get('beats', [])}
    for v in pj['versions']:
        v['sections'] = sections(pid, v['v'], labels)
        if isinstance(v.get('qa'), dict) and 'items' in v['qa']: v['qa'] = dict(v['qa'], items=qa.surface(v['qa']['items']))
        v['captions_stale'] = pipeline.stale_captions(pj, v)
    pj['fixes'] = pj.pop('caption_fixes', None) or {}
    pj['title'] = prj.title_of(pj, pj['storyboard'])
    pj['chat'] = prj.chat(pid)
    pj['jobs'] = [{k: j.get(k) for k in ('id', 'type', 'status', 'text', 'reply', 'created', 'taken')} for j in jobs.listing(prj.jobs_dir(), pid)][-20:]
    pj['folder_name'] = os.path.basename(pj['folder']) if pj.get('folder') else ''
    rel = os.path.relpath(pj['folder'], os.path.expanduser('~')) if pj.get('folder') else ''
    pj['folder_where'] = ' › '.join(rel.split(os.sep)) if rel and not rel.startswith('..') else pj.get('folder', '')
    pj.pop('folder', None); pj.pop('removed_paths', None)   # the page never needs full paths
    for t in pj['takes']:
        t['has_proxy'] = os.path.exists(pipeline.cache(pid, f'proxy-{t["name"]}.mp4'))
        t.pop('path', None)   # the page never needs the full path
    return pj


def interest(body):
    """A "Coming next" feature someone wants (Story Studio). Opens the waitlist page and notes the click in the
    project's own settings on this Mac. Nothing is sent anywhere."""
    what = str(body.get('what', ''))
    if what != 'story_studio': raise ValueError('unknown feature')
    pid = str(body.get('project') or '')
    if prj.valid_id(pid) and os.path.exists(os.path.join(prj.folder(pid), 'project.json')):
        prj.update(pid, lambda pj: pj['settings'].setdefault('interest', {}).update({what: time.time()}))
    P.open_url(WAITLIST_URL)
    return {'ok': True, 'url': WAITLIST_URL}


class Handler(BaseHTTPRequestHandler):
    server_version = 'CreatorPack/1'

    def log_message(self, fmt, *a):
        if os.environ.get('CPACK_DEBUG'): super().log_message(fmt, *a)

    # ---- guards
    def _host_ok(self):
        host = (self.headers.get('Host') or '').lower()
        port = self.server.server_address[1]
        if host not in (f'127.0.0.1:{port}', f'localhost:{port}'): return False
        origin = self.headers.get('Origin')
        return origin is None or origin in (f'http://127.0.0.1:{port}', f'http://localhost:{port}')

    def _send(self, code, body=b'', ctype='application/json', extra=None):
        self.send_response(code)
        self.send_header('Content-Type', ctype); self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store'); self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                         "font-src 'self' https://fonts.gstatic.com; script-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:")
        for k, v in (extra or {}).items(): self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD': self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode())

    def _err(self, code, msg):
        self._json({'error': msg}, code)

    def _body(self):
        n = int(self.headers.get('Content-Length') or 0)
        if n > MAX_JSON: raise ValueError('too big')
        raw = self.rfile.read(n) if n else b'{}'
        return json.loads(raw or b'{}')

    # ---- files
    def _file(self, path, ctype=None):
        if not os.path.isfile(path): return self._err(404, 'not found')
        size = os.path.getsize(path); ctype = ctype or mimetypes.guess_type(path)[0] or 'application/octet-stream'
        rng = self.headers.get('Range')
        m = re.match(r'bytes=(\d*)-(\d*)$', rng or '')
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                a = int(m.group(1)); b = int(m.group(2)) if m.group(2) else size - 1
            else:
                a = max(0, size - int(m.group(2))); b = size - 1
            b = min(b, size - 1)
            if a > b: return self._send(416, b'', extra={'Content-Range': f'bytes */{size}'})
            self.send_response(206)
            self.send_header('Content-Range', f'bytes {a}-{b}/{size}'); length = b - a + 1
        else:
            a, length = 0, size; self.send_response(200)
        self.send_header('Content-Type', ctype); self.send_header('Content-Length', str(length))
        self.send_header('Accept-Ranges', 'bytes'); self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        if self.command == 'HEAD': return
        with open(path, 'rb') as f:
            f.seek(a); left = length
            try:
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk: break
                    self.wfile.write(chunk); left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError): pass

    def do_HEAD(self): self.do_GET()

    def do_GET(self):
        if not self._host_ok(): return self._err(403, 'local only')
        u = urlparse(self.path); path = unquote(u.path)
        try:
            if path == '/favicon.ico': return self._send(204)
            if path in ('/', '/index.html'): return self._file(os.path.join(UI, 'index.html'), 'text/html; charset=utf-8')
            if path.startswith('/fonts/'):   # the caption fonts in the pack, for the Look preview
                f = os.path.join(FONTS, path[7:])
                return self._file(f, 'font/ttf') if inside(FONTS, f) and f.endswith('.ttf') else self._err(404, 'not found')
            if path.startswith('/ui/'):
                f = os.path.join(UI, path[4:])
                return self._file(f) if inside(UI, f) else self._err(404, 'not found')
            if path == '/api/state':
                return self._json({'setup': setup_check.detect(), 'connected': jobs.connected(prj.jobs_dir()),
                                   'projects': prj.listing(), 'home': prj.home(), 'exports': prj.exports_dir(), 'prefs': prj.prefs()})
            m = re.fullmatch(r'/api/project/([a-z0-9-]+)/captions/(\d+)', path)
            if m: return self._json(pipeline.captions_view(m.group(1), int(m.group(2))))
            m = re.fullmatch(r'/api/project/([a-z0-9-]+)', path)
            if m: return self._json(project_view(m.group(1)))
            m = re.fullmatch(r'/media/([a-z0-9-]+)/(frame|proxy|video)/(.+)', path)
            if m:
                pid, kind, name = m.groups()
                base = prj.folder(pid)
                f = {'frame': lambda: pipeline.cache(pid, f'frame-{name}.jpg'),
                     'proxy': lambda: pipeline.cache(pid, f'proxy-{name}.mp4'),
                     'video': lambda: os.path.join(base, f'v{int(name)}', 'video.mp4') if name.isdigit() else ''}[kind]()
                if not f or not inside(base, f): return self._err(404, 'not found')
                return self._file(f)
            return self._err(404, 'not found')
        except KeyError: return self._err(404, 'no such project')
        except ValueError as e: return self._err(400, str(e))

    def do_POST(self):
        if not self._host_ok() or self.headers.get('X-CPack') != '1': return self._err(403, 'local page only')
        u = urlparse(self.path); path = unquote(u.path)
        try:
            if path == '/api/setup/install':
                return self._json({'started': setup_check.install(self._body().get('ids', []))})
            if path == '/api/licence':
                if not licence.required(): return self._err(404, 'not found')
                return self._json(licence.set_key(self._body().get('key', '')))
            if path == '/api/interest':
                return self._json(interest(self._body()))
            if path == '/api/project/new':
                return self._json(prj.create())
            if path == '/api/prefs':
                return self._json(prj.save_prefs(self._body()))
            m = re.fullmatch(r'/api/project/([a-z0-9-]+)/(\w+)', path)
            if not m: return self._err(404, 'not found')
            pid, act = m.groups(); prj.load(pid)
            if act == 'upload': return self._upload(pid, parse_qs(u.query).get('name', [''])[0])
            body = self._body()
            if act == 'pick':
                paths = P.pick_files()
                added, errors = pipeline.add_takes(pid, paths)
                return self._json({'added': added, 'errors': errors})
            if act == 'add':
                paths = [str(x) for x in (body.get('paths') or [])][:20]
                added, errors = pipeline.add_takes(pid, [x for x in paths if os.path.splitext(x)[1].lower() in VIDEO_EXT])
                if len(added) < len(paths) and not errors: errors = ['Only video files can be added']
                return self._json({'added': added, 'errors': errors})
            if act == 'remove_take':
                return self._json(pipeline.remove_take(pid, str(body.get('name', ''))))
            if act == 'scan':
                return self._json(pipeline.scan(pid))
            if act == 'open_folder':
                pj = prj.load(pid); d = prj.sub(pj, str(body.get('sub') or 'Footage'))
                prj.update(pid, lambda x: x.update(folder=pj['folder']))
                P.open_folder(d); return self._json({'path': d})
            if act == 'fit_new':
                background(pid, pipeline.fit_new); return self._json({'started': True})
            if act == 'fresh':
                background(pid, pipeline.start_fresh); return self._json({'started': True})
            if act == 'story_version':
                pipeline.use_story_version(pid, int(body.get('n', 0))); return self._json({'ok': True})
            if act == 'dismiss_back':
                prj.update(pid, lambda pj: pj.update(offer_back=None)); return self._json({'ok': True})
            if act == 'rename':
                prj.rename(pid, body.get('title')); return self._json({'projects': prj.listing()})
            if act == 'settings':
                pj = prj.update(pid, lambda pj: pj.update(settings=prj.merge_settings(pj['settings'], body)))
                return self._json(pj['settings'])
            if act == 'turn':
                name = str(body.get('name', ''))
                if not any(t['name'] == name for t in prj.load(pid)['takes']): return self._err(400, 'no such clip')
                return self._json({'name': name, 'turn': pipeline.turn_take(pid, name, by=body.get('by'), to=body.get('to'))})
            if act == 'go':
                if not prj.load(pid)['takes']: return self._err(400, 'Add a take first')
                background(pid, pipeline.hear); return self._json({'started': True})
            if act == 'story':
                return self._json(pipeline.edit_story(pid, body))
            if act == 'cut':
                background(pid, pipeline.cut); return self._json({'started': True})
            if act in ('change', 'chat'):
                text = str(body.get('text', '')).strip()
                if not text: return self._err(400, 'Say what should change')
                prj.add_chat(pid, 'you', text, part=body.get('part'))
                j = jobs.new(prj.jobs_dir(), act, pid, text, part=body.get('part'))
                return self._json({'job': j['id']})
            if act == 'fix_word':
                # a caption word put right: saved for this video, then the captions of the version on screen are drawn again
                v = int(body.get('v') or 0)
                if not any(x['v'] == v for x in prj.load(pid)['versions']): return self._err(400, 'no such version')
                fixes = pipeline.fix_word(pid, body.get('from'), body.get('to'))
                background(pid, pipeline.recaption, v)
                return self._json({'fixes': fixes, 'started': True})
            if act == 'recaption':
                v = int(body.get('v') or 0)
                if not any(x['v'] == v for x in prj.load(pid)['versions']): return self._err(400, 'no such version')
                background(pid, pipeline.recaption, v); return self._json({'started': True})
            if act == 'export':
                out = pipeline.export(pid, body.get('v'))
                if body.get('reveal', True) and not os.environ.get('CPACK_NO_REVEAL'): P.reveal(out)   # tests keep Finder shut
                return self._json({'path': out})
            return self._err(404, 'not found')
        except KeyError: return self._err(404, 'no such project')
        except (ValueError, RuntimeError) as e: return self._err(400, str(e))

    def _upload(self, pid, name):
        name = os.path.basename(name or '')
        if not name or os.path.splitext(name)[1].lower() not in VIDEO_EXT: return self._err(400, 'Drop a video file')
        n = int(self.headers.get('Content-Length') or 0)
        pj = prj.load(pid); foot = prj.sub(pj, 'Footage')
        prj.update(pid, lambda x: x.update(folder=pj['folder']))
        dst = os.path.join(foot, name)
        if not inside(foot, dst): return self._err(400, 'bad name')
        if os.path.exists(dst):
            stem, ext = os.path.splitext(name); n = 2
            while os.path.exists(os.path.join(foot, f'{stem}-{n}{ext}')): n += 1
            dst = os.path.join(foot, f'{stem}-{n}{ext}')
        tmp = dst + '.part'
        with open(tmp, 'wb') as f:
            left = n
            while left > 0:
                chunk = self.rfile.read(min(1 << 20, left))
                if not chunk: break
                f.write(chunk); left -= len(chunk)
        if left: os.remove(tmp); return self._err(400, 'upload cut short')
        os.replace(tmp, dst)
        added, errors = pipeline.add_takes(pid, [dst])
        return self._json({'added': added, 'errors': errors})


def serve(port=8765, open_browser=False):
    for p in range(port, port + 20):
        try:
            httpd = ThreadingHTTPServer(('127.0.0.1', p), Handler); break
        except OSError: continue
    else: raise SystemExit('no free port')
    httpd.daemon_threads = True
    url = f'http://127.0.0.1:{httpd.server_address[1]}/'
    os.makedirs(prj.home(), exist_ok=True)
    with open(os.path.join(prj.home(), 'server.url'), 'w') as f: f.write(url)
    print(url, flush=True)
    if open_browser: P.open_url(url)
    httpd.serve_forever()
