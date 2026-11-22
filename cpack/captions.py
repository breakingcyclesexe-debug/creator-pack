"""Burned captions without Remotion or libass: each caption is drawn by Pillow into a transparent strip, and
ffmpeg's concat demuxer plays the strips as one overlay stream (render.py).

Styles: "word" (one word at a time), "three" (up to 3 words), "lines" (up to 3 lines). The word being said is
drawn in the pop colour. Captions only ever show words that are in the cut (the kept words, as heard).

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
            ev.append({'s': round(s, 3), 'e': round(max(e, s + 0.06), 3),
                       'lines': [[_clean(x['w']) for x in l] for l in ls], 'hi': flat[k]})
    for a, b in zip(ev, ev[1:]):  # never overlap
        if a['e'] > b['s']: a['e'] = b['s']
    return [x for x in ev if x['e'] - x['s'] > 0.02]


def _hex(c, default):
    c = (c or default).lstrip('#')
    try: return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)) + (255,)
    except ValueError: return _hex(default, '#ffffff')


def _font(font_path, size):
    """font_path: a file, or (file, face number) for a collection such as PingFang.ttc (the Traditional face)."""
    from PIL import ImageFont
    if not font_path: return ImageFont.load_default(size)
    if isinstance(font_path, (tuple, list)): return ImageFont.truetype(font_path[0], size, index=int(font_path[1]))
    return ImageFont.truetype(font_path, size)


def draw(ev, W, H, cfg, font_path):
    """One caption strip (W x H, transparent) for an event."""
    from PIL import Image, ImageDraw
    style = cfg.get('style', 'three')
    size = int(W * (LINES_SIZE if style == 'lines' else SIZES).get(cfg.get('size', 'm'), 0.064))
    font = _font(font_path, size)
    col, pop = _hex(cfg.get('color'), '#ffffff'), _hex(cfg.get('pop'), '#e8a13d')
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    stroke = max(2, size // 12)
    lines = ev['lines'] if style != 'word' else [[ev['lines'][0][ev['hi'][1]]]]
    hi = ev['hi'] if style != 'word' else (0, 0)
    space = d.textlength(' ', font=font)
    lh = int(size * 1.18)
    y = (H - lh * len(lines)) // 2
    for li, l in enumerate(lines):
        txt = [t.upper() if cfg.get('upper', True) else t for t in l]
        # Chinese is written without spaces between words
        gap = [0 if (wi + 1 < len(txt) and CJK.search(t[-1:]) and CJK.search(txt[wi + 1][:1])) else 1 for wi, t in enumerate(txt)]
        widths = [d.textlength(t, font=font) for t in txt]
        total = sum(widths) + space * sum(gap[:-1])
        scale = min(1.0, (W * 0.88) / total) if total else 1.0
        f2 = font if scale >= 1 else (_font(font_path, int(size * scale)) if font_path else font)
        sp = space if scale >= 1 else d.textlength(' ', font=f2)
        if scale < 1: widths = [d.textlength(t, font=f2) for t in txt]; total = sum(widths) + sp * sum(gap[:-1])
        x = (W - total) / 2
        for wi, t in enumerate(txt):
            fill = pop if (li, wi) == tuple(hi) and cfg.get('pop_on', True) else col
            d.text((x, y), t, font=f2, fill=fill, stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
            x += widths[wi] + sp * gap[wi]
        y += lh
    return img


def strip_height(W, cfg):
    style = cfg.get('style', 'three')
    size = W * (LINES_SIZE if style == 'lines' else SIZES).get(cfg.get('size', 'm'), 0.064)
    return int(size * 1.18 * (3 if style == 'lines' else 1) + size)


def write_track(evs, W, H, cfg, font_path, folder, total):
    """PNG strips + an ffmpeg concat list covering 0..total. Returns (list path, strip height, y offset)."""
    from PIL import Image
    os.makedirs(folder, exist_ok=True)
    sh = strip_height(W, cfg); sh += sh % 2
    y = int(H * POS.get(cfg.get('position', 'bottom'), 0.74) - sh / 2)
    y = max(0, min(H - sh, y))
    blank = os.path.join(folder, 'blank.png'); Image.new('RGBA', (W, sh), (0, 0, 0, 0)).save(blank)
    rows, t, cache = [], 0.0, {}
    for n, ev in enumerate(evs):
        if ev['s'] > t + 0.001: rows.append((blank, ev['s'] - t))
        key = (tuple(map(tuple, ev['lines'])), tuple(ev['hi']))
        if key not in cache:
            p = os.path.join(folder, f'c{len(cache):05d}.png'); draw(ev, W, sh, cfg, font_path).save(p, compress_level=1); cache[key] = p
        rows.append((cache[key], ev['e'] - ev['s'])); t = ev['e']
    if total > t: rows.append((blank, total - t))
    lst = os.path.join(folder, 'captions.txt')
    with open(lst, 'w') as f:
        f.write('ffconcat version 1.0\n')
        for p, d in rows: f.write(f"file '{os.path.basename(p)}'\nduration {max(d, 0.001):.3f}\n")
        f.write(f"file '{os.path.basename(rows[-1][0] if rows else blank)}'\n")
    return lst, sh, y
