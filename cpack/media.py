"""ffmpeg / ffprobe calls: probe a take, grab a frame, decode its sound once for the edge maths, make a small
preview copy for playing beats in the browser."""
import json, os, subprocess
import numpy as np
from . import shape, edges, hdr
from .platform import get as platform

P = platform()
SYNC = 'aresample=async=1:first_pts=0'   # iPhone sound starts 17-31 ms after the picture; pad so sample 0 = picture time 0


def ff(name): return P.tool(name) or name


def probe(path):
    r = subprocess.run([ff('ffprobe'), '-v', 'error', '-show_entries',
                        'stream=index,codec_type,codec_name,width,height,r_frame_rate,channels,pix_fmt,color_range,color_transfer,'
                        'color_primaries,color_space:stream_tags:stream_side_data=rotation:format=duration:format_tags',
                        '-of', 'json', path], capture_output=True, text=True)
    if r.returncode != 0: raise ValueError(f'not a video ffmpeg can read: {os.path.basename(path)}')
    d = json.loads(r.stdout or '{}')
    v = next((s for s in d.get('streams', []) if s.get('codec_type') == 'video'), None)
    a = next((s for s in d.get('streams', []) if s.get('codec_type') == 'audio' and s.get('codec_name')), None)
    if not v: raise ValueError(f'no picture in {os.path.basename(path)}')
    rot = next((int(x.get('rotation', 0)) for x in v.get('side_data_list', []) if 'rotation' in x), 0)
    num, den = (v.get('r_frame_rate') or '30/1').split('/')
    fps = float(num) / float(den or 1) if float(den or 1) else 30.0
    sw, sh = shape.shown_wh(v['width'], v['height'], rot)
    return {'duration': round(float(d.get('format', {}).get('duration', 0)), 3), 'width': v['width'], 'height': v['height'],
            'rotation': rot, 'shown_w': sw, 'shown_h': sh, 'fps': round(fps, 3), 'fps_rational': v.get('r_frame_rate', '30/1'),
            'codec': v.get('codec_name'), 'has_audio': bool(a), 'channels': (a or {}).get('channels', 0),
            'shape': 'vertical' if sh > sw else 'horizontal' if sw > sh else 'square',
            'color_transfer': v.get('color_transfer'), 'color_primaries': v.get('color_primaries'),
            'color_range': v.get('color_range'), 'pix_fmt': v.get('pix_fmt'),
            'tags': {k: str(x)[:80] for k, x in list((v.get('tags') or {}).items()) + list((d.get('format', {}).get('tags') or {}).items())
                     if 'color' in k.lower() or 'log' in str(x).lower() or 'profile' in k.lower()}}


def sdr(probe):
    """HDR / log to normal video (D34), '' for normal video."""
    return hdr.vf(probe, P.data_home()) if probe else ''


def frame(path, t, out, turn=0, width=640, probe=None):
    vf = ','.join(x for x in [shape.turn_filter(turn), f'scale={width}:-2', sdr(probe)] if x)
    subprocess.run([ff('ffmpeg'), '-v', 'error', '-y', '-ss', f'{max(0, t):.2f}', '-i', path, '-frames:v', '1', '-vf', vf,
                    '-q:v', '4', out], capture_output=True)
    return os.path.exists(out)


def energy(path, cache):
    """10 ms frames in dB for the whole take, cached next to the project."""
    if os.path.exists(cache): return np.load(cache)
    b = subprocess.run([ff('ffmpeg'), '-v', 'error', '-i', path, '-map', '0:a:0', '-ac', '2', '-ar', '16000', '-af', SYNC,
                        '-f', 'f32le', '-'], capture_output=True).stdout
    x = np.frombuffer(b, np.float32)
    e = edges.frames_db(x[:len(x) // 2 * 2].reshape(-1, 2))
    np.save(cache, e)
    return e


def pcm16k(path, cache):
    """The take's sound as 16 kHz mono int16 samples (same clock as energy()), cached for the self-check."""
    if os.path.exists(cache): return np.load(cache, mmap_mode='r')
    b = subprocess.run([ff('ffmpeg'), '-v', 'error', '-i', path, '-map', '0:a:0', '-ac', '1', '-ar', '16000', '-af', SYNC,
                        '-f', 's16le', '-'], capture_output=True).stdout
    x = np.frombuffer(b, np.int16)
    np.save(cache, x)
    return x


def wav16k(path, out):
    subprocess.run([ff('ffmpeg'), '-v', 'error', '-y', '-i', path, '-map', '0:a:0', '-ac', '1', '-ar', '16000', '-af', SYNC,
                    '-c:a', 'pcm_s16le', out], check=True, capture_output=True)
    return out


def proxy(path, out, turn=0, probe=None):
    """540 px preview copy, so the story map can play any beat in the browser (4K HEVC won't)."""
    vf = ','.join(x for x in [shape.turn_filter(turn), "scale='if(gt(iw,ih),960,-2)':'if(gt(iw,ih),-2,960)'", sdr(probe)] if x)
    tmp = out + '.part.mp4'
    r = subprocess.run([ff('ffmpeg'), '-v', 'error', '-y'] + P.HWACCEL + ['-i', path, '-map', '0:v:0', '-map', '0:a:0?', '-vf', vf,
                       '-c:v', P.VIDEO_ENCODER, '-b:v', '1500k', '-c:a', 'aac', '-b:a', '96k', '-movflags', '+faststart', tmp],
                       capture_output=True)
    if r.returncode == 0: os.replace(tmp, out)
    return r.returncode == 0
