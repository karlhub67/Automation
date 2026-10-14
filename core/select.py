"""Candidate generation + multi-signal scoring + diversity selection + continuity checks."""
import re
import numpy as np
from . import intent as I

HOOK_OPEN = re.compile(r"^(why|how|what|nobody|never|stop|imagine|wait|listen|the secret|here's|you can't|you|if you|most people|i used to|did you)\b", re.I)
BAD_START = re.compile(r"^(and|but|so|because|or|which|then|also)\b", re.I)

def _z(a):
    a = np.asarray(a, dtype=float)
    if a.size < 2 or a.std() < 1e-6: return np.zeros_like(a)
    return (a - a.mean()) / a.std()

def _norm01(a):
    a = np.asarray(a, dtype=float)
    return np.clip((a - np.percentile(a, 10)) / max(1e-6, np.percentile(a, 95) - np.percentile(a, 10)), 0, 1) if a.size else a

def build_timeline(dur, audio, visual, segs, intent, res=0.5):
    n = int(dur / res) + 1
    tl = dict(res=res, text=np.zeros(n), audio=np.zeros(n), visual=np.zeros(n), seg_scores=[])
    lex = I.lexicon(intent)
    for s in segs:
        sc, hits = I.score_text(s["text"], lex, intent["exclusions"])
        tl["seg_scores"].append((sc, hits))
        a, b = int(s["start"] / res), min(n, int(s["end"] / res) + 1)
        tl["text"][a:b] = np.maximum(tl["text"][a:b], sc)
    if audio and audio.get("rms"):
        hop = audio["hop"]; rms = np.array(audio["rms"])
        k = max(1, int(res / hop))
        e = np.array([rms[i:i + k].mean() for i in range(0, len(rms), k)])[:n]
        tl["audio"][:len(e)] = _norm01(e) * 0.5
        want_laugh = any(c in intent["concepts"] for c in ("happy", "funny", "emotional", "surprising"))
        for b in audio.get("bursts", []):
            a0, b0 = int(b["start"] / res), min(n, int(b["end"] / res) + 1)
            tl["audio"][a0:b0] += b["strength"] * (1.0 if want_laugh else 0.4)
    if visual and visual.get("motion"):
        m = np.array(visual["motion"]); k = max(1, int(res * visual["fps"]))
        v = np.array([m[i:i + k].mean() for i in range(0, len(m), k)])[:n]
        tl["visual"][:len(v)] = _norm01(v)
        for c in visual.get("cuts", []):
            i = int(c / res)
            if i < n: tl["visual"][max(0, i - 1):i + 2] += 0.3
    for key in ("audio", "visual"): tl[key] = np.clip(tl[key], 0, 1)
    return tl

def _snap_start(t, segs, silences, back):
    best = None
    for s in segs:
        if t - back <= s["start"] <= t + 0.3 and (best is None or abs(s["start"] - t) < abs(best - t)): best = s["start"]
    if best is not None: return best, "sentence"
    for a, b in silences:
        if t - back <= b <= t + 0.3: return max(0, b - 0.15), "pause"
    return t, "none"

def _snap_end(t, segs, silences, fwd):
    best = None
    for s in segs:
        if t - 0.3 <= s["end"] <= t + fwd and (best is None or abs(s["end"] - t) < abs(best - t)): best = s["end"]
    if best is not None: return best, "sentence"
    for a, b in silences:
        if t - 0.3 <= a <= t + fwd: return a + 0.15, "pause"
    return t, "none"

def propose(probe, audio, visual, segs, intent, params):
    dur = probe["duration"]
    tmin = float(params.get("min_dur") or intent["min"] or 15)
    tmax = float(params.get("max_dur") or intent["max"] or 60)
    target = float(params.get("target_dur") or intent["target"] or (tmin + tmax) / 2)
    target = min(max(target, tmin), tmax)
    n_clips = int(params.get("n_clips") or 5)
    silences = (audio or {}).get("silences", [])
    tl = build_timeline(dur, audio, visual, segs, intent)
    res = tl["res"]
    has_text = bool(segs) and bool(tl["text"].max() > 0)
    w_text, w_aud, w_vis = (0.55, 0.30, 0.15) if has_text else (0.0, 0.65, 0.35)
    comb = w_text * tl["text"] + w_aud * tl["audio"] + w_vis * tl["visual"]
    sm = np.convolve(comb, np.ones(5) / 5, mode="same") if comb.size > 5 else comb
    # anchors: local maxima, strongest first
    idx = [i for i in range(1, len(sm) - 1) if sm[i] >= sm[i - 1] and sm[i] >= sm[i + 1] and sm[i] > 0]
    idx.sort(key=lambda i: -sm[i])
    cands = []
    for i in idx[: n_clips * 8]:
        ta = i * res
        s0, sk = _snap_start(max(0, ta - target * 0.35), segs, silences, 8)
        e0, ek = _snap_end(min(dur, ta + target * 0.65), segs, silences, 8)
        # clamp to min/max by walking sentence boundaries
        while e0 - s0 < tmin and e0 < dur - 0.5: e0, _ = _snap_end(min(dur, e0 + 3), segs, silences, 6)
        if e0 - s0 > tmax:
            e0 = s0 + tmax; e0, ek = _snap_end(e0, segs, silences, 0.5)
            if e0 - s0 > tmax + 0.5: e0 = s0 + tmax
        if e0 - s0 < min(tmin, dur): continue
        a, b = int(s0 / res), max(int(s0 / res) + 1, int(e0 / res))
        text_sc, aud_sc, vis_sc = float(tl["text"][a:b].max()), float(tl["audio"][a:b].max()), float(tl["visual"][a:b].mean())
        in_segs = [s for s in segs if s["end"] > s0 and s["start"] < e0]
        first = in_segs[0]["text"] if in_segs else ""
        hook = 0.0
        if first:
            hook = 0.35 * bool(HOOK_OPEN.match(first)) + 0.25 * ("?" in first) + 0.15 * ("!" in first) + 0.15 * bool(re.search(r"\d|\$", first)) + 0.1 * (len(first.split()) <= 14)
        else:
            hook = float(tl["audio"][a:min(b, a + 4)].mean())
        cont = 0.5 * (sk != "none") + 0.5 * (ek != "none")
        if first and BAD_START.match(first): cont -= 0.3
        if intent["teaser"]: cont = max(cont, 0.5)
        dur_fit = 1.0 - min(1.0, abs((e0 - s0) - target) / max(target, 1))
        if has_text: total = 0.45 * text_sc + 0.2 * aud_sc + 0.1 * vis_sc + 0.1 * hook + 0.1 * max(cont, 0) + 0.05 * dur_fit
        else: total = 0.45 * aud_sc + 0.25 * vis_sc + 0.1 * hook + 0.1 * max(cont, 0) + 0.1 * dur_fit
        hits = sorted({h for s, (sc, hs) in zip(segs, tl["seg_scores"]) if s["end"] > s0 and s["start"] < e0 for h in hs})
        bursts = [bb for bb in (audio or {}).get("bursts", []) if bb["end"] > s0 and bb["start"] < e0]
        cuts = [c for c in (visual or {}).get("cuts", []) if s0 <= c <= e0]
        why = []
        if has_text and text_sc > 0: why.append("Transcript match (%.0f%%): %s" % (text_sc * 100, ", ".join(hits[:8]) or "context"))
        if not segs: why.append("No transcript available - selected from audio/visual evidence only.")
        if bursts: why.append("%d loud noise-like burst(s) in window (laughter/applause/cheer proxy, peak strength %.2f)" % (len(bursts), max(x["strength"] for x in bursts)))
        why.append("Audio energy peak score %.2f; visual activity %.2f%s" % (aud_sc, vis_sc, (" with %d scene cut(s)" % len(cuts)) if cuts else ""))
        if hook > 0.3: why.append("Hook strength %.2f: opens with \"%s\"" % (hook, first[:70]))
        why.append("Context continuity %.2f: starts on %s boundary, ends on %s boundary" % (max(cont, 0), sk if sk != "none" else "no", ek if ek != "none" else "no"))
        cands.append(dict(start=round(s0, 2), end=round(e0, 2), score=round(float(total), 3),
                          breakdown=dict(text=round(text_sc, 2), audio=round(aud_sc, 2), visual=round(vis_sc, 2), hook=round(hook, 2), continuity=round(max(cont, 0), 2), duration_fit=round(dur_fit, 2)),
                          why=why, hook_text=first, anchor=round(ta, 2)))
    cands.sort(key=lambda c: -c["score"])
    picked = []
    for c in cands:  # near-duplicate / overlap suppression -> diverse set
        if any(min(c["end"], p["end"]) - max(c["start"], p["start"]) > 0.3 * min(c["end"] - c["start"], p["end"] - p["start"]) for p in picked): continue
        picked.append(c)
        if len(picked) >= n_clips: break
    for k, c in enumerate(picked): c["id"] = "c%d" % (k + 1); c["status"] = "pending"; c["locked"] = False
    return picked, dict(has_transcript=bool(segs), has_text_signal=has_text, weights=dict(text=w_text, audio=w_aud, visual=w_vis), target=target, min=tmin, max=tmax)
