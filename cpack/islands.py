"""Speech islands: runs of words with no pause over min_pause between them. The whole file is heard once
(fast), then grouped here, so no voice-activity model needs installing."""


def islands(words, min_pause=0.3):
    out, cur = [], []
    for w in words:
        if cur and w['s'] - cur[-1]['e'] > min_pause:
            out.append(cur); cur = []
        cur.append(w)
    if cur: out.append(cur)
    return [{'id': k, 's': round(ws[0]['s'], 3), 'e': round(ws[-1]['e'], 3),
             'text': ''.join(w['w'] for w in ws).strip(), 'words': ws} for k, ws in enumerate(out)]
