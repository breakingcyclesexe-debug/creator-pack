"""Picture shape maths (no ffmpeg calls here, so it is testable).

iPhones store a sideways take as 3840x2160 plus a rotation flag, and sometimes tag it wrong. So: the shape is
always worked out "as shown" (flag applied), the buyer sees a frame and can turn it, and the output size is never
forced: one side is fixed and the other follows the picture, rounded to an even number."""

FORMATS = {'9:16': (1080, 1920), '16:9': (1920, 1080), '4:5': (1080, 1350), '1:1': (1080, 1080)}


def shown_wh(w, h, rotation=0):
    return (h, w) if abs(int(rotation or 0)) % 180 == 90 else (w, h)


def turned_wh(w, h, extra):
    return (h, w) if int(extra or 0) % 180 == 90 else (w, h)


def even(x): return int(round(x / 2.0)) * 2


def target(sw, sh, fmt='source', long_side=1920):
    """Output (W, H). fmt 'source' keeps the picture's own shape, long side at most long_side."""
    if fmt in FORMATS: return FORMATS[fmt]
    k = min(1.0, long_side / max(sw, sh))
    return even(sw * k), even(sh * k)


def turn_filter(extra):
    return {90: 'transpose=1', 180: 'hflip,vflip', 270: 'transpose=2'}.get(int(extra or 0) % 360, '')


def fit_filter(sw, sh, W, H, fit='crop'):
    """Filter chain that puts a sw x sh picture into W x H. crop = fill and trim the centre; pad = whole picture
    over a blurred, filled copy of itself."""
    if abs(sw / sh - W / H) < 0.01:
        return f'scale={W}:{H}:flags=lanczos,setsar=1'
    if fit == 'crop':
        return f'scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},setsar=1'
    # format first: the Mac's hardware decoder hands over nv12 frames, and the background's crop / blur on those came
    # out green on one side (seen on an upright clip into a wide video, 22 Nov)
    return (f'format=yuv420p,split=2[bg][fg];[bg]scale={W // 4}:{H // 4}:force_original_aspect_ratio=increase,crop={W // 4}:{H // 4},'
            f'boxblur=10:2,scale={W}:{H},setsar=1[bgb];[fg]scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos,'
            f'setsar=1[fgs];[bgb][fgs]overlay=(W-w)/2:(H-h)/2')


def matches(ow, oh, W, H, tol=0.02):
    return abs(ow / oh - W / H) / (W / H) <= tol


def mismatch(sw, sh, fmt):
    """D35: 'sideways' (a wide clip into an upright / tall / square video), 'upright' (an upright clip into a wide
    video), or None when the clip already fits (or the video keeps each clip's shape)."""
    if fmt not in FORMATS: return None
    W, H = FORMATS[fmt]
    if sw > sh and W <= H: return 'sideways'
    if sh > sw and W > H: return 'upright'
    return None
