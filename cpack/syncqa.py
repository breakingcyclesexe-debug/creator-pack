"""Lip sync measured on the FINISHED file, at the middle of every clip (CT-133).

For each clip: take its middle frame and the second of sound around its middle from the clip file (segments/),
then find both in the final video near where that clip should sit:
  picture  the final frame that looks most like the clip's middle frame (small grey thumbnails, caption band left out)
  sound    the lag where the clip's sound lines up best with the final sound (cross-correlation, 16 kHz)
sound minus picture = how far the voice is from the lips there. Above LIMIT_MS anywhere = the cut fails.

The final sound is decoded from the start in one go, sample after sample, the way a player plays it: a player does
not honour gaps in the sound's timestamps, it just plays the samples. a tester's v1 (22 Nov) had 33 ms gaps at 12 joins:
read by timestamp it looked in sync, played it ran up to 0.45 s ahead of his lips.
"""
import json, subprocess
import numpy as np
from . import media

LIMIT_MS = 40
SR = 16000
TW = 96             # thumbnail width
SEARCH = 0.6        # seconds either side of where the clip should be
HALF = 0.5          # seconds of sound either side of the middle
RUN = 7             # frames either side of the middle in the picture match
CLEAR = 1.08        # best picture match must beat every other offset (beyond +-1 frame) by 8 %


def _frames(path, t0, dur, tw=TW):
    """Grey thumbnails and their times (as stored in the file) for path between t0 and t0+dur."""
    p = media.probe(path)
    th = int(round(p['shown_h'] * tw / p['shown_w'] / 2) * 2)
    r = subprocess.run([media.ff('ffmpeg'), '-v', 'info', '-hide_banner', '-ss', f'{max(0, t0):.3f}', '-t', f'{dur:.3f}', '-i', path,
                        '-copyts', '-map', '0:v:0', '-vf', f'scale={tw}:{th},format=gray,showinfo', '-fps_mode', 'passthrough',
                        '-f', 'rawvideo', '-'], capture_output=True)
    n = tw * th
    x = np.frombuffer(r.stdout, np.uint8)
    imgs = x[:len(x) // n * n].reshape(-1, th, tw).astype(np.float32)
    ts = [float(l.split('pts_time:')[1].split()[0]) for l in r.stderr.decode('utf-8', 'replace').splitlines() if 'pts_time:' in l]
    k = min(len(ts), len(imgs))
    return imgs[:k], np.array(ts[:k]), th


def played(path):
    """The whole sound track as a player plays it: every sample in order from the track's start, no gaps."""
    r = subprocess.run([media.ff('ffmpeg'), '-v', 'error', '-i', path, '-map', '0:a:0', '-af', 'asetpts=N/SR/TB',
                        '-ac', '1', '-ar', str(SR), '-f', 'f32le', '-'], capture_output=True)
    return np.frombuffer(r.stdout, np.float32)


def _cut(x, t0, dur):
    a = max(0, int(round(t0 * SR))); return x[a:a + int(round(dur * SR))]


def starts(path):
    r = subprocess.run([media.ff('ffprobe'), '-v', 'error', '-show_entries', 'stream=codec_type,start_time', '-of', 'json', path],
                       capture_output=True, text=True)
    return {s['codec_type']: float(s.get('start_time') or 0) for s in json.loads(r.stdout or '{}').get('streams', [])}


def lag(ref, big):
    """Seconds into big where ref fits best (normalised cross-correlation via FFT) and how well (0..1)."""
    ref = ref - ref.mean(); n = len(ref)
    if n < 100 or len(big) < n: return None, 0.0
    m = 1 << int(np.ceil(np.log2(len(big) + n)))
    c = np.fft.irfft(np.fft.rfft(big, m) * np.conj(np.fft.rfft(ref, m)), m)[:len(big) - n + 1]
    b = big.astype(np.float64)
    cs = np.concatenate([[0], np.cumsum(b ** 2)]); cm = np.concatenate([[0], np.cumsum(b)])
    energy = (cs[n:] - cs[:-n]) - (cm[n:] - cm[:-n]) ** 2 / n
    score = c / np.sqrt(np.maximum(energy, 1e-12) * float((ref ** 2).sum()) + 1e-12)
    i = int(np.argmax(score))
    return i / SR, float(score[i])


def measure(video, seg_paths, durs, band=None):
    """video: the final file; seg_paths: clip files in order; durs: each clip's length in the final timeline.
    band: (y0, y1) caption rows in the final picture, left out of the picture match.
    Returns [{"clip", "at", "picture_ms", "sound_ms", "sync_ms", "match"}]: offsets are final minus expected."""
    out, T = [], 0.0
    vp = media.probe(video)
    fa = played(video); a_start = starts(video).get('audio', 0.0)
    for n, (seg, d) in enumerate(zip(seg_paths, durs)):
        st = starts(seg); mid = d / 2
        row = {'clip': n, 'at': round(T + mid, 2)}
        sf, sts, _ = _frames(seg, 0, d + 0.2)
        if len(sf):
            k = int(np.argmin(np.abs(sts - (st.get('video', 0) + mid))))
            # a run of frames around the middle, not one frame: a talking head barely moves from frame to frame, so
            # one frame matches its neighbours almost as well (measured: false 100-330 ms readings). When the run
            # is still not clearly better than its neighbours, widen it (1 s, then the whole clip).
            for run in (RUN, 15, len(sf)):
                k0, k1 = max(0, k - run), min(len(sf), k + run + 1)
                ref, ref_t = sf[k0:k1], sts[k0] - min(st.values())      # where the run's first frame should show
                ff, fts, th = _frames(video, T + ref_t - SEARCH, 2 * SEARCH + (k1 - k0) / 20)
                if len(ff) < len(ref): break
                keep = np.ones(ff.shape[1], bool)
                if band:
                    y0, y1 = int(band[0] * th / vp['shown_h']), int(np.ceil(band[1] * th / vp['shown_h']))
                    keep[max(0, y0 - 1):y1 + 1] = False
                    if keep.sum() < th * 0.3: keep[:] = True
                L = len(ref)
                err = np.array([np.abs(ff[j:j + L][:, keep, :] - ref[:, keep, :]).mean() for j in range(len(ff) - L + 1)])
                j = int(np.argmin(err))
                rest = np.concatenate([err[:max(0, j - 1)], err[j + 2:]])
                clear = float(rest.min() / max(err[j], 1e-6)) if len(rest) else 9.0
                row['picture_ms'] = round((fts[j] - (T + ref_t)) * 1000); row['picture_clear'] = round(clear, 2)
                if clear >= CLEAR: break
        a0 = max(0, mid - HALF); al = min(2 * HALF, d - a0)
        ref_a = _cut(played(seg), a0 - (st.get('audio', 0) - min(st.values())), al)
        lead = min(SEARCH, T + a0)
        big = _cut(fa, T + a0 - lead - a_start, al + lead + SEARCH)
        at, score = lag(ref_a, big)
        if at is not None:
            row['sound_ms'] = round((at - lead) * 1000); row['match'] = round(score, 2)
        if 'picture_ms' in row and 'sound_ms' in row:
            row['sync_ms'] = row['sound_ms'] - row['picture_ms']
        out.append(row)
        T += d
    return out


def verdict(rows, limit=LIMIT_MS):
    """Worst clip and whether every clip is inside the limit. Clips whose sound matched poorly (under 0.5:
    near-silence lines up anywhere) are not counted."""
    good = [r for r in rows if 'sync_ms' in r and r.get('match', 0) >= 0.5]
    worst = max(good, key=lambda r: abs(r['sync_ms']), default=None)
    return {'worst_ms': worst and worst['sync_ms'], 'worst_clip': worst and worst['clip'], 'measured': len(good),
            'clips': len(rows), 'limit_ms': limit, 'ok': bool(good) and all(abs(r['sync_ms']) <= limit for r in good)}
