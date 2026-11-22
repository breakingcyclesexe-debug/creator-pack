"""Hear the take: whisper-cli with the large-v3-turbo model on the Mac's graphics chip, the whole file in one pass
(a 7 minute take in about 15 seconds), word by word, then grouped into speech islands.

Hearing each short island separately on the processor took 13 minutes for the same take, so it is not done.
The prompt is full of fillers and restarts on purpose: whisper leaves "um" and "I- I" out unless primed, and the
cut rules need them in the words to cut them."""
import json, os, re, subprocess, tempfile, time
from . import media, cutrules, islands, edges
from .platform import get as platform

P = platform()
PROMPT = 'Umm, so, uh, I- I was, like, the- the thing, uhh, I mean, hmm. Okay so, um, I, I made, uh-'


def available():
    return bool(P.tool('whisper-cli')) and os.path.exists(P.whisper_model())


HAN_PROMPT = {'trad': '以下是繁體中文的句子。', 'simp': '以下是简体中文的句子。'}


def prompt_for(language='auto', fillers=True, words=(), chinese=''):
    """What the listener is told before it starts. The buyer's own words (names, brands, places) go in so they are
    heard right first time ("Claude", not "clock"); the filler line only for English, and only on a long hearing;
    for Chinese a line in the characters the captions use (Cantonese: always Traditional)."""
    lang = language if language else 'auto'
    parts = []
    if lang in ('yue', 'zh'):
        from . import captions
        parts.append(HAN_PROMPT[captions.script_for(lang, chinese) or 'trad'])
    elif fillers and lang in ('auto', 'en'): parts.append(PROMPT)
    mine = [w for w in words if w]
    if mine: parts.append(', '.join(mine)[:600] + '.')
    return ' '.join(parts)


def hear(path, language='auto', threads=8, prompt=True):
    """Words [{"w","s","e","p"}] in seconds for a whole recording."""
    from . import project as prj
    pf = prj.prefs()
    if not available(): raise RuntimeError('Speech model or whisper-cli missing: run Setup first')
    with tempfile.TemporaryDirectory() as d:
        wav = media.wav16k(path, os.path.join(d, 'a.wav'))
        lang = language if language and language != 'auto' else 'auto'
        cmd = [P.tool('whisper-cli'), '-m', P.whisper_model(), '-f', wav, '-l', lang, '-ml', '1', '-sow', '-ojf',
               '-of', os.path.join(d, 'a'), '-t', str(threads), '-np']
        preset = dtw_preset(P.whisper_model())
        if preset: cmd += ['-dtw', preset, '-nfa']
        said = prompt_for(lang, prompt, pf['words'], pf['chinese'])
        if said: cmd += ['--prompt', said]
        subprocess.run(cmd, capture_output=True, check=True)
        with open(os.path.join(d, 'a.json')) as f: segs = json.load(f)['transcription']
    return words_from(segs)


def dtw_preset(model):
    """whisper.cpp's alignment-head preset for the model file, e.g. ggml-large-v3-turbo.bin -> large.v3.turbo."""
    m = re.match(r'ggml-(tiny|base|small|medium|large-v1|large-v2|large-v3-turbo|large-v3)(\.en)?\.bin$', os.path.basename(model))
    return (m.group(1) + (m.group(2) or '')).replace('-', '.') if m else None


def words_from(segs):
    """Words from whisper-cli JSON. Times come from the DTW token times (t_dtw, CT-129): the plain segment offsets
    run edge to edge and swallow pauses, measured 3 s off after a long pause on a tester's IMG_0265; t_dtw sat on the
    voice. t_dtw marks a token inside the word, so a word ends just after its last token's t_dtw and starts no
    earlier than the previous word's end (and at most 0.35 s before its first token); the energy trims both."""
    out, prev_e = [], 0.0
    for seg in segs:
        if not seg['text'].strip(): continue
        toks = [t for t in seg.get('tokens', []) if not t['text'].startswith('[')]
        p = round(sum(t['p'] for t in toks) / len(toks), 3) if toks else 1.0
        dt = [t['t_dtw'] / 100 for t in toks if t.get('t_dtw', -1) >= 0]
        if dt:
            e = max(dt[-1] + 0.04, prev_e + 0.02)
            s = max(prev_e, min(dt[0], e - 0.02) - 0.35)
        else:
            s, e = seg['offsets']['from'] / 1000, seg['offsets']['to'] / 1000
        w = {'w': seg['text'], 's': round(s, 3), 'e': round(e, 3), 'p': p}
        if dt: w.update(d0=round(dt[0], 3), d=round(dt[-1], 3))   # the DTW anchors; edges.dtw_spans widens them on the sound
        out.append(w)
        prev_e = e
    return out


def hear_span(path, a, b, language='auto'):
    """Words of a stretch [a, b] of a recording, heard on its own; times in the recording's seconds."""
    with tempfile.TemporaryDirectory() as d:
        x = os.path.join(d, 'span.wav')
        subprocess.run([media.ff('ffmpeg'), '-v', 'error', '-y', '-ss', f'{max(0, a):.3f}', '-t', f'{b - max(0, a):.3f}', '-i', path,
                        '-map', '0:a:0', '-ac', '1', '-ar', '16000', '-af', media.SYNC, '-c:a', 'pcm_s16le', x], check=True, capture_output=True)
        ws = hear(x, language)
    return [dict(w, s=round(w['s'] + max(0, a), 3), e=round(w['e'] + max(0, a), 3)) for w in ws]


CHUNK = 24.0   # seconds of clips per hearing: inside whisper's own 30 s window, where its word times hold
GAP = 1.2      # silence between clips in a chunk, so words never run from one clip into the next


def hear_clips(spans, pcm_of, language='auto'):
    """The self-check's ears: each stretch (take, a, b) heard again on its own, words in take seconds.
    pcm_of(take) -> 16 kHz mono int16 samples of the take. Clips are packed into ~24 s chunks with silence
    between them (one whisper run per chunk, not per clip), without the filler prompt (on short audio it
    makes whisper invent "um"s)."""
    import numpy as np, wave
    SR = 16000
    out = [[] for _ in spans]
    chunks, cur, used = [], [], 0.0
    for k, (take, a, b) in enumerate(spans):
        if cur and used + (b - a) > CHUNK: chunks.append(cur); cur, used = [], 0.0
        cur.append(k); used += (b - a) + GAP
    if cur: chunks.append(cur)
    with tempfile.TemporaryDirectory() as d:
        for ci, ks in enumerate(chunks):
            parts, offs, t = [np.zeros(int(0.5 * SR), np.int16)], [], 0.5
            for k in ks:
                take, a, b = spans[k]
                x = pcm_of(take)[max(0, int(round(a * SR))):max(0, int(round(b * SR)))]
                offs.append((k, t, len(x) / SR, a)); parts += [x, np.zeros(int(GAP * SR), np.int16)]
                t += len(x) / SR + GAP
            wav = os.path.join(d, f'c{ci}.wav')
            with wave.open(wav, 'wb') as f:
                f.setnchannels(1); f.setsampwidth(2); f.setframerate(SR); f.writeframes(np.concatenate(parts).tobytes())
            for w in hear(wav, language, prompt=False):
                m = (w['s'] + w['e']) / 2
                hit = next(((k, o, L, a) for k, o, L, a in offs if o - 0.15 <= m <= o + L + 0.15), None)
                if not hit: continue
                k, o, L, a = hit
                out[k].append(dict(w, s=round(a + max(0.0, w['s'] - o), 3), e=round(a + min(L, max(0.0, w['e'] - o)), 3)))
    return out


def take_transcript(path, language='auto', energy=None):
    """energy: the take's 10 ms dB frames (media.energy); used to trim word times to where they sound."""
    t = time.time()
    from . import captions, project as prj
    heard = captions.to_script(hear(path, language), captions.script_for(language, prj.prefs()['chinese']), P.han)
    W = cutrules.prepare(heard)
    if energy is not None:
        fl = edges.noise_floor(energy)
        if W and all('d' in w for w in W): edges.dtw_spans(W, energy, fl)
        else: edges.refine_words(W, energy, fl)
    isl = islands.islands(W)
    return {'words': W, 'islands': [{k: v for k, v in i.items() if k != 'words'} | {'first': i['words'][0]['i'], 'last': i['words'][-1]['i']}
                                    for i in isl], 'seconds': round(time.time() - t, 1)}


def compact(tr, take):
    """The transcript as the session reads it: one line per sentence (or per island when there is no full stop),
    with start and end in seconds, so a beat can be quoted with its time."""
    lines, cur = [f'## take {take}'], []
    starts = {i['first'] for i in tr['islands']}
    for w in tr['words']:
        if cur and w['i'] in starts:
            lines.append(_line(cur)); cur = []
        cur.append(w)
        if re.search(r'[.?!]["\')]*$', w['w'].strip()):
            lines.append(_line(cur)); cur = []
    if cur: lines.append(_line(cur))
    return '\n'.join(lines)


def _line(ws):
    return f"[{ws[0]['s']:.2f}-{ws[-1]['e']:.2f}] " + ''.join(w['w'] for w in ws).strip()
