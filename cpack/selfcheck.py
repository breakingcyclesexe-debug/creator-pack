"""Place every clip's edges by sound, then listen to the cut before the buyer does (D24: "do it for me" must be
right first time; a tester, 22 Nov: "it would be hard for ppl to fine tune if the cut was shit all the time").

  place(clips, energy_of, pre, post)   in / out by sound (edges.find_in / find_out) from the words' times,
                                       back-to-back pieces of one take joined into one clip
  run(clips, energy_of, hear, fps, pre, post)
      up to 3 rounds, all automatic:
        a. energy at both edges on the source (no voice in the 10 ms frames at a cut)
        b. each clip heard again on its own: first and last words against the words meant to be kept
        c. a word said again across a join
      repairs: an edge with a word cut off moves outward to the next real silence; a stray fragment of the
      neighbouring word is dropped (the edge moves in to the silence after / before it); a repeat across a join
      is dropped from the later clip. Never across the neighbouring word.
      Before the rounds: a small word said twice in a row inside a clip ("but but", "and and", "for for"), that
      the first hearing wrote down once, is cut out (the clip is split on the two gaps around the first copy).
      These are never listed on the finish screen: they are fixed here or they are too small to hear.
      Returns (items, log): items = what is still not clean, each with its time in the video, kind, a plain
      sentence and a ready chat request; log = every repair made.
"""
import difflib, math
import numpy as np
from . import edges
from .cutrules import norm, ALWAYS, MEANT_DOUBLE, LOOSE1, LOOSE2

ROUNDS = 3
REACH = 1.0   # a word cut off at an edge starts / ends within this of the cut; further away is another word
EXPAND = {"i'm": 'i am', "don't": 'do not', "doesn't": 'does not', "didn't": 'did not', "it's": 'it is',
          "that's": 'that is', "you're": 'you are', "we're": 'we are', "they're": 'they are', "i'll": 'i will',
          "i've": 'i have', "i'd": 'i would', "can't": 'can not', "cannot": 'can not', "won't": 'will not',
          "isn't": 'is not', "wasn't": 'was not', "there's": 'there is', "what's": 'what is', "let's": 'let us',
          "gonna": 'going to', "wanna": 'want to', "gotta": 'got to', "you've": 'you have', "we've": 'we have',
          "he's": 'he is', "she's": 'she is', "aren't": 'are not', "couldn't": 'could not', "wouldn't": 'would not',
          "shouldn't": 'should not', "haven't": 'have not', "here's": 'here is', "y'all": 'you all', 'ok': 'okay'}
NUMS = {'zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve',
        'thirteen', 'fourteen', 'fifteen', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty',
        'ninety', 'hundred', 'thousand', 'million', 'first', 'second', 'third', 'percent'}


def tokens(words):
    """[{"w","s","e"}] -> [(token, s, e)], fillers out, contractions spelled out (whisper writes both ways)."""
    out = []
    for w in words:
        n = norm(w['w'])
        if not n or n in ALWAYS: continue
        for t in EXPAND.get(n, n).split(): out.append((t, w.get('s', 0), w.get('e', 0)))
    return out


def fuzzy(a, b):
    if a == b: return True
    if any(ch.isdigit() for ch in a + b):
        return (any(ch.isdigit() for ch in a) or a in NUMS) and (any(ch.isdigit() for ch in b) or b in NUMS)
    a2, b2 = a.replace("'", ''), b.replace("'", '')
    if a2 == b2 or (a2.endswith('s') and a2[:-1] == b2) or (b2.endswith('s') and b2[:-1] == a2): return True
    return min(len(a2), len(b2)) >= 4 and difflib.SequenceMatcher(None, a2, b2).ratio() >= 0.75


def _side(H, I):
    """(skipped heard, skipped intended) at the start of H/I where they line up, or None."""
    for tot in range(4):
        for i in range(tot + 1):
            j = tot - i
            if i >= len(H) or j >= len(I) or not fuzzy(H[i], I[j]): continue
            if i + 1 < len(H) and j + 1 < len(I) and not fuzzy(H[i + 1], I[j + 1]): continue
            return i, j
    return None


def ends(intended, heard):
    """intended / heard: token tuples (or strings). {"head": (state, n), "tail": (state, n)}; state is ok, stray
    (n extra heard words before the first / after the last meant one), missing (n meant words not heard) or
    unclear (the hearing does not line up at all)."""
    I = [t[0] if isinstance(t, tuple) else t for t in intended]
    H = [t[0] if isinstance(t, tuple) else t for t in heard]
    out = {}
    for name, h, i in (('head', H, I), ('tail', H[::-1], I[::-1])):
        r = _side(h, i) if h and i else None
        out[name] = ('unclear', 0) if r is None else ('ok', 0) if r == (0, 0) else ('stray', r[0]) if r[0] else ('missing', r[1])
    return out


def join_repeat(p_heard, c_heard, p_meant, c_meant):
    """Words heard at the end of one clip and again at the start of the next, that the cut did not mean to say
    twice. Returns how many words to drop from the next clip's start (0 = none)."""
    P = [t[0] if isinstance(t, tuple) else t for t in p_heard]
    C = [t[0] if isinstance(t, tuple) else t for t in c_heard]
    Pm = [t[0] if isinstance(t, tuple) else t for t in p_meant]
    Cm = [t[0] if isinstance(t, tuple) else t for t in c_meant]
    for n in (4, 3, 2, 1):
        if len(P) < n or len(C) < n or P[-n:] != C[:n]: continue
        if n == 1 and P[-1] in MEANT_DOUBLE: continue
        if Pm[-n:] == Cm[:n]: continue   # the story itself says it twice
        return n
    return 0


def place(clips, energy_of, pre, post):
    """Edges by sound for every clip (in place). Clips are cut-rule clips: words, ws/we (first word start, last
    word end), fl/ce (middles of the words either side in the take)."""
    for c in clips:
        e = energy_of(c['take']); floor = edges.noise_floor(e)
        c['thr'], c['speech_db'] = edges.clip_threshold(e, floor, c['ws'], c['we'])
        c['ein'] = edges.find_in(e, c['thr'], c['ws'], c['fl'], pre, t_end=c['we'])
        c['eout'] = edges.find_out(e, c['thr'], c['we'], c['ce'], post, t_start=c['ws'])
        # run-on speech next to a word that stays in the video anyway: take it in, cut on the pause after it
        if not c['ein']['ok'] and (c.get('in_free') or _loose(c.get('before', [])[-1:]) or _loose(c.get('before', [])[-2:])): _take_in(e, c, pre)
        if not c['eout']['ok'] and (c.get('out_free') or _loose(c.get('after', [])[:1]) or _loose(c.get('after', [])[:2])): _take_out(e, c, post)
        # run-on speech next to a cut-out restart: cut in the gap between the two words
        v = c['speech_db'] - edges.VALLEY_DB
        if not c['ein']['ok']: c['ein'] = edges.find_in(e, c['thr'], c['ws'], c['fl'], pre, t_end=c['we'], valley=v)
        if not c['eout']['ok']: c['eout'] = edges.find_out(e, c['thr'], c['we'], c['ce'], post, t_start=c['ws'], valley=v)
    _keep_fused(clips)
    _no_lost_voice(clips, energy_of)
    _join_touching(clips)
    return clips


def _no_lost_voice(clips, energy_of):
    """Two clips split only at a pause (nothing cut out between them) must not lose any voice in the gap: word
    times can call a short pause long and leave a word sitting between the two edges. Then play straight on."""
    k = 1
    while k < len(clips):
        p, c = clips[k - 1], clips[k]
        if p['take'] == c['take'] and c['words'][0]['i'] == p['words'][-1]['i'] + 1 and c['ein']['t'] > p['eout']['t']:
            e = energy_of(p['take'])
            a, b = edges._I(e, p['eout']['t']), edges._I(e, c['ein']['t'])
            if b > a and (e[a:b] >= min(p['thr'], c['thr'])).sum() >= 5:
                p.update(words=p['words'] + c['words'], text=(p['text'] + ' ' + c['text']).strip(), we=c['we'], ce=c['ce'],
                         eout=c['eout'], thr=min(p['thr'], c['thr']), after=c.get('after', []))
                clips.pop(k); continue
        k += 1


FUSED_GAP = 1.5   # at most this much cut-out speech is put back to avoid cutting through run-on speech


def _keep_fused(clips):
    """A restart cut out of the middle of run-on speech (no pause on either side to cut on) would be cut through
    the words. Better to leave the restart in: the two clips become one, played straight through. The finished
    video's hearing then lists the repeat with a Fix it, and nothing is clipped."""
    k = 1
    while k < len(clips):
        p, c = clips[k - 1], clips[k]
        gap_words = c['words'][0]['i'] - p['words'][-1]['i'] - 1
        if (p['take'] == c['take'] and gap_words > 0 and 0 <= c['ws'] - p['we'] <= FUSED_GAP
                and (not p['eout']['ok'] or not c['ein']['ok'])):
            mid = [w for w in p.get('after', []) if p['words'][-1]['i'] < w['i'] < c['words'][0]['i']]
            p.update(words=p['words'] + mid + c['words'], text=(p['text'] + ''.join(w['w'] for w in mid) + ' ' + c['text']).strip(),
                     we=c['we'], ce=c['ce'], eout=c['eout'], thr=min(p['thr'], c['thr']), after=c.get('after', []),
                     kept_restart=True)
            clips.pop(k); continue
        k += 1


def _loose(ws):
    """A loose filler ("so", "like", "okay") the rules cut, fused to the kept word with no pause: keeping it is
    better than cutting through the word next to it."""
    return bool(ws) and (ws[-1]['n'] in LOOSE1 or (len(ws) == 2 and (ws[0]['n'], ws[1]['n']) in LOOSE2))


def _take_in(e, c, pre):
    """No pause between the first word and the word before it, which is outside the story beat (not cut by the
    rules): start at the pause before that word instead of cutting through run-on speech (at most 2 words, 1 s)."""
    prev = [w for w in c.get('before', []) if w['n'] and w['n'] not in ALWAYS][-2:]
    if not prev: return
    lim = max(c['ws'] - REACH, (prev[0]['s'] + prev[0]['e']) / 2 - 0.4)
    r = edges.find_in(e, c['thr'], c['ws'], lim, pre, t_end=c['we'])
    if not r['ok']: return
    took = [w for w in prev if (w['s'] + w['e']) / 2 > r['quiet'] - 0.05]
    c['ein'] = r; c['words'] = took + c['words']; c['ws'] = min(c['ws'], r['quiet'])
    c['fl'] = min(c['fl'], r['lo']); c['text'] = (''.join(w['w'] for w in took) + ' ' + c['text']).strip()


def _take_out(e, c, post):
    nxt = [w for w in c.get('after', []) if w['n'] and w['n'] not in ALWAYS][:2]
    if not nxt: return
    lim = min(c['we'] + REACH, (nxt[-1]['s'] + nxt[-1]['e']) / 2 + 0.4)
    r = edges.find_out(e, c['thr'], c['we'], lim, post, t_start=c['ws'])
    if not r['ok']: return
    took = [w for w in nxt if (w['s'] + w['e']) / 2 < r['quiet'] + 0.05]
    c['eout'] = r; c['words'] = c['words'] + took; c['we'] = max(c['we'], r['quiet'])
    c['ce'] = max(c['ce'], r['hi']); c['text'] = (c['text'] + ''.join(w['w'] for w in took)).strip()


def _join_touching(clips):
    """Back-to-back pieces of one take whose edges meet are one clip (playing on, no fade in the middle of a
    word); edges of two clips that overlap inside one silence meet in its middle."""
    k = 1
    while k < len(clips):
        p, c = clips[k - 1], clips[k]
        if p['take'] == c['take'] and c['words'][0]['i'] == p['words'][-1]['i'] + 1 and c['ein']['t'] <= p['eout']['t'] + 0.05:
            p.update(words=p['words'] + c['words'], text=(p['text'] + ' ' + c['text']).strip(), we=c['we'], ce=c['ce'],
                     eout=c['eout'], thr=min(p['thr'], c['thr']))
            clips.pop(k); continue
        if p['take'] == c['take'] and p['we'] <= c['ws'] and p['eout']['t'] > c['ein']['t']:
            mid = round((p['eout']['t'] + c['ein']['t']) / 2, 3)
            p['eout'] = dict(p['eout'], t=mid, hi=max(mid, p['eout']['lo']))
            c['ein'] = dict(c['ein'], t=mid, lo=min(mid, c['ein']['hi']))
        k += 1


def _no_overlap(clips):
    """Two clips of one take never play the same sound twice: a later clip starts where the earlier one ended."""
    for p, c in zip(clips, clips[1:]):
        if p['take'] == c['take'] and c['ein']['t'] < p['eout']['t'] < c['eout']['t'] and c['ein']['t'] > p['ein']['t']:
            t = p['eout']['t']
            c['ein'] = dict(c['ein'], t=t, lo=min(t, c['ein']['lo']), hi=max(t, c['ein']['hi']))


def _span(c, fps):
    """The sound is cut exactly at the edges (a word gap can be 20 ms wide, narrower than a frame); the picture
    runs on to the next whole frame and the sound is padded with silence to match, so every clip is still a
    whole number of frames and picture and sound stay in step."""
    ss = c['ein']['t']
    aud = max(1.0 / fps, c['eout']['t'] - ss)
    n = max(1, int(math.ceil(aud * fps - 1e-6)))
    c['ss'], c['aud'], c['frames'], c['dur'], c['fps'] = round(ss, 4), round(aud, 4), n, n / fps, fps
    c['in'], c['out'] = round(ss, 3), round(ss + aud, 3)
    return c['in'], c['out']


def _extend_in(e, c, pre):
    """The first meant word is cut off: the in point moves back over the next stretch of voice to the pause (or
    word gap) before it. Only voice that ends after the word before it in the take has ended is ours to take."""
    q = e < c['thr']; j = edges._I(e, c['in']) - 1
    while j > 0 and q[j]: j -= 1
    prev = [w for w in c.get('before', []) if w['n']]
    if j / 100 <= c['fl'] or j / 100 < c['in'] - REACH or (prev and j / 100 < prev[-1]['e'] + 0.05): return None
    r = edges.find_in(e, c['thr'], j / 100, c['fl'], pre, t_end=c['we'], valley=c['speech_db'] - edges.VALLEY_DB)
    return r if r['ok'] and r['t'] < c['in'] - 0.01 else None


def _extend_out(e, c, post):
    q = e < c['thr']; j = edges._I(e, c['out'])
    while j < len(e) - 1 and q[j]: j += 1
    nxt = [w for w in c.get('after', []) if w['n']]
    if j / 100 >= c['ce'] or j / 100 > c['out'] + REACH or (nxt and j / 100 > nxt[0]['s'] - 0.05): return None
    r = edges.find_out(e, c['thr'], j / 100, c['ce'], post, t_start=c['ws'], valley=c['speech_db'] - edges.VALLEY_DB)
    return r if r['ok'] and r['t'] > c['out'] + 0.01 else None


LOUD_DB = 20   # a cut on a pause this close to the voice level is moved to the quietest moment of the pause
SLIDE = 0.08   # a cut on a pause may move this far to its quietest point (the breathing room hardly changes)


def _slide(e, c, edge):
    """Voice at a cut: move it to the quietest instant nearby, never past the clip's own first / last word's middle
    or the neighbouring word. On a pause the cut stays inside the pause; in a word gap it moves at most 50 ms."""
    key = 'ein' if edge == 'in' else 'eout'; ed, t = c[key], c[edge]
    w = SLIDE if ed.get('kind') == 'silence' else 0.05
    lo, hi = t - w, t + w
    if ed.get('kind') == 'silence': lo, hi = max(lo, ed['lo']), min(hi, ed['hi'])
    if edge == 'in':
        w0 = c['words'][0]; hi = min(hi, (w0['s'] + w0['e']) / 2); lo = max(lo, c['fl'])
    else:
        w1 = c['words'][-1]; lo = max(lo, (w1['s'] + w1['e']) / 2); hi = min(hi, c['ce'])
    a, b = int(math.ceil(lo * 100 - 0.5)), int(math.floor(hi * 100 - 0.5)) + 1
    if b <= a: return None
    t2, db = edges.best_point(e, a, b)
    if db >= edges.edge_quiet(e, 1e9, t)[1] - 1.0: return None
    return dict(ed, t=round(t2, 3), lo=round(min(t2, ed.get('lo', t2)), 3), hi=round(max(t2, ed.get('hi', t2)), 3))


def _move_touching(clips, n, edge, old, t, changed, done):
    """Two pieces of one take that meet at one instant share the cut: when one end slides, the other follows (or
    the next round would push it back to avoid playing a sound twice)."""
    m = n - 1 if edge == 'in' else n + 1
    if not 0 <= m < len(clips) or clips[m]['take'] != clips[n]['take']: return
    o = clips[m]; oedge = 'out' if edge == 'in' else 'in'
    if abs(o[oedge] - old) > 0.02: return
    w = o['words'][-1] if oedge == 'out' else o['words'][0]
    mid = (w['s'] + w['e']) / 2
    if (oedge == 'out' and t <= mid) or (oedge == 'in' and t >= mid): return
    key = 'eout' if oedge == 'out' else 'ein'
    o[key] = dict(o[key], t=round(t, 3), lo=round(min(t, o[key].get('lo', t)), 3), hi=round(max(t, o[key].get('hi', t)), 3))
    changed.add(m); done.add((m, oedge))


def _droppable(e, c, edge, meant, got, k):
    """Meant words at a clip's edge that the clip's own hearing does not hear, and that can go without changing what
    is said: loose fillers ("like", "so", "you know"), or a broken-off start / tail of at most 2 words with a real
    pause between it and the heard words ("I had, | so in a way"). Quiet fillers next to a join are often 30 dB
    under the voice: whisper does not hear them and neither does a viewer."""
    if k < 1 or k > 3 or len(meant) <= k: return False
    miss = [t[0] for t in (meant[:k] if edge == 'in' else meant[-k:])]
    if all(t in LOOSE1 for t in miss) or tuple(miss) in LOOSE2 or (len(miss) == 3 and miss[0] in LOOSE1 and tuple(miss[1:]) in LOOSE2):
        return True
    if k > 2: return False
    # a fragment: voice, then a real pause, then the heard words
    q = e < c['thr']; kk = int(round(edges.MIN_SIL * 100))
    if edge == 'in':
        a, b = edges._I(e, c['in'] + 0.03), edges._I(e, got[0][1])
    else:
        a, b = edges._I(e, got[-1][2]), edges._I(e, c['out'] - 0.03)
    if b - a < kk + 5: return False
    seg_q, seg_v = q[a:b], ~q[a:b]
    if edge == 'in':
        v = np.flatnonzero(seg_v)
        if not len(v) or v[0] > 20: return False   # no voice right after the in point: nothing unheard there
        rest = seg_q[v[0]:]
    else:
        v = np.flatnonzero(seg_v)
        if not len(v) or len(seg_v) - 1 - v[-1] > 20: return False
        rest = seg_q[:v[-1] + 1]
    run = best = 0
    for x in rest:
        run = run + 1 if x else 0; best = max(best, run)
    return best >= kk


def _trim_unheard(e, c, edge, got, pre, post, k=1):
    """The edge moves in to the pause (or word gap) between the unheard words and the first / last heard word.
    Looked for from the clip's own word times first (trimmed on the sound), then from the hearing's."""
    v = c['speech_db'] - edges.VALLEY_DB
    ws = [w for w in c['words'] if tokens([w])]
    tries = []
    if len(ws) > k:
        if edge == 'in': tries.append((ws[k]['s'], ws[k - 1]['e'] - 0.02))
        else: tries.append((ws[-k - 1]['e'], ws[-k]['s'] + 0.02))
    tries.append((got[0][1], c['in'] + 0.05) if edge == 'in' else (got[-1][2], c['out'] - 0.05))
    for t0, lim in tries:
        if edge == 'in':
            r = edges.find_in(e, c['thr'], t0, max(lim, c['in'] + 0.05), pre, t_end=c['we'], valley=v)
            if r['ok'] and r['t'] > c['in'] + 0.05: c['ws'] = max(c['ws'], t0); c['fl'] = max(c['fl'], r['lo'] - 0.01); return r
        else:
            r = edges.find_out(e, c['thr'], t0, min(lim, c['out'] - 0.05), post, t_start=c['ws'], valley=v)
            if r['ok'] and r['t'] < c['out'] - 0.05: c['we'] = min(c['we'], t0); c['ce'] = min(c['ce'], r['hi'] + 0.01); return r
    return None


def _drop_edge_words(c, edge, k):
    """Take the k meant tokens (and fillers next to them) off the clip's words at that edge."""
    ws = list(c['words']) if edge == 'in' else list(c['words'])[::-1]
    out, n = [], 0
    while ws and n < k:
        w = ws.pop(0); out.append(w); n += len(tokens([w]))
    while ws and not tokens([ws[0]]): out.append(ws.pop(0))
    if not ws: return
    c['words'] = ws if edge == 'in' else ws[::-1]
    c.setdefault('dropped_words', []).extend(w['w'].strip() for w in out)


def _check(clips, energy_of, heard):
    """Problems per clip: {"n", "edge": in|out, "kind", "word"?, "db"?, "count"?}."""
    probs = []
    for n, c in enumerate(clips):
        e = energy_of(c['take'])
        for edge in ('in', 'out'):
            t = c[edge]
            if edge == 'in' and t < 0.03: continue
            # a cut on a pause must be quiet; a cut in the gap between two run-on words must at least sit in the
            # gap (VALLEY_DB under the voice), or it cuts through a word
            kind = c['ein' if edge == 'in' else 'eout'].get('kind')
            lim = c['thr'] if kind == 'silence' else c['speech_db'] - edges.VALLEY_DB
            ok, db = edges.edge_quiet(e, lim, t)
            if not ok: probs.append({'n': n, 'edge': edge, 'kind': 'voice', 'db': db})
            elif db >= c['speech_db'] - LOUD_DB:
                # a pause in rain or wind can sit only 15-20 dB under the voice: still a pause, but the cut should
                # sit in the quietest moment of it (repaired silently, never listed)
                probs.append({'n': n, 'edge': edge, 'kind': 'loud', 'db': db})
        if heard is None: continue
        meant, got = tokens(c['words']), tokens(heard[n])
        r = ends(meant, got)
        for edge, side in (('in', 'head'), ('out', 'tail')):
            state, k = r[side]
            if state == 'ok': continue
            if state == 'missing' and got and _droppable(e, c, edge, meant, got, k):
                probs.append({'n': n, 'edge': edge, 'kind': 'unheard', 'count': k,
                              'word': ' '.join(t[0] for t in (meant[:k] if side == 'head' else meant[-k:]))})
                continue
            word = (meant[k - 1 if side == 'head' else -k][0] if state == 'missing' else
                    got[k - 1 if side == 'head' else -k][0] if state == 'stray' else (meant[0] if side == 'head' else meant[-1])[0]) if meant else ''
            probs.append({'n': n, 'edge': edge, 'kind': state, 'count': k, 'word': word})
        if n and clips[n - 1]['take'] == c['take']:
            # a word on the "wrong" side of a join (in the next clip instead of this one, or the other way) is still
            # heard once, in order: not a problem
            pt = next((x for x in probs if x['n'] == n - 1 and x['edge'] == 'out' and x['kind'] in ('missing', 'stray')), None)
            ch = next((x for x in probs if x['n'] == n and x['edge'] == 'in' and x['kind'] in ('missing', 'stray')), None)
            if pt and ch and pt['kind'] != ch['kind'] and pt['count'] == ch['count']:
                probs.remove(pt); probs.remove(ch)
        if n:
            k = join_repeat(tokens(heard[n - 1]), got, tokens(clips[n - 1]['words']), meant)
            if k: probs.append({'n': n, 'edge': 'in', 'kind': 'repeat', 'count': k, 'word': ' '.join(t[0] for t in got[:k])})
    return probs


def _repair(clips, probs, energy_of, heard, pre, post, log):
    changed, done = set(), set()
    order = {'repeat': 0, 'stray': 1, 'unheard': 2, 'missing': 3, 'voice': 4, 'loud': 5, 'unclear': 6}
    for pr in sorted(probs, key=lambda p: order[p['kind']]):
        n, c = pr['n'], clips[pr['n']]
        if (n, pr['edge']) in done: continue
        e = energy_of(c['take']); new = None
        got = tokens(heard[n]) if heard is not None else []
        if pr['kind'] in ('stray', 'repeat') and got:
            k = pr['count']
            if pr['edge'] == 'in' and k < len(got):
                first, stray = got[k], got[k - 1]
                new = edges.find_in(e, c['thr'], first[1], stray[2] - 0.02, pre, t_end=c['we'], valley=c['speech_db'] - edges.VALLEY_DB)
                if new['ok'] and new['t'] > c['in']: c['fl'] = max(c['fl'], stray[2] - 0.02); c['ws'] = max(c['ws'], first[1])
                else: new = None
            elif pr['edge'] == 'out' and k < len(got):
                last, stray = got[-k - 1], got[-k]
                new = edges.find_out(e, c['thr'], last[2], stray[1] + 0.02, post, t_start=c['ws'], valley=c['speech_db'] - edges.VALLEY_DB)
                if new['ok'] and new['t'] < c['out']: c['ce'] = min(c['ce'], stray[1] + 0.02); c['we'] = min(c['we'], last[2])
                else: new = None
        elif pr['kind'] == 'unheard' and got:
            new = _trim_unheard(e, c, pr['edge'], got, pre, post, pr['count'])
        elif pr['kind'] == 'missing':
            new = _extend_in(e, c, pre) if pr['edge'] == 'in' else _extend_out(e, c, post)
        elif pr['kind'] in ('voice', 'loud'):
            new = _slide(e, c, pr['edge'])
        if new is None: continue
        tried = c.setdefault('tried', {'in': [], 'out': []})[pr['edge']]
        old = c[pr['edge']]
        near = 0.005 if pr['kind'] in ('voice', 'loud') else 0.03
        if any(abs(new['t'] - x) < near for x in tried + [old]): continue   # never undo an earlier repair: report instead
        if pr['kind'] == 'unheard': _drop_edge_words(c, pr['edge'], pr['count'])
        tried.append(old)
        key = 'ein' if pr['edge'] == 'in' else 'eout'
        c[key] = new; changed.add(n); done.add((n, pr['edge']))
        if pr['kind'] in ('voice', 'loud'): _move_touching(clips, n, pr['edge'], old, new['t'], changed, done)
        fix = {'stray': 'dropped a stray sound', 'repeat': 'dropped a repeat', 'unheard': 'dropped a filler or false start', 'missing': 'in earlier' if key == 'ein' else 'out later',
               'voice': 'moved to the quietest point', 'loud': 'moved to the quietest point'}[pr['kind']]
        log.append({'clip': n, 'edge': pr['edge'], 'kind': pr['kind'], 'fix': fix, 'from': old, 'to': new['t'], 'word': pr.get('word', '')})
    return changed


def _inner_repeats(c, got):
    """Small words heard twice in a row inside a clip that the clip's own words have once.
    got: tokens of the clip's hearing. Returns [(j, n, wi)]: got[j:j+n] is said again straight after, and wi is
    the index in c['words'] of the word that the kept (second) copy stands for."""
    meant, widx = [], []
    for k, w in enumerate(c['words']):
        for t in tokens([w]): meant.append(t[0]); widx.append(k)
    H = [t[0] for t in got]
    h2m = {}
    for a, b, size in difflib.SequenceMatcher(None, meant, H, autojunk=False).get_matching_blocks():
        for x in range(size): h2m[b + x] = a + x
    out, used = [], set()
    for n in (2, 1):
        for j in range(1, len(H) - 2 * n + 1):
            if H[j:j + n] != H[j + n:j + 2 * n] or used & set(range(j, j + 2 * n)): continue
            if n == 1 and H[j] in MEANT_DOUBLE: continue
            first = all(j + x in h2m for x in range(n)); second = all(j + n + x in h2m for x in range(n))
            if first == second: continue   # the story says it twice, or the hearing does not line up here
            out.append((j, n, widx[h2m[j] if first else h2m[j + n]])); used |= set(range(j, j + 2 * n))
    return sorted(out)


def _split_repeats(clips, heard, energy_of, pre, post, log):
    """Cut a small repeated word out of the middle of a clip (a tester, 22 Nov: "but", "like", "for" said twice were
    listed with Play and Fix it; they are fixed here instead). The clip becomes two: one ends in the gap before
    the first copy, the next starts in the gap before the second. With no gap on both sides nothing is cut
    (never through a word). Returns the indexes of the new clips, which need hearing again."""
    fresh, n = [], 0
    while n < len(clips):
        c = clips[n]; got = tokens(heard[n] or [])
        done = False
        for j, k, wi in (_inner_repeats(c, got) if got else []):
            left, right = c['words'][:wi], [dict(w) for w in c['words'][wi:]]
            if not tokens(left) or not tokens(right): continue
            a_end, b_start = got[j - 1][2], got[j][1]               # last word before the repeat ends; first copy starts
            d_end, k_start = got[j + k - 1][2], got[j + k][1]       # first copy ends; the copy we keep starts
            if not (c['in'] + 0.15 < a_end and b_start < k_start and k_start < c['out'] - 0.15): continue
            e = energy_of(c['take']); v = c['speech_db'] - edges.VALLEY_DB
            out = edges.find_out(e, c['thr'], a_end, b_start + 0.02, post, t_start=c['ws'], valley=v)
            inn = edges.find_in(e, c['thr'], k_start, d_end - 0.02, pre, t_end=c['we'], valley=v)
            if not (out['ok'] and inn['ok'] and c['in'] + 0.1 < out['t'] and out['t'] + 0.08 <= inn['t'] < c['out'] - 0.1): continue
            for q, w in enumerate(right[:k]):   # the kept copy's words sit on the heard times, so the captions keep them
                if w['s'] < inn['t'] and j + k + q < len(got):
                    hs, he = got[j + k + q][1], got[j + k + q][2]
                    w['s'], w['e'] = round(max(hs, inn['t']), 3), round(max(he, hs + 0.05), 3)
            base = {x: y for x, y in c.items() if x != 'tried'}
            txt = lambda ws: ''.join(w['w'] for w in ws).strip()
            p = dict(base, words=left, text=txt(left), we=min(c['we'], max(a_end, left[-1]['s'] + 0.05)), ce=b_start + 0.02,
                     eout=out, after=right[:3], out_free=False)
            r = dict(base, words=right, text=txt(right), ws=max(c['ws'], k_start), fl=d_end - 0.02, ein=inn,
                     before=left[-3:], in_free=False)
            clips[n:n + 1] = [p, r]; heard[n:n + 1] = [None, None]
            log.append({'clip': n, 'edge': 'mid', 'kind': 'repeat', 'fix': 'cut a small repeated word', 'from': out['t'], 'to': inn['t'],
                        'word': ' '.join(t[0] for t in got[j:j + k]), 'round': 0})
            fresh = [x + 1 if x > n else x for x in fresh] + [n, n + 1]
            done = True; break
        n += 2 if done else 1
    return fresh


def _mmss(t): return f'{int(t // 60)}:{int(t % 60):02d}'


def _items(clips, probs):
    starts, T = [], 0.0
    for c in clips: starts.append(T); T += c['dur']
    items, seen = [], set()
    for p in probs:
        if p['kind'] == 'loud': continue
        n, c = p['n'], clips[p['n']]
        at = starts[n] if p['edge'] == 'in' else starts[n] + c['dur']
        key = (round(at, 1), p['kind'])
        if key in seen: continue
        seen.add(key)
        w = p.get('word') or ''
        q = f'"{w}"' if w else 'a word'
        if p['kind'] == 'unheard': p = dict(p, kind='missing')
        say = {'voice': f'The cut at {_mmss(at)} lands while you are still talking',
               'missing': f'{q} may be cut short at {_mmss(at)}',
               'stray': f'A bit of {q} slips in at {_mmss(at)}',
               'repeat': f'{q} is said twice at {_mmss(at)}',
               'unclear': f'The words at {_mmss(at)} did not come through clearly'}[p['kind']]
        ask = {'voice': f'The cut at {_mmss(at)} clips my voice. Move it to the pause so no word is cut.',
               'missing': f'At {_mmss(at)} the word {q} is cut short. Move that cut so the whole word is heard.',
               'stray': f'At {_mmss(at)} a bit of {q} slips in. Cut it out.',
               'repeat': f'At {_mmss(at)} {q} is said twice. Keep it once.',
               'unclear': f'Check the cut at {_mmss(at)}: the words there sound wrong. Fix it so it reads cleanly.'}[p['kind']]
        items.append({'at': round(at, 2), 'kind': p['kind'], 'clip': n, 'edge': p['edge'], 'word': w, 'say': say, 'ask': ask})
    return sorted(items, key=lambda i: i['at'])


def run(clips, energy_of, hear, fps, pre, post, rounds=ROUNDS):
    """hear([(take, a, b), ...]) -> words heard in each stretch, in take seconds (None: energy check only).
    Sets each clip's ss / frames / dur / in / out. Returns (items, log)."""
    log, heard, todo = [], [None] * len(clips), set(range(len(clips)))   # heard grows with clips when a repeat is cut out
    probs = []
    for rnd in range(rounds + 1):
        _no_overlap(clips)
        for c in clips: _span(c, fps)
        if hear is not None and todo:
            idx = sorted(todo)
            got = hear([(clips[n]['take'], clips[n]['in'], clips[n]['out']) for n in idx])
            for n, ws in zip(idx, got): heard[n] = ws
            if rnd == 0:
                fresh = _split_repeats(clips, heard, energy_of, pre, post, log)
                if fresh:
                    _no_overlap(clips)
                    for c in clips: _span(c, fps)
                    for n, ws in zip(fresh, hear([(clips[n]['take'], clips[n]['in'], clips[n]['out']) for n in fresh])): heard[n] = ws
        probs = _check(clips, energy_of, heard if hear is not None else None)
        fixable = [p for p in probs if p['kind'] != 'unclear']
        if not fixable or rnd == rounds: break
        changed = _repair(clips, fixable, energy_of, heard if hear is not None else None, pre, post, log)
        if not changed: break
        _join_touching_after_repair(clips)
        todo = changed | {n + 1 for n in changed if n + 1 < len(clips)} | {n - 1 for n in changed if n > 0}
        for entry in log: entry.setdefault('round', rnd + 1)
    _no_overlap(clips)
    for c in clips: _span(c, fps); _words_in_clip(c)
    return _items(clips, probs), log


def _words_in_clip(c):
    """The clip's words are the ones it plays, by the captions' own rule (render.caption_words): a word that ends
    before the in point or starts after the out point was dropped by a repair or sits across a join."""
    keep = [w for w in c['words'] if not (w['e'] <= c['ss'] + 0.02 or w['s'] >= c['ss'] + c['dur'] - 0.02)]
    if keep and len(keep) < len(c['words']):
        c['dropped_words'] = [w['w'].strip() for w in c['words'] if w not in keep]
        c['words'] = keep


def _join_touching_after_repair(clips):
    for p, c in zip(clips, clips[1:]):
        if p['take'] == c['take'] and p['we'] <= c['ws'] and p['eout']['t'] > c['ein']['t']:
            mid = round((p['eout']['t'] + c['ein']['t']) / 2, 3)
            p['eout'] = dict(p['eout'], t=mid, hi=max(mid, p['eout']['lo']))
            c['ein'] = dict(c['ein'], t=mid, lo=min(mid, c['ein']['hi']))
