"""Punch-in zooms on talking-head cuts (the first effect). a tester, 22 Nov: "where are the motion graphics and effects".

The framing alternates at every join between the normal shot and a punch-in centred on the face (about 115 %), so a
jump cut reads as a change of shot instead of a skip, the way YouTube and Reels editors hide them. Optional: a slow
push-in (100 to 106 %) across the hook part, then the alternation carries on.

Sharp, always: the zoom is done in the one scale from the source picture (never a second scale of an already
scaled frame), and the punch is only as big as the source has pixels for. A 4K upright take into 1080 x 1920 has 2x
to spare, so it gets the full 115 %. A 1080-wide take has none: it gets 112 % (the floor below which the change
of shot stops reading), a 12 % upscale, and the clip is marked `upscaled`.

The face stays in frame and out of the captions: the punched window is centred on the face (half across, 40 % down,
like the face-following crop) and clamped inside the picture, so the face can only move towards the middle, never
below where the normal shot has it when that is low in the frame.

  mode(settings)                    'off' | 'punch' | 'push'
  plan(clips, mode, headroom)       [(z_start, z_end)] per clip, 1.0 = the normal shot
  headroom(sw, sh, W, H)            source pixels per output pixel at 100 %
  fit_filter(sw, sh, W, H, samples, z0, z1, dur)  scale + crop filter text
"""
from . import shape

MODES = ('off', 'punch', 'push')
PUNCH = 1.15        # the punch-in when the source has the pixels for it
FLOOR = 1.12        # never less: under this the change of shot stops hiding the jump
PUSH = 1.06         # the slow push across the hook part ends here
FACE_X, FACE_Y = 0.5, 0.4   # where the punch puts the face (share of the output), as far as the picture allows


def mode(settings):
    m = ((settings or {}).get('captions') or {}).get('zoom', 'punch')
    return m if m in MODES else 'punch'


def headroom(sw, sh, W, H):
    """How many source pixels there are per output pixel when the picture just covers W x H (2.0 for a 4K upright
    take into 1080 x 1920, 1.0 for a 1080 take, under 1 when a wide take is cropped to upright)."""
    return 1.0 / max(W / sw, H / sh)


def punch(room):
    """The punch-in for a source with `room` (see headroom): PUNCH when it is there, never under FLOOR."""
    return round(max(FLOOR, min(PUNCH, room)), 3)


def fills(sw, sh, W, H, fit):
    """Zoom only where the picture fills the frame (same shape, or cropped to fill): a padded picture with a
    blurred background is left as it is."""
    return fit == 'crop' or abs(sw / sh - W / H) < 0.01


def plan(clips, how, room=None):
    """(z_start, z_end) for each clip. room: headroom per clip (list) or one number for all; None = 2.0.
    'punch': normal, punch, normal, ... switching at each join. 'push': the clips of the first beat (the hook)
    push in 1.00 -> PUSH over their joined length, then the alternation starts again on the normal shot."""
    n = len(clips)
    if how not in ('punch', 'push') or not n: return [(1.0, 1.0)] * n
    rooms = room if isinstance(room, (list, tuple)) else [2.0 if room is None else room] * n
    out, start = [], 0
    if how == 'push':
        beat = clips[0].get('beat')
        while start < n and beat is not None and clips[start].get('beat') == beat: start += 1
        start = start or 1
        total = sum(c['dur'] for c in clips[:start]) or 1.0
        T = 0.0
        for c in clips[:start]:
            a, b = T / total, (T + c['dur']) / total
            out.append((round(1 + (PUSH - 1) * a, 4), round(1 + (PUSH - 1) * b, 4))); T += c['dur']
    for k in range(start, n):
        z = punch(rooms[k]) if (k - start) % 2 == 1 else 1.0
        out.append((z, z))
    return out


def window(cx, cy, Sw, Sh, W, H):
    """Top-left of the W x H window in an Sw x Sh picture that puts the face (cx, cy in 0..1) at FACE_X, FACE_Y,
    clamped inside the picture."""
    x = min(max(cx * Sw - FACE_X * W, 0), Sw - W)
    y = min(max(cy * Sh - FACE_Y * H, 0), Sh - H)
    return x, y


def size(sw, sh, W, H, z):
    """The picture scaled once from the source to cover W x H at zoom z (even, never smaller than W x H)."""
    k = max(W / sw, H / sh) * z
    return max(W, shape.even(sw * k + 1)), max(H, shape.even(sh * k + 1))


def _lerp(pts):
    if len(pts) == 1: return f'{pts[0][1]:.1f}'
    expr = f'{pts[-1][1]:.1f}'
    for (t0, v0), (t1, v1) in reversed(list(zip(pts, pts[1:]))):
        expr = f'if(lt(t,{t1:.2f}),{v0:.1f}+({v1 - v0:.1f})*(t-{t0:.2f})/{max(0.01, t1 - t0):.2f},{expr})'
    return expr


def fit_filter(sw, sh, W, H, samples, z0, z1=None, dur=1.0):
    """Scale a sw x sh picture once to cover W x H at zoom z0 (or growing z0 -> z1 over dur seconds) and crop W x H
    around the face path samples [(t, cx, cy)] (None: the centre)."""
    z1 = z0 if z1 is None else z1
    pts = samples or [(0.0, 0.5, 0.5)]
    if abs(z1 - z0) < 1e-4:
        Sw, Sh = size(sw, sh, W, H, z0)
        keys = pts[::2] if len(pts) > 2 else pts   # one point a second, as the face crop
        if pts[-1] is not keys[-1]: keys = keys + [pts[-1]]
        xs = [(t, window(cx, cy, Sw, Sh, W, H)[0]) for t, cx, cy in keys]
        ys = [(t, window(cx, cy, Sw, Sh, W, H)[1]) for t, cx, cy in keys]
        return f"scale={Sw}:{Sh}:flags=lanczos,crop={W}:{H}:x='{_lerp(xs)}':y='{_lerp(ys)}',setsar=1"
    # the push: the size grows frame by frame (one scale from the source, so still sharp); the face is held at its
    # median spot so the window only grows, never wanders
    cx = sorted(p[1] for p in pts)[len(pts) // 2]; cy = sorted(p[2] for p in pts)[len(pts) // 2]
    k = max(W / sw, H / sh)
    zt = f'({z0:.4f}+{z1 - z0:.4f}*min(t/{max(dur, 0.01):.3f},1))'
    w = f"max({W},2*trunc({sw * k:.2f}*{zt}/2+0.5))"; h = f"max({H},2*trunc({sh * k:.2f}*{zt}/2+0.5))"
    x = f"min(max({cx:.4f}*in_w-{FACE_X * W:.1f},0),in_w-{W})"; y = f"min(max({cy:.4f}*in_h-{FACE_Y * H:.1f},0),in_h-{H})"
    return f"scale=w='{w}':h='{h}':eval=frame:flags=lanczos,crop={W}:{H}:x='{x}':y='{y}',setsar=1"
