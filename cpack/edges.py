"""Cut edges on real silence. Works on 10 ms frames of the take's sound in dB (louder channel per frame,
because a clip-on mic often records on one channel only), computed once per take.

  frames_db(x)                 x: float32 array (n, channels) at 16 kHz -> dB per 10 ms frame
  noise_floor(e)               room tone: 5th percentile of the first 5 minutes

Edges by sound (CT-129, D24 "right first time"). Word times from whisper drift (seen: 0.15 s to 2.5 s), so they only
say WHERE to look; the sound decides the frame:
  clip_threshold(e, floor, a, b)   silence = under the clip's speech level - 30 dB, or room tone + 8 dB if that is
                                   higher (never closer than 10 dB under the voice, for noisy rooms)
  find_out(...)                    out point: from the last kept word's end, forward to the first 80 ms of silence
                                   (or back to where it began, when the word time is late), then the breathing room,
                                   never past where the voice starts again
  find_in(...)                     in point: the same, backward from the first kept word
  edge_quiet(e, thr, t)            no voice within 20 ms of a cut
If there is no silence before the neighbouring word (run-on speech), the quietest 10 ms is used and the edge is
flagged (ok False) for the self-check to repair or report.
"""
import numpy as np

SR = 16000
QUIET_DB = -55   # under this (or 8 dB over the room tone, if that is higher) counts as silence for snapping
EDGE_DB = -50    # over this right at a cut edge means a word is still sounding
EDGE_WIN = 0.03
REL_DB = 30      # silence: this far under the clip's speech level ...
FLOOR_DB = 8     # ... or this far over the room tone, whichever is higher
MIN_SIL = 0.08   # silence must last this long to count (a 40 ms dip inside a word is not a pause)
VALLEY_DB = 18   # no pause at all: a dip this far under the speech level for 20 ms is the gap between two words
MARGIN = 0.015   # a cut stays this far inside the silence (the 10 ms sound fade sits on room tone)


def frames_db(x):
    x = np.asarray(x, np.float32)
    if x.ndim == 1: x = x[:, None]
    n = len(x) // 160
    if n == 0: return np.zeros(0)
    f = x[:n * 160].reshape(n, 160, x.shape[1])
    return 20 * np.log10(np.sqrt((f ** 2).mean(1)).max(1) + 1e-9)


def noise_floor(e):
    return float(np.percentile(e[:30000], 5)) if len(e) else -90.0


def _I(e, t): return max(0, min(len(e) - 1, int(round(t * 100))))
def _T(i): return round(i / 100, 2)


def _speech(e, floor): return e >= max(QUIET_DB, floor + 8)


def speech_at(e, floor, t, win=0.25):
    """True when at least 40% of the `win` seconds from t sound like speech (a word really starts there)."""
    if not len(e): return True
    s = _speech(e, floor)[_I(e, t):_I(e, t + win) + 1]
    return bool(len(s)) and s.mean() >= 0.4


def level(e, a, b):
    s = e[max(0, a):max(max(0, a) + 1, b)]
    return float(10 * np.log10(np.mean(10 ** (s / 10)))) if len(s) else -200.0


def refine_words(words, e, floor):
    """whisper.cpp word times run edge to edge (a pause is swallowed by the word before it). Trim each word to
    the stretch of it that actually sounds, so real pauses show up as gaps. Times only ever move inward; the
    first and last word of every clip get edge room and a snap outward later, so a soft ending is not lost.
    Keeps the heard times as s0 / e0."""
    if not len(e): return words
    speech = e >= max(QUIET_DB, floor + 8)
    for w in words:
        w.setdefault('s0', w['s']); w.setdefault('e0', w['e'])
        a, b = _I(e, w['s0']), max(_I(e, w['s0']) + 1, _I(e, w['e0']))
        idx = np.flatnonzero(speech[a:b])
        if len(idx):
            w['s'] = round(max(w['s0'], (a + idx[0]) / 100), 3)
            w['e'] = round(min(w['e0'], (a + idx[-1] + 1) / 100), 3)
        else:
            w['e'] = round(min(w['e0'], w['s0'] + 0.1), 3)
        if w['e'] <= w['s']: w['e'] = round(w['s'] + 0.02, 3)
    return words


def clip_threshold(e, floor, a, b):
    """(silence threshold dB, speech level dB) for a clip whose words run a..b seconds. The room tone is the
    louder of the take's (first 5 minutes) and the local one (10th percentile within 3 s of the clip): rain on an
    umbrella sat at -40 dB in IMG_0284 while the take's quietest stretch was -60, so nothing counted as a pause."""
    seg = e[_I(e, a):_I(e, b) + 1]
    sp = float(np.percentile(seg, 90)) if len(seg) else -20.0
    near = e[_I(e, a - 3):_I(e, b + 3) + 1]
    room = max(floor, float(np.percentile(near, 10))) if len(near) else floor
    return round(min(max(sp - REL_DB, room + FLOOR_DB), sp - 10), 2), round(sp, 2)


def _run(q, j):
    """[s, r) of the run of equal q values around frame j."""
    s, r = j, j
    while s > 0 and q[s - 1] == q[j]: s -= 1
    while r < len(q) and q[r] == q[j]: r += 1
    return s, r


def _edge(t, lo, hi, ok, **kw):
    lo, hi = round(lo, 3), round(max(lo, hi), 3)
    return dict(t=round(min(max(t, lo), hi), 3), lo=lo, hi=hi, ok=ok, **kw)


def find_out(e, thr, t_end, t_limit, post, t_start=None, min_sil=MIN_SIL, valley=None):
    """Out point after a clip's last word (heard end t_end). The silence must begin before t_limit (the middle
    of the next word in the take, kept or not). Returns {t, lo, hi, ok, quiet}: t the cut, [lo, hi] where a cut is
    still clean (frame rounding picks inside it), quiet the time the voice stopped."""
    n = len(e)
    if n < 10: return _edge(t_end + post, t_end + post, t_end + post, True, quiet=t_end)
    k = max(1, int(round(min_sil * 100)))
    q = e < thr
    i0, lim = _I(e, t_end), _I(e, t_limit)
    back = _I(e, t_start + 0.05) if t_start is not None else max(0, i0 - 30)
    found = None
    if q[i0]:
        s, r = _run(q, i0)
        s = max(s, min(back, i0))
        if r - s >= k or r >= n: found = (s, r)
    if not found:
        j = i0
        while j < min(lim, n):
            if q[j]:
                s, r = _run(q, j)
                s = max(s, j)
                if r - s >= k or r >= n: found = (s, r); break
                j = r
            else: j += 1
    if found:
        s, r = found
        lo, hi = s / 100 + MARGIN, (r / 100 - MARGIN) if r < n else n / 100
        return _edge(s / 100 + post, lo, hi, True, quiet=s / 100, kind='silence')
    if valley is not None:   # run-on speech: the first gap between words after the last word
        q2 = e < valley
        for j in range(i0, min(lim, n - 2)):
            if q2[j:j + 2].all():
                s, r = _run(q2, j); s = max(s, j)
                t, _ = best_point(e, s, r)
                return _edge(t, s / 100 + 0.005, max(s / 100 + 0.005, r / 100 - 0.005), True, quiet=s / 100, kind='valley')
    t, _ = best_point(e, i0, max(i0 + 1, min(lim, n - 1) + 1))   # no gap at all: the quietest instant
    return _edge(t, t, t, False, quiet=None, kind='none')


def find_in(e, thr, t_start, t_limit, pre, t_end=None, min_sil=MIN_SIL, valley=None):
    """In point before a clip's first word (heard start t_start); the silence must end after t_limit (the middle
    of the word before it in the take). Same return as find_out, quiet = where the voice starts."""
    n = len(e)
    if n < 10: return _edge(max(0.0, t_start - pre), max(0.0, t_start - pre), max(0.0, t_start - pre), True, quiet=t_start)
    k = max(1, int(round(min_sil * 100)))
    q = e < thr
    i0, lim = _I(e, t_start), _I(e, max(0.0, t_limit))
    fwd = _I(e, t_end - 0.05) if t_end is not None else min(n - 1, i0 + 30)
    found = None
    if q[i0]:
        s, r = _run(q, i0)
        r = min(r, max(fwd, i0 + 1))
        if r - s >= k or s == 0: found = (s, r)
    if not found:
        j = i0
        while j > lim:
            if q[j - 1]:
                s, r = _run(q, j - 1)
                if r - s >= k or s == 0: found = (s, r); break
                j = s
            else: j -= 1
    if found:
        s, r = found
        if s == 0 and r / 100 <= pre + MARGIN: return _edge(0.0, 0.0, 0.0, True, quiet=r / 100, kind='silence')
        lo, hi = (s / 100 + MARGIN) if s > 0 else 0.0, r / 100 - MARGIN
        return _edge(r / 100 - pre, lo, hi, True, quiet=r / 100, kind='silence')
    a = max(lim, 0)
    if valley is not None:   # run-on speech: the last gap between words before the first word
        q2 = e < valley
        for j in range(i0, a + 1, -1):
            if q2[j - 2:j].all():
                s, r = _run(q2, j - 1); r = min(r, j)
                t, _ = best_point(e, s, r)
                return _edge(t, s / 100 + 0.005, max(s / 100 + 0.005, r / 100 - 0.005), True, quiet=r / 100, kind='valley')
    t, _ = best_point(e, a, max(a + 1, i0 + 1))
    return _edge(t, t, t, False, quiet=None, kind='none')


def best_point(e, a, b):
    """The cut instant in frames [a, b) where the loudest of the three 10 ms frames around it is lowest, at the
    middle of a frame (a cut on a frame boundary touches the louder frame either side). Returns (t, loudest dB)."""
    n = len(e); a, b = max(0, int(a)), min(n, int(b))
    if b <= a: a, b = max(0, min(a, n - 1)), max(0, min(a, n - 1)) + 1
    best = None
    for m in range(a, b):
        v = (float(e[max(0, m - 1):m + 2].max()), float(e[m]))   # ties: the quieter frame itself
        if best is None or v < best[1]: best = (m, v)
    return (best[0] + 0.5) / 100, round(best[1][0], 1)


def edge_quiet(e, thr, t, win=0.01):
    """(clean, loudest dB) of the 10 ms frames touching the cut instant (t +- win)."""
    if not len(e): return True, -200.0
    a = max(0, min(len(e) - 1, int(np.floor((t - win) * 100))))
    b = max(a, min(len(e) - 1, int(np.floor((t + win) * 100))))
    m = float(e[a:b + 1].max())
    return m < thr, round(m, 1)


def dtw_spans(words, e, floor, gap=0.08):
    """Word spans from DTW anchors and the sound: a word runs from the voice onset before its first anchor to the
    end of the voice after its last one (a dip under 80 ms is inside the word), never past the neighbours'
    anchors. So a real pause shows up as a gap between words, and a long word is not cut to its anchor."""
    if not len(e) or not words: return words
    sp = e >= max(QUIET_DB, floor + FLOOR_DB)
    n, k = len(e), int(round(gap * 100))
    for i, w in enumerate(words):
        w.setdefault('s0', w['s']); w.setdefault('e0', w['e'])
        lo = _I(e, words[i - 1]['d'] + 0.03) if i else 0
        hi = _I(e, words[i + 1]['d0'] - 0.03) if i + 1 < len(words) else n - 1
        a, b = _I(e, w['d0']), _I(e, w['d'])
        lo, hi = min(lo, a), max(hi, b)
        j, quiet = b, 0                       # forward from the last anchor to the first pause
        while j + 1 <= hi and quiet < k:
            j += 1; quiet = quiet + 1 if not sp[j] else 0
        end = j - quiet + 1 if quiet else j
        j, quiet = a, 0                       # back from the first anchor to the pause before it
        while j - 1 >= lo and quiet < k:
            j -= 1; quiet = quiet + 1 if not sp[j] else 0
        start = j + quiet if quiet else j
        w['s'], w['e'] = round(start / 100, 3), round(max(end, start + 2) / 100, 3)
    for p, q in zip(words, words[1:]):       # anchors can sit close: never overlap
        if q['s'] < p['e']: q['s'] = p['e'] = round((p['e'] + q['s']) / 2, 3)
        if q['e'] <= q['s']: q['e'] = round(q['s'] + 0.02, 3)
    return words
