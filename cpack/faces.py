"""Face-following crop for "Zoom in to fill the screen" (CT-127). A wide take cut to an upright video used to keep
the middle, so a speaker sitting left of centre lost half his face.

Faces come from the Mac's own Vision framework through a 20-line Swift helper, compiled once with the Command Line
Tools that Homebrew already needs (no download, no Python package). Per clip: 2 frames a second, the biggest face's
centre, smoothed (median, then a moving average), a still crop when the face hardly moves, a slow pan otherwise.
No helper, or no face found: the centre, as before.

  track(src, ss, dur, turn) -> [(t, cx, cy)] in 0..1 of the (turned) picture, or None
  crop(sw, sh, W, H, samples) -> filter text that scales to cover W x H and crops around the face
"""
import json, os, subprocess, tempfile
from . import media, shape
from .platform import get as platform

P = platform()
SWIFT = r'''
import Foundation
import Vision
import ImageIO
for path in CommandLine.arguments.dropFirst() {
    var boxes: [[Double]] = []
    if let src = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil),
       let img = CGImageSourceCreateImageAtIndex(src, 0, nil) {
        let req = VNDetectFaceRectanglesRequest()
        try? VNImageRequestHandler(cgImage: img, options: [:]).perform([req])
        for f in req.results ?? [] {
            let b = f.boundingBox
            boxes.append([b.minX, 1 - b.maxY, b.width, b.height, Double(f.confidence)])
        }
    }
    print(String(data: try! JSONSerialization.data(withJSONObject: boxes), encoding: .utf8)!)
}
'''
RATE = 2.0        # frames looked at per second
STILL = 0.06      # face moving less than this share of the picture: hold the crop still


def helper():
    """Path to the compiled face finder, building it on first use; None when it can't be built (not a Mac)."""
    if P.NAME != 'mac': return None
    d = os.path.join(P.data_home(), 'bin'); exe = os.path.join(d, 'faces')
    if os.access(exe, os.X_OK): return exe
    swiftc = P.tool('swiftc') or ('/usr/bin/swiftc' if os.path.exists('/usr/bin/swiftc') else None)
    if not swiftc: return None
    os.makedirs(d, exist_ok=True)
    src = os.path.join(d, 'faces.swift')
    with open(src, 'w') as f: f.write(SWIFT)
    r = subprocess.run([swiftc, '-O', src, '-o', exe + '.part'], capture_output=True)
    if r.returncode != 0: return None
    os.replace(exe + '.part', exe)
    return exe


def _median(xs, k=5):
    h = k // 2
    return [sorted(xs[max(0, i - h):i + h + 1])[len(xs[max(0, i - h):i + h + 1]) // 2] for i in range(len(xs))]


def _mean(xs, k=5):
    h = k // 2
    return [sum(xs[max(0, i - h):i + h + 1]) / len(xs[max(0, i - h):i + h + 1]) for i in range(len(xs))]


def smooth(raw):
    """raw: [(t, cx|None, cy|None)] -> smoothed [(t, cx, cy)], gaps filled from neighbours; None if no face."""
    have = [(t, x, y) for t, x, y in raw if x is not None]
    if not have: return None
    xs, ys = [], []
    for t, x, y in raw:
        if x is None: _, x, y = min(have, key=lambda h: abs(h[0] - t))
        xs.append(x); ys.append(y)
    xs, ys = _mean(_median(xs)), _mean(_median(ys))
    if max(xs) - min(xs) < STILL and max(ys) - min(ys) < STILL:
        mx, my = sorted(xs)[len(xs) // 2], sorted(ys)[len(ys) // 2]
        return [(raw[0][0], mx, my)]
    return [(t, x, y) for (t, _, _), x, y in zip(raw, xs, ys)]


def track(src, ss, dur, turn=0):
    exe = helper()
    if not exe: return None
    vf = ','.join(x for x in [shape.turn_filter(turn), f'fps={RATE}', 'scale=320:-2'] if x)
    with tempfile.TemporaryDirectory() as d:
        r = subprocess.run([media.ff('ffmpeg'), '-v', 'error'] + P.HWACCEL + ['-ss', f'{ss:.3f}', '-t', f'{max(0.5, dur):.3f}', '-i', src,
                            '-vf', vf, '-q:v', '5', os.path.join(d, 'f%04d.jpg')], capture_output=True)
        files = sorted(f for f in os.listdir(d) if f.endswith('.jpg'))
        if r.returncode != 0 or not files: return None
        out = subprocess.run([exe] + [os.path.join(d, f) for f in files], capture_output=True, text=True)
        if out.returncode != 0: return None
        raw = []
        for k, line in enumerate(out.stdout.splitlines()):
            boxes = [b for b in json.loads(line or '[]') if b[4] >= 0.5]
            if boxes:
                x, y, w, h, _ = max(boxes, key=lambda b: b[2] * b[3])
                raw.append((k / RATE, x + w / 2, y + h / 2))
            else: raw.append((k / RATE, None, None))
    return smooth(raw)


def _lerp_expr(pts):
    """ffmpeg expression in t for a piecewise-linear path through pts [(t, v)]."""
    if len(pts) == 1: return f'{pts[0][1]:.1f}'
    expr = f'{pts[-1][1]:.1f}'
    for (t0, v0), (t1, v1) in reversed(list(zip(pts, pts[1:]))):
        expr = f'if(lt(t,{t1:.2f}),{v0:.1f}+({v1 - v0:.1f})*(t-{t0:.2f})/{max(0.01, t1 - t0):.2f},{expr})'
    return expr


def crop(sw, sh, W, H, samples):
    """Scale a sw x sh picture to cover W x H, then crop W x H around the face path (or the centre)."""
    k = max(W / sw, H / sh)
    Sw, Sh = max(W, shape.even(sw * k + 1)), max(H, shape.even(sh * k + 1))
    if not samples:
        return f'scale={Sw}:{Sh}:flags=lanczos,crop={W}:{H},setsar=1'
    keys = samples[::2] if len(samples) > 2 else samples   # one point a second
    if samples[-1] is not keys[-1]: keys = keys + [samples[-1]]
    xs = [(t, min(max(cx * Sw - W / 2, 0), Sw - W)) for t, cx, _ in keys]
    ys = [(t, min(max(cy * Sh - 0.4 * H, 0), Sh - H)) for t, _, cy in keys]
    return f"scale={Sw}:{Sh}:flags=lanczos,crop={W}:{H}:x='{_lerp_expr(xs)}':y='{_lerp_expr(ys)}',setsar=1"
