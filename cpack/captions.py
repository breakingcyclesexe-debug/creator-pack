"""Burned captions without Remotion or libass: each caption is drawn by Pillow into a transparent strip, and
ffmpeg's concat demuxer plays the strips as one overlay stream (render.py).

Styles: "word" (one word at a time), "three" (up to 3 words), "lines" (up to 3 lines). The word being said is
drawn in the pop colour. Looks (soft, clean, glow), where they sit (top, middle, bottom, left, right, moves around)
and how they come in (a quick pop) are at the end of this file. Captions only ever show words that are in the cut (the kept words, as heard).

fix()      a word the listener got wrong ("clock" for "Claude"), corrected by the buyer: every time it shows up in
           this video. Only the caption text changes, never the cut.
script     Chinese captions: Cantonese is always Traditional characters; Mandarin is what the buyer picked once,
           Traditional (Taiwan, Hong Kong) or Simplified (mainland China). Drawn with a font that has them."""
import os, re
from .cutrules import norm

SIZES = {'s': 0.050, 'm': 0.064, 'l': 0.080}   # font size as a share of the frame width, one word or three
LINES_SIZE = {'s': 0.040, 'm': 0.048, 'l': 0.058}
POS = {'top': 0.16, 'middle': 0.50, 'bottom': 0.74}  # centre of the caption strip, share of frame height
BREAK_GAP = 0.45
END = re.compile(r'[.?!]["\')]*$')


def _clean(w):
    return w.strip()


CJK = re.compile(r'[\u3400-\u9fff\uf900-\ufaff]')


def has_cjk(words):
    return any(CJK.search(w['w'] if isinstance(w, dict) else str(w)) for w in words)


def script_for(language, chinese=''):
    """Which Chinese characters the captions use: 'trad', 'simp', or None when the take is not Chinese.
    Cantonese is always Traditional. Mandarin (and a take whose language was worked out for us) uses the buyer's
    one-time pick, Traditional until they pick."""
    if language == 'yue': return 'trad'
    if language in ('zh', 'auto', '', None): return chinese if chinese in ('trad', 'simp') else ('trad' if language == 'zh' else None)
    return None


def to_script(words, script, convert):
    """Words with their Chinese text in the wanted script. convert(texts, 'trad'|'simp') -> texts (the platform's)."""
    if script not in ('trad', 'simp') or not has_cjk(words): return words
    idx = [k for k, w in enumerate(words) if CJK.search(w['w'])]
    try: new = convert([words[k]['w'] for k in idx], script)
    except Exception: return words
    if len(new) != len(idx): return words
    out = [dict(w) for w in words]
    for k, t in zip(idx, new): out[k]['w'] = t
    return out


def clean_fix(text):
    """The buyer's corrected word: one line, no control characters, 40 characters at most."""
    return ' '.join(re.sub(r'[\x00-\x1f\x7f]', ' ', str(text or '')).split())[:40]


def fix(words, fixes):
    """Apply the buyer's corrections {heard word, normalised: right word} to every caption word that matches.
    Punctuation around the word stays ("clock," -> "Claude,"), and so does a possessive ("clock's" -> "Claude's")."""
    if not fixes: return words
    out = []
    for w in words:
        t = w['w']; core = t.strip(); n = norm(core)
        new = fixes.get(n)
        if new is None and n.endswith("'s") and n[:-2] in fixes: new = fixes[n[:-2]] + "'s"
        if new is not None:
            m = re.match(r"^([^\w']*)(.*?)([^\w']*)$", core, re.S)
            lead = t[:len(t) - len(t.lstrip())]
            w = dict(w, w=lead + m.group(1) + new + m.group(3), was=core)
        out.append(w)
    return out


def chunks(words, style='three', per_line=4, max_lines=3):
    """Group output-timed words [{"w","s","e"}] into captions. Returns lists of words."""
    cap = {'word': 1, 'three': 3}.get(style, per_line * max_lines)
    if has_cjk(words): cap = {'word': 2, 'three': 6}.get(style, per_line * max_lines * 2)   # a Chinese "word" here is 1-2 characters
    out, cur = [], []
    for k, w in enumerate(words):
        if cur and (len(cur) >= cap or w['s'] - cur[-1]['e'] > BREAK_GAP or END.search(_clean(cur[-1]['w']))):
            out.append(cur); cur = []
        cur.append(w)
    if cur: out.append(cur)
    return out


def srt(words, per_line=4, max_lines=2):
    """Timed words [{"w","s","e"}] as a .srt subtitle file: full lines, two at most per block, broken at the same
    pauses and sentence ends as the captions on screen."""
    def ts(t):
        ms = int(round(max(0.0, t) * 1000))
        return f'{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}'
    groups = chunks(words, 'lines', per_line, max_lines)
    out = []
    for n, ch in enumerate(groups, 1):
        e = ch[-1]['e']
        if n < len(groups): e = min(e + 0.25, groups[n][0]['s'])
        text = '\n'.join(' '.join(w['w'].strip() for w in l) for l in lines_of(ch, 'lines', per_line))
        out.append(f'{n}\n{ts(ch[0]["s"])} --> {ts(max(e, ch[0]["s"] + 0.1))}\n{text}\n')
    return '\n'.join(out)


def lines_of(chunk, style, per_line=4):
    if style != 'lines': return [chunk]
    if has_cjk(chunk): per_line *= 2
    return [chunk[i:i + per_line] for i in range(0, len(chunk), per_line)]


def events(words, style='three', per_line=4, max_lines=3):
    """Timed caption events [{"s","e","lines":[[text,...]],"hi":(line, index)}], one per word said, each showing
    its chunk with that word lit. Gaps under a pause are bridged so captions don't flicker."""
    if style == 'none' or not words: return []
    ev = []
    groups = chunks(words, style, per_line, max_lines)
    for g, ch in enumerate(groups):
        ls = lines_of(ch, style, per_line)
        flat = [(li, wi) for li, l in enumerate(ls) for wi in range(len(l))]
        nxt_start = groups[g + 1][0]['s'] if g + 1 < len(groups) else None
        for k, w in enumerate(ch):
            s = w['s']
            e = ch[k + 1]['s'] if k + 1 < len(ch) else w['e'] + 0.25
            if k + 1 == len(ch) and nxt_start is not None and nxt_start - w['e'] < BREAK_GAP: e = nxt_start
            if nxt_start is not None: e = min(e, nxt_start)
            ev.append({'s': round(s, 3), 'e': round(max(e, s + 0.06), 3), 'g': g,
                       'lines': [[_clean(x['w']) for x in l] for l in ls], 'hi': flat[k]})
    for a, b in zip(ev, ev[1:]):  # never overlap
        if a['e'] > b['s']: a['e'] = b['s']
    return [x for x in ev if x['e'] - x['s'] > 0.02]





# ---- how captions look, where they sit, how they come in (a tester, 22 Nov: "i don't like the words like hard shadow i
# don't like the fonts at least have something is pleasing to watch"; "the placement the words can be on the left
# hand side on the right hand side or maybe random"; "where are the fucking motion graphics and effects").
#
# Looks. No hard outline on any of them: a soft blurred shadow (and a wide faint one so it still reads on a bright
# sky), or a warm glow.
#   soft   a tester's own reel subtitles (reel skill S1): DM Sans semi-bold, as spoken, cream, soft shadow. The default,
#          and what an older project with no look gets.
#   clean  the NatGeo type a tester approved (style references R4): Avenir Next Heavy, capitals, white, a little tracking.
#   glow   white DM Sans in a warm gold halo; the word being said glows brighter.
# shadow rows: (alpha 0..1, blur radius, drop, spread) as a share of the font size. spread thickens the shadow a
# little before the blur, so it reads on bright footage; after the blur it still has no edge.
FONTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'fonts')
DM_SANS = os.path.join(FONTS_DIR, 'DMSans.ttf')
CREAM, GOLD, WHITE = '#FAF6EC', '#E3991D', '#FFFFFF'
LOOKS = {
    'soft':  {'weight': 580, 'upper': False, 'color': CREAM, 'track': 0.0,
              'shadow': [(0.55, 0.07, 0.04, 0), (0.50, 0.22, 0.02, 0.06)], 'glow': None, 'motion': 'settle'},
    'clean': {'weight': None, 'upper': True, 'color': WHITE, 'track': 0.04,
              'shadow': [(0.30, 0.07, 0.03, 0), (0.42, 0.22, 0.02, 0.05)], 'glow': None, 'motion': 'pop'},
    'glow':  {'weight': 600, 'upper': False, 'color': WHITE, 'track': 0.0,
              'shadow': [(0.45, 0.22, 0.03, 0.05)], 'glow': (GOLD, 0.17, 0.85), 'motion': 'settle'},
}
OLD_GOLDS = ('#e3991d', '#e8a13d')   # the default pop colours, now and before
# Where. Left / right: the text lines up with that side, 7% in. Upright video keeps out of Instagram's buttons and
# caption (the right 11% and the bottom 12%).
SIDE = 0.07
IG_RIGHT, IG_BOTTOM = 0.11, 0.12
SIDE_Y = 0.70
# "moves around": these few spots, a new one only when a new sentence starts and the last one has been up a while
SPOTS = [('center', 0.74), ('left', 0.62), ('right', 0.30), ('left', 0.24), ('right', 0.56), ('center', 0.20)]
HOLD = 1.6
# Motion: (scale, drop as a share of font size, opacity) per frame, then the caption as drawn. "pop" is quick,
# "settle" pops a touch past full size and eases back. The word-being-said change stays a hard switch.
MOTION = {'pop': [(0.88, 0.0, 0.35), (0.93, 0.0, 0.70), (0.97, 0.0, 0.92), (0.99, 0.0, 1.0)],
          'settle': [(0.88, 0.10, 0.35), (0.94, 0.06, 0.70), (0.99, 0.03, 0.92), (1.025, 0.0, 1.0), (1.01, 0.0, 1.0)]}


def look_of(cfg):
    return cfg.get('look') if cfg.get('look') in LOOKS else 'soft'


def pop_colour(cfg):
    p = cfg.get('pop') or GOLD
    if look_of(cfg) == 'glow' and str(p).lower() in OLD_GOLDS: return CREAM
    return p


def motion_of(cfg):
    return LOOKS[look_of(cfg)]['motion'] if cfg.get('motion', True) else None


def _hex(c, default):
    c = (c or default).lstrip('#')
    try: return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)) + (255,)
    except ValueError: return _hex(default, '#ffffff')


_fonts = {}


def _font(font_path, size, weight=None):
    """font_path: a file, or (file, face number) for a collection such as PingFang.ttc (the Traditional face).
    weight: for a variable font (DM Sans), its weight; ignored by a font that has no weight axis."""
    from PIL import ImageFont
    key = (tuple(font_path) if isinstance(font_path, (tuple, list)) else font_path, size, weight)
    if key in _fonts: return _fonts[key]
    if not font_path: f = ImageFont.load_default(size)
    elif isinstance(font_path, (tuple, list)): f = ImageFont.truetype(font_path[0], size, index=int(font_path[1]))
    else: f = ImageFont.truetype(font_path, size)
    if weight:
        try:
            axes = f.get_variation_axes()
            vals = []
            for a in axes:
                name = a['name'].decode() if isinstance(a['name'], bytes) else str(a['name'])
                want = weight if name.lower() == 'weight' else min(a['maximum'], max(a['minimum'], 32)) if 'optical' in name.lower() else a['default']
                vals.append(min(a['maximum'], max(a['minimum'], want)))
            f.set_variation_by_axes(vals)
        except Exception: pass
    _fonts[key] = f
    return f


def font_size(W, cfg):
    style = cfg.get('style', 'three')
    return int(W * (LINES_SIZE if style == 'lines' else SIZES).get(cfg.get('size', 'm'), 0.064))


def upright(W, H):
    return H > W * 1.2


def text_area(W, frame_h, align):
    """(left, right) pixels the text may use. Centred text stays centred, so it keeps the same room both sides."""
    up = upright(W, frame_h or 0)
    right = W * (1 - (IG_RIGHT if up else 0.06))
    if align == 'left': return W * SIDE, right
    if align == 'right': return W * SIDE, W * (1 - max(SIDE, IG_RIGHT if up else SIDE))
    m = IG_RIGHT if up else 0.06
    return W * m, W * (1 - m)


def fixed_spot(position):
    if position == 'left': return ('left', SIDE_Y)
    if position == 'right': return ('right', SIDE_Y)
    return ('center', POS.get(position, POS['bottom']))


def seed_of(evs):
    """The same cut gives the same seed (its caption timings, not its words, so a fixed word moves nothing)."""
    import zlib
    return zlib.crc32(','.join(f"{e['s']:.2f}" for e in evs).encode())


def move_plan(evs, seed=None):
    """One spot per event for "moves around". A caption only moves when a new sentence starts (after a full stop
    or a pause) and the spot has been held HOLD seconds; never to the spot it is already in."""
    import random
    rng = random.Random(seed_of(evs) if seed is None else seed)
    cur = rng.randrange(len(SPOTS)); since = evs[0]['s'] if evs else 0.0
    out, prev, prev_e, ends = [], None, None, False
    for ev in evs:
        g = ev.get('g', tuple(map(tuple, ev['lines'])))
        if prev is not None and g != prev:
            new_sentence = ends or (ev['s'] - prev_e > BREAK_GAP)
            if new_sentence and ev['s'] - since >= HOLD:
                cur = rng.choice([k for k in range(len(SPOTS)) if k != cur]); since = ev['s']
        if g != prev:
            last = ev['lines'][-1][-1] if ev['lines'] and ev['lines'][-1] else ''
            ends = bool(END.search(last))
        prev, prev_e = g, ev['e']
        out.append(SPOTS[cur])
    return out


def _width(d, t, font, track):
    w = d.textlength(t, font=font)
    return w + track * max(0, len(t) - 1)


def _put(d, xy, t, font, fill, track):
    if not track: d.text(xy, t, font=font, fill=fill); return
    x, y = xy
    for ch in t:
        d.text((x, y), ch, font=font, fill=fill); x += d.textlength(ch, font=font) + track


def draw(ev, W, H, cfg, font_path, spot=None, frame_h=None):
    """One caption image (W x H, transparent) for an event. spot: (align, centre y in this image's pixels), default
    the middle of the image lined up as the setting says. frame_h: the video's height, for the safe area."""
    from PIL import Image, ImageDraw, ImageFilter, ImageChops
    L = LOOKS[look_of(cfg)]
    style = cfg.get('style', 'three')
    size = font_size(W, cfg)
    font = _font(font_path, size, L['weight'])
    col, pop = _hex(L['color'], WHITE), _hex(pop_colour(cfg), GOLD)
    if spot is None: spot = (fixed_spot(cfg.get('position', 'bottom'))[0], H / 2)
    align, cy = spot
    lines = ev['lines'] if style != 'word' else [[ev['lines'][0][ev['hi'][1]]]]
    hi = ev['hi'] if style != 'word' else (0, 0)
    cjk = has_cjk([t for l in lines for t in l])
    track = 0 if cjk else L['track'] * size
    txt_l = Image.new('RGBA', (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(txt_l)
    hi_m = Image.new('L', (W, H), 0); dh = ImageDraw.Draw(hi_m)
    x0, x1 = text_area(W, frame_h or H, align)
    lh = int(size * 1.18)
    y = int(cy - lh * len(lines) / 2)
    for li, l in enumerate(lines):
        txt = [t.upper() if L['upper'] else t for t in l]
        # Chinese is written without spaces between words
        gap = [0 if (wi + 1 < len(txt) and CJK.search(t[-1:]) and CJK.search(txt[wi + 1][:1])) else 1 for wi, t in enumerate(txt)]
        f2, tr = font, track
        space = d.textlength(' ', font=f2) + tr
        widths = [_width(d, t, f2, tr) for t in txt]
        total = sum(widths) + space * sum(gap[:-1])
        scale = 1.0
        for _ in range(4):   # too wide: a smaller size until it fits (the size is whole pixels, so check again)
            if not total or total <= x1 - x0 or not font_path: break
            scale *= (x1 - x0) / total * 0.99
            f2 = _font(font_path, max(8, int(size * scale)), L['weight']); tr = track * scale
            space = d.textlength(' ', font=f2) + tr
            widths = [_width(d, t, f2, tr) for t in txt]; total = sum(widths) + space * sum(gap[:-1])
        x = x0 if align == 'left' else (x1 - total - size * 0.04 if align == 'right' else (W - total) / 2)   # a glyph's ink can sit past its width
        for wi, t in enumerate(txt):
            said = (li, wi) == tuple(hi) and cfg.get('pop_on', True)
            _put(d, (x, y), t, f2, pop if said else col, tr)
            if said: _put(dh, (x, y), t, f2, 255, tr)
            x += widths[wi] + space * gap[wi]
        y += lh
    box = txt_l.getbbox()
    if not box: return txt_l
    # effects on the text's own area only (fast), then back into the full image
    pad = int(size * 0.9)
    bx = (max(0, box[0] - pad), max(0, box[1] - pad), min(W, box[2] + pad), min(H, box[3] + pad))
    t_c = txt_l.crop(bx); a = t_c.getchannel('A'); h_c = hi_m.crop(bx)
    out = Image.new('RGBA', t_c.size, (0, 0, 0, 0))

    def layer(mask, rgb, alpha, blur, drop, spread=0):
        if spread: mask = mask.filter(ImageFilter.MaxFilter(2 * max(1, int(spread * size / 2)) + 1))
        m = mask.filter(ImageFilter.GaussianBlur(max(1, blur * size))) if blur else mask
        if alpha < 1: m = m.point(lambda v: int(v * alpha))
        lay = Image.new('RGBA', mask.size, rgb + (0,)); lay.putalpha(m)
        dy = int(round(drop * size))
        if dy:
            sh = Image.new('RGBA', mask.size, (0, 0, 0, 0)); sh.paste(lay, (0, dy)); lay = sh
        return lay

    for alpha, blur, drop, spread in L['shadow']:
        out = Image.alpha_composite(out, layer(a, (0, 0, 0), alpha, blur, drop, spread))
    if L['glow']:
        g_rgb, g_blur, g_alpha = L['glow']
        g = _hex(g_rgb, GOLD)[:3]
        out = Image.alpha_composite(out, layer(a, g, g_alpha * 0.75, g_blur, 0))
        if h_c.getbbox():   # the word being said glows brighter
            out = Image.alpha_composite(out, layer(h_c, g, 1.0, g_blur * 1.3, 0))
            out = Image.alpha_composite(out, layer(h_c, g, 0.9, g_blur * 0.5, 0))
    out = Image.alpha_composite(out, t_c)
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0)); img.paste(out, bx[:2])
    return img


def moved(img, scale, drop, alpha):
    """img with its caption scaled about its own centre, dropped by drop pixels and faded to alpha."""
    from PIL import Image
    box = img.getbbox()
    if not box: return img
    if abs(scale - 1) < 1e-3 and not drop and alpha >= 0.999: return img
    part = img.crop(box)
    w, h = max(1, round(part.width * scale)), max(1, round(part.height * scale))
    part = part.resize((w, h), Image.LANCZOS)
    if alpha < 0.999:
        part.putalpha(part.getchannel('A').point(lambda v: int(v * alpha)))
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    out = Image.new('RGBA', img.size, (0, 0, 0, 0))
    out.paste(part, (int(round(cx - w / 2)), int(round(cy - h / 2 + drop))))   # onto clear: no mask (a mask would square the fade)
    return out


def strip_height(W, cfg):
    style = cfg.get('style', 'three')
    size = W * (LINES_SIZE if style == 'lines' else SIZES).get(cfg.get('size', 'm'), 0.064)
    return int(size * 1.18 * (3 if style == 'lines' else 1) + size * 2)   # room for the soft shadow and the pop


def plan_rows(evs, fps, motion):
    """[(event index, frame k or None, seconds)] covering each event: k = the motion frame (MOTION[motion][k]),
    None = the caption as drawn. The motion frames are taken out of the event's own time, so every event still
    starts and ends exactly when it did: the sound and the clock never move."""
    frames = MOTION.get(motion) if motion else None
    out, prev = [], None
    for n, ev in enumerate(evs):
        g = ev.get('g', tuple(map(tuple, ev['lines'])))
        d = ev['e'] - ev['s']
        fresh = frames and (g != prev or (n and evs[n - 1]['e'] < ev['s'] - 0.001))
        if fresh:
            k = max(0, min(len(frames), int(d * fps) - 1))
            for j in range(k): out.append((n, j, 1.0 / fps))
            d -= k / fps
        out.append((n, None, d))
        prev = g
    return out


# Each picture is read with a 1 ms clock. The image reader's own is 1/25 s: every caption landed up to 20 ms off,
# and a one-frame motion row (33 ms) could vanish between two ticks.
TB = 'option framerate 1000\n'


def band_y(evs, W, H, cfg, band):
    """Centre y (pixels) of the captions in the empty band under the picture (black and image fits): centred
    between the picture's bottom edge and Instagram's bottom 12%, or just under the picture when that is too small
    for the caption's lines. band: (top band bottom, bottom band top) from shape.bands."""
    size = font_size(W, cfg)
    lines = max([1] + [len(e['lines']) for e in evs]) if cfg.get('style', 'three') != 'word' else 1
    need = size * 1.18 * lines
    gap = size * 0.45
    top, safe = band[1], H * (1 - IG_BOTTOM)
    if safe - top >= need + 2 * gap: return (top + safe) / 2
    return top + gap + need / 2


def write_track(evs, W, H, cfg, font_path, folder, total, fps=30, seed=None, band=None):
    """PNG strips + an ffmpeg concat list covering 0..total. Returns (list path, strip height, y offset).
    band: the empty bands round a black / image fit picture (shape.bands): the captions go centred in the one
    below it, unless the buyer chose top."""
    from PIL import Image
    os.makedirs(folder, exist_ok=True)
    sh0 = strip_height(W, cfg); sh0 += sh0 % 2
    pos = cfg.get('position', 'bottom')
    spots = move_plan(evs, seed) if pos == 'moves' else [fixed_spot(pos)] * len(evs)
    if band and pos != 'top': spots = [('center', band_y(evs, W, H, cfg, band) / H)] * len(evs)
    cys = [cy * H for _, cy in spots] or [POS['bottom'] * H]
    y0 = max(0, int(min(cys) - sh0 / 2)); y1 = min(H, int(max(cys) + sh0 / 2))
    sh = y1 - y0; sh -= sh % 2
    blank = os.path.join(folder, 'blank.png'); Image.new('RGBA', (W, sh), (0, 0, 0, 0)).save(blank)
    motion = motion_of(cfg)
    rows, t, cache, full, begun = [], 0.0, {}, {}, set()
    for n, k, dur in plan_rows(evs, fps, motion):
        ev = evs[n]
        if n not in begun:   # the event's first row: the gap before it is blank
            begun.add(n)
            if ev['s'] > t + 0.001: rows.append((blank, ev['s'] - t, None))
            t = max(t, ev['s'])
        sp = spots[n]
        key = (tuple(map(tuple, ev['lines'])), tuple(ev['hi']), sp)
        if key not in full:
            full[key] = draw(ev, W, sh, cfg, font_path, (sp[0], sp[1] * H - y0), frame_h=H)
        ck = key + (k,)
        if ck not in cache:
            img = full[key] if k is None else moved(full[key], MOTION[motion][k][0], MOTION[motion][k][1] * font_size(W, cfg), MOTION[motion][k][2])
            p = os.path.join(folder, f'c{len(cache):05d}.png'); img.save(p, compress_level=1); cache[ck] = p
        rows.append((cache[ck], dur, n)); t += dur
    if total > t: rows.append((blank, total - t, None))
    lst = os.path.join(folder, 'captions.txt')
    with open(lst, 'w') as f:
        f.write('ffconcat version 1.0\n')
        clock = written = 0.0
        for p, d, _ in rows:
            clock += d
            dd = round(clock - written, 3)
            if dd < 0.001: continue
            written += dd
            f.write(f"file '{os.path.basename(p)}'\n{TB}duration {dd:.3f}\n")
        f.write(f"file '{os.path.basename(rows[-1][0] if rows else blank)}'\n{TB}")
    return lst, sh, y0
