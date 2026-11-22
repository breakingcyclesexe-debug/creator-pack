"""Whisper's word times drift on long files (measured on a 7 minute take: up to about 2 s, so a cut landed on the
wrong words: feedback in results.md). Fix: hear each clip again on its own with a few seconds either side (short
audio times are accurate), find the clip's first and last words in what was heard, and move the clip there.
The edges then get their room and the snap to silence as usual."""
from .cutrules import norm, ALWAYS

WINDOW = 2.5


def _find(heard, want, start=0):
    """Index in heard where the token run `want` starts (fillers skipped), searching from start."""
    toks = [h['n'] for h in heard]
    for i in range(start, len(toks)):
        if toks[i] != want[0]: continue
        k, j = 1, i
        while k < len(want) and j + 1 < len(toks):
            j += 1
            if toks[j] in ALWAYS: continue
            if toks[j] != want[k]: break
            k += 1
        if k == len(want): return i, j
    return None


def retime(clip, heard, pre, post):
    """clip: from cutrules (words, in, out); heard: [{"w","s","e"}] in take seconds around it.
    Returns (in, out, shift) or None when the clip's words can't be found (keep the old times)."""
    heard = [dict(h, n=norm(h['w'])) for h in heard if norm(h['w'])]
    ws = [w['n'] for w in clip['words'] if w['n'] not in ALWAYS]
    if len(ws) < 1 or not heard: return None
    head, tail = ws[:2], ws[-2:]
    heads, tails, pos = [], [], 0
    while (h := _find(heard, head, pos)): heads.append(h); pos = h[0] + 1
    pos = 0
    while (t := _find(heard, tail, pos)): tails.append(t); pos = t[0] + 1
    # the pair whose stretch is closest to the clip's own word count (restarts and second tellings lose),
    # then the one nearest where the transcript put it
    real = lambda i, j: sum(1 for h in heard[i:j + 1] if h['n'] not in ALWAYS)
    pairs = [(abs(real(f[0], l[1]) - len(ws)), abs(heard[f[0]]['s'] - clip['words'][0]['s']), f[0], l[1])
             for f in heads for l in tails if l[1] >= f[0] and real(f[0], l[1]) <= len(ws) * 1.5 + 4]
    if not pairs: return None
    _, _, i0, i1 = min(pairs)
    a = heard[i0]['s'] - pre
    if i0 > 0: a = max(a, heard[i0 - 1]['e'] + 0.02)
    b = heard[i1]['e'] + post
    if i1 + 1 < len(heard): b = min(b, heard[i1 + 1]['s'] - 0.02)
    if b - a < 0.2: return None
    return round(a, 3), round(b, 3), round(heard[i0]['s'] - clip['words'][0]['s'], 3)
