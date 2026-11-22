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


# How a picture of another shape goes into the frame:
#   crop   fill the frame, trim the sides (follows the face)
#   pad    the whole picture over a soft blur of itself
#   black  the whole picture, centred, on black (a tester, 22 Nov: "I don't like the blur, it's better to have black").
#          The default for new projects.
#   image  the NatGeo look: the whole picture in a thin white keyline over a still frame of the video, scaled to
#          fill, darkened and vignetted. No blur.
FITS = ('crop', 'pad', 'black', 'image')
SHOWS_ALL = ('pad', 'black', 'image')   # the whole picture is shown, the frame has empty space around it
IMAGE_INSET = 0.92   # image: the picture is this share of the frame's width (or height), so the backdrop frames it
KEYLINE = 2          # image: the white line round the picture, pixels (style references R4: 1 to 2 px)


def picture_box(sw, sh, W, H, fit):
    """(x, y, w, h) of the picture in the W x H frame for black and image (even numbers), or None when the picture
    fills the frame (same shape, crop) or for pad (its blur fills the frame, so there is no empty band)."""
    if fit not in ('black', 'image') or abs(sw / sh - W / H) < 0.01: return None
    k = min(W / sw, H / sh) * (IMAGE_INSET if fit == 'image' else 1.0)
    w, h = min(W, even(sw * k)), min(H, even(sh * k))
    return (W - w) // 2 // 2 * 2, (H - h) // 2 // 2 * 2, w, h


def fit_filter(sw, sh, W, H, fit='crop'):
    """Filter chain that puts a sw x sh picture into W x H. crop = fill and trim the centre; pad = whole picture
    over a blurred, filled copy of itself; black = whole picture centred on black. image needs the backdrop as a
    second input: render.segment_cmd builds it (image_filter)."""
    if abs(sw / sh - W / H) < 0.01:
        return f'scale={W}:{H}:flags=lanczos,setsar=1'
    if fit == 'crop':
        return f'scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},setsar=1'
    if fit in ('black', 'image'):   # image without its backdrop (render.segment_cmd adds it): black
        x, y, w, h = picture_box(sw, sh, W, H, 'black')
        return f'format=yuv420p,scale={w}:{h}:flags=lanczos,setsar=1,pad={W}:{H}:{x}:{y}:black'
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


def image_filter(sw, sh, W, H, fg_tail=''):
    """image fit, as filter_complex parts: (picture chain, overlay text). The picture is scaled into its box and gets
    the white keyline on its edge; fg_tail runs on it before the keyline (colour, frame rate). The backdrop ([bg],
    already W x H) is laid under it."""
    x, y, w, h = picture_box(sw, sh, W, H, 'image')
    fg = (f"format=yuv420p,scale={w}:{h}:flags=lanczos,setsar=1{',' + fg_tail if fg_tail else ''},"
          f"drawbox=x=0:y=0:w=iw:h=ih:color=white@0.92:t={KEYLINE}")
    return fg, f'overlay={x}:{y}:shortest=1'


def bands(boxes, W, H):
    """The empty bands above and below the picture(s): (top band bottom, bottom band top) in pixels, the tightest
    over every box given (clips of other shapes in one video), or None when no clip leaves a band."""
    boxes = [b for b in boxes if b and b[3] < H - 1]
    if not boxes: return None
    return min(b[1] for b in boxes), max(b[1] + b[3] for b in boxes)
