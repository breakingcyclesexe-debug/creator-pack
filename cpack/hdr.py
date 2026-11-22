"""HDR and log footage to normal video, silently (D34: no footage-type choice in the page).

iPhone HDR video is HLG (BT.2020), some cameras give PQ, iPhone 15 Pro and up can film Apple Log. Played as if it
were normal video it looks grey and washed out, so every such clip is turned into normal Rec.709 video before any
look or caption. Normal iPhone video (Rec.709) is never touched.

This Mac's ffmpeg has `tonemap`, but `tonemap` needs linear light in and out, and the filters that get there
(zscale, libplacebo) are not in Homebrew's ffmpeg. So the whole conversion is one 3D LUT made here once, applied with
`lut3d` (which every ffmpeg has): signal -> scene light (HLG / PQ / Apple Log curve) -> display light with 260 nits as
normal white (HLG mid-tones kept) -> BT.2020 to BT.709 colours -> a soft roll-off of highlights above 50% linear (max of R, G, B, so
colours keep their hue) -> the BT.1886 2.4 display curve.

  kind(probe)        'hlg' | 'pq' | 'log' | None
  vf(probe, home)    filter chain (yuv in, yuv420p Rec.709 out) or '' for normal video
"""
import math, os
import numpy as np

SIZE = 33
WHITE = 260.0     # nits shown as normal white: keeps HLG's mid-tones where an SDR screen shows them (HLG 50% stays 50%)
KNEE = 0.5        # light above this rolls off softly (sky, sun on the road) instead of clipping to white
M2020_709 = np.array([[1.6605, -0.5876, -0.0728], [-0.1246, 1.1329, -0.0083], [-0.0182, -0.1006, 1.1187]])
LOG_TRC = {'log', 'log100', 'log316', 'log_sqrt'}


def kind(probe):
    if not probe: return None
    trc = (probe.get('color_transfer') or '').lower()
    prim = (probe.get('color_primaries') or '').lower()
    tags = ' '.join(str(v) for v in (probe.get('tags') or {}).values()).lower()
    if trc == 'arib-std-b67': return 'hlg'
    if trc == 'smpte2084': return 'pq'
    if trc in LOG_TRC or 'apple log' in tags or 'applelog' in tags: return 'log'
    if prim == 'bt2020' and trc in ('', 'unknown', 'unspecified', 'reserved'): return 'log'   # Apple Log is tagged like this
    return None


def hlg_to_nits(e):
    a, b, c = 0.17883277, 0.28466892, 0.55991073
    e = np.clip(e, 0, 1)
    lin = np.where(e <= 0.5, e * e / 3.0, (np.exp((e - c) / a) + b) / 12.0)
    return lin   # scene light 0..1; the OOTF is applied per pixel below


def pq_to_nits(e):
    m1, m2, c1, c2, c3 = 2610 / 16384, 2523 / 4096 * 128, 3424 / 4096, 2413 / 4096 * 32, 2392 / 4096 * 32
    p = np.power(np.clip(e, 0, 1), 1 / m2)
    return 10000 * np.power(np.maximum(p - c1, 0) / (c2 - c3 * p), 1 / m1)


def applelog_to_linear(p):
    R0, Rt, c, b, g, be = -0.05641088, 0.01, 47.28711236, 0.00964052, 0.08550479, 0.69336945
    Pt = c * (Rt - R0) ** 2
    return np.where(p < Pt, np.sqrt(np.maximum(p, 0) / c) + R0, np.power(2.0, (p - g) / be) - b)


def rolloff(m):
    """1:1 up to KNEE, then x / (1 + x): a 1000 nit highlight lands near 93%, detail kept, never a hard clip."""
    k = KNEE; x = np.maximum(m - k, 0) / (1 - k)
    return np.where(m <= k, m, k + (1 - k) * x / (1 + x))


def to_display(rgb, which):
    """rgb: (..., 3) signal values 0..1 in BT.2020 -> BT.709 display signal 0..1."""
    if which == 'hlg':
        sc = hlg_to_nits(rgb)
        ys = sc @ np.array([0.2627, 0.6780, 0.0593])
        lin = 1000.0 * np.power(np.maximum(ys, 1e-6), 0.2)[..., None] * sc / WHITE   # HLG OOTF, 1000 nit system gamma 1.2
    elif which == 'pq':
        lin = pq_to_nits(rgb) / WHITE
    else:   # Apple Log: scene light with 18% grey at 0.18; shown like the camera's own normal video
        lin = np.maximum(applelog_to_linear(rgb), 0) * 1.0
    lin = np.maximum(lin @ M2020_709.T, 0)
    m = lin.max(-1, keepdims=True)
    lin = np.where(m > 1e-6, lin * rolloff(m) / np.maximum(m, 1e-6), lin)
    return np.clip(lin, 0, 1) ** (1 / 2.4)


def cube(which, home):
    """The LUT file for one kind, written once under <data home>/luts."""
    d = os.path.join(home, 'luts'); os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f'{which}-to-709-v2.cube')
    if os.path.exists(path): return path
    g = np.linspace(0, 1, SIZE)
    b, gg, r = np.meshgrid(g, g, g, indexing='ij')          # .cube order: red changes fastest
    out = to_display(np.stack([r, gg, b], -1).reshape(-1, 3), which)
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        f.write(f'TITLE "Creator Pack {which} to Rec.709"\nLUT_3D_SIZE {SIZE}\n')
        f.write('\n'.join(f'{x:.6f} {y:.6f} {z:.6f}' for x, y, z in out) + '\n')
    os.replace(tmp, path)
    return path


def vf(probe, home):
    which = kind(probe)
    if not which: return ''
    path = cube(which, home).replace('\\', '/').replace(':', '\\:').replace("'", "\\'")
    rng = 'pc' if (probe.get('color_range') or 'tv') == 'pc' else 'tv'
    return (f"scale=in_color_matrix=bt2020:in_range={rng}:out_range=pc,format=gbrp16le,"
            f"lut3d=file='{path}':interp=tetrahedral,"
            f"scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,"
            f"setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv")
