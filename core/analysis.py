"""Real signal analysis: audio (energy, silence, laughter/cheer-like bursts) and visual (motion, cuts).
Streams media through FFmpeg pipes in chunks - the full video is never loaded into RAM."""
import subprocess
import numpy as np

SR = 16000

def analyze_audio(path, hop=0.25, progress=None, duration=0):
    n = int(SR * hop)
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    rms, flat, buf, done = [], [], b"", 0
    win = np.hanning(n)
    lo, hi = int(300 / (SR / n)), int(6000 / (SR / n))
    while True:
        chunk = p.stdout.read(n * 2 * 80)
        if not chunk: break
        buf += chunk
        k = len(buf) // (n * 2)
        if not k: continue
        arr = np.frombuffer(buf[:k * n * 2], dtype=np.int16).astype(np.float32) / 32768.0
        buf = buf[k * n * 2:]
        fr = arr.reshape(k, n)
        rms.extend((20 * np.log10(np.sqrt((fr ** 2).mean(1)) + 1e-6)).tolist())
        s = np.abs(np.fft.rfft(fr * win, axis=1))[:, lo:hi] + 1e-9
        flat.extend((np.exp(np.log(s).mean(1)) / s.mean(1)).tolist())
        done += k * hop
        if progress and duration: progress(min(done / duration, 1.0))
    p.wait()
    rms, flat = np.array(rms), np.array(flat)
    out = dict(hop=hop, rms=[round(float(x), 2) for x in rms], silences=[], bursts=[], floor_db=None)
    if len(rms) < 8: return out
    p10, p90, p60 = np.percentile(rms, 10), np.percentile(rms, 90), np.percentile(rms, 60)
    thr = p10 + 0.25 * (p90 - p10)
    out["floor_db"], out["silence_thr_db"] = round(float(p10), 1), round(float(thr), 1)
    # silences: contiguous hops under threshold, >= 0.4 s
    low = rms < thr
    i = 0
    while i < len(low):
        if low[i]:
            j = i
            while j < len(low) and low[j]: j += 1
            if (j - i) * hop >= 0.4: out["silences"].append([round(i * hop, 2), round(j * hop, 2)])
            i = j
        else: i += 1
    # laughter/cheer/applause PROXY: loud + noise-like (high spectral flatness) for >= 0.75 s
    fthr = max(0.25, float(np.percentile(flat, 85)))
    cand = (rms > p60) & (flat > fthr)
    i = 0
    while i < len(cand):
        if cand[i]:
            j = i
            while j < len(cand) and cand[j]: j += 1
            if (j - i) * hop >= 0.75:
                out["bursts"].append(dict(start=round(i * hop, 2), end=round(j * hop, 2),
                                          strength=round(float(min(1.0, (rms[i:j].mean() - p60) / max(6.0, p90 - p60) + 0.4)), 2)))
            i = j
        else: i += 1
    return out

def analyze_visual(path, fps=2, progress=None, duration=0):
    W, H = 160, 90
    fs = W * H
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", path, "-an", "-vf", "fps=%g,scale=%d:%d,format=gray" % (fps, W, H),
                          "-f", "rawvideo", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    prev, prevh, motion, hd, idx = None, None, [], [], 0
    while True:
        b = p.stdout.read(fs)
        if len(b) < fs: break
        f = np.frombuffer(b, dtype=np.uint8)
        h = np.bincount(f // 16, minlength=16) / fs
        if prev is None: motion.append(0.0); hd.append(0.0)
        else:
            motion.append(float(np.abs(f.astype(np.int16) - prev.astype(np.int16)).mean()))
            hd.append(float(np.abs(h - prevh).sum()))
        prev, prevh, idx = f, h, idx + 1
        if progress and duration and idx % 20 == 0: progress(min(idx / fps / duration, 1.0))
    p.wait()
    hd_a = np.array(hd) if hd else np.zeros(1)
    thr = max(0.5, float(hd_a.mean() + 3 * hd_a.std()))
    cuts = [round(i / fps, 2) for i, v in enumerate(hd) if v > thr and i > 0]
    return dict(fps=fps, motion=[round(x, 3) for x in motion], cuts=cuts)
