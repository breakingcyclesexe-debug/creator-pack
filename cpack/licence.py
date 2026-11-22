"""Licence key check for the paid version. Off for the beta: with licence_required false nothing is checked,
nothing is shown and nothing goes over the network.

When it is on, the buyer's key is checked with Polar when the page asks for its state. The check needs no account
or secret on the Mac: Polar's customer-portal validate endpoint is made for desktop apps.
  POST https://api.polar.sh/v1/customer-portal/license-keys/validate   body {"key", "organization_id"}
  200 = good (status "granted"); 404 = not found, revoked, disabled or expired; 400 = usage used up; 422 = bad body.
  Docs: https://polar.sh/docs/api-reference/customer-portal/license-keys/validate (read 22 Nov 2026)

Offline: a key that passed once keeps working for GRACE_DAYS after its last good check, so someone filming
somewhere without signal can still cut. After that the page asks for an internet connection once.

Settings live in licence.json next to this file (shipped with the pack). CPACK_LICENCE_REQUIRED=1 turns it on
for testing. The key and the last good check are kept in <data home>/licence.json, outside the pack."""
import datetime, json, os, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
GRACE_DAYS = 7
CHECK_EVERY = 6 * 3600   # once a good check is this fresh, don't ask Polar again (the page polls every few seconds)
DEFAULTS = {'licence_required': False, 'organization_id': '', 'benefit_id': '',
            'api': 'https://api.polar.sh/v1/customer-portal/license-keys/validate', 'buy_url': ''}


def settings():
    s = dict(DEFAULTS)
    try:
        with open(os.path.join(HERE, 'licence.json')) as f: s.update(json.load(f) or {})
    except (OSError, ValueError): pass
    env = os.environ.get('CPACK_LICENCE_REQUIRED')
    if env is not None: s['licence_required'] = env.strip().lower() in ('1', 'true', 'yes', 'on')
    return s


def required(): return bool(settings()['licence_required'])


def _state_file():
    from .platform import get
    return os.path.join(get().data_home(), 'licence.json')


def _load():
    try:
        with open(_state_file()) as f: return json.load(f) or {}
    except (OSError, ValueError): return {}


def _save(st):
    p = _state_file(); os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + '.tmp'
    with open(tmp, 'w') as f: json.dump(st, f, indent=1)
    os.replace(tmp, p)


def validate_online(key, s=None, timeout=8):
    """One call to Polar. Returns ('ok', body) / ('bad', reason) / ('offline', reason). Never raises."""
    s = s or settings()
    body = {'key': key, 'organization_id': s['organization_id']}
    if s.get('benefit_id'): body['benefit_id'] = s['benefit_id']
    req = urllib.request.Request(s['api'], data=json.dumps(body).encode(), method='POST',
                                 headers={'Content-Type': 'application/json', 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        if e.code in (404, 422): return 'bad', 'That key is not active. Check it, or get a new one.'
        if e.code == 400: return 'bad', 'That key has been used up.'
        return 'offline', f'The licence server answered {e.code}.'
    except (urllib.error.URLError, OSError, ValueError):
        return 'offline', 'No internet connection.'
    if data.get('status') != 'granted': return 'bad', 'That key is not active.'
    exp = data.get('expires_at')
    if exp:
        try:
            if datetime.datetime.fromisoformat(exp.replace('Z', '+00:00')).timestamp() < time.time():
                return 'bad', 'That key has run out.'
        except ValueError: pass
    return 'ok', data


def status(now=None, online=True):
    """What the page shows. {'required': False, 'ok': True} when the licence check is off (the beta)."""
    if not required(): return {'required': False, 'ok': True}
    now = now or time.time()
    st = _load(); key = st.get('key', '')
    out = {'required': True, 'ok': False, 'has_key': bool(key), 'buy_url': settings().get('buy_url', '')}
    if not key: return dict(out, reason='Add your licence key.')
    last = st.get('last_ok')
    if last and 0 <= now - last < CHECK_EVERY: return dict(out, ok=True)
    if online:
        res, info = validate_online(key)
        if res == 'ok':
            st['last_ok'] = now; _save(st)
            return dict(out, ok=True)
        if res == 'bad':
            st.pop('last_ok', None); _save(st)
            return dict(out, reason=info)
    if last and now - last <= GRACE_DAYS * 86400:
        return dict(out, ok=True, offline=True, days_left=GRACE_DAYS - int((now - last) // 86400))
    return dict(out, reason='Connect to the internet once so the pack can check your licence.')


def set_key(key, now=None):
    key = (key or '').strip()
    if not key or len(key) > 200: raise ValueError('That does not look like a licence key.')
    st = _load(); st['key'] = key; st.pop('last_ok', None); _save(st)
    return status(now)
