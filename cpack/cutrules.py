"""The cut rules, as pure functions over word lists. No audio here (edges.py snaps the edges to real silence).

A word is {"w": text as heard, "s": start s, "e": end s, "p": confidence}; prepare() adds "i" (index in the take)
and "n" (normalised text).

For each beat of the approved story (a time span in one take) the rules run in this order:
  1. Fillers (switch "fillers"): um / uh / erm / ah / hmm always go; like / basically / yeah / okay / right / so /
     actually, and "you know" / "i mean" / "you see", go only when they stand alone (a pause or a comma on them),
     so "like a software" and "you know what you want" stay.
  2. Restarts (switch "repeats"): a run of 1-4 words said twice in a row ("the the", "analysis from analysis from")
     keeps the last copy. "that that" / "very very" stay unless the first one broke off.
  3. Retakes (switch "repeats"): a 3+ word run said again within 10 words, a 2-word run restarted within 3, or
     "X the, X": the earlier attempt goes, the last take stays. A single word left said twice in a row by that cut
     ("out like ... like I am") loses its first copy. When the transcript marks broken-off words with "-",
     a run said again after a finished phrase is a list or emphasis ("I love to be in the mountains, I love to be
     off-grid") and stays. A lone "and" / "so" left before a dropped attempt goes too.
  4. Pauses (switch "pauses"): a clip splits where the gap between two kept words is over max_pause (0.7 s).
  5. Edge room (setting "breath"): in = first word start - pre, out = last word end + post, never closer than
     20 ms to the neighbouring word in the take.
  6. Breath runs: two clips that sit back to back in the same take (gap under max_pause, nothing dropped between)
     become one clip, so a few sentences said in one breath are one cut.
"""
import re

ALWAYS = {'um', 'umm', 'uh', 'uhh', 'erm', 'ah', 'hmm', 'mm', 'uhm'}
LOOSE1 = {'like', 'basically', 'yeah', 'okay', 'ok', 'right', 'so', 'actually'}
LOOSE2 = {('you', 'know'), ('i', 'mean'), ('you', 'see')}
STANDALONE = 0.25   # a pause this long either side makes a loose filler "stand alone"
ROOM = {'tight': (0.04, 0.08), 'normal': (0.10, 0.20), 'relaxed': (0.22, 0.42)}  # (before the voice starts, after it stops):
# a join's pause is about post + pre of silence, so 0.12 s / 0.3 s / 0.64 s (CT-130: the setting must be heard)
RSTOP = {'the', 'a', 'to', 'and', 'i', 'you', 'is', 'it', 'of', 'that', 'in', 'what', 'are', 'be', 'so', 'we', 'they', 'or'}
CONJ = {'and', 'so', 'but', 'or', 'then'}
MEANT_DOUBLE = {'that', 'had', 'very', 'so', 'no', 'really'}
DEFAULTS = {'fillers': True, 'repeats': True, 'pauses': True, 'max_pause': 0.7, 'breath': 'normal'}


def norm(w):
    # Chinese characters count as words too (Cantonese and Mandarin takes); everything else as before
    return re.sub(r"[^a-z0-9'\u3400-\u9fff]", '', w.lower())


def prepare(words):
    for i, w in enumerate(words):
        w['i'] = i; w['n'] = norm(w['w'])
    return words


def _settings(s):
    out = dict(DEFAULTS); out.update({k: v for k, v in (s or {}).items() if v is not None})
    if out['breath'] not in ROOM: out['breath'] = 'normal'
    return out


def clean_span(W, a, b, settings=None):
    """Words of take W whose middle sits in [a, b], after the rules. Returns (runs, log, retakes, kept_reps):
    runs = lists of kept words, split at dropped words and long pauses."""
    st = _settings(settings)
    marks = any(w['w'].strip() == '-' or w['w'].strip().endswith('-') for w in W)
    broke = lambda w: w['w'].strip().endswith('-') or (w['i'] + 1 < len(W) and W[w['i'] + 1]['w'].strip() == '-')
    ws = [w for w in W if a - 0.02 <= (w['s'] + w['e']) / 2 <= b + 0.02 and w['n']]
    drop, log, retakes, kept_reps = set(), [], [], []

    def note(kind, *xs):
        log.append({'kind': kind, 'at': round(xs[0]['s'], 2), 'text': ' '.join(x['w'].strip() for x in xs)})

    if st['fillers']:
        for k, w in enumerate(ws):
            prev_gap = w['s'] - ws[k - 1]['e'] if k else 9
            nxt = ws[k + 1] if k + 1 < len(ws) else None
            if w['n'] in ALWAYS:
                drop.add(w['i']); note('filler', w); continue
            if nxt and (w['n'], nxt['n']) in LOOSE2:
                after = (ws[k + 2]['s'] - nxt['e']) if k + 2 < len(ws) else 9
                if prev_gap > STANDALONE or after > STANDALONE or nxt['w'].rstrip().endswith(','):
                    drop.update({w['i'], nxt['i']}); note('filler', w, nxt); continue
            if w['n'] in LOOSE1:
                after = (nxt['s'] - w['e']) if nxt else 9
                comma = w['w'].rstrip().endswith(',')
                if (comma or after > STANDALONE) and prev_gap > STANDALONE or (comma and k == 0):
                    drop.add(w['i']); note('filler', w)

    def restarts(sizes=(4, 3, 2, 1)):
        kept = [w for w in ws if w['i'] not in drop]
        k = 0
        while k < len(kept):
            hit = False
            for n in sizes:
                x, y = kept[k:k + n], kept[k + n:k + 2 * n]
                if len(y) == n and [q['n'] for q in x] == [q['n'] for q in y] and not re.search(r'[.?!]$', x[-1]['w'].strip()):
                    if n == 1 and x[0]['n'] in MEANT_DOUBLE and not broke(x[0]): continue
                    drop.update(q['i'] for q in x); note('restart', *x); kept = kept[:k] + kept[k + n:]; hit = True; break
            if not hit: k += 1

    if st['repeats']:
        restarts()
        retook = True
        while retook:
            retook = False; kept = [w for w in ws if w['i'] not in drop]; t = [w['n'] for w in kept]
            for i in range(len(t)):
                for j in range(i + 1, min(len(t), i + 11)):
                    m = 0
                    while j + m < len(t) and i + m < j and t[i + m] == t[j + m]: m += 1
                    long_run = m >= 3 and any(x not in RSTOP for x in t[i:i + m])
                    deliberate = marks and not broke(kept[j - 1])
                    if m <= 2 and re.search(r'[.?!]$', kept[i + m - 1]['w'].strip()):
                        continue   # "on the side. A side hustle": a short run that ended a sentence was finished, not restarted
                    if long_run and deliberate:
                        if not any(p <= kept[i]['i'] < q for p, q, _ in kept_reps):
                            kept_reps.append((kept[i]['i'], kept[j]['i'], (kept[i:j], kept[j:j + m + 3])))
                        continue
                    if (long_run and not deliberate) or (m == 2 and j - i <= 3) or (m == 1 and j == i + 2 and t[i] not in RSTOP):
                        gone = kept[i:j]; drop.update(x['i'] for x in gone); note('retake', *gone)
                        retakes.append({'at': round(gone[0]['s'], 2), 'dropped': ' '.join(x['w'].strip() for x in gone),
                                        'kept': ' '.join(x['w'].strip() for x in kept[j:j + m + 3]), 'first': gone[0]['i']})
                        retook = True; break
                if retook: break
        # a retake cut out can leave one small word on each side of it ("out like | this, like, like I did, | like I am"):
        # said twice in a row now, so the first one goes too (a tester, 22 Nov: small repeated words are cut, never listed)
        if retakes: restarts((1,))
        firsts = {r['first'] for r in retakes}
        for k, w in enumerate(ws):
            if w['i'] not in drop and w['n'] in CONJ and k + 1 < len(ws) and ws[k + 1]['i'] in firsts:
                drop.add(w['i']); note('stranded', w)

    kept = [w for w in ws if w['i'] not in drop]
    runs, cur = [], []
    for w in kept:
        if cur and ((st['pauses'] and w['s'] - cur[-1]['e'] > st['max_pause'])
                    or any(j in drop for j in range(cur[-1]['i'] + 1, w['i']))):
            runs.append(cur); cur = []
        cur.append(w)
    if cur: runs.append(cur)
    reps = [{'at': round(f[0]['s'], 2), 'first': ' '.join(x['w'].strip() for x in f), 'again': ' '.join(x['w'].strip() for x in g)}
            for _, _, (f, g) in kept_reps]
    return runs, log, retakes, reps


def clip_of(W, run, take, st, beat=None):
    pre, post = ROOM[st['breath']]
    a, b = run[0], run[-1]
    prev_e = W[a['i'] - 1]['e'] if a['i'] else -9
    next_s = W[b['i'] + 1]['s'] if b['i'] + 1 < len(W) else b['e'] + 9
    i_ = max(a['s'] - pre, prev_e + 0.02, 0.0)
    o_ = min(b['e'] + post, next_s - 0.02)
    fl = (W[a['i'] - 1]['s'] + W[a['i'] - 1]['e']) / 2 if a['i'] else 0.0   # neighbour words' middles: snapping never reaches them
    ce = (W[b['i'] + 1]['s'] + W[b['i'] + 1]['e']) / 2 if b['i'] + 1 < len(W) else b['e'] + 1
    return {'take': take, 'in': round(i_, 3), 'out': round(o_, 3), 'text': ''.join(w['w'] for w in run).strip(),
            'words': run, 'beat': beat, 'fl': fl, 'ce': ce, 'ws': a['s'], 'we': b['e']}


def cut_beats(beats, takes, settings=None):
    """beats: [{"take", "start", "end", "id"?}] in story order; takes: {take: prepared words}.
    Returns {"clips": [...], "log": [...], "retakes": [...], "kept_repeats": [...]}."""
    st = _settings(settings)
    clips, log, retakes, reps = [], [], [], []
    for bi, bt in enumerate(beats):
        W = takes[bt['take']]
        runs, lg, rt, rp = clean_span(W, bt['start'], bt['end'], st)
        log += lg; retakes += rt; reps += rp
        for r in runs:
            c = clip_of(W, r, bt['take'], st, bt.get('id', bi))
            i0, i1 = r[0]['i'], r[-1]['i']
            mid = lambda w: (w['s'] + w['e']) / 2
            # an edge is "free" when the word next to it lies outside the beat (not one the rules cut out): if
            # the speech runs on with no pause there, the edge may take that word in rather than cut through it
            c['in_free'] = i0 == 0 or mid(W[i0 - 1]) < bt['start'] - 0.02
            c['out_free'] = i1 + 1 >= len(W) or mid(W[i1 + 1]) > bt['end'] + 0.02
            c['before'], c['after'] = W[max(0, i0 - 3):i0], W[i1 + 1:i1 + 4]
            if c['out'] - c['in'] >= 0.2: clips.append(c)
    k = 1
    while k < len(clips):
        p, c = clips[k - 1], clips[k]
        W = takes[c['take']]
        if p['take'] == c['take'] and 0 <= c['ws'] - p['we'] < st['max_pause'] and \
                not [w for w in W if w['n'] and p['we'] < (w['s'] + w['e']) / 2 < c['ws']]:
            p.update(out=c['out'], text=(p['text'] + ' ' + c['text']).strip(), ce=c['ce'], we=c['we'], words=p['words'] + c['words'],
                     out_free=c['out_free'], after=c['after'])
            clips.pop(k)
        else: k += 1
    return {'clips': clips, 'log': log, 'retakes': retakes, 'kept_repeats': reps}
