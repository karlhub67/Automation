"""Speech-to-text with timestamps. Backends: faster-whisper, openai-whisper, or an imported .srt/.vtt/.json.
If none is available the pipeline still runs on audio/visual evidence and reports that clearly."""
import os, re, subprocess, json, tempfile

class TranscriptUnavailable(Exception):
    pass

def backends():
    out = []
    try:
        import faster_whisper  # noqa
        out.append("faster-whisper")
    except Exception: pass
    try:
        import whisper  # noqa
        out.append("openai-whisper")
    except Exception: pass
    return out

def _ts(s):
    s = s.strip().replace(",", ".")
    parts = s.split(":")
    parts = [float(x) for x in parts]
    while len(parts) < 3: parts.insert(0, 0.0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]

def parse_subs(text):
    segs = []
    blocks = re.split(r"\n\s*\n", text.replace("\r", "").strip())
    for b in blocks:
        lines = [l for l in b.split("\n") if l.strip()]
        for k, l in enumerate(lines):
            if "-->" in l:
                a, c = l.split("-->")[:2]
                try:
                    st, en = _ts(a.split()[0]), _ts(c.split()[0])
                except Exception: continue
                t = " ".join(re.sub(r"<[^>]+>", "", x).strip() for x in lines[k + 1:]).strip()
                if t: segs.append(dict(start=st, end=en, text=t))
                break
    return add_approx_words(segs)

def add_approx_words(segs):
    for s in segs:
        if s.get("words"): continue
        ws = s["text"].split()
        if not ws: s["words"] = []; continue
        tot = sum(len(w) + 1 for w in ws)
        t, out = s["start"], []
        for w in ws:
            d = (s["end"] - s["start"]) * (len(w) + 1) / tot
            out.append(dict(w=w, start=round(t, 3), end=round(t + d, 3)))
            t += d
        s["words"], s["approx_words"] = out, True
    return segs

def load_sidecar(video_path):
    base = os.path.splitext(video_path)[0]
    for ext in (".srt", ".vtt"):
        if os.path.isfile(base + ext):
            return parse_subs(open(base + ext, encoding="utf-8", errors="replace").read())
    return None

def transcribe(video_path, model="base", language=None, progress=None):
    be = backends()
    if not be:
        raise TranscriptUnavailable("No speech model installed. Run: pip install faster-whisper   (or import an .srt/.vtt file in the UI).")
    wav = os.path.join(tempfile.mkdtemp(prefix="cf_asr_"), "a.wav")
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", video_path, "-vn", "-ac", "1", "-ar", "16000", wav])
    if r.returncode: raise TranscriptUnavailable("Could not extract audio for transcription.")
    segs = []
    if "faster-whisper" in be:
        from faster_whisper import WhisperModel
        m = WhisperModel(model, device="auto", compute_type="int8")
        it, info = m.transcribe(wav, word_timestamps=True, vad_filter=True, language=language)
        for s in it:
            segs.append(dict(start=s.start, end=s.end, text=s.text.strip(),
                             words=[dict(w=w.word.strip(), start=w.start, end=w.end) for w in (s.words or [])]))
            if progress and info.duration: progress(min(s.end / info.duration, 1.0))
    else:
        import whisper
        m = whisper.load_model(model)
        res = m.transcribe(wav, word_timestamps=True, language=language)
        for s in res["segments"]:
            segs.append(dict(start=s["start"], end=s["end"], text=s["text"].strip(),
                             words=[dict(w=w["word"].strip(), start=w["start"], end=w["end"]) for w in s.get("words", [])]))
    return add_approx_words(segs)
