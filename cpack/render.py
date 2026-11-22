"""From an approved storyboard to a finished mp4.

1. plan():  kept beats in story order -> cut rules -> re-timed from a short hearing -> edges by sound
            (selfcheck.place) -> the self-listen check and its repairs (selfcheck.run) -> whole output frames.
2. segments(): each clip encoded on its own (fast seek, turn, fit or face-following crop, the punch-in zoom
            that alternates at joins (zoom.py), one frame rate, 10 ms sound fades on room tone), in parallel.
3. final(): clips joined, captions laid over, loudness to -14 LUFS, one encode at the size asked for.
"""
import math, os, subprocess, time
from concurrent.futures import ThreadPoolExecutor
from . import cutrules, edges, media, shape, captions, retime, selfcheck, faces, zoom, titles
from .platform import get as platform

P = platform()
FADE = 0.01   # cuts sit on room tone now, so the fade only has to stop a click


def beats_in_order(sb):
    out = []
    for b in sb['beats']:
        if not b.get('keep', True): continue
        use = b
        if b.get('use_alt') is not None and 0 <= int(b['use_alt']) < len(b.get('alts', [])): use = b['alts'][int(b['use_alt'])]
        out.append({'id': b['id'], 'take': use['take'], 'start': use['start'], 'end': use['end']})
    return out


STANDARD = [(23.976, '24000/1001'), (24, '24/1'), (25, '25/1'), (29.97, '30000/1001'), (30, '30/1'),
            (50, '50/1'), (59.94, '60000/1001'), (60, '60/1')]


def output_rate(pj, clips):
    """One frame rate for the whole video (CT-132): the rate of the take most of the cut comes from, snapped to
    a standard rate (iPhone takes are variable; 30 and 29.97 takes in one cut used to drift)."""
    probes = {t['name']: t['probe'] for t in pj['takes']}
    weight = {}
    for c in clips: weight[c['take']] = weight.get(c['take'], 0) + (c['eout']['t'] - c['ein']['t'])
    take = max(weight, key=weight.get) if weight else pj['takes'][0]['name']
    fps = probes[take].get('fps') or 30
    if fps > 61: fps = 60
    return min(STANDARD, key=lambda s: abs(s[0] - fps))


def plan(pj, sb, transcript, energy_of, hear_span=None, hear_clips=None):
    """energy_of(take) -> dB frames; hear_span(take, a, b) -> words heard in that stretch (re-times each clip from
    a fresh, short hearing); hear_clips([(take, a, b)]) -> words heard in each finished clip (the self-check).
    Returns {"clips", "log", "retakes", "kept_repeats", "edges", "retimed", "selfcheck", "fps", "fps_rational"}."""
    st = pj['settings']['cut']
    takes = {k: cutrules.prepare(v['words']) for k, v in transcript.items()}
    res = cutrules.cut_beats(beats_in_order(sb), takes, st)
    moved = []
    pre, post = cutrules.ROOM[cutrules._settings(st)['breath']]
    if hear_span:
        def one(c):
            try: return retime.retime(c, hear_span(c['take'], c['in'] - retime.WINDOW, c['out'] + retime.WINDOW), pre, post)
            except Exception: return None
        with ThreadPoolExecutor(2) as ex: found = list(ex.map(one, res['clips']))
        for n, (c, r) in enumerate(zip(res['clips'], found)):
            if not r: continue
            a, b, shift = r
            e = energy_of(c['take']); fl = edges.noise_floor(e)
            if not edges.speech_at(e, fl, c['words'][0]['s'] + shift):
                continue   # a short hearing put the first word on silence (often the window's start): keep the old times
            if abs(shift) > 0.05: moved.append({'clip': n, 'shift': shift})
            c['words'] = [dict(w, s=w['s'] + shift, e=w['e'] + shift) for w in c['words']]
            c.update({'ws': c['words'][0]['s'], 'we': c['words'][-1]['e'],
                      'fl': min(c['fl'] + shift, c['words'][0]['s'] - 0.05), 'ce': max(c['ce'] + shift, c['words'][-1]['e'] + 0.05)})
    clips = selfcheck.place(res['clips'], energy_of, pre, post)
    fps, fps_r = output_rate(pj, clips)
    items, fixes = selfcheck.run(clips, energy_of, hear_clips, fps, pre, post)
    bad = [i for i in items if i['kind'] == 'voice']
    res.update(clips=clips, edges={'checked': 2 * len(clips), 'clipped': bad}, retimed=moved, fps=fps, fps_rational=fps_r,
               selfcheck={'items': items, 'repairs': fixes, 'heard': hear_clips is not None})
    return res


def caption_words(clips):
    out, T = [], 0.0
    for c in clips:
        for w in c['words']:
            if w['e'] <= c['ss'] + 0.02 or w['s'] >= c['ss'] + c['dur'] - 0.02: continue   # dropped by a repair
            s = T + max(0.0, w['s'] - c['ss']); e = T + min(c['dur'], w['e'] - c['ss'])
            out.append({'w': w['w'], 's': round(s, 3), 'e': round(max(e, s + 0.05), 3), 'n': w['n']})
        T += c['dur']
    return out, T


def shown_words(words, fixes=None, script=None):
    """The caption words as they are drawn: Chinese in the wanted characters, then the buyer's corrections."""
    return captions.fix(captions.to_script(words, script, P.han), fixes)


def caption_font(words, script=None, look='soft'):
    """Chinese: the Mac's PingFang (Traditional or Simplified), any look. Otherwise the look's own font: DM Sans
    (in the pack) for soft and glow, Avenir Next Heavy (on every Mac) for clean."""
    if captions.has_cjk(words): return P.font_cjk(script or 'trad') or P.font()
    if look == 'clean':
        heavy = getattr(P, 'font_heavy', lambda: None)()
        if heavy: return heavy
    return captions.DM_SANS if os.path.exists(captions.DM_SANS) else P.font()


def words_from_transcript(rep, transcript):
    """Caption words for a cut made before they were kept in cut.json: each clip's words found again in the
    take's transcript (by text, near the clip's time) and put on the clip's clock."""
    from difflib import SequenceMatcher
    out, T = [], 0.0
    for c in rep.get('clips', []):
        W = (transcript.get(c['take']) or {}).get('words', [])
        want = [n for n in c.get('words', []) if n]
        cand = [w for w in W if cutrules.norm(w['w']) and c['ss'] - 2.0 <= (w['s'] + w['e']) / 2 <= c['ss'] + c['dur'] + 2.0]
        got = []
        for a, b, size in SequenceMatcher(None, want, [cutrules.norm(w['w']) for w in cand], autojunk=False).get_matching_blocks():
            got += cand[b:b + size]
        if got:
            shift = (c.get('ws') or got[0]['s']) - got[0]['s']
            if abs(shift) > 1.5: shift = 0.0
            for w in got:
                s0, e0 = w['s'] + shift, w['e'] + shift
                if e0 <= c['ss'] + 0.02 or s0 >= c['ss'] + c['dur'] - 0.02: continue
                s = T + max(0.0, s0 - c['ss']); e = T + min(c['dur'], e0 - c['ss'])
                out.append({'w': w['w'], 's': round(s, 3), 'e': round(max(e, s + 0.05), 3), 'n': cutrules.norm(w['w'])})
        T += c['dur']
    return out


def recaption(rep, folder, words, fixes=None, script=None):
    """New captions on a finished cut, nothing else touched (a corrected caption word: a tester, 22 Nov). The clips
    are already on the Mac (folder/segments), so this is one join and encode: seconds, free, no Claude.
    Returns the number of caption events."""
    seg = os.path.join(folder, 'segments', 'segments.txt')
    if not os.path.exists(seg): raise RuntimeError('This version is too old to change its captions. Make a new version first.')
    cap = (rep.get('settings') or {}).get('captions') or {}
    W, H, total = rep['width'], rep['height'], rep['duration']
    fps_r = min(STANDARD, key=lambda x: abs(x[0] - (rep.get('fps') or 30)))[1]
    show = shown_words(words, fixes, script)
    show, ttl = titles.prepare(rep.get('settings'), show)
    evs = captions.events(show, cap.get('style', 'three'), int(cap.get('per_line', 4)))
    band = rep.get('bands')
    cap_list, cap_y = None, 0
    if evs:
        d = os.path.join(folder, 'captions.new')
        if os.path.isdir(d):
            import shutil; shutil.rmtree(d)
        cap_list, _, cap_y = captions.write_track(evs, W, H, cap, caption_font(show, script, captions.look_of(cap)), d, total,
                                                  fps=rep.get('fps') or 30, band=band, title_end=(ttl or {}).get('e', 0.0))
    title = ttl and titles.write_track(ttl, W, H, titles.font_for(ttl['style'], ttl['words'], script), os.path.join(folder, 'title'), total,
                                       rep.get('fps') or 30, band=band,
                                       reserve=captions.top_reserve(evs, W, H, cap, band))
    final(seg, cap_list, cap_y, W, H, fps_r, total, 0, os.path.join(folder, 'video.mp4'), kb=rep.get('kbps'), title=title)
    if evs:
        import shutil
        old = os.path.join(folder, 'captions')
        shutil.rmtree(old, ignore_errors=True); os.replace(os.path.join(folder, 'captions.new'), old)
    return len(evs)


def rate(fps_r):
    num, den = (str(fps_r).split('/') + ['1'])[:2]
    return int(num), int(den or 1)


def samples(frames, fps_r, sr=48000):
    """Sound samples that last exactly `frames` frames: picture and sound of a clip share one clock."""
    num, den = rate(fps_r)
    return int(round(frames * den * sr / num))


def segment_cmd(src, c, probe, turn, W, H, fit, out, fps_r, focus=None, zm=(1.0, 1.0), backdrop=None):
    """One clip: exactly c['frames'] frames at the output rate, the first one at time 0, and exactly that long of
    sound, so every join is frame-exact and picture and sound never drift apart (CT-132, CT-133).
    The fps filter starts at 0: after a seek into a variable-rate iPhone take the first frame can sit 20-30 ms in,
    and without start_time=0 the clip's picture began one frame late (start_time 0.033) while its sound began at 0.
    The frame count is cut in the filter, not with -frames:v: ffmpeg 8 closes the whole file when the picture
    reaches -frames:v, which cut the padded sound short (7 of a tester's 23 clips were 5-30 ms short of their picture).
    backdrop: the image fit's background (the buyer's picture or a still, W x H, make_backdrop), a second input laid under the picture. Both
    are put on the same frame clock before they meet, so the overlay is frame for frame and the timing is unchanged."""
    sw, sh = shape.turned_wh(probe['shown_w'], probe['shown_h'], turn)
    pre = (shape.turn_filter(turn) + ',') if shape.turn_filter(turn) else ''
    if zm and (abs(zm[0] - 1) > 1e-4 or abs(zm[1] - 1) > 1e-4):   # a punch-in or the hook's push (zoom.py)
        fitf = zoom.fit_filter(sw, sh, W, H, focus, zm[0], zm[1], c['dur'])
    else:
        fitf = faces.crop(sw, sh, W, H, focus) if (fit == 'crop' and abs(sw / sh - W / H) >= 0.01) else shape.fit_filter(sw, sh, W, H, fit)
    num, den = rate(fps_r)
    conv = media.sdr(probe)   # HDR / log to normal video first, so any look and the captions sit on normal colours (D34)
    clock = f"fps=fps={fps_r}:start_time=0,trim=end_frame={c['frames']},setpts=N*{den}/{num}/TB"
    image = fit == 'image' and backdrop and shape.picture_box(sw, sh, W, H, 'image') and not (zm and (abs(zm[0] - 1) > 1e-4 or abs(zm[1] - 1) > 1e-4))
    if image:
        fg, lay = shape.image_filter(sw, sh, W, H, f"{conv + ',' if conv else ''}{clock}")
        vf = (f"[0:v]{pre}{fg}[fg];[1:v]format=yuv420p,{clock}[bg];[bg][fg]{lay},format=yuv420p[v]")
    else:
        if fit == 'image': fitf = shape.fit_filter(sw, sh, W, H, 'black')   # no backdrop made: black, never a broken clip
        vf = f"[0:v]{pre}{fitf},{conv + ',' if conv else ''}{clock},format=yuv420p[v]"
    d, a = c['dur'], min(c.get('aud') or c['dur'], c['dur'])
    ns = samples(c['frames'], fps_r)
    af = (f"[0:a:0]{media.SYNC},atrim=0:{a:.5f},afade=t=in:st=0:d={FADE},afade=t=out:st={max(0, a - FADE):.4f}:d={FADE},"
          f"aformat=sample_rates=48000:channel_layouts=stereo,apad=whole_len={ns},atrim=end_sample={ns},asetpts=N/SR/TB[a]")
    bg = ['-loop', '1', '-framerate', str(fps_r), '-t', f'{d + 0.5:.4f}', '-i', backdrop] if image else []
    return [media.ff('ffmpeg'), '-v', 'error', '-y'] + P.HWACCEL + ['-ss', f"{c['ss']:.4f}", '-t', f'{d + 0.5:.4f}', '-i', src] + bg + [
            '-filter_complex', vf + ';' + af, '-map', '[v]', '-map', '[a]',
            '-c:v', P.VIDEO_ENCODER, '-b:v', '16M', '-c:a', 'pcm_s16le', out]


def segment_ok(path, frames, fps_r):
    """The clip file really is `frames` frames from time 0 and exactly as long in sound. Returns a problem or None."""
    import json
    r = subprocess.run([media.ff('ffprobe'), '-v', 'error', '-count_packets', '-show_entries',
                        'stream=codec_type,start_time,nb_read_packets,duration_ts,sample_rate', '-of', 'json', path],
                       capture_output=True, text=True)
    st = {x['codec_type']: x for x in json.loads(r.stdout or '{}').get('streams', [])}
    v, a = st.get('video', {}), st.get('audio', {})
    if int(v.get('nb_read_packets', -1)) != frames: return f"{v.get('nb_read_packets')} frames, wanted {frames}"
    if abs(float(v.get('start_time') or 0)) > 0.001 or abs(float(a.get('start_time') or 0)) > 0.001:
        return f"picture starts at {v.get('start_time')} s, sound at {a.get('start_time')} s"
    if a and int(a.get('duration_ts') or 0) != samples(frames, fps_r, int(a.get('sample_rate') or 48000)):
        return f"{a.get('duration_ts')} sound samples, wanted {samples(frames, fps_r)}"
    return None


DARKEN, VIGNETTE = 0.55, 0.45   # image fit backdrop: 45% darker, corners a further 45% down


def backdrop_spot(pj, clips):
    """(take, time) of the image fit's still: the buyer's pick (settings.backdrop) if it names a take, else the
    middle of the first clip."""
    b = pj['settings'].get('backdrop') or {}
    names = {t['name'] for t in pj['takes']}
    if b.get('take') in names and float(b.get('t', -1)) >= 0: return b['take'], float(b['t'])
    c = clips[0]
    return c['take'], c['ss'] + c['dur'] / 2


def make_backdrop(pj, clips, W, H, folder):
    """The image fit's backdrop: the buyer's own picture (settings.backdrop.image, kept in the project's backdrop/
    folder) if there is one, else one still from the video. Scaled to fill W x H, darkened, soft vignette. No blur.
    Returns its path, or None when neither can be read (the clips then go on black)."""
    from PIL import Image, ImageOps
    from . import project as prj
    own = prj.backdrop_image(pj)
    im = None
    if own:
        try:
            with Image.open(own) as f: im = ImageOps.exif_transpose(f).convert('RGB')   # a phone photo stands the way it was taken
        except Exception: im = None
    if im is None:
        take, t = backdrop_spot(pj, clips)
        tk = next(x for x in pj['takes'] if x['name'] == take)
        raw = os.path.join(folder, 'backdrop-frame.png')
        vf = ','.join(x for x in [shape.turn_filter(int(tk.get('turn', 0)) % 360), media.sdr(tk.get('probe'))] if x)
        subprocess.run([media.ff('ffmpeg'), '-v', 'error', '-y', '-ss', f'{max(0.0, t):.3f}', '-i', tk['path'], '-frames:v', '1']
                       + (['-vf', vf] if vf else []) + [raw], capture_output=True)
        if not os.path.exists(raw): return None
        im = Image.open(raw).convert('RGB')
    out = os.path.join(folder, 'backdrop.png')
    grade_backdrop(im, W, H).save(out)
    return out


def grade_backdrop(im, W, H):
    """Scale to fill W x H (centre crop), DARKEN, then the vignette: the same look for a still and a picture."""
    from PIL import Image, ImageChops
    k = max(W / im.width, H / im.height)
    im = im.resize((max(W, round(im.width * k)), max(H, round(im.height * k))), Image.LANCZOS)
    x, y = (im.width - W) // 2, (im.height - H) // 2
    im = im.crop((x, y, x + W, y + H))
    im = Image.eval(im, lambda v: int(v * DARKEN))
    # vignette: full at the middle, falling smoothly to (1 - VIGNETTE) at the corners
    small = Image.new('L', (64, 64))
    px = small.load()
    for j in range(64):
        for i in range(64):
            r = min(1.0, (((i + 0.5) / 32 - 1) ** 2 + ((j + 0.5) / 32 - 1) ** 2) ** 0.5 / 2 ** 0.5)
            px[i, j] = int(255 * (1 - VIGNETTE * r * r))
    mask = small.resize((W, H), Image.BICUBIC)
    return ImageChops.multiply(im, Image.merge('RGB', [mask] * 3))


def picture_boxes(pj, clips, W, H):
    """Each clip's picture box in the frame (shape.picture_box), None where the picture fills it."""
    probes = {t['name']: t['probe'] for t in pj['takes']}
    turns = {t['name']: int(t.get('turn', 0)) % 360 for t in pj['takes']}
    fit = pj['settings'].get('fit', 'pad')
    return [shape.picture_box(*shape.turned_wh(probes[c['take']]['shown_w'], probes[c['take']]['shown_h'], turns.get(c['take'], 0)), W, H, fit)
            for c in clips]


def zoom_plan(pj, clips, W, H):
    """(z_start, z_end) per clip from the project's zoom setting; 1.0 where the picture doesn't fill the frame."""
    probes = {t['name']: t['probe'] for t in pj['takes']}
    turns = {t['name']: int(t.get('turn', 0)) % 360 for t in pj['takes']}
    fit = pj['settings'].get('fit', 'pad')
    sizes = [shape.turned_wh(probes[c['take']]['shown_w'], probes[c['take']]['shown_h'], turns.get(c['take'], 0)) for c in clips]
    zs = zoom.plan(clips, zoom.mode(pj['settings']), [zoom.headroom(sw, sh, W, H) for sw, sh in sizes])
    return [z if zoom.fills(sw, sh, W, H, fit) else (1.0, 1.0) for z, (sw, sh) in zip(zs, sizes)]


def segments(pj, clips, W, H, folder, progress=None, workers=3, fps_r='30/1'):
    os.makedirs(folder, exist_ok=True)
    probes = {t['name']: t['probe'] for t in pj['takes']}; paths = {t['name']: t['path'] for t in pj['takes']}
    turns = {t['name']: int(t.get('turn', 0)) % 360 for t in pj['takes']}   # each clip's own turn (CT-133)
    fit = pj['settings'].get('fit', 'pad')
    zooms = zoom_plan(pj, clips, W, H)
    bd = make_backdrop(pj, clips, W, H, folder) if fit == 'image' and any(picture_boxes(pj, clips, W, H)) else None
    outs = [os.path.join(folder, f'seg{n:04d}.mov') for n in range(len(clips))]
    done = [0]

    def one(n):
        c, pr = clips[n], probes[clips[n]['take']]
        turn = turns.get(c['take'], 0)
        sw, sh = shape.turned_wh(pr['shown_w'], pr['shown_h'], turn)
        focus, zm = None, zooms[n]
        zoomed = abs(zm[0] - 1) > 1e-4 or abs(zm[1] - 1) > 1e-4
        if zoomed: c['zoom'] = [zm[0], zm[1]] + (['upscaled'] if max(zm) > zoom.headroom(sw, sh, W, H) + 1e-6 else [])
        if (fit == 'crop' and abs(sw / sh - W / H) >= 0.01) or zoomed:
            try: focus = faces.track(paths[c['take']], c['ss'], c['dur'], turn)
            except Exception: focus = None
            c['focus'] = focus and [[round(t, 2), round(x, 3), round(y, 3)] for t, x, y in focus]
        r = subprocess.run(segment_cmd(paths[c['take']], c, pr, turn, W, H, fit, outs[n], fps_r, focus, zm, **({'backdrop': bd} if bd else {})),
                           capture_output=True, text=True)
        if r.returncode != 0: raise RuntimeError(f'clip {n}: {r.stderr[-400:]}')
        bad = segment_ok(outs[n], c['frames'], fps_r)
        if bad: raise RuntimeError(f'clip {n} came out wrong ({bad}): picture and sound would drift')
        done[0] += 1
        if progress: progress(done[0], len(clips))
    with ThreadPoolExecutor(workers) as ex: list(ex.map(one, range(len(clips))))
    lst = os.path.join(folder, 'segments.txt')
    with open(lst, 'w') as f:
        f.write('ffconcat version 1.0\n')
        for o in outs: f.write(f"file '{os.path.basename(o)}'\n")
    return lst


DEFAULT_MB = 55   # a 2-3 minute reel lands around 40-60 MB: Instagram re-encodes anyway, and big files upload slowly


def bitrate(total, max_mb, W, H):
    """Video kbit/s. Default: what fits DEFAULT_MB, between 2.3 and 6 Mbps (8 for wide). max_mb (the small file):
    what fits that many MB (1 MB = 1,000,000 bytes, as the Mac shows it), sound and 7% overhead counted."""
    top = 8000 if W > H else 6000
    budget = lambda mb: mb * 8000 * 0.93 / max(total, 1) - 128
    if not max_mb: return int(max(2300, min(top, budget(DEFAULT_MB))))
    return int(max(300, min(top, budget(max_mb))))


def final(seg_list, cap_list, cap_y, W, H, fps, total, max_mb, out, kb=None, title=None):
    # One clock for the whole video (CT-133): frame n of the joined clips shows at n / fps and sample k plays at
    # k / 48000, counted, never read from the joined files' timestamps. The concat reader offsets each next clip by
    # the clip file's container length: 12 of a tester's 23 clips had their picture start one frame in, so each pushed the
    # picture 33 ms later, while the sound got a 33 ms gap there that players skip. By the end of his v1 his voice
    # ran 0.49 s ahead of his lips (results: _tests/2026-11-22-sync).
    num, den = rate(fps)
    cmd = [media.ff('ffmpeg'), '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', seg_list]
    clock = f'setpts=N*{den}/{num}/TB'
    if cap_list:
        cmd += ['-f', 'concat', '-safe', '0', '-i', cap_list]
        fc = f'[0:v]{clock}[m];[1:v]format=rgba[c];[m][c]overlay=0:{cap_y}:eof_action=pass:format=auto,format=yuv420p[v];'
    else:
        fc = f'[0:v]{clock},format=yuv420p[v];'
    if title:   # the hook title (titles.py): (concat list, y), laid over the captions
        cmd += ['-f', 'concat', '-safe', '0', '-i', title[0]]
        fc = fc[:-4] + f'[u];[{2 if cap_list else 1}:v]format=rgba[t];[u][t]overlay=0:{title[1]}:eof_action=pass:format=auto,format=yuv420p[v];'
    fc += '[0:a]asetpts=N/SR/TB,loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000,asetpts=N/SR/TB[a]'
    kb = kb or bitrate(total, max_mb, W, H)
    tmp = out + '.part.mp4'
    cmd += ['-filter_complex', fc, '-map', '[v]', '-map', '[a]', '-r', str(fps), '-fps_mode', 'cfr', '-c:v', P.VIDEO_ENCODER, '-b:v', f'{kb}k',
            '-maxrate', f'{int(kb * 1.3)}k', '-bufsize', f'{kb * 2}k', '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart',
            '-t', f'{total:.3f}', tmp]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0: raise RuntimeError(f'final render: {r.stderr[-600:]}')
    os.replace(tmp, out)
    return kb


def run(pj, sb, transcript, energy_of, folder, progress=lambda *a: None, hear_span=None, hear_clips=None):
    """The whole cut into folder/video.mp4. Returns a report with timings per step."""
    T = {}; t = time.time()
    progress('plan', 0, 'Lining up your story, hearing each clip again')
    p = plan(pj, sb, transcript, energy_of, hear_span, hear_clips); T['plan'] = round(time.time() - t, 1)
    if not p['clips']: raise RuntimeError('Nothing left to cut: every beat is dropped')
    first = next(x['probe'] for x in pj['takes'] if x['name'] == p['clips'][0]['take'])
    sw, sh = shape.turned_wh(first['shown_w'], first['shown_h'], next(int(x.get('turn', 0)) for x in pj['takes'] if x['name'] == p['clips'][0]['take']))
    W, H = shape.target(sw, sh, pj['settings'].get('format', 'source'))
    band = shape.bands(picture_boxes(pj, p['clips'], W, H), W, H)   # black / image: the empty space for the words
    t = time.time()
    lst = segments(pj, p['clips'], W, H, os.path.join(folder, 'segments'),
                   lambda d, n: progress('segments', d / n, f'Cutting clip {d} of {n}'), fps_r=p['fps_rational'])
    T['segments'] = round(time.time() - t, 1)
    t = time.time(); progress('captions', 0, 'Drawing captions')
    words, total = caption_words(p['clips'])
    cap = pj['settings']['captions']
    fixes, script = pj.get('caption_fixes') or {}, pj.get('caption_script')
    show = shown_words(words, fixes, script)
    show, ttl = titles.prepare(pj['settings'], show)
    evs = captions.events(show, cap.get('style', 'three'), int(cap.get('per_line', 4)))
    cap_list, cap_y, cap_h = (None, 0, 0)
    if evs:
        cap_list, cap_h, cap_y = captions.write_track(evs, W, H, cap, caption_font(show, script, captions.look_of(cap)),
                                                      os.path.join(folder, 'captions'), total, fps=p['fps'] or 30, band=band,
                                                      title_end=(ttl or {}).get('e', 0.0))
    title = ttl and titles.write_track(ttl, W, H, titles.font_for(ttl['style'], ttl['words'], script), os.path.join(folder, 'title'), total,
                                       p['fps'] or 30, band=band,
                                       reserve=captions.top_reserve(evs, W, H, cap, band))
    T['captions'] = round(time.time() - t, 1)
    t = time.time(); progress('final', 0, 'Joining, sound levels, captions')
    out = os.path.join(folder, 'video.mp4')
    max_mb = pj['settings']['export'].get('max_mb', 0)
    kb = final(lst, cap_list, cap_y, W, H, p['fps_rational'], total, max_mb, out, title=title)
    limit = (max_mb or 0) * 1e6
    for _ in range(3):   # the Mac's encoder can overshoot its target: a small file must really be small
        if not limit or os.path.getsize(out) <= limit: break
        kb = int(kb * limit / os.path.getsize(out) * 0.93)
        final(lst, cap_list, cap_y, W, H, p['fps_rational'], total, max_mb, out, kb, title=title)
    T['final'] = round(time.time() - t, 1)
    clips = [{k: c.get(k) for k in ('take', 'in', 'out', 'ss', 'aud', 'dur', 'frames', 'text', 'beat', 'thr', 'focus', 'zoom')} |
             {'words': [w['n'] for w in c['words']], 'ws': round(c['ws'], 3), 'we': round(c['we'], 3),
              'edge_kind': [c['ein'].get('kind'), c['eout'].get('kind')], 'voice_from': c['ein'].get('quiet'), 'voice_to': c['eout'].get('quiet')}
             for c in p['clips']]
    return {'video': out, 'width': W, 'height': H, 'duration': round(total, 2), 'kbps': kb, 'clips': clips,
            'caption_events': len(evs), 'log': p['log'], 'retakes': p['retakes'], 'kept_repeats': p['kept_repeats'],
            'edges': p['edges'], 'retimed': p['retimed'], 'selfcheck': p['selfcheck'], 'fps': p['fps'], 'timings': T,
            'caption_band': [cap_y, cap_y + cap_h] if cap_list else None, 'title': ttl and {k: ttl[k] for k in ('style', 'text', 's', 'e')},
            'caption_words': words, 'caption_fixes': dict(fixes), 'bands': list(band) if band else None}
