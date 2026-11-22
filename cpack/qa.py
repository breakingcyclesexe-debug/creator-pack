"""Check the finished video before the buyer sees it: shape, size, and the cut heard again from the file itself.

  shape      output shape vs the shape asked for (source shape counts the rotation flag)
  heard      the output transcribed once (fast path) and lined up with the words the cut meant to keep:
             missing words next to a join = a clipped word; fillers heard; words said twice in a row
  sync       picture and sound streams the same length (one frame rate, whole frames per clip: CT-132)
  lip_sync   voice against lips measured in the finished file at the middle of every clip (syncqa, CT-133);
             over 40 ms anywhere fails the cut and is the first thing on the finish screen
  items      everything not clean, from the self-check (render) and from this hearing, each with its time,
             a plain sentence and a ready chat request, so the finish screen never shows a warning without a fix
  rank       objective errors are repaired by the self-check; what is left is ranked by how audible it is and
             only the top 3 are shown as worth a look (show=True). Nothing else is listed anywhere.
  small      a small word said twice ("but but", "and and", "for for") is cut by the self-check, never listed;
             a small word that "may be cut short" counts for less, so only real, audible spots are shown.
"""
import difflib, os, re, subprocess
import numpy as np
from . import media, shape, transcribe, syncqa
from .cutrules import norm, ALWAYS, MEANT_DOUBLE, RSTOP, CONJ, LOOSE1

SMALL = RSTOP | CONJ | LOOSE1 | {'for', 'at', 'on', 'with', 'this', 'my', 'if', 'as', 'was', 'just', 'not', 'do', 'have', 'from',
                                 'your', 'when', 'there', 'then', 'well', 'because', "it's", "i'm", 'know', 'mean', 'me', 'he', 'she',
                                 'an', 'by', 'up', 'no', 'not', 'can', 'will', 'had', 'has', 'did', 'were', 'them', 'our', 'his', 'her'}


def small(word):
    """One or two little words ("but", "and", "like", "for", "i", "you know"): nobody notices them said twice."""
    t = [norm(x) for x in str(word or '').split()]
    t = [x for x in t if x]
    return bool(t) and len(t) <= 2 and all(len(x) <= 2 or x in SMALL for x in t)


def repeats(tokens, ends=None):
    """Runs of 1-4 words said twice in a row. ends[i] = word i finished a sentence: a run said again after a
    full stop ("Everyone can build. Everyone can build now.") is emphasis, not a leftover restart."""
    out = []; ends = ends or [False] * len(tokens)
    for n in (4, 3, 2, 1):
        for i in range(len(tokens) - 2 * n + 1):
            a, b = tokens[i:i + n], tokens[i + n:i + 2 * n]
            if a == b and not (n == 1 and a[0] in MEANT_DOUBLE) and not ends[i + n - 1]:
                out.append({'at_word': i, 'text': ' '.join(a)})
    seen, uniq = set(), []
    for r in out:
        if r['at_word'] not in seen: uniq.append(r); seen.add(r['at_word'])
    return uniq


def missing_at_joins(expected, heard, joins):
    """expected/heard: token lists; joins: indexes in expected where a new clip starts."""
    sm = difflib.SequenceMatcher(None, expected, heard, autojunk=False)
    miss = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op in ('delete', 'replace'):
            for i in range(i1, i2):
                near = any(abs(i - j) <= 1 or abs(i - (j - 1)) <= 1 for j in joins)
                miss.append({'word': expected[i], 'index': i, 'near_join': near})
    return round(sm.ratio(), 3), miss


def _mmss(t): return f'{int(t // 60)}:{int(t % 60):02d}'


def items(report, hw, ht, ends, miss, joins_t, exp_join_idx):
    """Items from the whole-video hearing, merged with the self-check's (same kind within 1.5 s = one item)."""
    out = [i for i in (report.get('selfcheck') or {}).get('items', []) if not (i['kind'] == 'repeat' and small(i.get('word')))]
    def add(at, kind, word, say, ask):
        if kind == 'repeat' and small(word): return   # cut by the self-check where it can be; never listed (a tester, 22 Nov)
        if any(abs(i['at'] - at) < 1.5 and i['kind'] in (kind, 'missing' if kind == 'missing' else kind) for i in out): return
        out.append({'at': round(at, 2), 'kind': kind, 'word': word, 'say': say, 'ask': ask})
    for k, w in enumerate(hw):
        if ht[k] in ALWAYS:
            add(w['s'], 'filler', ht[k], f'An "{ht[k]}" is still in at {_mmss(w["s"])}', f'Cut the "{ht[k]}" at {_mmss(w["s"])}.')
    for r in repeats(ht, ends):
        t = hw[r['at_word']]['s']
        add(t, 'repeat', r['text'], f'"{r["text"]}" is said twice at {_mmss(t)}', f'At {_mmss(t)} "{r["text"]}" is said twice. Keep it once.')
    for m in miss:
        if not m['near_join']: continue
        j = min(range(len(exp_join_idx)), key=lambda k: abs(exp_join_idx[k] - m['index']))
        t = joins_t[j]
        add(t, 'missing', m['word'], f'"{m["word"]}" may be cut short at {_mmss(t)}',
            f'At {_mmss(t)} the word "{m["word"]}" is cut short. Move that cut so the whole word is heard.')
    return sorted(out, key=lambda i: i['at'])


def av_sync(video):
    """Milliseconds between the picture's and the sound's length in the file."""
    import json, subprocess
    r = subprocess.run([media.ff('ffprobe'), '-v', 'error', '-show_entries', 'stream=codec_type,duration', '-of', 'json', video],
                       capture_output=True, text=True)
    d = {s['codec_type']: float(s.get('duration', 0)) for s in json.loads(r.stdout or '{}').get('streams', [])}
    return round(abs(d.get('video', 0) - d.get('audio', 0)) * 1000) if 'video' in d and 'audio' in d else None


# How much each kind of leftover is noticed by a viewer, before its loudness counts (CT-134)
NOTICE = {'sync': 100, 'shape': 100, 'voice': 40, 'stray': 35, 'missing': 30, 'repeat': 20, 'filler': 15, 'unclear': 5}
SHOW_MAX, SHOW_MIN = 3, 12
SMALL_LESS = 15   # a little word that "may be cut short" or "slips in" is mostly the hearing, not the cut


def heard_as(i):
    """How audible an item is once its word's size counts."""
    less = SMALL_LESS if i.get('kind') in ('missing', 'stray') and small(i.get('word')) else 0
    return i.get('loud', -99) - less


def mark(spots):
    """The SHOW_MAX most audible spots get show=True and a number 1..3 in time order; the rest show=False."""
    for i in spots: i['show'] = False; i.pop('mark', None)
    top = sorted([i for i in spots if heard_as(i) >= SHOW_MIN], key=lambda i: -heard_as(i))[:SHOW_MAX]
    for n, i in enumerate(sorted(top, key=lambda i: i['at']), 1): i['show'] = True; i['mark'] = n
    return spots


def surface(items):
    """What the finish screen may show of a cut's items, old cuts included: no small repeats, at most 3 marked."""
    out = [dict(i) for i in (items or []) if not (i.get('kind') == 'repeat' and small(i.get('word')))]
    for i in out:
        if 'loud' not in i: i['loud'] = float(NOTICE.get(i.get('kind'), 10) - 30)   # cuts from before the ranking: no loudness known
    return mark(out)


def _level(video):
    """Peak dB of the finished sound in 20 ms frames, and the speaking level (80th percentile)."""
    b = subprocess.run([media.ff('ffmpeg'), '-v', 'error', '-i', video, '-map', '0:a:0', '-ac', '1', '-ar', '16000', '-f', 'f32le', '-'],
                       capture_output=True).stdout
    x = np.frombuffer(b, np.float32)
    n = len(x) // 320
    if not n: return np.zeros(0), 0.0
    db = 20 * np.log10(np.sqrt((x[:n * 320].reshape(n, 320).astype(np.float64) ** 2).mean(axis=1)) + 1e-9)
    return db, float(np.percentile(db, 80))


def rank(items, db=None, speech=0.0):
    """One item per spot (within 0.5 s, the most noticeable kind leads), each with 'loud': how audible it is
    (kind first, then how loud the sound right at the spot is against the speaking level), the top SHOW_MAX above SHOW_MIN
    marked show=True, numbered 1..3 in time order."""
    spots = []
    for i in sorted(items, key=lambda i: i['at']):
        if i['kind'] == 'repeat' and small(i.get('word')): continue
        if spots and abs(i['at'] - spots[-1]['at']) < 0.5:
            if NOTICE.get(i['kind'], 10) > NOTICE.get(spots[-1]['kind'], 10): spots[-1] = dict(i, also=spots[-1]['kind'])
            continue
        spots.append(dict(i))
    for i in spots:
        rel = -30.0
        if db is not None and len(db):
            # mean power 0.1 s either side of the spot: a cut short or a stray bit sits right at the cut, and a cut
            # on near-silence is barely heard (the loudest frame alone was at speaking level almost everywhere)
            a, b = max(0, int((i['at'] - 0.1) * 50)), int((i['at'] + 0.1) * 50) + 1
            if a < len(db):
                m = 10 * np.log10(np.mean(10 ** (db[a:b] / 10)))
                rel = max(-30.0, min(0.0, float(m) - speech))
        i['loud'] = round(NOTICE.get(i['kind'], 10) + rel, 1)
    return mark(spots)


def lip_sync(video, report):
    """syncqa on the finished file against its own clip files (segments/ next to it)."""
    folder = os.path.join(os.path.dirname(video), 'segments')
    segs = [os.path.join(folder, f'seg{n:04d}.mov') for n in range(len(report['clips']))]
    if not all(os.path.exists(p) for p in segs): return None
    rows = syncqa.measure(video, segs, [c['dur'] for c in report['clips']], report.get('caption_band'))
    return dict(syncqa.verdict(rows), rows=rows)


def check(video, report, want_wh, language='auto'):
    pr = media.probe(video)
    ow, oh = pr['shown_w'], pr['shown_h']
    out = {'size_mb': round(os.path.getsize(video) / 1e6, 1), 'duration': pr['duration'], 'width': ow, 'height': oh,
           'shape_ok': shape.matches(ow, oh, *want_wh)}
    heard = [w for w in transcribe.hear(video, language)]
    hw = [w for w in heard if norm(w['w'])]
    ht = [norm(w['w']) for w in hw]
    ends = [bool(re.search(r'[.?!]["\')]*$', w['w'].strip())) for w in hw]
    exp, joins, joins_t, T = [], [], [], 0.0
    for c in report['clips']:
        joins.append(len(exp)); joins_t.append(T); exp += [w for w in c['words'] if w]; T += c.get('dur') or 0
    ratio, miss = missing_at_joins(exp, ht, joins[1:])
    out.update(heard_words=len(ht), expected_words=len(exp), match=ratio,
               fillers_heard=[w for w in ht if w in ALWAYS], repeats_heard=repeats(ht, ends),
               missing_near_joins=[m for m in miss if m['near_join']], missing_elsewhere=len([m for m in miss if not m['near_join']]),
               edges_clipped_by_energy=len(report['edges']['clipped']), av_sync_ms=av_sync(video),
               self_repairs=len((report.get('selfcheck') or {}).get('repairs', [])))
    found = items(report, hw, ht, ends, miss, joins_t[1:], joins[1:])
    try: out['lip_sync'] = lip_sync(video, report)
    except Exception as e: out['lip_sync'] = {'ok': False, 'error': str(e)[:200]}
    ls = out['lip_sync']
    if ls and not ls.get('ok') and ls.get('measured'):
        bad = next(r for r in ls['rows'] if r.get('clip') == ls['worst_clip'])
        found.append({'at': bad['at'], 'kind': 'sync', 'word': '', 'say': f'Your voice is {abs(ls["worst_ms"])} ms off your lips at {_mmss(bad["at"])}',
                      'ask': f'The sound and my lips are out of sync at {_mmss(bad["at"])}. Make a new version with them in sync.'})
    if not out['shape_ok']:
        found.append({'at': 0, 'kind': 'shape', 'word': '', 'say': 'The shape came out different from what you picked',
                      'ask': 'The video came out the wrong shape. Make it the shape I picked.'})
    try: db, speech = _level(video)
    except Exception: db, speech = None, 0.0
    out['items'] = rank(found, db, speech)
    return out
