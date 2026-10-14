"""SFX library (procedurally generated, so license-free) + user imports. Events are stored in the project,
never baked in until render, so the user can move/trim/mute/delete every one."""
import os, wave, uuid
import numpy as np
SR = 44100
BUILTIN = {  # name: (category, description)
    "whoosh": ("whoosh", "Filtered-noise sweep"), "whoosh_fast": ("transition", "Short fast sweep"),
    "pop": ("pop", "Bubble pop"), "impact": ("impact", "Low impact hit"),
    "boom": ("meme", "Deep boom (pitch-dropping sine)"), "ding": ("alert", "Bell ding"),
    "riser": ("transition", "Rising tension sweep"), "click": ("pop", "Soft click")}

def _env(n, a=0.005, r=0.3):
    t = np.arange(n) / SR
    return np.minimum(1, t / a) * np.exp(-t / r)

def gen(name):
    rng = np.random.default_rng(7)
    if name in ("whoosh", "whoosh_fast"):
        d = 0.9 if name == "whoosh" else 0.4; n = int(SR * d); x = rng.standard_normal(n)
        t = np.linspace(0, 1, n); k = np.cos(np.pi * t) ** 2 * 0 + np.sin(np.pi * t) ** 2
        y = np.convolve(x, np.ones(int(30 - 24 * 0)) / 30, mode="same") * 0
        lp = np.cumsum(x) / 80; lp = lp - np.convolve(lp, np.ones(400) / 400, mode="same")
        y = lp * k
    elif name == "pop":
        n = int(SR * 0.18); t = np.arange(n) / SR; y = np.sin(2 * np.pi * (600 + 900 * np.exp(-t * 40)) * t) * _env(n, 0.001, 0.04)
    elif name == "impact":
        n = int(SR * 0.9); t = np.arange(n) / SR; y = (np.sin(2 * np.pi * 60 * np.exp(-t * 3) * t * 2) + 0.4 * rng.standard_normal(n) * np.exp(-t * 25)) * _env(n, 0.002, 0.25)
    elif name == "boom":
        n = int(SR * 1.6); t = np.arange(n) / SR; y = np.sin(2 * np.pi * (45 + 80 * np.exp(-t * 6)) * t) * _env(n, 0.003, 0.55) + 0.2 * np.sin(2 * np.pi * 110 * t) * _env(n, 0.003, 0.2)
    elif name == "ding":
        n = int(SR * 1.2); t = np.arange(n) / SR; y = (np.sin(2 * np.pi * 1320 * t) + 0.5 * np.sin(2 * np.pi * 2640 * t)) * _env(n, 0.002, 0.35)
    elif name == "riser":
        n = int(SR * 1.5); t = np.arange(n) / SR; y = np.sin(2 * np.pi * (200 + 900 * t ** 2) * t) * (t / 1.5) ** 1.5 * 0.7
    else:  # click
        n = int(SR * 0.05); y = rng.standard_normal(n) * _env(n, 0.0005, 0.008)
    y = y / (np.abs(y).max() + 1e-9) * 0.8
    return y.astype(np.float32)

def ensure_library(libdir):
    os.makedirs(libdir, exist_ok=True)
    for name in BUILTIN:
        p = os.path.join(libdir, name + ".wav")
        if os.path.isfile(p): continue
        y = (gen(name) * 32767).astype(np.int16)
        with wave.open(p, "wb") as w: w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(y.tobytes())

def list_library(libdir):
    ensure_library(libdir)
    out = []
    for f in sorted(os.listdir(libdir)):
        if f.lower().endswith((".wav", ".mp3", ".ogg", ".m4a", ".flac")):
            n = os.path.splitext(f)[0]
            cat, desc = BUILTIN.get(n, ("user", "Imported sound"))
            out.append(dict(id=f, name=n, category=cat, description=desc, builtin=n in BUILTIN))
    return out

def new_event(sound, t, gain_db=-8.0, source="manual"):
    return dict(id="s" + uuid.uuid4().hex[:6], sound=sound, t=round(float(t), 2), gain_db=gain_db, fade_in=0.0, fade_out=0.15,
                trim_start=0.0, trim_len=0.0, enabled=True, duck=True, source=source)

def auto_place(clip_dur, peak_t, has_burst):
    """Proposals only - the user can drag/replace/delete each one."""
    ev = [new_event("whoosh_fast.wav", 0.0, -12, "auto")]
    if peak_t is not None and 1.0 < peak_t < clip_dur - 0.5: ev.append(new_event("impact.wav" if not has_burst else "pop.wav", peak_t, -10, "auto"))
    return ev
