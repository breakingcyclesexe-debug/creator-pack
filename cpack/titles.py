"""Titles: the hook line big on screen at the start of the video, the way good Reels and Shorts open (a tester, 22 Nov:
"where are the fucking motion graphics and effects"; titles are the first one).

When the project's `title` setting is on, the first part's opening line, in the speaker's own words, shows in the
upper third for the first 1.5 to 3 seconds. A long line is shortened to 3 to 7 words (a run of the words as said,
never reworded; the cut itself never changes). It comes in and goes out with motion, and while it is up the
captions for exactly those words are left out, so a word never shows twice.

Styles, one per caption look:
  soft    DM Sans bold, cream, soft shadow, spoken case. Fades in with a slight rise.
  clean   the NatGeo type a tester approved (style references R4): Avenir Next Heavy, capitals, white, tight tracking,
          one word in Bahamas Gold #E3991D. Fades in with a slight rise.
  poster  Anton capitals in gold, a tester's reel cover energy (reel skill T1). Each word comes in as it is said.
All three sit on a soft shade at the top of the frame (reel skill TitleCard: light type over the live opening shot,
soft top shade). No hard outline, no box. Placement: the upper third, inside Instagram's safe area (the right 11%
and the bottom 12% stay clear).

Drawn the same way as the captions (captions.py): Pillow draws each picture, ffmpeg's concat reader plays them as
one overlay stream on the same 1 ms clock, laid over the video in render.final().

  prepare(settings, words) -> (caption words, plan or None)   plan: {"style", "words", "text", "s", "e", "n0", "n1"}
  write_track(plan, W, H, font_path, folder, total, fps) -> (list path, y)
"""
import os, re
from . import captions
from .cutrules import norm
from .platform import get as platform

P = platform()
STYLES = ('soft', 'clean', 'poster')
MIN_T, MAX_T = 1.5, 3.0        # how long the title is up
TAIL = 0.45                    # it stays this long after its last word is said (inside MIN_T..MAX_T)
MAX_WORDS, MIN_WORDS = 7, 3
ANTON = os.path.join(captions.FONTS_DIR, 'Anton-Regular.ttf')
# Leading words a hook reads better without ("so you work 40 hours" -> "you work 40 hours"). They keep their caption.
LEAD = {'so', 'and', 'but', 'um', 'uh', 'umm', 'erm', 'like', 'okay', 'ok', 'well', 'yeah', 'now', 'right', 'alright'}
# A shortened line should not stop on one of these ("i wish i started something on the" reads broken)
WEAK = LEAD | {'a', 'an', 'the', 'to', 'of', 'for', 'in', 'on', 'at', 'by', 'with', 'from', 'my', 'your', 'our', 'his',
               'her', 'their', 'its', 'i', 'you', 'we', 'they', 'he', 'she', 'it', 'is', 'are', 'was', 'were', 'be',
               'that', 'this', 'than', 'then', 'if', 'or', 'as', 'just', 'really', 'very', 'even', 'don\'t', 'didn\'t',
               'i\'m', 'i\'ve', 'it\'s', 'have', 'has', 'had', 'do', 'did', 'not', 'no', 'when', 'what', 'who', 'how'}
PUNCT_END = re.compile(r'[,;:.?!…]["\')]*$')

# size: share of the frame's shorter side (upright: its width). shade: the soft top shade's darkest alpha.
# shadow rows: (alpha, blur, drop) as a share of the font size, the same soft kind the captions use.
LOOK = {
    'soft':   {'font': 'dm', 'weight': 700, 'upper': False, 'color': captions.CREAM, 'accent': None, 'size': 0.092,
               'track': 0.0, 'lh': 1.12, 'motion': 'rise', 'shade': 0.42,
               'shadow': [(0.55, 0.07, 0.04), (0.45, 0.24, 0.02)]},
    'clean':  {'font': 'heavy', 'weight': 800, 'upper': True, 'color': captions.WHITE, 'accent': captions.GOLD,
               'size': 0.082, 'track': 0.01, 'lh': 1.08, 'motion': 'rise', 'shade': 0.40,
               'shadow': [(0.35, 0.07, 0.03), (0.40, 0.24, 0.02)]},
    'poster': {'font': 'anton', 'weight': None, 'upper': True, 'color': captions.GOLD, 'accent': None, 'size': 0.138,
               'track': 0.012, 'lh': 1.02, 'motion': 'words', 'shade': 0.55,
               'shadow': [(0.65, 0.05, 0.035), (0.60, 0.18, 0.02), (0.35, 0.40, 0.0)]},   # gold needs more lift off warm footage
}
IN, OUT, WORD_IN = 0.40, 0.30, 0.20     # seconds: the title coming in, going out, one word coming in (poster)
RISE = 0.20                             # how far it rises as it comes in, share of the font size


def style_of(settings):
    s = (settings or {}).get('title', 'off')
    return s if s in STYLES else None


# ---- which words -------------------------------------------------------------------------------------------------

def opening_line(words):
    """Indexes [a, b) of the opening line: the first sentence of the first part, up to a full stop or a pause."""
    if not words: return 0, 0
    b = 1
    while b < len(words):
        if captions.END.search(words[b - 1]['w'].strip()) or words[b]['s'] - words[b - 1]['e'] > captions.BREAK_GAP: break
        b += 1
    return 0, b


def pick(words):
    """Indexes [n0, n1) of the title words: the opening line, or 3 to 7 of its words in a row when it is long,
    chosen to end on a natural break (a comma) and a strong word, and to be said inside MAX_T. One word more (8)
    only when every run of up to 7 stops on a weak word and the 8th lands it (all-on test, 22 Nov: a slow opener
    gave "I FEEL WE ARE IN A VERY" where "... VERY EXCITING" was said in time)."""
    a, b = opening_line(words)
    if b - a == 0: return 0, 0
    while b - a > MIN_WORDS and norm(words[a]['w']) in LEAD: a += 1
    def fits(n1): return words[n1 - 1]['e'] - words[0]['s'] <= MAX_T - 0.3
    if b - a <= MAX_WORDS and fits(b): return a, b
    best, best_score = None, None
    for n1 in range(a + 1, min(b, a + MAX_WORDS + 1) + 1):
        n = n1 - a
        if not fits(n1) and n1 > a + 1: break
        last = words[n1 - 1]['w'].strip()
        score = n * 1.0
        if n < MIN_WORDS: score -= 6
        if n > MAX_WORDS: score -= 3   # the extra word only wins over a run that stops on a weak word
        if PUNCT_END.search(last): score += 3
        if norm(last) in WEAK: score -= 5
        if best_score is None or score >= best_score: best, best_score = n1, score
    return a, best


def prepare(settings, words):
    """(the words the captions show, the title plan or None). Off, or no words: the words as they are, untouched."""
    style = style_of(settings)
    if not style or not words: return words, None
    n0, n1 = pick(words)
    if n1 <= n0: return words, None
    tw = words[n0:n1]
    end = min(MAX_T, max(MIN_T, tw[-1]['e'] + TAIL))
    plan = {'style': style, 'n0': n0, 'n1': n1, 's': 0.0, 'e': round(end, 3),
            'words': [{'w': w['w'].strip(), 's': w['s'], 'e': w['e']} for w in tw],
            'text': ' '.join(w['w'].strip() for w in tw)}
    return words[:n0] + words[n1:], plan


# ---- how it looks ------------------------------------------------------------------------------------------------

def font_for(style, words=None, script=None):
    """The style's font. Chinese: the Mac's PingFang, any style."""
    if words and captions.has_cjk(words): return P.font_cjk(script or 'trad') or P.font()
    f = LOOK[style]['font']
    if f == 'anton' and os.path.exists(ANTON): return ANTON
    if f == 'heavy':
        heavy = getattr(P, 'font_heavy', lambda: None)()
        if heavy: return heavy
    return captions.DM_SANS if os.path.exists(captions.DM_SANS) else P.font()


def safe_box(W, H):
    """(left, top, right, bottom) pixels the title's letters may use: the upper third, and on upright video clear
    of Instagram's buttons on the right (kept the same on the left, so the title stays centred)."""
    side = W * (captions.IG_RIGHT if captions.upright(W, H) else 0.06)
    top = H * (0.075 if captions.upright(W, H) else 0.07)
    return side, top, W - side, H * (0.31 if captions.upright(W, H) else 0.33)   # upright: a little air above the speaker's head


def band_height(H):
    h = int(H * 0.42); return h - h % 2


def _clean_text(w, L):
    t = re.sub(r'[,;:]+$', '', w)
    return t.upper() if L['upper'] else t


def accent_index(words):
    """The one gold word of the clean style: a number if there is one, else the longest strong word (the last of
    equals)."""
    ns = [norm(w) for w in words]
    for k in range(len(words) - 1, -1, -1):
        if re.search(r'\d', words[k]): return k
    best, bl = None, -1
    for k, n in enumerate(ns):
        if n in WEAK: continue
        if len(n) >= bl: best, bl = k, len(n)
    return best if best is not None else len(words) - 1


def layout(plan, W, H, font_path, area=None):
    """Where each word goes: [(text, x, y, colour)], the font, its size. Lines are split where the title fits
    biggest (fewer lines when it is close), then centred in the safe box around 20% of the frame height."""
    from PIL import Image, ImageDraw
    L = LOOK[plan['style']]
    texts = [_clean_text(w['w'], L) for w in plan['words']]
    left, top, right, bottom = safe_box(W, H)
    if area: top, bottom = area
    aw, ah = right - left, bottom - top
    up = captions.upright(W, H)
    base = int(min(W, H) * L['size'] * (1.0 if up else 0.95))
    d = ImageDraw.Draw(Image.new('L', (8, 8)))
    cjk = captions.has_cjk(texts)
    f0 = captions._font(font_path, base, L['weight'])
    tr0 = 0 if cjk else L['track'] * base
    space0 = d.textlength(' ', font=f0) + tr0
    wid0 = [captions._width(d, t, f0, tr0) for t in texts]
    n = len(texts); best = None
    for mask in range(1 << max(0, n - 1)):          # every way to break the words into lines (7 words: 64 ways)
        lines, cur = [], [0]
        for k in range(1, n):
            if mask >> (k - 1) & 1: lines.append(cur); cur = [k]
            else: cur.append(k)
        lines.append(cur)
        if len(lines) > 4: continue
        widths = [sum(wid0[k] for k in l) + space0 * (len(l) - 1) for l in lines]
        height = base * L['lh'] * len(lines)
        scale = min(1.0, aw * 0.98 / max(widths), ah / height)
        balance = min(widths) / max(widths)
        score = scale - 0.04 * (len(lines) - 1) + 0.03 * balance
        if best is None or score > best[0]: best = (score, scale, lines)
    _, scale, lines = best
    size = max(10, int(base * scale))
    for _ in range(6):   # fit the letters' real ink (caps can reach past the line height) inside the safe box
        font = captions._font(font_path, size, L['weight'])
        tr = 0 if cjk else L['track'] * size
        space = d.textlength(' ', font=font) + tr
        lh = size * L['lh']
        line_txt = [' '.join(texts[k] for k in l) for l in lines]
        ink_top = min(font.getbbox(t)[1] for t in line_txt[:1])
        ink_bot = lh * (len(lines) - 1) + max(font.getbbox(t)[3] for t in line_txt[-1:])
        widest = max(sum(captions._width(d, texts[k], font, tr) for k in l) + space * (len(l) - 1) for l in lines)
        fit = min(ah / max(1, ink_bot - ink_top), aw * 0.98 / max(1, widest))
        if fit >= 1 or size <= 10: break
        size = max(10, int(size * fit * 0.99))
    acc = accent_index(texts) if L['accent'] and not cjk else None
    cy = (top + bottom) / 2 if area else H * (0.195 if up else 0.20)
    y = cy - (ink_top + ink_bot) / 2
    y = max(top - ink_top, min(bottom - ink_bot, y))
    out = []
    for l in lines:
        ws_ = [captions._width(d, texts[k], font, tr) for k in l]
        x = (left + right) / 2 - (sum(ws_) + space * (len(l) - 1)) / 2
        for k, w in zip(l, ws_):
            out.append((texts[k], x, y, L['accent'] if k == acc else L['color']))
            x += w + space
        y += lh
    return out, font, size, tr


def word_tiles(plan, W, H, font_path, area=None):
    """Each word drawn once with its soft shadow: [(RGBA tile, x, y)] in frame pixels, plus the bottom of the text."""
    from PIL import Image, ImageDraw, ImageFilter
    L = LOOK[plan['style']]
    placed, font, size, tr = layout(plan, W, H, font_path, area)
    pad = int(size * 0.8)
    tiles, low = [], 0
    for text, x, y, col in placed:
        w = int(captions._width(ImageDraw.Draw(Image.new('L', (8, 8))), text, font, tr) + 2 * pad + size * 0.2)
        h = int(size * 1.6 + 2 * pad)
        m = Image.new('L', (w, h), 0)
        captions._put(ImageDraw.Draw(m), (pad, pad), text, font, 255, tr)
        tile = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        for alpha, blur, drop in L['shadow']:
            sm = m.filter(ImageFilter.GaussianBlur(max(1, blur * size))).point(lambda v, a=alpha: int(v * a))
            lay = Image.new('RGBA', (w, h), (0, 0, 0, 0)); lay.putalpha(sm)
            sh = Image.new('RGBA', (w, h), (0, 0, 0, 0)); sh.paste(lay, (0, int(round(drop * size)))); tile = Image.alpha_composite(tile, sh)
        txt = Image.new('RGBA', (w, h), captions._hex(col, '#ffffff')[:3] + (0,)); txt.putalpha(m)
        tile = Image.alpha_composite(tile, txt)
        tiles.append((tile, int(round(x - pad)), int(round(y - pad))))
        box = m.getbbox()
        if box: low = max(low, y - pad + box[3])
    return tiles, low, size


def shade(W, BH, low, H):
    """The soft top shade: darkest at the top, gone a little under the title. A smooth curve, no edge."""
    from PIL import Image
    reach = min(BH, int(low + H * 0.07))
    col = Image.new('L', (1, BH), 0)
    px = col.load()
    for y in range(reach):
        v = 1 - y / max(1, reach)
        px[0, y] = int(255 * v * v * (3 - 2 * v))   # smoothstep down to 0
    return col.resize((W, BH))


def _ease_out(u): u = min(1.0, max(0.0, u)); return 1 - (1 - u) ** 3


def _ease_in(u): u = min(1.0, max(0.0, u)); return u * u


def state_at(plan, t, n_words):
    """(shade alpha, [(alpha, rise in font sizes) per word]) at time t inside the title's window."""
    s, e = plan['s'], plan['e']
    out_u = _ease_in((t - (e - OUT)) / OUT) if t > e - OUT else 0.0
    fade_out, lift = 1 - out_u, -0.08 * out_u
    if LOOK[plan['style']]['motion'] == 'words':
        sh = _ease_out((t - s) / 0.25) * fade_out
        last_in = e - OUT - WORD_IN - 0.15
        per = []
        for k, w in enumerate(plan['words']):
            t0 = s if k == 0 else min(max(s, w['s'] - 0.04), last_in)
            u = _ease_out((t - t0) / WORD_IN)
            per.append((u * fade_out, (1 - u) * RISE * 0.7 + lift))
        return sh, per
    u = _ease_out((t - s) / IN)
    return u * fade_out, [(u * fade_out, (1 - u) * RISE + lift)] * n_words


def frame(plan, tiles, shade_mask, W, BH, size, state):
    from PIL import Image
    sh_a, per = state
    img = Image.new('RGBA', (W, BH), (0, 0, 0, 0))
    if sh_a > 0.003:
        m = shade_mask.point(lambda v: int(v * LOOK[plan['style']]['shade'] * sh_a))
        img.putalpha(m)
    for (tile, x, y), (a, rise) in zip(tiles, per):
        if a <= 0.003: continue
        t = tile if a >= 0.997 else tile.copy()
        if a < 0.997: t.putalpha(tile.getchannel('A').point(lambda v: int(v * a)))
        lay = Image.new('RGBA', (W, BH), (0, 0, 0, 0)); lay.paste(t, (x, y + int(round(rise * size))))
        img = Image.alpha_composite(img, lay)
    return img


def rows(plan, fps):
    """[(state key, seconds)] covering the window frame by frame; a run of identical frames is one row."""
    n = len(plan['words'])
    frames = max(1, int(round((plan['e'] - plan['s']) * fps)))
    out = []
    for f in range(frames):
        st = state_at(plan, plan['s'] + (f + 0.5) / fps, n)
        key = (round(st[0], 3), tuple((round(a, 3), round(r, 3)) for a, r in st[1]))
        if out and out[-1][0] == key: out[-1][1] += 1
        else: out.append([key, 1])
    # the last row takes up whatever rounding left, so the window ends exactly at plan["e"]
    secs = [c / fps for _, c in out]
    secs[-1] += (plan['e'] - plan['s']) - sum(secs)
    return [(k, d) for (k, _), d in zip(out, secs)]


def band_area(W, H, band, reserve=0):
    """(top, bottom) pixels for the title in the empty band above a black / image fit picture: from the safe top
    to a little above the picture's top edge, less reserve pixels kept for top captions just above the picture
    (captions.top_reserve; dropped when the band can't hold both). None when there is no band or it is too thin."""
    if not band: return None
    top = safe_box(W, H)[1]
    if reserve and not captions.title_room(W, H, band, reserve): reserve = 0
    bottom = band[0] - H * 0.02 - reserve
    return (top, bottom) if bottom - top >= H * 0.06 else None


def write_track(plan, W, H, font_path, folder, total, fps=30, band=None, reserve=0):
    """PNG pictures of the title band (the top of the frame) + an ffmpeg concat list covering 0..total on the 1 ms
    clock. Returns (list path, y of the band: always 0). band: shape.bands, the title goes in the one above."""
    from PIL import Image
    os.makedirs(folder, exist_ok=True)
    BH = band_height(H)
    tiles, low, size = word_tiles(plan, W, H, font_path, band_area(W, H, band, reserve))
    mask = shade(W, BH, low, H)
    blank = os.path.join(folder, 'blank.png'); Image.new('RGBA', (W, BH), (0, 0, 0, 0)).save(blank)
    files, written_rows = {}, []
    if plan['s'] > 0.001: written_rows.append((blank, plan['s']))
    for key, dur in rows(plan, fps):
        if key not in files:
            p = os.path.join(folder, f't{len(files):04d}.png')
            frame(plan, tiles, mask, W, BH, size, (key[0], list(key[1]))).save(p, compress_level=1)
            files[key] = p
        written_rows.append((files[key], dur))
    if total > plan['e']: written_rows.append((blank, total - plan['e']))
    lst = os.path.join(folder, 'title.txt')
    with open(lst, 'w') as f:
        f.write('ffconcat version 1.0\n')
        clock = written = 0.0
        for p, d in written_rows:
            clock += d
            dd = round(clock - written, 3)
            if dd < 0.001: continue
            written += dd
            f.write(f"file '{os.path.basename(p)}'\n{captions.TB}duration {dd:.3f}\n")
        f.write(f"file '{os.path.basename(blank)}'\n{captions.TB}")
    return lst, 0
