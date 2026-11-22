"""The storyboard the buyer's Claude Code session writes, checked against the transcript before anyone sees it.

Rule: only the speaker's own words. Every beat's "line" must be words the speaker said, in that order, in that
take, near the time given. The check finds that stretch of words, snaps the beat's start and end to its first and
last word, and stores what was actually said ("heard"), which is what the interface quotes and the cut uses.
A line that can't be found is an error the session must fix; nothing is guessed.

Shape:
{"mode": "find|keep|script", "shape": "turn|tips|qa|beforeafter|rant", "one_line": "...",
 "shape_alts": ["tips", ...], "advice": ["..."],
 "beats": [{"id": "b1", "label": "Hook", "line": "exact words", "take": "IMG_0001.MOV", "start": 12.3, "end": 18.9,
            "keep": true, "alts": [{"take", "start", "end", "line"}]}],
 "left_out": [{"line": "...", "take": "...", "start": 40.1, "end": 52.0, "why": "..."}]}

Story-method fields (dump-to-script step 3, all optional so older storyboards still save and load):
 "trying_to_tell", "arcs": [2-3 competing arcs, each {id, way_in, shape, first_gate, hook: {problem, search},
 openings, beats, after_feeling, ending, open_thread, missing_question, left_out}], "score": {by, <arc id>: {hook,
 arc_turn, own_lines, stranger, goal_fit, missing, total, why}} from a judge that wrote none of the arcs,
 "winner": arc id, "question": the winner's one missing-beat question. Top-level beats are the winner's beats
 (copied from the winning arc when left out). Every quoted line in an arc is checked like a beat.
"""
from .cutrules import norm, ALWAYS

SHAPES = {'turn': 'Story with a turn', 'tips': 'Tips list', 'qa': 'Question and answer',
          'beforeafter': 'Before and after', 'rant': 'Rant with a point', 'setback': 'Setback',
          'belief': 'Belief then break', 'opinion': 'Against the common view'}
SCORE_KEYS = ('hook', 'arc_turn', 'own_lines', 'stranger', 'goal_fit', 'missing')
# every key the story method (dump-to-script step 3 JSON) uses; tests/test_story_sync.py checks step 3 against it
STORY_KEYS = {'one_line', 'trying_to_tell', 'arcs', 'id', 'way_in', 'shape', 'first_gate', 'hook', 'problem', 'search',
              'openings', 'line', 'take', 'on_screen', 'beats', 'label', 'start', 'end', 'plants', 'pays_off',
              'after_feeling', 'missing', 'ending', 'open_thread', 'missing_question', 'left_out', 'why', 'score',
              'by', 'arc_turn', 'own_lines', 'stranger', 'goal_fit', 'total', 'winner', 'question', 'approved'}
KEY_ALIASES = {'source': 'take'}   # step 3 says "source"; in a take that is the take name + start seconds
MODES = {'find', 'keep', 'script'}
NEAR = 8.0   # seconds a beat's given start may be off


def _locate(W, line, start, end):
    """Best stretch of take words W that says `line`. Returns (i, j, skipped) or None."""
    L = [t for t in (norm(x) for x in line.split()) if t and t not in ALWAYS]
    if not L: return None
    best = None
    lo, hi = (start or 0) - NEAR, (start or 0) + NEAR
    for i, w in enumerate(W):
        if w['n'] != L[0] or start is not None and not lo <= w['s'] <= hi: continue
        k, j, skipped = 1, i, 0
        limit = max(2, len(L) // 4)
        while k < len(L) and j + 1 < len(W):
            j += 1
            t = W[j]['n']
            if not t: continue
            if t == L[k]: k += 1
            elif t not in ALWAYS:
                skipped += 1
                if skipped > limit: break
        if k == len(L):
            cand = (skipped, abs(w['s'] - (start or w['s'])), i, j)
            if best is None or cand < best: best = cand
    return (best[2], best[3], best[0]) if best else None


def _check_span(obj, takes, where, errors):
    take = obj.get('take')
    if take not in takes:
        errors.append(f'{where}: take "{take}" is not one of {sorted(takes)}'); return None
    line = (obj.get('line') or '').strip()
    if not line:
        errors.append(f'{where}: "line" is empty, quote the words as said'); return None
    try: start = float(obj['start']) if obj.get('start') is not None else None
    except (TypeError, ValueError): start = None
    W = takes[take]
    hit = _locate(W, line, start, obj.get('end'))
    if not hit:
        errors.append(f'{where}: "{line[:60]}" not found in {take} near {start} s. Quote the words exactly as said, in order')
        return None
    i, j, skipped = hit
    return {'take': take, 'start': round(W[i]['s'], 3), 'end': round(W[j]['e'], 3), 'line': line,
            'heard': ''.join(w['w'] for w in W[i:j + 1]).strip(), 'words': [i, j]}


def check(sb, takes):
    """sb: dict from the session; takes: {name: prepared words}. Returns (clean storyboard, errors)."""
    errors = []
    if not isinstance(sb, dict): return None, ['storyboard must be a JSON object']
    mode = sb.get('mode', 'find')
    if mode not in MODES: errors.append(f'mode must be one of {sorted(MODES)}')
    arcs = sb.get('arcs') if isinstance(sb.get('arcs'), list) else []
    won = next((a for a in arcs if isinstance(a, dict) and str(a.get('id')) == str(sb.get('winner'))), None)
    shp = sb.get('shape') or (won or {}).get('shape')
    if shp not in SHAPES: errors.append(f'shape must be one of {sorted(SHAPES)}')
    alts0 = sb.get('shape_alts') or [a.get('shape') for a in arcs if isinstance(a, dict) and a is not won]
    out = {'mode': mode, 'shape': shp, 'one_line': str(sb.get('one_line', ''))[:240],
           'shape_alts': list(dict.fromkeys(s for s in alts0 if s in SHAPES and s != shp)),
           'advice': [str(a)[:200] for a in sb.get('advice', [])][:5], 'beats': [], 'left_out': []}
    if not out['one_line']: errors.append('one_line is empty: the story in one sentence, in plain words')
    win = _story_fields(sb, takes, out, errors)
    beats = sb.get('beats') or (win or {}).get('beats') or []
    if not beats: errors.append('beats is empty')
    out['beats'] = _beats(beats, takes, '', errors)
    _overlaps(out['beats'], '', errors)
    order = sorted(range(len(out['beats'])), key=lambda k: (out['beats'][k]['take'], out['beats'][k]['start']))
    for rank, k in enumerate(order): out['beats'][k]['src_order'] = rank
    if mode in ('keep', 'script') and [b['src_order'] for b in out['beats']] != sorted(b['src_order'] for b in out['beats']) and mode == 'keep':
        errors.append('mode "keep" must keep the beats in the order they were said')
    out['left_out'] = _left_out(sb.get('left_out') or (win or {}).get('left_out'), '', errors)
    return out, errors


def _beats(beats, takes, where, errors):
    out = []
    for n, b in enumerate(beats, 1):
        if not isinstance(b, dict):
            errors.append(f'{where}beat {n}: must be an object'); continue
        span = _check_span(b, takes, f'{where}beat {n}', errors)
        if not span: continue
        alts = []
        for m, a in enumerate(b.get('alts') or [], 1):
            s2 = _check_span(a, takes, f'{where}beat {n} alt {m}', errors)
            if s2: alts.append(s2)
        item = dict(span, id=str(b.get('id') or f'b{n}'), label=str(b.get('label', ''))[:40],
                    keep=bool(b.get('keep', True)), alts=alts, src_order=None)
        for k in ('plants', 'pays_off'):
            if b.get(k): item[k] = str(b[k])
        out.append(item)
    ids = {b['id'] for b in out}
    for b in out:
        for k in ('plants', 'pays_off'):
            if b.get(k) and b[k] not in ids:
                errors.append(f'{where}beat {b["id"]}: "{k}" names beat "{b[k]}", which is not in the same arc')
    return out


def _overlaps(beats, where, errors):
    seen = {}
    for b in beats:
        for o in seen.get(b['take'], []):
            if b['start'] < o['end'] - 0.05 and o['start'] < b['end'] - 0.05:
                errors.append(f'{where}beat {b["id"]} overlaps beat {o["id"]} in {b["take"]}: each spoken line can be used once')
        seen.setdefault(b['take'], []).append(b)


def _txt(v, n=300):
    return str(v if v is not None else '').strip()[:n]


def _left_out(items, where, errors):
    out = []
    for n, x in enumerate(items or [], 1):
        if not isinstance(x, dict): continue
        item = {'line': _txt(x.get('line')), 'why': _txt(x.get('why'), 200), 'take': x.get('take'),
                'start': x.get('start'), 'end': x.get('end')}
        if not item['why']: errors.append(f'{where}left_out {n}: say why it was left out')
        out.append(item)
    return out


def _arc(a, takes, n, mode, errors):
    w = f'arc {a.get("id") or n}: '
    shp = a.get('shape')
    if shp not in SHAPES: errors.append(f'{w}shape must be one of {sorted(SHAPES)}')
    hook = a.get('hook') if isinstance(a.get('hook'), dict) else {}
    search = [_txt(s, 120) for s in hook.get('search') or [] if _txt(s)]
    if not _txt(hook.get('problem')): errors.append(f'{w}hook.problem is empty: the viewer\'s problem or the question they would type')
    if not 2 <= len(search) <= 3: errors.append(f'{w}hook.search needs 2-3 search phrasings')
    if not _txt(a.get('first_gate')): errors.append(f'{w}first_gate is empty: after this, the viewer can ___')
    openings = []
    for m, o in enumerate(a.get('openings') or [], 1):
        sp = _check_span(o, takes, f'{w}opening {m}', errors) if isinstance(o, dict) else None
        if sp: openings.append(dict(sp, on_screen=_txt(o.get('on_screen'), 200)))
    beats = _beats(a.get('beats') or [], takes, w, errors)
    if not beats: errors.append(f'{w}beats is empty')
    _overlaps(beats, w, errors)
    af = a.get('after_feeling') if isinstance(a.get('after_feeling'), dict) else {}
    feel = {'line': None, 'missing': True}
    if _txt(af.get('line')):
        sp = _check_span(af, takes, f'{w}after_feeling', errors)   # only where they already said one
        if sp: feel = dict(sp, missing=False)
    return {'id': str(a.get('id') or chr(64 + n)), 'way_in': _txt(a.get('way_in'), 200), 'shape': shp,
            'first_gate': _txt(a.get('first_gate')), 'hook': {'problem': _txt(hook.get('problem')), 'search': search},
            'openings': openings, 'beats': beats, 'after_feeling': feel, 'ending': _txt(a.get('ending')),
            'open_thread': _txt(a.get('open_thread')), 'missing_question': _txt(a.get('missing_question')),
            'left_out': _left_out(a.get('left_out'), w, errors)}


def _story_fields(sb, takes, out, errors):
    """The step 3 fields. Returns the winning arc (checked) or None when the storyboard has no arcs (older ones)."""
    if sb.get('trying_to_tell'): out['trying_to_tell'] = _txt(sb['trying_to_tell'])
    arcs = sb.get('arcs')
    if arcs in (None, []): return None
    if not isinstance(arcs, list): errors.append('arcs must be a list of 2-3 arcs'); return None
    lo = 2 if out['mode'] == 'find' else 1
    if not lo <= len(arcs) <= 3: errors.append(f'arcs: give {lo}-3 competing arcs, each a different way in and shape')
    clean = [_arc(a, takes, n, out['mode'], errors) for n, a in enumerate(arcs, 1) if isinstance(a, dict)]
    ids = [a['id'] for a in clean]
    if len(set(ids)) != len(ids): errors.append('arcs: every arc needs its own id')
    if out['mode'] == 'find' and len(clean) > 1 and len({a['shape'] for a in clean}) < 2:
        errors.append('arcs: use a different shape per arc')
    sc = sb.get('score') if isinstance(sb.get('score'), dict) else {}
    by = _txt(sc.get('by'), 120)
    score = {'by': by}
    if not by: errors.append('score.by is empty: the arcs are scored by a separate judge that wrote none of them')
    elif sb.get('written_by') and by.lower() == str(sb['written_by']).strip().lower():
        errors.append('score.by is the same as written_by: the judge must not be the one who wrote the arcs')
    for a in clean:
        s = sc.get(a['id'])
        if not isinstance(s, dict): errors.append(f'score: arc {a["id"]} has no score'); continue
        row = {}
        for k in SCORE_KEYS:
            try: v = float(s.get(k))
            except (TypeError, ValueError): v = None
            if v is None or not 0 <= v <= 10: errors.append(f'score {a["id"]}.{k} must be 0-10'); v = 0
            row[k] = v
        row['total'] = round(sum(row.values()), 1)
        row['why'] = _txt(s.get('why'), 240)
        if not row['why']: errors.append(f'score {a["id"]}: one line of why')
        score[a['id']] = row
    out.update(arcs=clean, score=score)
    if sb.get('written_by'): out['written_by'] = _txt(sb['written_by'], 120)
    win = str(sb.get('winner') or '')
    if win not in ids: errors.append(f'winner must be one of the arc ids {ids}'); return None
    rows = [(score[i]['total'], score[i]['missing'], i) for i in ids if i in score]
    if rows and sb.get('picked_by') != 'creator':
        best = max(rows)[:2]
        if (score.get(win, {}).get('total'), score.get(win, {}).get('missing')) != best:
            errors.append(f'winner {win} is not the top score (a tie goes to fewer missing lines); '
                          'set "picked_by": "creator" only when the creator chose it')
    if sb.get('picked_by') == 'creator': out['picked_by'] = 'creator'
    w = next(a for a in clean if a['id'] == win)
    out['winner'] = win
    out['question'] = _txt(sb.get('question')) or w['missing_question']
    # the winner as sent: its beats and left_out feed the top-level ones when those are left out
    return next((a for n, a in enumerate(arcs, 1) if isinstance(a, dict) and str(a.get('id') or chr(64 + n)) == win), {})
